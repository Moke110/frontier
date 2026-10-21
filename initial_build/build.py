"""Write an approved initial-build draft into the knowledge archive.

A draft is the reviewed output of the initial-build sample flow
(``drafts/initial-build/<theme>/``): ``cards.jsonl``, ``propositions.jsonl``
and ``sources.jsonl``. Applying it is idempotent: identical cards and
propositions are skipped, so a rerun never duplicates the first batch.

Validation happens before anything is written; one bad item fails the whole
batch, leaving the archive untouched.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from archive.store import Archive
from common import now, write_json
from pdf_ingest.anchors import locate_quote

CARD_ID_RE = re.compile(r"^card_[a-z0-9][a-z0-9_]*$")
PROP_ID_RE = re.compile(r"^prop_[a-z0-9][a-z0-9_]*$")
CARD_FIELDS = ("id", "label", "ontology", "annotation")
PROP_FIELDS = ("id", "title", "content", "related_knowledge", "history")
MIN_EVIDENCE_PAPERS = 2


# -------------------------------------------------------------------- draft
def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_draft(draft_dir: str | Path) -> dict:
    draft_dir = Path(draft_dir).expanduser().resolve()
    return {
        "dir": str(draft_dir),
        "theme": draft_dir.name,
        "cards": _read_jsonl(draft_dir / "cards.jsonl"),
        "propositions": _read_jsonl(draft_dir / "propositions.jsonl"),
        "sources": _read_jsonl(draft_dir / "sources.jsonl"),
    }


# --------------------------------------------------------------- validation
def _validate_card(card: dict, draft_ids: set[str], seen: set[str]) -> list[str]:
    errors = []
    name = card.get("id") or f"<card {card.get('label')!r}>"
    missing = [field for field in CARD_FIELDS if card.get(field) in (None, "", [])]
    if missing:
        errors.append(f"{name}: missing {', '.join(missing)}")
    if not CARD_ID_RE.match(str(card.get("id", ""))):
        errors.append(f"{name}: id must match card_<slug>")
    if name in seen:
        errors.append(f"{name}: duplicate card id")
    seen.add(name)
    ontology = card.get("ontology")
    if not isinstance(ontology, list) or len(ontology) < 3 or not all(
        isinstance(term, str) and term.strip() for term in ontology
    ):
        errors.append(f"{name}: ontology needs at least 3 non-empty terms")
    annotation = str(card.get("annotation") or "")
    if "⛔" not in annotation or "⚠️" not in annotation:
        errors.append(f"{name}: annotation needs ⛔ exclusions and ⚠️ confusions")
    draft_ids.add(str(card.get("id")))
    return errors


def _validate_prop(prop: dict, draft_ids: set[str], seen: set[str]) -> list[str]:
    errors = []
    name = prop.get("id") or f"<proposition {prop.get('title')!r}>"
    missing = [field for field in PROP_FIELDS if prop.get(field) in (None, "", [])]
    if missing:
        errors.append(f"{name}: missing {', '.join(missing)}")
    if not PROP_ID_RE.match(str(prop.get("id", ""))):
        errors.append(f"{name}: id must match prop_<slug>")
    if name in seen:
        errors.append(f"{name}: duplicate proposition id")
    seen.add(name)

    related = prop.get("related_knowledge")
    if not isinstance(related, list) or len(related) < 2:
        errors.append(f"{name}: needs at least 2 related_knowledge cards")
    elif len(set(related)) != len(related):
        errors.append(f"{name}: duplicate related_knowledge")
    else:
        unknown = [card for card in related if card not in draft_ids]
        if unknown:
            errors.append(f"{name}: unknown related_knowledge {unknown}")

    history = prop.get("history")
    if not isinstance(history, list) or not history:
        errors.append(f"{name}: needs a non-empty history")
        return errors
    if history[0].get("action") != "created":
        errors.append(f"{name}: first history entry must be 'created'")
    if not str(history[0].get("rationale") or "").strip():
        errors.append(f"{name}: created history needs a rationale")

    evidence = [item for entry in history for item in (entry.get("evidence") or [])]
    for item in evidence:
        if item.get("paper_id") and (
            not isinstance(item.get("page"), int) or item.get("page") < 1
        ):
            errors.append(f"{name}: evidence page must be a positive integer")
        if item.get("paper_id") and not str(item.get("quote") or "").strip():
            errors.append(f"{name}: evidence needs a quote")
    return errors


def evidence_papers(prop: dict) -> set[str]:
    return {
        item.get("paper_id")
        for entry in prop.get("history", [])
        for item in (entry.get("evidence") or [])
        if item.get("paper_id")
    }


def hold_reasons(prop: dict) -> list[str]:
    """Props that must wait for a later batch (not written, not a failure)."""
    name = prop.get("id") or prop.get("title")
    papers = evidence_papers(prop)
    if len(papers) < MIN_EVIDENCE_PAPERS:
        return [
            f"{name}: needs evidence from at least {MIN_EVIDENCE_PAPERS} "
            f"independent papers (got {len(papers)}); held for a later batch"
        ]
    return []


def validate_structure(draft: dict) -> list[str]:
    """Field, id and cross-reference checks that need no archive."""
    errors: list[str] = []
    if not draft["cards"]:
        errors.append("draft has no cards")
    if not draft["propositions"]:
        errors.append("draft has no propositions")
    card_ids: set[str] = set()
    seen_cards: set[str] = set()
    for card in draft["cards"]:
        errors.extend(_validate_card(card, card_ids, seen_cards))
    seen_props: set[str] = set()
    for prop in draft["propositions"]:
        errors.extend(_validate_prop(prop, card_ids, seen_props))
    return errors


def _draft_evidence(draft: dict):
    for prop in draft["propositions"]:
        for entry in prop.get("history", []):
            for item in entry.get("evidence") or []:
                yield prop, item


def validate_evidence(store: Archive, draft: dict) -> tuple[list[str], dict]:
    """Check every evidence quote against the ingested page anchors."""
    errors = []
    checked = located = 0
    for prop, item in _draft_evidence(draft):
        checked += 1
        paper_id = item.get("paper_id")
        page = item.get("page")
        quote = item.get("quote", "")
        name = prop.get("id") or prop.get("title")
        try:
            store.get_paper(paper_id)
        except Exception:
            errors.append(f"{name}: evidence paper {paper_id} is not in the archive")
            continue
        pages = store.read_pages(paper_id)
        if not pages:
            errors.append(f"{name}: {paper_id} has no page anchors")
            continue
        text_path = store.root / (pages.get("text_path") or "")
        if not text_path.exists():
            errors.append(f"{name}: {paper_id} text file is missing")
            continue
        text = text_path.read_text(encoding="utf-8")
        if locate_quote(text, pages.get("page_anchors", []), page, quote):
            located += 1
        else:
            errors.append(f"{name}: quote not found on {paper_id} page {page}")
    return errors, {"checked": checked, "located": located}


# -------------------------------------------------------------------- apply
def _same_card(existing: dict, card: dict) -> bool:
    return all(existing.get(field) == card.get(field) for field in CARD_FIELDS)


def _same_prop(existing: dict, prop: dict) -> bool:
    return all(existing.get(field) == prop.get(field) for field in PROP_FIELDS)


def _backup(store: Archive) -> Path:
    tmp_root = store.root / ".tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="initial_build_", dir=str(tmp_root)))
    for name, path in (("cards", store.cards), ("propositions", store.props)):
        if path.exists():
            shutil.copytree(path, tmp / name)
    return tmp


def _restore(store: Archive, backup: Path) -> None:
    for name, path in (("cards", store.cards), ("propositions", store.props)):
        if (backup / name).exists():
            if path.exists():
                shutil.rmtree(path)
            shutil.copytree(backup / name, path)
    shutil.rmtree(backup, ignore_errors=True)


def apply(
    home_dir: str | Path, draft_dir: str | Path, *, dry_run: bool = False
) -> dict:
    store = Archive(Path(home_dir).expanduser().resolve())
    draft = load_draft(draft_dir)
    report: dict[str, Any] = {
        "schema_version": 1,
        "kind": "initial-build",
        "theme": draft["theme"],
        "draft": draft["dir"],
        "home": str(store.home),
        "dry_run": dry_run,
        "started_at": now(),
        "ok": False,
        "counts": {
            "cards": {},
            "propositions": {},
            "sources": len(draft["sources"]),
            "evidence": {"checked": 0, "located": 0},
        },
        "held": [],
        "failures": [],
        "report_path": None,
    }

    active_props = []
    for prop in draft["propositions"]:
        reasons = hold_reasons(prop)
        if reasons:
            report["held"].append(
                {
                    "id": prop.get("id"),
                    "title": prop.get("title"),
                    "reason": reasons[0],
                }
            )
        else:
            active_props.append(prop)

    errors = validate_structure(draft)
    if not errors:
        errors, evidence = validate_evidence(
            store, {**draft, "propositions": active_props}
        )
        report["counts"]["evidence"] = evidence
    report["failures"] = errors
    if errors:
        return _finish(report, dry_run)

    if dry_run:
        report["counts"]["cards"] = {"planned": len(draft["cards"])}
        report["counts"]["propositions"] = {
            "planned": len(active_props),
            "held": len(report["held"]),
        }
        report["ok"] = True
        return _finish(report, dry_run)

    backup = _backup(store)
    try:
        card_counts = {"created": 0, "updated": 0, "skipped": 0}
        for card in draft["cards"]:
            payload = {field: card[field] for field in CARD_FIELDS}
            previous = None
            try:
                previous = store.get_card(card["id"])
            except Exception:
                previous = None
            if previous and _same_card(previous, payload):
                card_counts["skipped"] += 1
                continue
            store.put_card(dict(payload))
            card_counts["updated" if previous else "created"] += 1

        prop_counts = {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "held": len(report["held"]),
        }
        for prop in active_props:
            payload = {field: prop[field] for field in PROP_FIELDS}
            previous = None
            try:
                previous = store.get_prop(prop["id"])
            except Exception:
                previous = None
            if previous and _same_prop(previous, payload):
                prop_counts["skipped"] += 1
                continue
            store.put_prop(dict(payload))
            prop_counts["updated" if previous else "created"] += 1
    except Exception as exc:  # noqa: BLE001 - restore the batch then report
        _restore(store, backup)
        report["failures"] = [f"write failed, batch rolled back: {exc}"]
        return _finish(report, dry_run)

    shutil.rmtree(backup, ignore_errors=True)
    report["counts"]["cards"] = card_counts
    report["counts"]["propositions"] = prop_counts
    report["ok"] = True
    return _finish(report, dry_run)


def _finish(report: dict, dry_run: bool) -> dict:
    report["finished_at"] = now()
    if not dry_run:
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        path = (
            Path(report["home"])
            / "archive"
            / "reports"
            / f"initial-build-{report['theme']}-{stamp}.json"
        )
        report["report_path"] = str(path)
        write_json(path, report)
    return report


def summary(report: dict) -> dict:
    return {
        "ok": report["ok"],
        "theme": report["theme"],
        "counts": report["counts"],
        "held": report["held"],
        "report": report["report_path"],
        "failures": report["failures"],
    }

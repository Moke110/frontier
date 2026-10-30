"""archive: the only writer of the knowledge store.

Layers (all under $KL_HOME/archive):
  1. raw/          original papers (metadata + text + PDF page anchors)
  2. pushes/       generated pushes (long-form PDF payload + proposals)
  3. cards/        knowledge cards (id / label / ontology / annotation)
  4. propositions/ cross-paper claims with history and related cards

A knowledge card has no links of its own. Propositions are the only place that
connects cards (``related_knowledge``, at least two cards).

Only this module writes archive/. Everything else reads the documented files.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from common import (
    append_jsonl,
    clip,
    ensure_dir,
    now,
    paper_id as make_paper_id,
    read_json,
    read_jsonl,
    slug,
    write_json,
)

SCHEMA_VERSION = 3
CARD_FIELDS = ("id", "label", "ontology", "annotation")
PROP_FIELDS = (
    "id",
    "title",
    "review",
    "related_knowledge",
    "evidence",
    "changelog",
)
EVIDENCE_FIELDS = ("id", "stance", "conclusion", "papers")
CHANGELOG_ACTIONS = {
    "created",
    "title_changed",
    "review_changed",
    "related_knowledge_changed",
}
CHANGELOG_FIELDS = {"title", "review", "related_knowledge"}
STANCES = {"supports", "contradicts"}
MAX_CONCLUSION = 200
MAX_REVIEW = 2000
MIN_EVIDENCE = 2
REVIEW_EVERY = 10
CARD_ID_RE = re.compile(r"^card_[a-z0-9][a-z0-9_]*$")
PROP_ID_RE = re.compile(r"^prop_[a-z0-9][a-z0-9_]*$")
EVIDENCE_ID_RE = re.compile(r"^ev_[a-z0-9][a-z0-9_]*$")
MIN_RELATED_CARDS = 2


def id_slug(text: str) -> str:
    """ASCII slug for ids: lower case, underscores only."""
    return slug(text, fallback="").replace("-", "_").replace(".", "_").strip("_")


class ArchiveError(RuntimeError):
    pass


def is_under_review(record: dict | None) -> bool:
    """Whether a card or proposition is kept but excluded from formal work.

    The flag is optional: a missing key (every record written before this
    field existed) means not under review.  Writes validate the type, so this
    only needs a truthful boolean read.
    """
    return bool((record or {}).get("under_review", False))


def _validate_under_review(record: dict, kind: str) -> None:
    value = record.get("under_review")
    if value is not None and not isinstance(value, bool):
        raise ArchiveError(f"{kind} under_review must be a boolean")


# --------------------------------------------------------------------- ids
def _taken(prefix: str, existing: dict[str, dict]) -> set[str]:
    return set(existing)


def card_id_for(label: str, existing: dict[str, dict]) -> str:
    """Semantic ``card_<slug>`` id, deduped against existing cards.

    ASCII labels slugify directly. Non-ASCII labels have no ASCII slug, so the
    caller must pass an explicit id instead.
    """
    base = "card_" + id_slug(label)
    if base == "card_":
        raise ArchiveError(
            f"label {label!r} has no ASCII slug; pass an explicit id like card_<slug>"
        )
    for card in existing.values():
        if (card.get("label") or "").strip().lower() == (label or "").strip().lower():
            return card["id"]
    candidate, n = base, 2
    while candidate in existing:
        candidate = f"{base}_{n}"
        n += 1
    return candidate


def prop_id_for(title: str, existing: dict[str, dict], explicit: str | None = None) -> str:
    """Semantic ``prop_<slug>`` id. Explicit ids win; collisions get ``_2``."""
    if explicit:
        if not PROP_ID_RE.match(explicit):
            raise ArchiveError(f"bad proposition id {explicit!r} (want prop_<slug>)")
        if explicit in existing:
            return explicit
        return explicit
    base = "prop_" + id_slug(title)
    if base == "prop_":
        raise ArchiveError(
            f"title {title!r} has no ASCII slug; pass an explicit id like prop_<slug>"
        )
    candidate, n = base, 2
    while candidate in existing:
        candidate = f"{base}_{n}"
        n += 1
    return candidate


# --------------------------------------------------------------- validation
def _validate_card(card: dict) -> None:
    missing = [f for f in CARD_FIELDS if card.get(f) in (None, "", [])]
    if missing:
        raise ArchiveError(f"card missing {', '.join(missing)}")
    if not CARD_ID_RE.match(card["id"]):
        raise ArchiveError(f"bad card id {card['id']!r} (want card_<slug>)")
    _validate_under_review(card, "card")
    if not isinstance(card["ontology"], list) or not all(
        isinstance(t, str) and t.strip() for t in card["ontology"]
    ):
        raise ArchiveError("card ontology must be a non-empty list of strings")
    if not str(card["annotation"]).strip():
        raise ArchiveError("card annotation must not be empty")


def _validate_evidence(prop_id: str, entry: dict, seen_ids: set[str]) -> None:
    missing = [f for f in EVIDENCE_FIELDS if entry.get(f) in (None, "", [])]
    if missing:
        raise ArchiveError(
            f"proposition {prop_id} evidence missing {', '.join(missing)}"
        )
    ev_id = entry["id"]
    if not EVIDENCE_ID_RE.match(ev_id):
        raise ArchiveError(f"bad evidence id {ev_id!r} (want ev_<slug>)")
    if ev_id in seen_ids:
        raise ArchiveError(f"proposition {prop_id} has duplicate evidence id {ev_id}")
    seen_ids.add(ev_id)
    if entry["stance"] not in STANCES:
        raise ArchiveError(
            f"proposition {prop_id} evidence {ev_id} stance must be one of {sorted(STANCES)}"
        )
    conclusion = str(entry["conclusion"])
    if len(conclusion) > MAX_CONCLUSION:
        raise ArchiveError(
            f"proposition {prop_id} evidence {ev_id} conclusion exceeds {MAX_CONCLUSION} chars"
        )
    papers = entry["papers"]
    if not isinstance(papers, list) or not papers:
        raise ArchiveError(
            f"proposition {prop_id} evidence {ev_id} needs at least one paper"
        )
    for paper in papers:
        if not paper.get("paper_id"):
            raise ArchiveError(
                f"proposition {prop_id} evidence {ev_id} paper needs paper_id"
            )
        page = paper.get("page")
        if page is not None and (not isinstance(page, int) or page < 1):
            raise ArchiveError(
                f"proposition {prop_id} evidence {ev_id} page must be >= 1 or null"
            )
        quote = str(paper.get("quote") or "")
        if not 8 <= len(quote) <= 500:
            raise ArchiveError(
                f"proposition {prop_id} evidence {ev_id} quote must be 8..500 chars"
            )


def _validate_prop(prop: dict, cards: dict[str, dict]) -> None:
    missing = [f for f in PROP_FIELDS if prop.get(f) in (None, "")]
    if missing:
        raise ArchiveError(f"proposition missing {', '.join(missing)}")
    if not PROP_ID_RE.match(prop["id"]):
        raise ArchiveError(f"bad proposition id {prop['id']!r} (want prop_<slug>)")
    _validate_under_review(prop, "proposition")
    related = prop["related_knowledge"]
    if not isinstance(related, list) or len(related) < MIN_RELATED_CARDS:
        raise ArchiveError(
            f"proposition {prop['id']} needs at least {MIN_RELATED_CARDS} related_knowledge cards"
        )
    if len(set(related)) != len(related):
        raise ArchiveError(f"proposition {prop['id']} has duplicate related_knowledge")
    unknown = [c for c in related if c not in cards]
    if unknown:
        raise ArchiveError(f"proposition {prop['id']} references unknown cards: {unknown}")

    review = prop["review"]
    if not isinstance(review, str) or not review.strip():
        raise ArchiveError(f"proposition {prop['id']} needs a non-empty review")
    if len(review) > MAX_REVIEW:
        raise ArchiveError(
            f"proposition {prop['id']} review exceeds {MAX_REVIEW} chars"
        )

    evidence = prop["evidence"]
    if not isinstance(evidence, list):
        raise ArchiveError(f"proposition {prop['id']} evidence must be a list")
    seen_ids: set[str] = set()
    for entry in evidence:
        if not isinstance(entry, dict):
            raise ArchiveError(f"proposition {prop['id']} evidence entries must be objects")
        _validate_evidence(prop["id"], entry, seen_ids)

    changelog = prop["changelog"]
    if not isinstance(changelog, list) or not changelog:
        raise ArchiveError(f"proposition {prop['id']} needs a non-empty changelog")
    for entry in changelog:
        if not entry.get("at") or not entry.get("action"):
            raise ArchiveError(
                f"proposition {prop['id']} changelog entries need at and action"
            )
        if entry["action"] not in CHANGELOG_ACTIONS:
            raise ArchiveError(
                f"proposition {prop['id']} has unknown changelog action {entry['action']!r}"
            )
        if entry.get("field") and entry["field"] not in CHANGELOG_FIELDS:
            raise ArchiveError(
                f"proposition {prop['id']} has unknown changelog field {entry['field']!r}"
            )

    counter = prop.get("evidence_updates_since_review", 0)
    if not isinstance(counter, int) or counter < 0:
        raise ArchiveError(
            f"proposition {prop['id']} evidence_updates_since_review must be a non-negative int"
        )


def evidence_id_for(prop: dict) -> str:
    """Next ``ev_<prop_slug>_<NN>`` id for a proposition."""
    slug_part = prop["id"][5:] if prop["id"].startswith("prop_") else prop["id"]
    base = f"ev_{slug_part}"
    taken = {e.get("id") for e in prop.get("evidence") or []}
    n = 1
    while f"{base}_{n:02d}" in taken:
        n += 1
    return f"{base}_{n:02d}"


def v3_prop_from_v2(prop: dict) -> dict:
    """Convert a v2 proposition (content + history) to the v3 shape.

    Idempotent. Each v2 history entry that carries evidence becomes one v3
    evidence entry; the conclusion is the entry's rationale (clipped), and the
    papers keep their page/quote anchors. Title/review changes go to changelog.
    """
    if "review" in prop and "evidence" in prop and "changelog" in prop:
        prop["schema_version"] = 3
        return prop
    out = {
        "schema_version": 3,
        "id": prop.get("id") or prop.get("prop_id"),
        "title": prop.get("title", ""),
        "review": prop.get("review") or prop.get("content") or prop.get("text") or "",
        "related_knowledge": list(prop.get("related_knowledge") or prop.get("node_ids") or []),
        "evidence": [],
        "changelog": [],
        "evidence_updates_since_review": int(
            prop.get("evidence_updates_since_review") or 0
        ),
        "created_at": prop.get("created_at") or now(),
        "updated_at": prop.get("updated_at") or now(),
    }
    if "under_review" in prop:
        out["under_review"] = bool(prop["under_review"])
    counter = 0
    for entry in prop.get("history") or []:
        at = entry.get("at") or now()
        papers = []
        for raw in entry.get("evidence") or []:
            quote = str(raw.get("quote") or "")
            if raw.get("paper_id") and quote:
                papers.append(
                    {
                        "paper_id": raw["paper_id"],
                        "push_id": raw.get("push_id"),
                        "page": raw.get("page"),
                        "quote": quote,
                        "added_at": at,
                    }
                )
        if papers:
            counter += 1
            out["evidence"].append(
                {
                    "id": f"ev_legacy_{counter:02d}",
                    "stance": "supports",
                    "conclusion": clip(
                        entry.get("rationale")
                        or (entry.get("after") or {}).get("content")
                        or out["review"],
                        MAX_CONCLUSION,
                    )
                    or "未提供结论（v2 迁移）",
                    "papers": papers,
                    "created_at": at,
                    "updated_at": at,
                    "migrated_from_v2": True,
                }
            )
        action = entry.get("action")
        if action == "created":
            out["changelog"].append(
                {
                    "at": at,
                    "action": "created",
                    "field": "review",
                    "before": None,
                    "after": out["review"],
                    "rationale": entry.get("rationale", ""),
                    "source": entry.get("source") or {"kind": "migration", "id": "v2"},
                }
            )
        elif action in ("title_changed", "related_knowledge_changed", "content_changed"):
            field = {
                "title_changed": "title",
                "related_knowledge_changed": "related_knowledge",
                "content_changed": "review",
            }[action]
            out["changelog"].append(
                {
                    "at": at,
                    "action": action,
                    "field": field,
                    "before": (entry.get("before") or {}).get(field),
                    "after": (entry.get("after") or {}).get(field),
                    "rationale": entry.get("rationale", ""),
                    "source": entry.get("source") or {"kind": "migration", "id": "v2"},
                }
            )
    if not out["changelog"]:
        out["changelog"].append(
            {
                "at": out["created_at"],
                "action": "created",
                "field": "review",
                "before": None,
                "after": out["review"],
                "rationale": "v2 迁移",
                "source": {"kind": "migration", "id": "v2"},
            }
        )
    # Renumber evidence ids to the canonical <prop>_<NN> scheme.
    slug_part = out["id"][5:] if out["id"].startswith("prop_") else out["id"]
    for index, entry in enumerate(out["evidence"], start=1):
        entry["id"] = f"ev_{slug_part}_{index:02d}"
    return out


class Archive:
    def __init__(self, home: Path):
        self.home = Path(home)
        self.root = self.home / "archive"
        self.raw = self.root / "raw"
        self.raw_text = self.raw / "text"
        self.pages = self.raw / "pages"
        self.pushes = self.root / "pushes"
        self.cards = self.root / "cards"
        self.props = self.root / "propositions"
        self.index = self.root / "index"
        self.applied = self.root / "applied"
        self.legacy = self.root / "legacy"

    # ---------------------------------------------------------------- setup
    def init(self) -> dict:
        for path in (
            self.raw,
            self.raw_text,
            self.pages,
            self.pushes,
            self.cards,
            self.props,
            self.index,
            self.applied,
        ):
            ensure_dir(path)
        for name in ("papers", "pushes", "cards", "propositions"):
            (self.index / f"{name}.jsonl").touch()
        return {"ok": True, "root": str(self.root)}

    def reindex(self) -> dict:
        ensure_dir(self.index)
        papers = [read_json(p) for p in sorted(self.raw.glob("*.json"))]
        pushes = [read_json(p) for p in sorted(self.pushes.glob("*.json"))]
        cards = [read_json(p) for p in sorted(self.cards.glob("*.json"))]
        props = [read_json(p) for p in sorted(self.props.glob("*.json"))]
        for name, rows in (
            ("papers", papers),
            ("pushes", pushes),
            ("cards", cards),
            ("propositions", props),
        ):
            target = self.index / f"{name}.jsonl"
            with target.open("w", encoding="utf-8") as fh:
                for row in rows:
                    if row:
                        import json

                        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {
            "ok": True,
            "papers": len(papers),
            "pushes": len(pushes),
            "cards": len(cards),
            "propositions": len(props),
        }

    # ------------------------------------------------------------ layer 1
    def _text_path(self, pid: str) -> Path:
        return self.raw_text / f"{pid}.txt"

    def find_paper(self, source: str, source_id: str) -> dict | None:
        """Look up the dedupe key ``source:source_id`` across raw records."""
        for path in sorted(self.raw.glob("*.json")):
            rec = read_json(path)
            if rec and rec.get("source") == source and rec.get("source_id") == source_id:
                return rec
        return None

    def add_paper(self, rec: dict) -> dict:
        source = rec.get("source")
        source_id = rec.get("source_id")
        if not source or not source_id:
            raise ArchiveError("paper needs source and source_id")
        pid = rec.get("paper_id") or make_paper_id(source, source_id)
        text = rec.pop("text", None)
        text_path = self._text_path(pid)
        target = self.raw / f"{pid}.json"
        existing = self.find_paper(source, source_id)
        if existing and existing["paper_id"] != pid:
            return {
                "paper_id": existing["paper_id"],
                "deduped": True,
                "repaired": False,
                "path": str(self.raw / f"{existing['paper_id']}.json"),
            }
        if target.exists():
            # Repair a missing/empty text file, never overwrite a good one.
            repaired = False
            if text and (not text_path.exists() or not text_path.read_text(encoding="utf-8").strip()):
                ensure_dir(self.raw_text)
                text_path.write_text(text, encoding="utf-8")
                repaired = True
            return {
                "paper_id": pid,
                "deduped": True,
                "repaired": repaired,
                "path": str(target),
            }

        record = {
            "schema_version": 1,
            "paper_id": pid,
            "fetched_at": now(),
            **{k: v for k, v in rec.items() if k != "paper_id"},
        }
        record["text_path"] = f"raw/text/{pid}.txt"
        write_json(target, record)
        ensure_dir(self.raw_text)
        text_path.write_text(text or rec.get("abstract", ""), encoding="utf-8")
        append_jsonl(self.index / "papers.jsonl", record)
        return {"paper_id": pid, "deduped": False, "repaired": False, "path": str(target)}

    def read_pages(self, pid: str) -> dict | None:
        return read_json(self.pages / f"{pid}.json")

    def put_pages(self, pid: str, payload: dict) -> dict:
        """Write the page-anchor sidecar; identical reruns are reported as-is."""
        target = self.pages / f"{pid}.json"
        previous = read_json(target)
        changed = True
        if previous:
            changed = {
                k: v for k, v in previous.items() if k != "extracted_at"
            } != {k: v for k, v in payload.items() if k != "extracted_at"}
        if changed:
            write_json(target, payload)
        return {
            "paper_id": pid,
            "created": previous is None,
            "changed": changed,
            "path": str(target),
        }

    def get_paper(self, pid: str) -> dict:
        rec = read_json(self.raw / f"{pid}.json")
        if not rec:
            raise ArchiveError(f"unknown paper: {pid}")
        return rec

    def list_papers(self, card_id: str | None = None) -> list[dict]:
        rows = [read_json(p) for p in sorted(self.raw.glob("*.json"))]
        rows = [r for r in rows if r]
        if card_id:
            rows = [
                r
                for r in rows
                if (r.get("card_id") or r.get("checkpoint_id")) == card_id
            ]
        return sorted(rows, key=lambda r: r.get("published") or "", reverse=True)

    # ------------------------------------------------------------ layer 2
    def add_push(self, push: dict, source_dir: Path | None = None) -> dict:
        pid = push.get("push_id")
        if not pid:
            raise ArchiveError("push needs push_id")
        push.setdefault("schema_version", 1)
        push.setdefault("created_at", now())
        push.setdefault("status", "written")
        write_json(self.pushes / f"{pid}.json", push)
        append_jsonl(self.index / "pushes.jsonl", push)
        copied = 0
        if source_dir:
            source_assets = Path(source_dir) / "assets" / pid
            if source_assets.is_dir():
                dest = self.pushes / "assets" / pid
                shutil.copytree(source_assets, dest, dirs_exist_ok=True)
                copied = len([p for p in dest.rglob("*") if p.is_file()])
        return {
            "push_id": pid,
            "path": str(self.pushes / f"{pid}.json"),
            "assets": copied,
        }

    def get_push(self, push_id: str) -> dict:
        rec = read_json(self.pushes / f"{push_id}.json")
        if not rec:
            raise ArchiveError(f"unknown push: {push_id}")
        return rec

    def list_pushes(self, card_id: str | None = None) -> list[dict]:
        rows = [read_json(p) for p in sorted(self.pushes.glob("*.json"))]
        rows = [r for r in rows if r]
        if card_id:
            rows = [
                r
                for r in rows
                if (r.get("card_id") or r.get("checkpoint_id")) == card_id
            ]
        return sorted(rows, key=lambda r: r.get("created_at") or "", reverse=True)

    # ------------------------------------------------------------ layer 3
    def put_card(self, card: dict) -> dict:
        card = dict(card)
        existing = {c["id"]: c for c in self.list_cards()}
        if not card.get("id"):
            card["id"] = card_id_for(card.get("label", ""), existing)
        _validate_card(card)
        target = self.cards / f"{card['id']}.json"
        previous = read_json(target)
        if previous and (previous.get("label") or "").lower() != card["label"].lower():
            # Changing a card's label under the same id is allowed, but make the
            # caller be explicit about the id it is updating.
            pass
        now_ts = now()
        card.setdefault("created_at", (previous or {}).get("created_at") or now_ts)
        card["updated_at"] = now_ts
        card["schema_version"] = SCHEMA_VERSION
        write_json(target, card)
        return {
            "card_id": card["id"],
            "created": previous is None,
            "path": str(target),
        }

    def get_card(self, card_id: str) -> dict:
        rec = read_json(self.cards / f"{card_id}.json")
        if not rec:
            raise ArchiveError(f"unknown card: {card_id}")
        return rec

    def list_cards(
        self, enabled_only: bool = False, *, include_under_review: bool = True
    ) -> list[dict]:
        rows = [read_json(p) for p in sorted(self.cards.glob("*.json"))]
        rows = [r for r in rows if r]
        if enabled_only:
            rows = [r for r in rows if r.get("enabled", True)]
        if not include_under_review:
            rows = [r for r in rows if not is_under_review(r)]
        return rows

    def set_under_review(
        self, record_id: str, flag: bool, *, kind: str = "card"
    ) -> dict:
        """Set or clear the optional review flag without a changelog entry.

        ``pull`` uses this for an owner's Base checkbox; the review console
        (#90) can reuse it when a kept candidate is written with the flag.
        """
        flag = bool(flag)
        if kind == "card":
            record = self.get_card(record_id)
            record["under_review"] = flag
            self.put_card(record)
        elif kind == "proposition":
            record = self.get_prop(record_id)
            record["under_review"] = flag
            self.put_prop(record)
        else:
            raise ArchiveError(f"unknown record kind {kind!r}")
        return {"kind": kind, "id": record_id, "under_review": flag}

    # ------------------------------------------------------------ layer 4
    def put_prop(self, prop: dict) -> dict:
        prop = v3_prop_from_v2(dict(prop))
        cards = {c["id"]: c for c in self.list_cards()}
        existing = {
            p.get("id") or p.get("prop_id"): p for p in self.list_props() if p
        }
        if not prop.get("id"):
            prop["id"] = prop_id_for(prop.get("title", ""), existing)
        _validate_prop(prop, cards)
        target = self.props / f"{prop['id']}.json"
        previous = read_json(target)
        now_ts = now()
        prop.setdefault("created_at", (previous or {}).get("created_at") or now_ts)
        prop["updated_at"] = now_ts
        prop["schema_version"] = SCHEMA_VERSION
        prop.setdefault("evidence_updates_since_review", 0)
        write_json(target, prop)
        return {
            "prop_id": prop["id"],
            "created": previous is None,
            "path": str(target),
        }

    def get_prop(self, prop_id: str) -> dict:
        rec = read_json(self.props / f"{prop_id}.json")
        if not rec:
            raise ArchiveError(f"unknown proposition: {prop_id}")
        return v3_prop_from_v2(rec)

    def list_props(
        self, card_id: str | None = None, *, include_under_review: bool = True
    ) -> list[dict]:
        rows = [read_json(p) for p in sorted(self.props.glob("*.json"))]
        rows = [v3_prop_from_v2(r) for r in rows if r]
        if not include_under_review:
            rows = [r for r in rows if not is_under_review(r)]
        if card_id:
            rows = [r for r in rows if card_id in r.get("related_knowledge", [])]
        return rows

    def update_prop(
        self,
        prop_id: str,
        changes: dict,
        *,
        action: str = "review_changed",
        source: dict | None = None,
        rationale: str = "",
    ) -> dict:
        prop = self.get_prop(prop_id)
        allowed = {"title", "review", "related_knowledge"}
        unknown = set(changes) - allowed
        if unknown:
            raise ArchiveError(f"cannot update {sorted(unknown)} on a proposition")
        field = next(iter(changes), None)
        before = {k: prop.get(k) for k in changes}
        prop = {**prop, **changes}
        after = {k: prop.get(k) for k in changes}
        prop.setdefault("changelog", []).append(
            {
                "at": now(),
                "action": action,
                "field": field,
                "before": before.get(field),
                "after": after.get(field),
                "rationale": rationale,
                "source": source or {"kind": "cli", "id": prop_id},
            }
        )
        self.put_prop(prop)
        return {"prop_id": prop_id, "updated": sorted(changes)}

    # ------------------------------------------------------------ context
    def context(self, card_id: str, limit: int = 5) -> dict:
        card = self.get_card(card_id)
        prop_rows = []
        for prop in self.list_props(card_id):
            prop_rows.append(
                {
                    "id": prop["id"],
                    "title": prop.get("title", ""),
                    "review": prop.get("review", ""),
                    "related_knowledge": prop.get("related_knowledge", []),
                    "evidence": prop.get("evidence", []),
                    "evidence_count": len(prop.get("evidence", [])),
                    "supports": sum(
                        1
                        for e in prop.get("evidence", [])
                        if e.get("stance") == "supports"
                    ),
                    "contradicts": sum(
                        1
                        for e in prop.get("evidence", [])
                        if e.get("stance") == "contradicts"
                    ),
                    "evidence_updates_since_review": prop.get(
                        "evidence_updates_since_review", 0
                    ),
                    "review_due": prop.get("evidence_updates_since_review", 0)
                    >= REVIEW_EVERY,
                }
            )
        papers = self.list_papers(card_id)
        pushes = self.list_pushes(card_id)
        return {
            "card": card,
            "propositions": prop_rows,
            "archived_count": len(papers),
            "recent_papers": [
                {
                    "paper_id": p["paper_id"],
                    "title": p.get("title", ""),
                    "published": p.get("published"),
                }
                for p in papers[:limit]
            ],
            "recent_pushes": [
                {"push_id": p["push_id"], "title": p.get("title", "")}
                for p in pushes[:limit]
            ],
        }

    # ------------------------------------------------------------ apply
    def apply_proposal(self, push_id: str, proposal_id: str) -> dict:
        push = self.get_push(push_id)
        proposal = next(
            (p for p in push.get("proposals", []) if p.get("proposal_id") == proposal_id),
            None,
        )
        if not proposal:
            raise ArchiveError(f"proposal {proposal_id} not found in push {push_id}")
        return self._apply(proposal)

    def apply_group(self, proposals: list[dict], group_id: str) -> dict:
        """Apply one update-question group atomically.

        Snapshots cards/propositions/applied, then applies each proposal. On any
        failure the snapshot is restored, so the queue never sees a partial
        group. Re-applying the same ``group_id`` is a no-op.
        """
        safe = re.sub(r"[^a-z0-9_]+", "_", str(group_id).lower()).strip("_") or "group"
        marker = self.applied / f"group_{safe}.json"
        previous = read_json(marker)
        if previous:
            return {**previous, "deduped": True}
        ensure_dir(self.applied)
        ensure_dir(self.root / ".tmp")
        tmp = Path(tempfile.mkdtemp(prefix="group_", dir=str(self.root / ".tmp")))
        backups = {}
        try:
            for name, path in (
                ("cards", self.cards),
                ("propositions", self.props),
                ("applied", self.applied),
            ):
                if path.exists():
                    dest = tmp / name
                    shutil.copytree(path, dest)
                    backups[name] = dest
            results = [self._apply(proposal) for proposal in proposals]
            record = {
                "schema_version": 2,
                "group_id": group_id,
                "proposal_ids": [p.get("proposal_id") for p in proposals],
                "applied_at": now(),
                "status": "applied",
                "results": results,
            }
            write_json(marker, record)
            return record
        except Exception as exc:  # noqa: BLE001 - restore then re-raise as ArchiveError
            for name, path in (
                ("cards", self.cards),
                ("propositions", self.props),
                ("applied", self.applied),
            ):
                if name in backups:
                    if path.exists():
                        shutil.rmtree(path)
                    shutil.copytree(backups[name], path)
            raise ArchiveError(f"group {group_id} failed, rolled back: {exc}") from exc
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _paper_record(self, raw: dict, push_id: str | None) -> dict:
        paper_id = raw.get("paper_id")
        if not paper_id:
            raise ArchiveError("evidence paper needs paper_id")
        quote = str(raw.get("quote") or "")
        if not 8 <= len(quote) <= 500:
            raise ArchiveError(f"evidence quote for {paper_id} must be 8..500 chars")
        page = raw.get("page")
        if page is not None and (not isinstance(page, int) or page < 1):
            raise ArchiveError(f"evidence page for {paper_id} must be >= 1 or null")
        return {
            "paper_id": paper_id,
            "push_id": raw.get("push_id") or push_id,
            "page": page,
            "quote": quote,
            "added_at": raw.get("added_at") or now(),
        }

    def _new_evidence_from_value(
        self, prop: dict, value: dict, proposal: dict
    ) -> dict:
        papers_raw = value.get("papers")
        if papers_raw is None:
            single = proposal.get("evidence") or {}
            if not single and value.get("paper_id"):
                single = value
            papers_raw = [single] if single else []
        if not isinstance(papers_raw, list) or not papers_raw:
            raise ArchiveError("add_proposition_evidence needs at least one paper")
        papers = [self._paper_record(raw, proposal.get("push_id")) for raw in papers_raw]
        conclusion = clip(
            value.get("conclusion") or proposal.get("rationale") or "", MAX_CONCLUSION
        )
        if not conclusion:
            raise ArchiveError("add_proposition_evidence needs a conclusion")
        return {
            "id": value.get("evidence_id")
            or value.get("id")
            or evidence_id_for(prop),
            "stance": value.get("stance") or "supports",
            "conclusion": conclusion,
            "papers": papers,
            "created_at": now(),
            "updated_at": now(),
        }

    def _apply(self, proposal: dict) -> dict:
        applied_path = self.applied / f"{proposal.get('proposal_id')}.json"
        previous = read_json(applied_path)
        if previous:
            return {**previous, "deduped": True}
        op = proposal.get("op") or proposal.get("kind")
        target_id = proposal.get("target_id")
        raw_value = proposal.get("diff", {}).get("value")
        value = raw_value if isinstance(raw_value, dict) else {}
        source = {
            "kind": "push",
            "id": proposal.get("push_id"),
        }

        if op in ("add_card_ontology", "add_alias", "add_ontology"):
            card = self.get_card(target_id)
            terms = raw_value if isinstance(raw_value, list) else [raw_value]
            if isinstance(value.get("term"), str):
                terms = [value["term"]]
            ontology = list(card.get("ontology", []))
            seen = {t.lower() for t in ontology}
            for term in terms:
                if isinstance(term, str) and term.strip() and term.lower() not in seen:
                    ontology.append(term.strip())
                    seen.add(term.lower())
            card["ontology"] = ontology
            self.put_card(card)
        elif op == "update_card_annotation":
            text = raw_value if isinstance(raw_value, str) else value.get("text", "")
            card = self.get_card(target_id)
            card["annotation"] = text
            self.put_card(card)
        elif op == "create_card":
            card = {
                "id": value.get("id") or None,
                "label": value.get("label"),
                "ontology": list(value.get("ontology") or []),
                "annotation": value.get("annotation"),
            }
            if not card["id"]:
                card.pop("id")
            result = self.put_card(card)
            target_id = result["card_id"]
        elif op in ("create_proposition", "add_proposition"):
            title = value.get("title")
            text = value.get("review") or value.get("content") or value.get("text", "")
            related = value.get("related_knowledge") or value.get("node_ids") or []
            raw_evidence = value.get("evidence") or []
            if not isinstance(raw_evidence, list) or len(raw_evidence) < MIN_EVIDENCE:
                raise ArchiveError(
                    f"create_proposition needs at least {MIN_EVIDENCE} evidence entries"
                )
            prop_id = prop_id_for(
                title,
                {
                    p.get("id") or p.get("prop_id"): p
                    for p in self.list_props()
                    if p
                },
                explicit=value.get("id") or value.get("prop_id"),
            )
            scaffold = {"id": prop_id, "evidence": []}
            entries = []
            for raw in raw_evidence:
                entry = {
                    "id": raw.get("id") or evidence_id_for(scaffold),
                    "stance": raw.get("stance") or "supports",
                    "conclusion": clip(raw.get("conclusion") or "", MAX_CONCLUSION),
                    "papers": [
                        self._paper_record(paper, proposal.get("push_id"))
                        for paper in (raw.get("papers") or [])
                    ],
                    "created_at": raw.get("created_at") or now(),
                    "updated_at": raw.get("updated_at") or now(),
                }
                if not entry["papers"]:
                    raise ArchiveError(
                        f"create_proposition evidence {entry['id']} needs a paper"
                    )
                scaffold["evidence"].append(entry)
                entries.append(entry)
            self.put_prop(
                {
                    "id": prop_id,
                    "title": title or clip(text, 60),
                    "review": text,
                    "related_knowledge": related,
                    "evidence": entries,
                    "changelog": [
                        {
                            "at": now(),
                            "action": "created",
                            "field": "review",
                            "before": None,
                            "after": text,
                            "rationale": proposal.get("rationale", ""),
                            "source": source,
                        }
                    ],
                    "evidence_updates_since_review": 0,
                }
            )
            target_id = prop_id
        elif op in ("add_proposition_evidence", "add_evidence"):
            prop = self.get_prop(target_id)
            entry = self._new_evidence_from_value(prop, value, proposal)
            prop.setdefault("evidence", []).append(entry)
            prop["evidence_updates_since_review"] = (
                int(prop.get("evidence_updates_since_review") or 0) + 1
            )
            self.put_prop(prop)
        elif op == "merge_proposition_evidence":
            prop = self.get_prop(target_id)
            evidence_id = value.get("target_evidence_id")
            entry = next(
                (e for e in prop.get("evidence", []) if e.get("id") == evidence_id),
                None,
            )
            if not entry:
                raise ArchiveError(
                    f"merge_proposition_evidence: unknown evidence {evidence_id}"
                )
            papers_raw = value.get("papers") or []
            if not isinstance(papers_raw, list):
                raise ArchiveError("merge_proposition_evidence papers must be a list")
            existing = {p.get("paper_id") for p in entry.get("papers", [])}
            added = 0
            for raw in papers_raw:
                paper = self._paper_record(raw, proposal.get("push_id"))
                if paper["paper_id"] in existing:
                    continue
                entry.setdefault("papers", []).append(paper)
                existing.add(paper["paper_id"])
                added += 1
            conclusion = value.get("conclusion")
            if conclusion:
                conclusion = clip(conclusion, MAX_CONCLUSION)
            if not added and not conclusion:
                raise ArchiveError(
                    "merge_proposition_evidence must add a paper or change the conclusion"
                )
            if conclusion:
                entry["conclusion"] = conclusion
            entry["updated_at"] = now()
            prop["evidence_updates_since_review"] = (
                int(prop.get("evidence_updates_since_review") or 0) + 1
            )
            self.put_prop(prop)
        elif op == "update_proposition_title":
            text = raw_value if isinstance(raw_value, str) else value.get("title", "")
            self.update_prop(
                target_id,
                {"title": text},
                action="title_changed",
                source=source,
                rationale=proposal.get("rationale", ""),
            )
        elif op in ("update_proposition_review", "update_proposition_content", "update_summary"):
            text = (
                raw_value
                if isinstance(raw_value, str)
                else value.get("review") or value.get("content") or value.get("text", "")
            )
            prop = self.get_prop(target_id)
            prop.setdefault("changelog", []).append(
                {
                    "at": now(),
                    "action": "review_changed",
                    "field": "review",
                    "before": prop.get("review", ""),
                    "after": text,
                    "rationale": proposal.get("rationale", ""),
                    "source": source,
                }
            )
            prop["review"] = text
            prop["evidence_updates_since_review"] = 0
            self.put_prop(prop)
        elif op == "update_proposition_related_knowledge":
            related = raw_value if isinstance(raw_value, list) else value.get("related_knowledge", [])
            self.update_prop(
                target_id,
                {"related_knowledge": related},
                action="related_knowledge_changed",
                source=source,
                rationale=proposal.get("rationale", ""),
            )
        else:
            raise ArchiveError(f"unknown proposal op: {op}")

        record = {
            "schema_version": 3,
            "proposal_id": proposal.get("proposal_id"),
            "push_id": proposal.get("push_id"),
            "op": op,
            "target_id": target_id,
            "applied_at": now(),
            "status": "applied",
        }
        write_json(applied_path, record)
        return record

    def apply_decisions(self, pending_dir: Path, decisions_path: Path) -> dict:
        pending_dir = Path(pending_dir)
        decisions = read_jsonl(Path(decisions_path))
        applied, rejected, skipped = [], [], []
        done = {
            r["proposal_id"]
            for r in read_jsonl(self.index / "decisions_applied.jsonl")
            if r.get("proposal_id")
        }
        for decision in decisions:
            proposal_id = decision.get("proposal_id")
            if not proposal_id:
                continue
            if proposal_id in done:
                skipped.append(proposal_id)
                continue
            if decision.get("decision") == "reject":
                record = {
                    "schema_version": 1,
                    "proposal_id": proposal_id,
                    "status": "rejected",
                    "at": now(),
                }
                write_json(self.applied / f"{proposal_id}.json", record)
                append_jsonl(self.index / "decisions_applied.jsonl", record)
                rejected.append(proposal_id)
                continue
            proposal = read_json(pending_dir / f"{proposal_id}.json")
            if not proposal:
                skipped.append(proposal_id)
                continue
            try:
                record = self._apply(proposal)
            except ArchiveError:
                skipped.append(proposal_id)
                continue
            append_jsonl(self.index / "decisions_applied.jsonl", record)
            applied.append(proposal_id)
        return {"applied": applied, "rejected": rejected, "skipped": skipped}

    # ------------------------------------------------------------ stats
    def stats(self) -> dict:
        return {
            "papers": len(list(self.raw.glob("*.json"))),
            "pushes": len(list(self.pushes.glob("*.json"))),
            "cards": len(list(self.cards.glob("*.json"))),
            "propositions": len(list(self.props.glob("*.json"))),
            "applied": len(list(self.applied.glob("*.json"))),
        }

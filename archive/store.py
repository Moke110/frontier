"""archive: the only writer of the knowledge store.

Layers (all under $KL_HOME/archive):
  1. raw/          original papers (metadata + text)
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

SCHEMA_VERSION = 2
CARD_FIELDS = ("id", "label", "ontology", "annotation")
PROP_FIELDS = ("id", "title", "content", "history", "related_knowledge")
HISTORY_ACTIONS = {
    "created",
    "content_changed",
    "title_changed",
    "related_knowledge_changed",
    "evidence_added",
}
CARD_ID_RE = re.compile(r"^card_[a-z0-9][a-z0-9_]*$")
PROP_ID_RE = re.compile(r"^prop_[a-z0-9][a-z0-9_]*$")
MIN_RELATED_CARDS = 2


def id_slug(text: str) -> str:
    """ASCII slug for ids: lower case, underscores only."""
    return slug(text, fallback="").replace("-", "_").replace(".", "_").strip("_")


class ArchiveError(RuntimeError):
    pass


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
    if not isinstance(card["ontology"], list) or not all(
        isinstance(t, str) and t.strip() for t in card["ontology"]
    ):
        raise ArchiveError("card ontology must be a non-empty list of strings")
    if not str(card["annotation"]).strip():
        raise ArchiveError("card annotation must not be empty")


def _validate_prop(prop: dict, cards: dict[str, dict]) -> None:
    missing = [f for f in PROP_FIELDS if prop.get(f) in (None, "")]
    if missing:
        raise ArchiveError(f"proposition missing {', '.join(missing)}")
    if not PROP_ID_RE.match(prop["id"]):
        raise ArchiveError(f"bad proposition id {prop['id']!r} (want prop_<slug>)")
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
    history = prop["history"]
    if not isinstance(history, list) or not history:
        raise ArchiveError(f"proposition {prop['id']} needs a non-empty history")
    for entry in history:
        if not entry.get("at") or not entry.get("action"):
            raise ArchiveError(f"proposition {prop['id']} history entries need at and action")
        if entry["action"] not in HISTORY_ACTIONS:
            raise ArchiveError(
                f"proposition {prop['id']} has unknown history action {entry['action']!r}"
            )


class Archive:
    def __init__(self, home: Path):
        self.home = Path(home)
        self.root = self.home / "archive"
        self.raw = self.root / "raw"
        self.raw_text = self.raw / "text"
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
    def add_paper(self, rec: dict) -> dict:
        source = rec.get("source")
        source_id = rec.get("source_id")
        if not source or not source_id:
            raise ArchiveError("paper needs source and source_id")
        pid = rec.get("paper_id") or make_paper_id(source, source_id)
        target = self.raw / f"{pid}.json"
        if target.exists():
            return {"paper_id": pid, "deduped": True, "path": str(target)}

        text = rec.pop("text", None) or rec.get("abstract", "")
        record = {
            "schema_version": 1,
            "paper_id": pid,
            "fetched_at": now(),
            **{k: v for k, v in rec.items() if k != "paper_id"},
        }
        record["text_path"] = f"raw/text/{pid}.txt"
        write_json(target, record)
        ensure_dir(self.raw_text)
        (self.raw_text / f"{pid}.txt").write_text(text or "", encoding="utf-8")
        append_jsonl(self.index / "papers.jsonl", record)
        return {"paper_id": pid, "deduped": False, "path": str(target)}

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

    def list_cards(self, enabled_only: bool = False) -> list[dict]:
        rows = [read_json(p) for p in sorted(self.cards.glob("*.json"))]
        rows = [r for r in rows if r]
        if enabled_only:
            rows = [r for r in rows if r.get("enabled", True)]
        return rows

    # ------------------------------------------------------------ layer 4
    def put_prop(self, prop: dict) -> dict:
        prop = dict(prop)
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
        return rec

    def list_props(self, card_id: str | None = None) -> list[dict]:
        rows = [read_json(p) for p in sorted(self.props.glob("*.json"))]
        rows = [r for r in rows if r]
        if card_id:
            rows = [r for r in rows if card_id in r.get("related_knowledge", [])]
        return rows

    def update_prop(
        self,
        prop_id: str,
        changes: dict,
        *,
        action: str = "content_changed",
        source: dict | None = None,
        rationale: str = "",
        evidence: list[dict] | None = None,
    ) -> dict:
        prop = self.get_prop(prop_id)
        before = {k: prop.get(k) for k in ("title", "content", "related_knowledge")}
        allowed = {"title", "content", "related_knowledge"}
        unknown = set(changes) - allowed
        if unknown:
            raise ArchiveError(f"cannot update {sorted(unknown)} on a proposition")
        prop = {**prop, **changes}
        after = {k: prop.get(k) for k in ("title", "content", "related_knowledge")}
        prop.setdefault("history", []).append(
            {
                "at": now(),
                "action": action,
                "source": source or {"kind": "cli", "id": prop_id},
                "before": before,
                "after": after,
                "rationale": rationale,
                "evidence": evidence or [],
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
                    "content": prop.get("content", ""),
                    "related_knowledge": prop.get("related_knowledge", []),
                    "evidence": [
                        e
                        for entry in prop.get("history", [])
                        for e in entry.get("evidence", [])
                    ],
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
        raw_evidence = proposal.get("evidence") or {}
        evidence = {
            "paper_id": raw_evidence.get("paper_id") or value.get("paper_id"),
            "push_id": proposal.get("push_id"),
            "page": raw_evidence.get("page") if raw_evidence else value.get("page"),
            "quote": raw_evidence.get("quote") or value.get("quote") or value.get("note", ""),
        }
        evidence_list = [evidence] if evidence.get("quote") or evidence.get("paper_id") else []

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
            text = value.get("content") or value.get("text", "")
            title = value.get("title") or clip(text, 60)
            related = value.get("related_knowledge") or value.get("node_ids") or []
            prop_id = prop_id_for(
                title,
                {
                    p.get("id") or p.get("prop_id"): p
                    for p in self.list_props()
                    if p
                },
                explicit=value.get("id") or value.get("prop_id"),
            )
            self.put_prop(
                {
                    "id": prop_id,
                    "title": title,
                    "content": text,
                    "related_knowledge": related,
                    "history": [
                        {
                            "at": now(),
                            "action": "created",
                            "source": source,
                            "before": None,
                            "after": {
                                "title": title,
                                "content": text,
                                "related_knowledge": related,
                            },
                            "rationale": proposal.get("rationale", ""),
                            "evidence": evidence_list,
                        }
                    ],
                }
            )
            target_id = prop_id
        elif op in ("add_proposition_evidence", "add_evidence"):
            self.update_prop(
                target_id,
                {},
                action="evidence_added",
                source=source,
                rationale=proposal.get("rationale", ""),
                evidence=evidence_list,
            )
        elif op == "update_proposition_title":
            text = raw_value if isinstance(raw_value, str) else value.get("title", "")
            self.update_prop(
                target_id,
                {"title": text},
                action="title_changed",
                source=source,
                rationale=proposal.get("rationale", ""),
                evidence=evidence_list,
            )
        elif op in ("update_proposition_content", "update_summary"):
            text = raw_value if isinstance(raw_value, str) else value.get("text", "")
            self.update_prop(
                target_id,
                {"content": text},
                action="content_changed",
                source=source,
                rationale=proposal.get("rationale", ""),
                evidence=evidence_list,
            )
        elif op == "update_proposition_related_knowledge":
            related = raw_value if isinstance(raw_value, list) else value.get("related_knowledge", [])
            self.update_prop(
                target_id,
                {"related_knowledge": related},
                action="related_knowledge_changed",
                source=source,
                rationale=proposal.get("rationale", ""),
                evidence=evidence_list,
            )
        else:
            raise ArchiveError(f"unknown proposal op: {op}")

        record = {
            "schema_version": 2,
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

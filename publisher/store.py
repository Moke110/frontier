"""Publisher-local state: message routing, ratings, pending proposals, decisions."""

from __future__ import annotations

from pathlib import Path

from common import append_jsonl, ensure_dir, read_json, read_jsonl, write_json


class PublisherStore:
    def __init__(self, home: Path):
        self.home = Path(home)
        self.root = self.home / "publisher"
        self.messages = self.root / "messages.jsonl"
        self.pending = self.root / "pending"
        self.decisions = self.root / "decisions.jsonl"
        self.outbox = self.root / "outbox"
        self.ratings = self.home / "ratings.jsonl"

    def init(self) -> None:
        for path in (self.root, self.pending, self.outbox):
            ensure_dir(path)
        self.messages.touch()
        self.decisions.touch()
        self.ratings.touch()

    # -------------------------------------------------------------- messages
    def record_message(
        self,
        message_id: str,
        kind: str,
        push_id: str,
        proposal_ids: list[str] | None = None,
        target: str = "",
    ) -> None:
        append_jsonl(
            self.messages,
            {
                "schema_version": 1,
                "message_id": message_id,
                "kind": kind,
                "push_id": push_id,
                "proposal_ids": proposal_ids or [],
                "target": target,
            },
        )

    def find_message(self, message_id: str) -> dict | None:
        found = None
        for row in read_jsonl(self.messages):
            if row.get("message_id") == message_id:
                found = row
        return found

    # -------------------------------------------------------------- ratings
    def append_rating(self, rating: dict) -> bool:
        existing = {r.get("rating_id") for r in read_jsonl(self.ratings)}
        if rating.get("rating_id") in existing:
            return False
        append_jsonl(self.ratings, rating)
        return True

    # -------------------------------------------------------------- proposals
    def stage_proposals(self, proposals: list[dict]) -> list[Path]:
        paths = []
        ensure_dir(self.pending)
        for proposal in proposals:
            proposal = {**proposal, "status": "pending_approval"}
            path = self.pending / f"{proposal['proposal_id']}.json"
            write_json(path, proposal)
            paths.append(path)
        return paths

    def pending_proposals(self) -> list[dict]:
        return [read_json(p) for p in sorted(self.pending.glob("*.json")) if read_json(p)]

    # -------------------------------------------------------------- decisions
    def append_decisions(self, rows: list[dict]) -> int:
        existing = {
            (r.get("proposal_id"), r.get("decision")) for r in read_jsonl(self.decisions)
        }
        added = 0
        for row in rows:
            key = (row.get("proposal_id"), row.get("decision"))
            if key in existing:
                continue
            append_jsonl(self.decisions, row)
            existing.add(key)
            added += 1
        return added

    # -------------------------------------------------------------- outbox
    def save_outbox(self, name: str, card: dict) -> Path:
        ensure_dir(self.outbox)
        path = self.outbox / f"{name}.json"
        write_json(path, card)
        return path

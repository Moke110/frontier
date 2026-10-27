"""Unified question queue: one active question, file-backed and lock-guarded.

Contract: `docs/specs/unified-question-queue.md`.
The queue is the only place that decides what question is active; publisher
renders and sends it, archive applies approved groups.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from archive.store import Archive, ArchiveError
from common import append_jsonl, ensure_dir, file_lock, now, read_json, write_json

TERMINAL = {"answered", "dropped"}
CARD_OPS = {
    "add_card_ontology",
    "update_card_annotation",
    "create_card",
}
PROP_OPS = {
    "create_proposition",
    "update_proposition_title",
    "update_proposition_review",
    "add_proposition_evidence",
    "merge_proposition_evidence",
    "update_proposition_related_knowledge",
}
MAX_TARGETS = 2
REVIEW_EVERY = 10
REVIEW_KIND = "proposition_review"
CORRECTION_KIND = "correction"
LEASE_MINUTES = 10
_ID_RE = re.compile(r"[^a-z0-9_]+")


class QueueError(RuntimeError):
    pass


def _safe(value: str) -> str:
    return _ID_RE.sub("_", str(value or "").lower()).strip("_") or "x"


class QueueStore:
    def __init__(self, home: Path):
        self.home = Path(home)
        self.root = self.home / "queue"
        self.state_path = self.root / "state.json"
        self.events_path = self.root / "events.jsonl"
        self.request_path = self.root / "request.json"
        self.lock_path = self.root / "lock"
        self.start_lock_path = self.root / "start.lock"

    def init(self) -> None:
        ensure_dir(self.root)
        if not self.state_path.exists() or self.state_path.stat().st_size == 0:
            write_json(self.state_path, {"schema_version": 1, "active_id": None, "items": []})
        self.events_path.touch()

    # ---------------------------------------------------------------- lock
    @contextmanager
    def locked(self) -> Iterator[None]:
        ensure_dir(self.root)
        with file_lock(self.lock_path):
            yield

    # --------------------------------------------------------------- state
    def _save(self, state: dict) -> None:
        write_json(self.state_path, state)

    def load(self) -> dict:
        state = read_json(self.state_path) or {"schema_version": 1, "active_id": None, "items": []}
        state.setdefault("active_id", None)
        state.setdefault("items", [])
        return state

    def event(self, event_type: str, **fields) -> None:
        append_jsonl(self.events_path, {"schema_version": 1, "at": now(), "kind": event_type, **fields})

    def items(self, push_id: str | None = None) -> list[dict]:
        rows = self.load()["items"]
        if push_id:
            rows = [r for r in rows if r.get("push_id") == push_id]
        return rows

    def get(self, item_id: str) -> dict:
        item = next((r for r in self.load()["items"] if r["id"] == item_id), None)
        if not item:
            raise QueueError(f"unknown queue item: {item_id}")
        return item

    def active(self) -> dict | None:
        state = self.load()
        active_id = state.get("active_id")
        if not active_id:
            return None
        return next((r for r in state["items"] if r["id"] == active_id), None)

    def has_unfinished(self) -> bool:
        return any(r.get("status") not in TERMINAL for r in self.load()["items"])

    def has_failed(self) -> bool:
        return any(r.get("status") == "failed" for r in self.load()["items"])

    # -------------------------------------------------------------- enqueue
    def enqueue_push(self, push: dict) -> dict:
        push_id = push.get("push_id")
        if not push_id:
            raise QueueError("push needs push_id")
        card_id = push.get("card_id") or push.get("checkpoint_id")
        with self.locked():
            state = self.load()
            existing = [r for r in state["items"] if r.get("push_id") == push_id]
            if existing:
                return {"ok": True, "enqueued": 0, "deduped": True, "items": existing}

            items, overflow = self._build_items(push, card_id)
            state["items"].extend(items)
            for entry in overflow:
                self.event("overflow", push_id=push_id, **entry)
            if not state.get("active_id"):
                self._activate(state)
            self._save(state)
            for item in items:
                self.event("enqueued", push_id=push_id, item_id=item["id"], kind=item["kind"])
            return {
                "ok": True,
                "enqueued": len(items),
                "overflow": overflow,
                "active": state.get("active_id"),
                "items": items,
            }

    def _build_items(self, push: dict, card_id: str | None) -> tuple[list[dict], list[dict]]:
        push_id = push["push_id"]
        created = now()
        items = [
            {
                "id": f"q_{_safe(push_id)}_rating",
                "kind": "rating",
                "push_id": push_id,
                "card_id": card_id,
                "status": "pending",
                "created_at": created,
                "sent_at": None,
                "answered_at": None,
                "message_id": None,
                "attempts": 0,
                "answer": None,
                "payload": {},
            }
        ]
        groups: list[tuple[str, str, dict]] = []
        index: dict[tuple[str, str], int] = {}
        overflow: list[dict] = []
        for proposal in push.get("proposals") or []:
            if proposal.get("status") != "draft":
                continue
            op = proposal.get("op") or proposal.get("kind")
            if op in CARD_OPS:
                target_type = "card"
            elif op in PROP_OPS:
                target_type = "proposition"
            else:
                overflow.append(
                    {
                        "reason": "unknown_op",
                        "proposal_id": proposal.get("proposal_id"),
                        "op": op,
                    }
                )
                continue
            key, label = self._target_key(proposal, target_type)
            dedupe = (target_type, key)
            if dedupe in index:
                groups[index[dedupe]][2]["proposals"].append(proposal)
            else:
                index[dedupe] = len(groups)
                groups.append(
                    (target_type, key, {"label": label, "proposals": [proposal]})
                )

        for position, (target_type, key, group) in enumerate(groups):
            if position >= MAX_TARGETS:
                overflow.append(
                    {
                        "reason": "target_limit",
                        "target_type": target_type,
                        "target": key,
                        "proposal_ids": [
                            p.get("proposal_id") for p in group["proposals"]
                        ],
                    }
                )
                continue
            kind = "card_update" if target_type == "card" else "proposition_update"
            items.append(
                self._update_item(kind, push_id, card_id, key, group, target_type)
            )
        return items, overflow

    def _target_key(self, proposal: dict, target_type: str) -> tuple[str, str]:
        op = proposal.get("op") or proposal.get("kind")
        value = (proposal.get("diff") or {}).get("value") or {}
        if op == "create_card":
            key = value.get("id") or "new_" + _safe(value.get("label"))
            return key, value.get("label") or "新建卡片"
        if op == "create_proposition":
            key = value.get("id") or "new_" + _safe(value.get("title"))
            return key, value.get("title") or "新建命题"
        target = proposal.get("target_id")
        if not target:
            raise QueueError(f"proposal {proposal.get('proposal_id')} needs target_id")
        return target, proposal.get("target_label") or target

    def _update_item(
        self,
        kind: str,
        push_id: str,
        card_id: str | None,
        target_key: str,
        group: dict,
        target_type: str,
    ) -> dict:
        proposals = group["proposals"]
        return {
            "id": f"q_{_safe(push_id)}_{'card' if target_type == 'card' else 'prop'}_{_safe(target_key)}",
            "kind": kind,
            "push_id": push_id,
            "card_id": card_id,
            "status": "pending",
            "created_at": now(),
            "sent_at": None,
            "answered_at": None,
            "message_id": None,
            "attempts": 0,
            "answer": None,
            "payload": {
                "target_type": target_type,
                "target_id": target_key if target_key and not target_key.startswith("new_") else None,
                "target_label": group["label"],
                "proposal_ids": [p.get("proposal_id") for p in proposals],
                "proposals": proposals,
            },
        }

    def _activate(self, state: dict) -> dict | None:
        active = next(
            (
                r
                for r in state["items"]
                if r["status"] == "pending"
                and (r.get("payload") or {}).get("ready", True) is not False
            ),
            None,
        )
        if not active:
            state["active_id"] = None
            return None
        active["status"] = "active"
        state["active_id"] = active["id"]
        self.event("activated", item_id=active["id"], push_id=active.get("push_id"))
        return active

    # -------------------------------------------------------------- delivery
    def next_active(self) -> dict | None:
        with self.locked():
            state = self.load()
            if state.get("active_id"):
                return next((r for r in state["items"] if r["id"] == state["active_id"]), None)
            if self.has_failed():
                return None
            item = self._activate(state)
            self._save(state)
            return item

    def mark_sent(self, item_id: str, message_id: str) -> dict:
        with self.locked():
            state = self.load()
            item = next((r for r in state["items"] if r["id"] == item_id), None)
            if not item:
                raise QueueError(f"unknown queue item: {item_id}")
            item["message_id"] = message_id
            item["sent_at"] = now()
            item["attempts"] = int(item.get("attempts") or 0) + 1
            self._save(state)
            self.event("sent", item_id=item_id, message_id=message_id)
            return item

    def mark_send_failed(self, item_id: str, error: str) -> dict:
        with self.locked():
            state = self.load()
            item = next((r for r in state["items"] if r["id"] == item_id), None)
            if not item:
                raise QueueError(f"unknown queue item: {item_id}")
            attempts = int(item.get("attempts") or 0)
            if attempts >= 3:
                item["status"] = "failed"
                item["answer"] = {"error": error}
                state["active_id"] = None
            else:
                item["status"] = "pending"
                state["active_id"] = None
            self._save(state)
            self.event("send_failed", item_id=item_id, error=error, attempts=attempts)
            return item

    # --------------------------------------------------------------- answer
    def answer(self, item_id: str, answer: dict, decisions_path: Path | None = None) -> dict:
        with self.locked():
            state = self.load()
            item = next((r for r in state["items"] if r["id"] == item_id), None)
            if not item:
                return {"ok": False, "reason": "unknown_item", "item_id": item_id}
            if item["status"] in TERMINAL:
                return {"ok": True, "deduped": True, "item": item}
            if item["status"] != "active":
                return {"ok": False, "reason": "not_active", "item": item}

            decision = None
            if item["kind"] == "rating":
                verdict = answer.get("verdict")
                if verdict not in {"irrelevant", "ok", "great"}:
                    return {"ok": False, "reason": "bad_verdict"}
                item["answer"] = answer
                item["status"] = "answered"
                item["answered_at"] = now()
                if verdict == "irrelevant":
                    for other in state["items"]:
                        if (
                            other.get("push_id") == item.get("push_id")
                            and other["kind"] != "rating"
                            and other["status"] not in TERMINAL
                        ):
                            other["status"] = "dropped"
                            other["answered_at"] = now()
                            other["answer"] = {"reason": "rating_irrelevant"}
                            self.event("dropped", item_id=other["id"], reason="rating_irrelevant")
            else:
                decision = answer.get("decision")
                allowed = (
                    {"adopt", "keep_previous"}
                    if item["kind"] == REVIEW_KIND
                    else {"agree_all", "reject_all"}
                )
                if decision not in allowed:
                    return {"ok": False, "reason": "bad_decision"}
                self._record_decision(item, decision, decisions_path)
                if decision in {"agree_all", "adopt"}:
                    try:
                        Archive(self.home).apply_group(
                            item["payload"]["proposals"], group_id=item_id
                        )
                    except ArchiveError as exc:
                        item["status"] = "failed"
                        item["answer"] = {"error": str(exc)}
                        state["active_id"] = None
                        self._save(state)
                        self.event("failed", item_id=item_id, error=str(exc))
                        return {"ok": False, "reason": "apply_failed", "error": str(exc)}
                item["answer"] = answer
                item["status"] = "answered"
                item["answered_at"] = now()

            state["active_id"] = None
            reviews = []
            if decision in {"agree_all", "adopt"} and any(
                (p.get("op") or p.get("kind"))
                in ("add_proposition_evidence", "merge_proposition_evidence", "add_evidence")
                for p in item["payload"].get("proposals", [])
            ):
                reviews = self._enqueue_due_reviews(state, item.get("push_id"))
            nxt = None
            if not any(r["status"] == "failed" for r in state["items"]):
                nxt = self._activate(state)
            self._save(state)
            self.event("answered", item_id=item_id, answer=answer)
            queue_empty = not any(r["status"] not in TERMINAL for r in state["items"])
            request = read_json(self.request_path)
            start_signal = None
            if queue_empty and request and not any(r["status"] == "failed" for r in state["items"]):
                start_signal = {
                    "ok": True,
                    "requested": True,
                    "card_id": request.get("card_id"),
                }
            result = {
                "ok": True,
                "item": item,
                "next": nxt,
                "reviews": reviews,
                "queue_empty": queue_empty,
                "start": start_signal,
            }
            return result

    def _enqueue_due_reviews(self, state: dict, push_id: str | None) -> list[dict]:
        """Queue one not-ready review item per proposition with >=10 updates."""
        out = []
        for prop in Archive(self.home).list_props():
            counter = int(prop.get("evidence_updates_since_review") or 0)
            if counter < REVIEW_EVERY:
                continue
            target = prop["id"]
            unfinished = any(
                r.get("kind") == REVIEW_KIND
                and (r.get("payload") or {}).get("target_id") == target
                and r.get("status") not in TERMINAL
                for r in state["items"]
            )
            if unfinished:
                continue
            evidence = prop.get("evidence") or []
            stats = {
                "evidence_count": len(evidence),
                "supports": sum(1 for e in evidence if e.get("stance") == "supports"),
                "contradicts": sum(1 for e in evidence if e.get("stance") == "contradicts"),
            }
            n = 1 + sum(
                1
                for r in state["items"]
                if r.get("kind") == REVIEW_KIND
                and (r.get("payload") or {}).get("target_id") == target
            )
            item = {
                "id": f"q_review_{_safe(target)}_{n:02d}",
                "kind": REVIEW_KIND,
                "push_id": push_id,
                "card_id": None,
                "status": "pending",
                "created_at": now(),
                "sent_at": None,
                "answered_at": None,
                "message_id": None,
                "attempts": 0,
                "answer": None,
                "payload": {
                    "target_type": "proposition_review",
                    "target_id": target,
                    "target_label": prop.get("title", target),
                    "stats": stats,
                    "proposal_ids": [],
                    "proposals": [],
                    "ready": False,
                    "base_url": None,
                },
            }
            state["items"].append(item)
            out.append(item)
            self.event(
                "review_due",
                item_id=item["id"],
                proposition_id=target,
                counter=counter,
            )
        return out

    def mark_review_ready(
        self,
        item_id: str,
        proposals: list[dict],
        *,
        stats: dict | None = None,
        base_url: str | None = None,
        html_path: str | None = None,
    ) -> dict:
        with self.locked():
            state = self.load()
            item = next((r for r in state["items"] if r["id"] == item_id), None)
            if not item:
                raise QueueError(f"unknown queue item: {item_id}")
            if item.get("kind") != REVIEW_KIND:
                raise QueueError(f"{item_id} is not a review item")
            item.setdefault("payload", {})
            item["payload"]["proposals"] = proposals
            item["payload"]["proposal_ids"] = [
                p.get("proposal_id") for p in proposals if p.get("proposal_id")
            ]
            item["payload"]["ready"] = True
            if stats is not None:
                item["payload"]["stats"] = stats
            if base_url:
                item["payload"]["base_url"] = base_url
            if html_path:
                item["payload"]["html_path"] = html_path
            if not state.get("active_id"):
                self._activate(state)
            self._save(state)
            self.event(
                "review_ready",
                item_id=item_id,
                proposal_ids=item["payload"]["proposal_ids"],
            )
            return item

    def mark_review_file_sent(self, item_id: str, message_id: str) -> dict:
        with self.locked():
            state = self.load()
            item = next((r for r in state["items"] if r["id"] == item_id), None)
            if not item:
                raise QueueError(f"unknown queue item: {item_id}")
            item.setdefault("payload", {})["file_message_id"] = message_id
            self._save(state)
            return item

    def review_items(self, status: str | None = None) -> list[dict]:
        rows = [r for r in self.load()["items"] if r.get("kind") == REVIEW_KIND]
        if status:
            rows = [r for r in rows if r.get("status") == status]
        return rows

    # ----------------------------------------------------------- corrections
    def enqueue_correction(
        self,
        *,
        correction_id: str,
        target_type: str,
        target_id: str | None,
        target_label: str,
        reason: str,
        proposals: list[dict] | None = None,
        card_id: str | None = None,
    ) -> dict:
        """A correction request enters the same serial queue as any other question.

        It starts not-ready: the host agent writes the corrected proposals first,
        then ``mark_correction_ready`` makes it askable. Nothing is applied by
        merely requesting a correction.
        """
        item_id = f"q_fix_{_safe(correction_id)}"
        with self.locked():
            state = self.load()
            existing = next((r for r in state["items"] if r["id"] == item_id), None)
            if existing:
                return {"ok": True, "deduped": True, "item": existing}
            item = {
                "id": item_id,
                "kind": CORRECTION_KIND,
                "push_id": None,
                "card_id": card_id,
                "status": "pending",
                "created_at": now(),
                "sent_at": None,
                "answered_at": None,
                "message_id": None,
                "attempts": 0,
                "answer": None,
                "payload": {
                    "target_type": target_type,
                    "target_id": target_id,
                    "target_label": target_label,
                    "correction_id": correction_id,
                    "reason": reason,
                    "proposal_ids": [p.get("proposal_id") for p in proposals or []],
                    "proposals": proposals or [],
                    "ready": bool(proposals),
                },
            }
            state["items"].append(item)
            if not state.get("active_id"):
                self._activate(state)
            self._save(state)
            self.event("correction_enqueued", item_id=item_id, correction_id=correction_id)
            return {"ok": True, "item": item, "active": state.get("active_id")}

    def mark_correction_ready(self, item_id: str, proposals: list[dict]) -> dict:
        with self.locked():
            state = self.load()
            item = next((r for r in state["items"] if r["id"] == item_id), None)
            if not item:
                raise QueueError(f"unknown queue item: {item_id}")
            if item.get("kind") != CORRECTION_KIND:
                raise QueueError(f"{item_id} is not a correction item")
            item.setdefault("payload", {})
            item["payload"]["proposals"] = proposals
            item["payload"]["proposal_ids"] = [
                p.get("proposal_id") for p in proposals if p.get("proposal_id")
            ]
            item["payload"]["ready"] = True
            if not state.get("active_id"):
                self._activate(state)
            self._save(state)
            self.event("correction_ready", item_id=item_id, proposal_ids=item["payload"]["proposal_ids"])
            return item

    def correction_items(self, status: str | None = None) -> list[dict]:
        rows = [r for r in self.load()["items"] if r.get("kind") == CORRECTION_KIND]
        if status:
            rows = [r for r in rows if r.get("status") == status]
        return rows

    # ------------------------------------------------------------- recovery
    def adopt(self, incoming: list[dict], *, keep_terminal: bool = True) -> dict:
        """Merge items rebuilt from persistent records into the local queue.

        Used after a machine switch: ids, statuses and proposal snapshots come
        from Feishu, so a rebuilt queue is the same queue. Terminal local items
        are never reopened — that is what stops a processed decision from being
        applied twice.
        """
        with self.locked():
            state = self.load()
            local = {row["id"]: row for row in state["items"]}
            rebuilt = kept = 0
            for item in incoming:
                current = local.get(item["id"])
                if current is None:
                    local[item["id"]] = item
                    rebuilt += 1
                    continue
                if keep_terminal and current.get("status") in TERMINAL:
                    kept += 1
                    continue
                local[item["id"]] = {
                    **item,
                    "created_at": current.get("created_at") or item.get("created_at"),
                }
                kept += 1
            state["items"] = list(local.values())
            if not any(row["id"] == state.get("active_id") for row in state["items"]):
                state["active_id"] = None
            if not state.get("active_id"):
                self._activate(state)
            self._save(state)
            self.event("adopted", rebuilt=rebuilt, kept=kept)
            return {
                "rebuilt": rebuilt,
                "kept": kept,
                "items": len(state["items"]),
                "active": state.get("active_id"),
            }

    def _record_decision(self, item: dict, decision: str, path: Path | None) -> None:
        target = Path(path or self.home / "publisher" / "decisions.jsonl")
        ensure_dir(target.parent)
        append_jsonl(
            target,
            {
                "schema_version": 1,
                "item_id": item["id"],
                "push_id": item.get("push_id"),
                "proposal_ids": item["payload"].get("proposal_ids", []),
                "decision": decision,
                "operator_id": "",
                "created_at": now(),
            },
        )

    # ---------------------------------------------------------- retry/abandon
    def retry(self, item_id: str) -> dict:
        with self.locked():
            state = self.load()
            item = next((r for r in state["items"] if r["id"] == item_id), None)
            if not item:
                return {"ok": False, "reason": "unknown_item"}
            if item["status"] != "failed":
                return {"ok": False, "reason": "not_failed"}
            item["status"] = "pending"
            item["answer"] = None
            item["message_id"] = None
            item["attempts"] = 0
            if not state.get("active_id"):
                self._activate(state)
            self._save(state)
            self.event("retried", item_id=item_id)
            return {"ok": True, "item": item, "active": state.get("active_id")}

    def abandon(self, item_id: str, reason: str = "manual_abandon") -> dict:
        with self.locked():
            state = self.load()
            item = next((r for r in state["items"] if r["id"] == item_id), None)
            if not item:
                return {"ok": False, "reason": "unknown_item"}
            if item["status"] in TERMINAL:
                return {"ok": True, "deduped": True}
            item["status"] = "dropped"
            item["answered_at"] = now()
            item["answer"] = {"reason": reason}
            if state.get("active_id") == item_id:
                state["active_id"] = None
                self._activate(state)
            self._save(state)
            self.event("abandoned", item_id=item_id, reason=reason)
            return {"ok": True, "active": state.get("active_id")}

    # ------------------------------------------------------ pending request
    def request_push(self, source: str, card_id: str | None = None) -> dict:
        with self.locked():
            request = read_json(self.request_path)
            active_lease = False
            if request and request.get("lease_until"):
                try:
                    active_lease = (
                        datetime.fromisoformat(request["lease_until"])
                        > datetime.now().astimezone()
                    )
                except ValueError:
                    active_lease = False
            if request:
                request["sources"] = sorted(set(request.get("sources", []) + [source]))
                request["count"] = int(request.get("count") or 0) + 1
                request["requested_at"] = min(
                    request.get("requested_at") or now(), now()
                )
                if active_lease:
                    request["after_start"] = True
                if card_id and not request.get("card_id"):
                    request["card_id"] = card_id
            else:
                request = {
                    "schema_version": 1,
                    "requested_at": now(),
                    "sources": [source],
                    "card_id": card_id,
                    "count": 1,
                    "after_start": False,
                    "started_at": None,
                    "lease_until": None,
                    "attempts": 0,
                    "last_error": None,
                }
            self._save_request(request)
            self.event("requested", source=source, card_id=card_id)
            return {"ok": True, "request": request}

    def _save_request(self, request: dict) -> None:
        write_json(self.request_path, request)

    def try_start(self, lease_minutes: int = LEASE_MINUTES) -> dict:
        with self.locked():
            return self.try_start_locked(lease_minutes)

    def try_start_locked(self, lease_minutes: int = LEASE_MINUTES) -> dict | None:
        request = read_json(self.request_path)
        if not request:
            return None
        if self.has_failed():
            return {"ok": False, "reason": "queue_blocked"}
        if self.has_unfinished():
            return {"ok": False, "reason": "queue_busy"}
        lease_until = request.get("lease_until")
        if lease_until:
            try:
                if datetime.fromisoformat(lease_until) > datetime.now().astimezone():
                    return {"ok": False, "reason": "starting"}
            except ValueError:
                pass
        lease_minutes = max(LEASE_MINUTES, int(lease_minutes or LEASE_MINUTES))
        started = datetime.now().astimezone()
        request["started_at"] = started.isoformat(timespec="seconds")
        request["lease_until"] = (started + timedelta(minutes=lease_minutes)).isoformat(
            timespec="seconds"
        )
        self._save_request(request)
        self.event("started", request=request, lease_minutes=lease_minutes)
        return {
            "ok": True,
            "start": True,
            "card_id": request.get("card_id"),
            "requested_at": request.get("requested_at"),
            "lease_minutes": lease_minutes,
        }

    def finish_start(self, success: bool, error: str | None = None) -> dict:
        with self.locked():
            request = read_json(self.request_path)
            if not request:
                return {"ok": True, "cleared": True}
            if success:
                if request.get("after_start"):
                    request["after_start"] = False
                    request["started_at"] = None
                    request["lease_until"] = None
                    request["requested_at"] = now()
                    self._save_request(request)
                    self.event("request_preserved")
                    return {"ok": True, "cleared": False}
                self.request_path.unlink(missing_ok=True)
                self.event("request_cleared")
                return {"ok": True, "cleared": True}
            request["lease_until"] = None
            request["started_at"] = None
            request["attempts"] = int(request.get("attempts") or 0) + 1
            request["last_error"] = error
            self._save_request(request)
            self.event("request_failed", error=error, attempts=request["attempts"])
            return {"ok": True, "cleared": False, "attempts": request["attempts"]}

    def status(self) -> dict:
        state = self.load()
        return {
            "schema_version": 1,
            "active_id": state.get("active_id"),
            "items": state["items"],
            "request": read_json(self.request_path),
        }

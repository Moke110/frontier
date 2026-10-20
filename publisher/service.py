"""Publisher service: send cards, ingest callbacks, stage approvals."""

from __future__ import annotations

import json
from pathlib import Path

from common import emit, now, read_json, read_jsonl, stable_id
from publisher import feishu
from publisher.cards import (
    ACTION_VERDICT,
    build_approval_card,
    build_confirmation_card,
    build_decision_card,
    build_rating_card,
)
from publisher.store import PublisherStore

# The map deliberately stops at rating collection. Approval cards and KB writes
# belong to the next phase; proposals stay as drafts inside the push.
ENABLE_APPROVALS = False


def _push_path(home: Path, push_id: str) -> Path:
    return Path(home) / "archive" / "pushes" / f"{push_id}.json"


def _duplicate_reason(home: Path, push: dict) -> dict | None:
    """Reject re-sending the same push or another push with an overlapping paper."""
    home = Path(home)
    push_id = push.get("push_id")
    store = PublisherStore(home)
    for row in read_jsonl(store.messages):
        if row.get("kind") == "push_file" and row.get("push_id") == push_id:
            return {"reason": "already_sent", "push_id": push_id}

    papers = set(push.get("paper_ids") or [])
    for path in sorted((home / "archive" / "pushes").glob("*.json")):
        other = read_json(path) or {}
        if other.get("push_id") == push_id:
            continue
        overlap = papers & set(other.get("paper_ids") or [])
        if overlap:
            return {
                "reason": "duplicate_paper",
                "paper_ids": sorted(overlap),
                "existing_push_id": other.get("push_id"),
            }
    return None


def send_rating(
    home: Path,
    push: dict,
    to_user: str,
    dry_run: bool = False,
    identity: str = "bot",
) -> dict:
    store = PublisherStore(home)
    store.init()
    card = build_rating_card(push)
    if dry_run:
        message_id = f"offline_rating_{push['push_id']}"
        path = store.save_outbox(f"rating_{push['push_id']}", card)
        store.record_message(message_id, "rating", push["push_id"], target=to_user)
        return {
            "ok": True,
            "dry_run": True,
            "push_id": push["push_id"],
            "message_id": message_id,
            "card_path": str(path),
        }
    sent = feishu.send_card(to_user, card, identity)
    store.record_message(sent["message_id"], "rating", push["push_id"], target=to_user)
    return {"ok": True, "dry_run": False, "push_id": push["push_id"], **sent}


def send_push(
    home: Path,
    push: dict,
    pdf_path: Path,
    to_user: str,
    dry_run: bool = False,
    identity: str = "bot",
    force: bool = False,
) -> dict:
    """Send the PDF file, then a small rating card. One paper, one push."""
    home = Path(home)
    store = PublisherStore(home)
    store.init()
    pdf_path = Path(pdf_path).expanduser().resolve()
    if not dry_run and not pdf_path.is_file():
        return {"ok": False, "reason": "pdf_not_found", "pdf": str(pdf_path)}

    if not force:
        duplicate = _duplicate_reason(home, push)
        if duplicate:
            return {"ok": False, **duplicate}

    if dry_run:
        pdf_message_id = f"offline_file_{push['push_id']}"
        store.save_outbox(
            f"file_{push['push_id']}",
            {
                "kind": "push_file",
                "push_id": push["push_id"],
                "target": to_user,
                "pdf": str(pdf_path),
                "dry_run": True,
            },
        )
    else:
        sent = feishu.send_file(to_user, str(pdf_path), identity)
        pdf_message_id = sent["message_id"]

    store.record_message(pdf_message_id, "push_file", push["push_id"], target=to_user)
    rating = send_rating(home, push, to_user, dry_run=dry_run, identity=identity)
    return {
        "ok": True,
        "dry_run": dry_run,
        "push_id": push["push_id"],
        "pdf": str(pdf_path),
        "pdf_message_id": pdf_message_id,
        "rating_message_id": rating["message_id"],
    }


def _parse_form(event: dict) -> dict:
    raw = event.get("form_value") or "{}"
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def handle_event(
    home: Path,
    event: dict,
    offline: bool = False,
    identity: str = "bot",
) -> dict:
    home = Path(home)
    store = PublisherStore(home)
    store.init()
    message_id = event.get("message_id") or ""
    action = event.get("action_name") or ""
    operator = event.get("operator_id") or ""
    token = event.get("token") or ""
    mapping = store.find_message(message_id)
    if not mapping:
        return {"ok": False, "reason": "unmapped_message", "message_id": message_id}
    push = read_json(_push_path(home, mapping["push_id"]))
    if not push:
        return {"ok": False, "reason": "unknown_push", "push_id": mapping["push_id"]}

    if mapping.get("kind") == "rating":
        verdict = ACTION_VERDICT.get(action)
        if not verdict:
            return {"ok": False, "reason": "unknown_action", "action": action}
        comment = str(_parse_form(event).get("comment") or "")
        rating = {
            "schema_version": 1,
            "rating_id": stable_id("r", message_id, action, operator),
            "push_id": push["push_id"],
            "message_id": message_id,
            "operator_id": operator,
            "verdict": verdict,
            "comment": comment,
            "created_at": now(),
        }
        stored = store.append_rating(rating)
        confirmation = build_confirmation_card(push, verdict, comment)
        if offline or not token:
            store.save_outbox(f"confirmation_{push['push_id']}", confirmation)
        else:
            feishu.update_card(token, confirmation, identity)

        result = {
            "ok": True,
            "kind": "rating",
            "push_id": push["push_id"],
            "verdict": verdict,
            "comment": comment,
            "stored": stored,
        }
        proposals = push.get("proposals") or []
        if ENABLE_APPROVALS and proposals and verdict != "irrelevant":
            store.stage_proposals(proposals)
            approval = build_approval_card(push, proposals)
            ids = [p["proposal_id"] for p in proposals]
            if offline:
                approval_id = f"offline_approval_{push['push_id']}"
                store.save_outbox(f"approval_{push['push_id']}", approval)
            else:
                chat_id = event.get("chat_id")
                target = chat_id or mapping.get("target") or ""
                sent = feishu.send_card(target, approval, identity, to_chat=bool(chat_id))
                approval_id = sent["message_id"]
            store.record_message(
                approval_id,
                "approval",
                push["push_id"],
                ids,
                target=event.get("chat_id") or mapping.get("target") or "",
            )
            result["approval_message_id"] = approval_id
            result["approval_card"] = approval
        return result

    if mapping.get("kind") == "approval":
        decision = "approve" if action == "approve" else "reject" if action == "reject" else None
        if not decision:
            return {"ok": False, "reason": "unknown_action", "action": action}
        ids = mapping.get("proposal_ids") or []
        rows = [
            {
                "schema_version": 1,
                "proposal_id": pid,
                "decision": decision,
                "operator_id": operator,
                "message_id": message_id,
                "created_at": now(),
            }
            for pid in ids
        ]
        added = store.append_decisions(rows)
        card = build_decision_card(decision, len(ids))
        if offline or not token:
            store.save_outbox(f"decision_{push['push_id']}", card)
        else:
            feishu.update_card(token, card, identity)
        return {
            "ok": True,
            "kind": "approval",
            "push_id": push["push_id"],
            "decision": decision,
            "proposal_ids": ids,
            "stored": added,
        }

    return {"ok": False, "reason": "unknown_message_kind", "kind": mapping.get("kind")}


def replay(home: Path, events_path: Path, offline: bool, identity: str) -> list[dict]:
    results = []
    with Path(events_path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            results.append(handle_event(home, event, offline=offline, identity=identity))
    return results


def listen(
    home: Path,
    identity: str = "bot",
    max_events: int = 1,
    timeout: str = "10m",
) -> int:
    count = 0
    try:
        events = feishu.consume_events(identity=identity, max_events=max_events, timeout=timeout)
        for line in events:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                emit({"ok": False, "reason": "bad_event_line", "line": line[:200]})
                continue
            try:
                result = handle_event(home, event, offline=False, identity=identity)
            except Exception as exc:  # noqa: BLE001 - keep listener alive
                result = {"ok": False, "reason": "handle_failed", "error": str(exc)}
            emit(result)
            count += 1
            if max_events and count >= max_events:
                break
    except feishu.FeishuError as exc:
        emit({"ok": False, "reason": "consume_failed", "error": str(exc)})
        return 1
    return 0

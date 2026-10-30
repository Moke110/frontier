"""Publisher service: send cards, ingest callbacks, stage approvals."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from common import append_jsonl, emit, now, read_json, read_jsonl, stable_id
from hostrun import layout
from publisher import feishu
from publisher.cards import (
    ACTION_VERDICT,
    build_approval_card,
    build_confirmation_card,
    build_decision_card,
    build_rating_card,
)
from publisher.store import PublisherStore
from publisher.update_cards import build_update_card
from question_queue.store import QueueStore

# The map deliberately stops at rating collection. Approval cards and KB writes
# belong to the next phase; proposals stay as drafts inside the push.
ENABLE_APPROVALS = False


def _push_path(home: Path, push_id: str) -> Path:
    return Path(home) / "archive" / "pushes" / f"{push_id}.json"


ATTEMPTS_REL = Path("publisher") / "send-attempts.jsonl"


def _attempts_path(home: Path) -> Path:
    return Path(home) / ATTEMPTS_REL


def _attempt_rows(home: Path) -> list[dict]:
    return read_jsonl(_attempts_path(home))


def _append_attempt(home: Path, row: dict) -> None:
    append_jsonl(_attempts_path(home), {"schema_version": 1, "at": now(), **row})


def _latest_attempt(home: Path, push_id: str) -> dict | None:
    rows = [row for row in _attempt_rows(home) if row.get("push_id") == push_id]
    return rows[-1] if rows else None


def _unresolved_attempt(home: Path, push_id: str) -> dict | None:
    """An attempt whose send outcome was never established (or never checked)."""
    latest = _latest_attempt(home, push_id)
    if latest and latest.get("state") in {"sending", "unknown"}:
        return latest
    return None


def resolve_send(
    home: Path,
    push_id: str,
    *,
    message_id: str | None = None,
    not_sent: bool = False,
) -> dict:
    """Reconcile an unknown send explicitly: it landed, or it never left."""
    home = Path(home)
    if bool(message_id) == bool(not_sent):
        return {
            "ok": False,
            "reason": "resolve_needs_one_action",
            "note": "用 --message <message_id>（已在飞书看到）或 --not-sent（确认未发出）",
            "push_id": push_id,
        }
    pending = _unresolved_attempt(home, push_id)
    if not pending:
        return {"ok": False, "reason": "no_unresolved_attempt", "push_id": push_id}
    if message_id:
        store = PublisherStore(home)
        store.init()
        store.record_message(
            str(message_id), "push_file", push_id, target=pending.get("target") or ""
        )
        _append_attempt(
            home,
            {
                "push_id": push_id,
                "attempt_id": pending.get("attempt_id"),
                "state": "sent",
                "message_id": str(message_id),
            },
        )
        return {
            "ok": True,
            "push_id": push_id,
            "state": "sent",
            "message_id": str(message_id),
        }
    _append_attempt(
        home,
        {
            "push_id": push_id,
            "attempt_id": pending.get("attempt_id"),
            "state": "not_sent",
        },
    )
    return {"ok": True, "push_id": push_id, "state": "not_sent"}


def _queue(home: Path) -> QueueStore:
    store = QueueStore(home)
    store.init()
    return store


def _spawn_log(home: Path, row: dict) -> None:
    try:
        append_jsonl(Path(home) / "publisher" / "trigger.log", row)
    except OSError:
        pass


def _spawn_alert(owner: str, text: str) -> None:
    if not owner:
        return
    try:
        feishu.send_text(owner, text)
    except feishu.FeishuError:
        pass


def _spawn_pending(home: Path, owner: str) -> dict:
    """Start the pending retrieval request in a detached process."""
    repo = Path(__file__).resolve().parents[1]
    home = Path(home)
    cmd = [sys.executable, "-m", "trigger.cli"]
    if owner:
        cmd += ["--owner", owner]
    cmd.append("run-request")
    env = {**os.environ, **layout.handoff(home)}
    log_path = home / "publisher" / "trigger-spawn.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n--- {now()} spawn: {' '.join(cmd)}\n")
            log.flush()
            proc = subprocess.Popen(
                cmd,
                cwd=str(repo),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError as exc:
        _spawn_log(home, {"schema_version": 1, "at": now(), "kind": "spawn_failed", "error": str(exc)})
        _spawn_alert(owner, f"自动拉起下一次推送失败：{exc}")
        return {"ok": False, "reason": "spawn_failed", "error": str(exc)}
    pid = getattr(proc, "pid", None)
    _spawn_log(
        home,
        {"schema_version": 1, "at": now(), "kind": "spawn", **({"pid": pid} if pid else {})},
    )
    # run-request only exits immediately when it refuses to start; a non-zero
    # exit here means the next push would silently never happen.
    time.sleep(0.5)
    code = proc.poll()
    if code not in (None, 0):
        _spawn_log(
            home,
            {"schema_version": 1, "at": now(), "kind": "spawn_exited", "pid": pid, "code": code},
        )
        _spawn_alert(owner, f"自动拉起下一次推送的进程异常退出（exit {code}），请查看 trigger-spawn.log。")
        return {"ok": False, "reason": "spawn_exited", "code": code}
    return {"ok": True, "pid": pid}


def _spawn_review(home: Path, owner: str, item_id: str) -> dict:
    """Start the review-writing agent for one queued review item."""
    repo = Path(__file__).resolve().parents[1]
    home = Path(home)
    cmd = [sys.executable, "-m", "trigger.cli"]
    if owner:
        cmd += ["--owner", owner]
    cmd += ["review-request", "--item", item_id]
    env = {**os.environ, **layout.handoff(home)}
    log_path = home / "publisher" / "trigger-spawn.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n--- {now()} spawn review: {' '.join(cmd)}\n")
            log.flush()
            proc = subprocess.Popen(
                cmd,
                cwd=str(repo),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError as exc:
        _spawn_log(home, {"schema_version": 1, "at": now(), "kind": "review_spawn_failed", "error": str(exc)})
        _spawn_alert(owner, f"命题综述生成启动失败：{exc}")
        return {"ok": False, "reason": "spawn_failed", "error": str(exc)}
    _spawn_log(
        home,
        {"schema_version": 1, "at": now(), "kind": "review_spawn", "item_id": item_id, "pid": proc.pid},
    )
    time.sleep(0.5)
    code = proc.poll()
    if code not in (None, 0):
        _spawn_alert(owner, f"命题综述生成进程异常退出（exit {code}），请查看 trigger-spawn.log。")
        return {"ok": False, "reason": "spawn_exited", "code": code}
    return {"ok": True, "pid": proc.pid}


def _spawn_sync(home: Path, owner: str) -> dict:
    """Mirror the freshly written local knowledge layer into Bitable."""
    if not (Path(home) / "knowledge" / "base.json").exists():
        return {"ok": True, "skipped": "no_config"}
    repo = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, "-m", "knowledge.cli", "sync"]
    env = {**os.environ, **layout.handoff(home)}
    log_path = Path(home) / "publisher" / "trigger-spawn.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n--- {now()} spawn sync\n")
            log.flush()
            proc = subprocess.Popen(
                cmd, cwd=str(repo), env=env, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError as exc:
        _spawn_log(home, {"schema_version": 1, "at": now(), "kind": "sync_spawn_failed", "error": str(exc)})
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "pid": proc.pid}


def _run_cli(home: Path, module: str, *args: str, timeout: int = 600) -> dict:
    """Run another module's CLI synchronously and return its JSON result."""
    repo = Path(__file__).resolve().parents[1]
    home = Path(home)
    cmd = [sys.executable, "-m", module, *args]
    env = {**os.environ, **layout.handoff(home)}
    proc = subprocess.run(
        cmd,
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        # The sibling CLIs always emit UTF-8 (Chinese JSON).  Windows would
        # otherwise decode with the locale code page and crash the reader
        # thread, hiding a successful push-library upload behind a false error.
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    try:
        result = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        result = {"ok": False, "error": (proc.stdout or proc.stderr)[-500:]}
    if proc.returncode != 0 and result.get("ok") is not False:
        result["ok"] = False
    result["exit_code"] = proc.returncode
    if proc.returncode != 0 and not result.get("error"):
        result["error"] = (proc.stderr or "").strip()[-500:]
    return result


def _library_tables(home: Path) -> dict:
    config = read_json(Path(home) / "knowledge" / "base.json") or {}
    return (config.get("tables") or {})


def _spawn_put_push(home: Path, push: dict, file_path: Path) -> dict:
    if Path(file_path).suffix.lower() not in (".html", ".htm"):
        return {"ok": True, "skipped": "legacy_pdf"}
    if not _library_tables(home).get("pushes"):
        return {"ok": True, "skipped": "no_config"}
    try:
        return _run_cli(
            home, "library.cli",
            "put-push", "--push", str(push.get("push_id")), "--html", str(file_path),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _spawn_log(home, {"schema_version": 1, "at": now(),
                          "kind": "put_push_failed", "error": str(exc)})
        return {"ok": False, "error": str(exc)}


def _spawn_decisions(home: Path) -> dict:
    if not _library_tables(home).get("decisions"):
        return {"ok": True, "skipped": "no_config"}
    try:
        return _run_cli(home, "library.cli", "decisions", "sync")
    except (OSError, subprocess.SubprocessError) as exc:
        _spawn_log(home, {"schema_version": 1, "at": now(),
                          "kind": "decisions_failed", "error": str(exc)})
        return {"ok": False, "error": str(exc)}


def _deliver_next(
    home: Path,
    store: PublisherStore,
    target: str,
    dry_run: bool,
    identity: str,
    push_override: dict | None = None,
) -> dict | None:
    """Send the active question (rating or one entity update), if any."""
    queue = _queue(home)
    item = queue.next_active()
    if not item:
        return None
    push = push_override or read_json(_push_path(home, item["push_id"]))
    if not push and item["kind"] != "proposition_review":
        return None
    file_message_id = (item.get("payload") or {}).get("file_message_id")
    if item["kind"] == "proposition_review":
        html_path = (item.get("payload") or {}).get("html_path")
        if html_path and not file_message_id:
            if dry_run:
                file_message_id = f"offline_review_file_{item['id']}"
            else:
                file_message_id = feishu.send_file(target, html_path, identity)["message_id"]
            store.record_message(
                file_message_id,
                "review_file",
                item.get("push_id"),
                target=target,
                queue_item_id=item["id"],
            )
            queue.mark_review_file_sent(item["id"], file_message_id)
    if item["kind"] == "rating":
        card = build_rating_card(push)
    else:
        siblings = queue.items(item["push_id"])
        index = next(
            (i for i, row in enumerate(siblings, start=1) if row["id"] == item["id"]), 1
        )
        card = build_update_card(push, item, index, len(siblings))
    proposal_ids = item.get("payload", {}).get("proposal_ids") or []
    kind = item["kind"] if item["kind"] in ("rating", "proposition_review") else "update"
    if dry_run:
        message_id = f"offline_{item['id']}"
        path = store.save_outbox(f"{kind}_{item['id']}", card)
    else:
        sent = feishu.send_card(target, card, identity)
        message_id = sent["message_id"]
        path = None
    store.record_message(
        message_id,
        kind,
        item["push_id"],
        proposal_ids,
        target=target,
        queue_item_id=item["id"],
    )
    queue.mark_sent(item["id"], message_id)
    return {
        "item_id": item["id"],
        "kind": kind,
        "message_id": message_id,
        "file_message_id": file_message_id,
        "card_path": str(path) if path else None,
        "card": card,
    }


def deliver_next(
    home: Path,
    target: str,
    dry_run: bool = False,
    identity: str = "bot",
) -> dict | None:
    """Send the active question (used after a review job marks its item ready)."""
    store = PublisherStore(home)
    store.init()
    return _deliver_next(home, store, target, dry_run, identity)


def _handle_queue_event(
    home: Path,
    store: PublisherStore,
    event: dict,
    mapping: dict,
    offline: bool,
    identity: str,
) -> dict:
    queue = _queue(home)
    item_id = mapping.get("queue_item_id")
    item = queue.get(item_id)
    action_value = _parse_action_value(event)
    action = event.get("action_name") or action_value.get("decision") or ""
    operator = event.get("operator_id") or ""
    token = event.get("token") or ""
    target = mapping.get("target") or event.get("chat_id") or operator
    push = read_json(_push_path(home, item["push_id"])) or {}

    if item["kind"] == "rating":
        verdict = ACTION_VERDICT.get(action)
        if not verdict:
            return {"ok": False, "reason": "unknown_action", "action": action}
        answer = {
            "verdict": verdict,
            "comment": str(_parse_form(event).get("comment") or ""),
            "operator_id": operator,
            "message_id": event.get("message_id"),
        }
        result = queue.answer(item_id, answer)
        if not result.get("ok"):
            return result
        if result.get("deduped"):
            return {"ok": True, "deduped": True, "item_id": item_id}
        rating = {
            "schema_version": 1,
            "rating_id": stable_id("r", event.get("message_id", ""), action, operator),
            "push_id": item["push_id"],
            "card_id": item.get("card_id"),
            "message_id": event.get("message_id"),
            "operator_id": operator,
            "verdict": verdict,
            "comment": answer["comment"],
            "created_at": now(),
        }
        store.append_rating(rating)
        confirmation = build_confirmation_card(push, verdict, answer["comment"])
        if offline or not token:
            store.save_outbox(f"confirmation_{item['push_id']}", confirmation)
        else:
            feishu.update_card(token, confirmation, identity)
        delivered = _deliver_next(home, store, target, offline, identity)
        if result.get("start") and not offline:
            _spawn_pending(home, operator or mapping.get("target") or "")
        return {
            "ok": True,
            "kind": "rating",
            "push_id": item["push_id"],
            "verdict": verdict,
            "comment": answer["comment"],
            "stored": True,
            "queue_empty": result.get("queue_empty"),
            "start": result.get("start"),
            "next_message_id": delivered["message_id"] if delivered else None,
        }

    if action not in {"agree_all", "reject_all", "adopt", "keep_previous"}:
        return {"ok": False, "reason": "unknown_action", "action": action}
    result = queue.answer(item_id, {"decision": action, "operator_id": operator})
    if not result.get("ok"):
        return result
    if result.get("deduped"):
        return {"ok": True, "deduped": True, "item_id": item_id}
    approved = action in {"agree_all", "adopt"}
    proposals = item.get("payload", {}).get("proposals") or []
    if proposals:
        comment = str(_parse_form(event).get("comment") or "")
        for proposal in proposals:
            append_jsonl(
                Path(home) / "publisher" / "decision_rows.jsonl",
                {
                    "schema_version": 1,
                    "question_id": item_id,
                    "push_id": item.get("push_id"),
                    "proposal_id": proposal.get("proposal_id"),
                    "target_id": proposal.get("target_id"),
                    "action": "采纳" if approved else "拒绝",
                    "comment": comment,
                    "at": now(),
                },
            )
    decision_card = build_decision_card("approve" if approved else "reject", len(
        item.get("payload", {}).get("proposal_ids") or []
    ))
    if offline or not token:
        store.save_outbox(f"decision_{item_id}", decision_card)
    else:
        feishu.update_card(token, decision_card, identity)
    delivered = _deliver_next(home, store, target, offline, identity)
    if not offline:
        if proposals:
            _spawn_decisions(home)
        if approved:
            _spawn_sync(home, operator or mapping.get("target") or "")
        for review in result.get("reviews") or []:
            _spawn_review(home, operator or mapping.get("target") or "", review["id"])
    if result.get("start") and not offline:
        _spawn_pending(home, operator or mapping.get("target") or "")
    return {
        "ok": True,
        "kind": "update",
        "push_id": item["push_id"],
        "item_id": item_id,
        "decision": action,
        "reviews": result.get("reviews") or [],
        "queue_empty": result.get("queue_empty"),
        "start": result.get("start"),
        "next_message_id": delivered["message_id"] if delivered else None,
    }


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
    """Enqueue the push's questions and send whichever question is active."""
    home = Path(home)
    store = PublisherStore(home)
    store.init()
    queue = _queue(home)
    queue.enqueue_push(push)
    delivered = _deliver_next(home, store, to_user, dry_run, identity, push_override=push)
    if not delivered:
        return {
            "ok": True,
            "dry_run": dry_run,
            "push_id": push["push_id"],
            "message_id": None,
            "reason": "no_active_question",
        }
    return {
        "ok": True,
        "dry_run": dry_run,
        "push_id": push["push_id"],
        "message_id": delivered["message_id"],
        "item_id": delivered["item_id"],
        "kind": delivered["kind"],
        "card_path": delivered["card_path"],
    }


def send_push(
    home: Path,
    push: dict,
    file_path: Path,
    to_user: str,
    dry_run: bool = False,
    identity: str = "bot",
    force: bool = False,
) -> dict:
    """Send the push file (HTML by default, PDF legacy), then the rating card."""
    home = Path(home)
    store = PublisherStore(home)
    store.init()
    file_path = Path(file_path).expanduser().resolve()
    is_html = file_path.suffix.lower() in (".html", ".htm")
    if not dry_run and not file_path.is_file():
        return {
            "ok": False,
            "reason": "html_not_found" if is_html else "pdf_not_found",
            "file": str(file_path),
        }

    if not dry_run:
        pending = _unresolved_attempt(home, push["push_id"])
        if pending:
            return {
                "ok": False,
                "reason": "send_status_unknown",
                "push_id": push["push_id"],
                "attempt_at": pending.get("at"),
                "note": (
                    "上次发送结果不明：先在飞书核对是否已收到；用 "
                    "`publisher.cli resolve-send --push <id> --message <message_id>` "
                    "登记已送达，或确认未发出后加 --not-sent；不要盲目重发"
                ),
            }

    if not force:
        duplicate = _duplicate_reason(home, push)
        if duplicate:
            return {"ok": False, **duplicate}

    if dry_run:
        file_message_id = f"offline_file_{push['push_id']}"
        store.save_outbox(
            f"file_{push['push_id']}",
            {
                "kind": "push_file",
                "push_id": push["push_id"],
                "target": to_user,
                "file": str(file_path),
                "file_type": "html" if is_html else "pdf",
                "dry_run": True,
            },
        )
    else:
        attempt_id = stable_id("sa", push["push_id"], now())
        _append_attempt(
            home,
            {
                "push_id": push["push_id"],
                "attempt_id": attempt_id,
                "target": to_user,
                "state": "sending",
            },
        )
        try:
            sent = feishu.send_file(to_user, str(file_path), identity)
        except Exception as exc:  # noqa: BLE001 - unknown outcome must be recorded
            _append_attempt(
                home,
                {
                    "push_id": push["push_id"],
                    "attempt_id": attempt_id,
                    "state": "unknown",
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return {
                "ok": False,
                "reason": "send_failed",
                "push_id": push["push_id"],
                "error": f"{type(exc).__name__}: {exc}",
                "note": "发送结果不明：先在飞书核对，再用 resolve-send 处理；不要重发",
            }
        file_message_id = sent["message_id"]
        _append_attempt(
            home,
            {
                "push_id": push["push_id"],
                "attempt_id": attempt_id,
                "state": "sent",
                "message_id": file_message_id,
            },
        )

    store.record_message(file_message_id, "push_file", push["push_id"], target=to_user)
    library = (
        {"ok": True, "skipped": "dry_run"}
        if dry_run
        else _spawn_put_push(home, push, file_path)
    )
    queue = _queue(home)
    queue.enqueue_push(push)
    delivered = _deliver_next(home, store, to_user, dry_run, identity, push_override=push)
    result = {
        "ok": True,
        "dry_run": dry_run,
        "push_id": push["push_id"],
        "file": str(file_path),
        "file_type": "html" if is_html else "pdf",
        "file_message_id": file_message_id,
        "rating_message_id": delivered["message_id"] if delivered else None,
        "first_item_id": delivered["item_id"] if delivered else None,
        "library": library,
    }
    if is_html:
        result["html"] = str(file_path)
        result["html_message_id"] = file_message_id
    else:
        result["pdf"] = str(file_path)
        result["pdf_message_id"] = file_message_id
    return result


def _parse_form(event: dict) -> dict:
    raw = event.get("form_value") or "{}"
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _parse_action_value(event: dict) -> dict:
    """Card 2.0 callback buttons arrive as a JSON string in action_value."""
    raw = event.get("action_value")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


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
    action_value = _parse_action_value(event)
    if action_value.get("queue_item_id") and not mapping.get("queue_item_id"):
        mapping = {
            **mapping,
            "queue_item_id": action_value["queue_item_id"],
            "proposal_ids": action_value.get("proposal_ids") or mapping.get("proposal_ids"),
        }
    if mapping.get("queue_item_id"):
        return _handle_queue_event(home, store, event, mapping, offline, identity)
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

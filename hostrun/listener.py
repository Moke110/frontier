"""Listener process core: the one resident frontier component (ADR 0008).

The user starts it manually; it runs in a foreground console and keeps every
decision mechanical:

    bounded event chunk -> parse -> owner-DM command whitelist -> bounded action

It writes ``<home>/listener/heartbeat.json`` every 60 s, appends to a rolling
``<home>/listener/listener.log``, holds exactly one instance through
``listener.lock``, and derives at most one model-backed host run at a time.
It never installs a service, writes PATH/registry, or retries a failed derived
run.

Command routing (decision D12):
  推一篇   -> one derived bounded host run (decision D5/D6)
  处理反馈 -> one mechanical feedback poll now, then a receipt
  状态     -> immediate receipt from ``intents.status``
  unknown  -> fixed usage hint, no execution
  group / other sender / non-message -> one log line, no reply, no action

All time, sleep, subprocess, messaging, install-report and event-source calls
are injectable, so the whole module is tested offline. The live lark-cli
envelope and the ``dsh --profile headless --prompt`` argv contract are
documented but ``untested`` against a real host here.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from common import append_jsonl, ensure_dir, file_lock, now, read_json, write_json
from hostrun import executor, intents
from hostrun.base import HostRunError, listener_dir, load_config, require_dsh
from publisher import feishu

LOCK_NAME = "listener.lock"
HEARTBEAT_NAME = "heartbeat.json"
LOG_NAME = "listener.log"
LOG_BACKUP_NAME = "listener.log.1"
STOP_NAME = "stop"
DERIVED_LOCK_NAME = "derived.lock"

HEARTBEAT_SCHEMA_VERSION = 1
LOG_MAX_BYTES = 1024 * 1024
CONSUME_TIMEOUT = "30s"
TICK_PAUSE_SECONDS = 1.0
POLL_INTERVAL_SECONDS = 1.0
DEGRADED_AFTER = 5
BACKOFF_SECONDS = (5, 15, 30, 60)

#: ``text`` -> action. Only exact commands are executed (no natural language).
COMMANDS = {"推一篇": "daily", "处理反馈": "feedback", "状态": "status"}
USAGE_HINT = "可用命令：推一篇 / 处理反馈 / 状态"
MESSAGE_EVENT_TYPE = "im.message.receive_v1"


# ------------------------------------------------------------------- paths
def lock_path(home: Path) -> Path:
    return listener_dir(home) / LOCK_NAME


def heartbeat_path(home: Path) -> Path:
    return listener_dir(home) / HEARTBEAT_NAME


def log_path(home: Path) -> Path:
    return listener_dir(home) / LOG_NAME


def stop_path(home: Path) -> Path:
    return listener_dir(home) / STOP_NAME


def derived_lock_path(home: Path) -> Path:
    return listener_dir(home) / DERIVED_LOCK_NAME


# ----------------------------------------------------------------- logging
def log_line(home: Path, message: str, *, at: str | None = None) -> str:
    """Append one rolling log line; logging never takes the listener down."""
    home = Path(home)
    path = log_path(home)
    ensure_dir(path.parent)
    try:
        if path.exists() and path.stat().st_size >= LOG_MAX_BYTES:
            backup = listener_dir(home) / LOG_BACKUP_NAME
            try:
                backup.unlink()
            except FileNotFoundError:
                pass
            path.replace(backup)
    except OSError:
        pass
    line = f"{at or now()} {str(message).rstrip()}\n"
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass
    return line


# --------------------------------------------------------------- heartbeat
def read_heartbeat(home: Path) -> dict:
    return read_json(heartbeat_path(home)) or {}


def write_heartbeat(
    home: Path,
    *,
    started_at: str | None = None,
    state: str = "running",
    last_event_at: str | None = None,
    last_success_at: str | None = None,
    consecutive_failures: int = 0,
    last_error: str = "",
    pid: int | None = None,
    at: str | None = None,
) -> dict:
    """Rewrite the heartbeat atomically (schema: decisions D2)."""
    beat = {
        "schema_version": HEARTBEAT_SCHEMA_VERSION,
        "pid": int(pid if pid is not None else os.getpid()),
        "started_at": started_at or now(),
        "updated_at": at or now(),
        "state": str(state or "running"),
        "last_event_at": last_event_at,
        "last_success_at": last_success_at,
        "consecutive_failures": int(consecutive_failures or 0),
        "last_error": str(last_error or ""),
    }
    write_json(heartbeat_path(home), beat)
    return beat


def request_stop(home: Path) -> Path:
    """Write the stop sentinel; ``serve`` consumes it at the loop top."""
    path = stop_path(home)
    ensure_dir(path.parent)
    path.write_text(now(), encoding="utf-8")
    return path


def stop_requested(home: Path) -> bool:
    return stop_path(home).exists()


# -------------------------------------------------------------- console title
def set_console_title(title: str, *, platform: str | None = None) -> bool:
    """Set the Windows console title; a guarded no-op everywhere else."""
    if (platform or os.name) != "nt":
        return False
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleTitleW.argtypes = [ctypes.c_wchar_p]
        kernel32.SetConsoleTitleW.restype = ctypes.c_bool
        return bool(kernel32.SetConsoleTitleW(str(title)))
    except Exception:  # noqa: BLE001 - a missing console is not a listener failure
        return False


# --------------------------------------------------------------- event parser
def _message_envelope(raw: object) -> tuple[dict | None, str]:
    """Return ``(envelope, event_type)`` for a message event, else ``(None, type)``."""
    if not isinstance(raw, dict):
        return None, ""
    event_type = ""
    for holder in (raw,):
        for key in ("type", "event_type"):
            value = holder.get(key)
            if isinstance(value, str) and value:
                event_type = value
                break
        if event_type:
            break
    header = raw.get("header")
    if not event_type and isinstance(header, dict) and header.get("event_type"):
        event_type = str(header["event_type"])
    data = raw.get("data")
    envelope = None
    if isinstance(data, dict) and isinstance(data.get("event"), dict):
        envelope = data["event"]
    elif isinstance(raw.get("event"), dict):
        envelope = raw["event"]
    elif isinstance(raw.get("message"), dict):
        envelope = raw
    if event_type and event_type != MESSAGE_EVENT_TYPE:
        return None, event_type
    return envelope, event_type or MESSAGE_EVENT_TYPE


def _message_text(content: object) -> str:
    if isinstance(content, dict):
        return str(content.get("text") or "")
    if isinstance(content, str):
        stripped = content.strip()
        if not stripped:
            return ""
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return stripped
        if isinstance(parsed, dict):
            return str(parsed.get("text") or "")
        if isinstance(parsed, str):
            return parsed
        return ""
    return ""


def parse_message_event(raw: object) -> dict | None:
    """Normalise one ``im.message.receive_v1`` payload (decisions D1).

    Accepts the lark-cli wrapper ``{"type", "data": {"event"}}``, the
    ``{"event": {...}}`` envelope and the bare event dict. Non-message events
    return ``None``. One real event can later correct only this function.
    """
    envelope, event_type = _message_envelope(raw)
    if envelope is None:
        return None
    message = envelope.get("message")
    if not isinstance(message, dict) or not message:
        return None
    sender = envelope.get("sender") if isinstance(envelope.get("sender"), dict) else {}
    sender_ids = sender.get("sender_id") if isinstance(sender.get("sender_id"), dict) else {}
    sender_id = (
        sender_ids.get("open_id")
        or sender_ids.get("user_id")
        or envelope.get("sender_id")
        or ""
    )
    sender_type = sender.get("sender_type") or envelope.get("sender_type") or ""
    chat_type = message.get("chat_type") or envelope.get("chat_type") or ""
    chat_id = message.get("chat_id") or envelope.get("chat_id") or ""
    message_id = message.get("message_id") or envelope.get("message_id") or ""
    message_type = message.get("message_type") or envelope.get("message_type") or "text"
    return {
        "event_type": event_type,
        "chat_type": str(chat_type or ""),
        "chat_id": str(chat_id or ""),
        "message_id": str(message_id or ""),
        "sender_type": str(sender_type or ""),
        "sender_id": str(sender_id or ""),
        "text": _message_text(message.get("content")),
        "message_type": str(message_type or "text"),
    }


# ------------------------------------------------------------ command routing
def _owner(home: Path) -> str:
    return str(intents._owner(Path(home)) or "")


def classify_message(home: Path, event: dict | None, *, owner: str | None = None) -> dict:
    """Decide the action for one parsed message; pure apart from the owner read.

    Only the verified owner's direct message (``chat_type == "p2p"``) is
    actionable. Everything else is ``ignored`` with no reply and no action.
    """
    resolved_owner = str(owner if owner is not None else _owner(home)).strip()
    decision = {
        "ok": True,
        "action": "ignored",
        "reason": "",
        "target": None,
        "text": "",
        "owner": resolved_owner,
    }
    if not event:
        decision["reason"] = "not_a_message"
        return decision
    text = str(event.get("text") or "").strip()
    decision["text"] = text
    if str(event.get("chat_type") or "") != "p2p":
        decision["reason"] = "not_owner_dm"
        return decision
    sender_type = str(event.get("sender_type") or "")
    if sender_type and sender_type != "user":
        decision["reason"] = "not_owner"
        return decision
    if not resolved_owner or str(event.get("sender_id") or "") != resolved_owner:
        decision["reason"] = "not_owner"
        return decision
    action = COMMANDS.get(text, "usage")
    decision.update(action=action, target=resolved_owner)
    if action == "usage":
        decision["reason"] = "unknown_command"
    return decision


# --------------------------------------------------------------- status view
def status_snapshot(home: Path, *, status=None) -> dict:
    """Listener + host subsystems snapshot for the ``状态`` receipt.

    ``intents.status`` stays the single read-only source of the host subsystems;
    the listener only adds its own heartbeat view.
    """
    status = status or intents.status
    subsystems = status(Path(home)) or {}
    beat = read_heartbeat(home)
    return {
        "listener": {
            "state": beat.get("state") or "offline",
            "pid": beat.get("pid"),
            "updated_at": beat.get("updated_at"),
            "consecutive_failures": beat.get("consecutive_failures", 0),
        },
        "executor": subsystems.get("executor") or {},
        "schedules": subsystems.get("schedules") or {},
        "queue": subsystems.get("queue") or {},
        "knowledge": ((subsystems.get("install") or {}).get("steps") or {}).get("knowledge"),
    }


def status_text(snapshot: dict) -> str:
    listener_state = snapshot.get("listener") or {}
    executor_state = (snapshot.get("executor") or {}).get("state") or "unknown"
    queue = snapshot.get("queue") or {}
    tasks = (snapshot.get("schedules") or {}).get("tasks") or []
    lines = [
        f"监听进程：{listener_state.get('state') or 'offline'}"
        f"（pid={listener_state.get('pid')}，心跳={listener_state.get('updated_at') or '无'}）",
        f"执行端：{executor_state}",
        f"队列：{queue.get('items', 0)} 项，未完成={'是' if queue.get('unfinished') else '否'}",
        f"知识：{snapshot.get('knowledge') or 'unknown'}",
        f"定时任务：{len(tasks)} 个",
    ]
    return "\n".join(lines)


def _reply(send, target: str, text: str) -> dict:
    """Send one receipt; a failed send is reported, never raised."""
    text = str(text)
    if send is None or not target:
        return {"ok": False, "reason": "no_target", "text": text}
    try:
        result = send(target, text)
    except Exception as exc:  # noqa: BLE001 - a reply failure must not kill the loop
        return {
            "ok": False,
            "reason": "send_failed",
            "error": f"{type(exc).__name__}: {exc}",
            "text": text,
        }
    if isinstance(result, dict) and result.get("ok") is False:
        return {**result, "text": text}
    return {"ok": True, "result": result, "text": text}


# ------------------------------------------------------------- feedback poll
def poll_feedback(home: Path, *, host: str | None = None, run=None) -> dict:
    """One mechanical feedback poll; skip while another executor holds the lease.

    Never sends a message: the listener stays quiet unless nothing changed
    (decisions D11). The explicit ``处理反馈`` command adds a receipt on top.
    """
    home = Path(home)
    run = run or intents.run
    if executor.status(home).get("state") == "held":
        return {"ok": True, "skipped": "executor_busy", "quiet": True}
    if not host:
        config = load_config(home)
        host = str((config.get("host") or {}).get("product") or "host")
    result = run(home, "feedback", host=host, minutes=5)
    if not result.get("ok") and result.get("reason") == "executor_busy":
        return {"ok": True, "skipped": "executor_busy", "quiet": True, "run": result}
    return {
        "ok": bool(result.get("ok", True)),
        "skipped": None,
        "quiet": bool(result.get("quiet", True)),
        "run": result,
    }


def _feedback_receipt(polled: dict) -> str:
    if polled.get("skipped"):
        return "执行端正忙，本轮反馈轮询已跳过。"
    result = polled.get("run") or {}
    actions = [str(action) for action in (result.get("actions") or []) if action]
    detail = "，".join(actions) if actions else "无变化"
    return f"反馈已处理（{detail}）。"


# ------------------------------------------------------------ derived runs
def derived_argv(dsh: str, brief: str) -> list[str]:
    """The recorded-``dsh`` argv for one bounded host run (decisions D5).

    The live prompt/argv contract is unverified; tests inject the spawner and
    the live acceptance stays ``untested`` until one real run is recorded.
    """
    return [str(dsh), "--profile", "headless", "--prompt", str(brief)]


def record_derived_run(home: Path, row: dict) -> dict:
    """Append a derived-run row to ``hostrun/runs.jsonl`` (decisions D4).

    Same schema as ``intents._runlog``: ``{schema_version, at, ...}`` plus the
    ``derived``/``parent`` markers, so schedules/history readers stay safe.
    """
    home = Path(home)
    entry = {"schema_version": 1, "at": now(), **row}
    entry["derived"] = True
    entry["parent"] = "listener"
    append_jsonl(home / intents.RUNS_REL, entry)
    return entry


def _install_report(home: Path) -> dict:
    # Imported lazily: install.py owns the listener steps in a sibling ticket.
    from hostrun import install

    return install.report(Path(home))


def _spawn(argv: list[str]):
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(argv, **kwargs)


def _kill_child(proc) -> None:
    try:
        if proc.poll() is None:
            proc.kill()
    except Exception:  # noqa: BLE001 - killing an already-dead child is fine
        pass


def _run_receipt(result: dict) -> str:
    actions = [str(action) for action in (result.get("actions") or []) if action]
    if actions:
        return "有界运行已完成（" + "，".join(actions) + "）。"
    return "有界运行已完成。"


def run_derived(
    home: Path,
    intent: str,
    *,
    target: str | None = None,
    send=None,
    run=None,
    spawn=None,
    report=None,
    dsh: str | None = None,
    host: str | None = None,
    clock=None,
    sleep=None,
    timeout_seconds: int | None = None,
    should_stop=None,
    on_wait=None,
) -> dict:
    """Derive at most one bounded host run (decisions D5/D6).

    Guards, in order: single-flight ``derived.lock``, no ``install report``
    blocked step, recorded absolute ``dsh``, free executor lease, a bounded
    ``intents.run`` for the intent, then at most one model session with a hard
    timeout. A failure is reported and never retried.
    """
    home = Path(home)
    config = load_config(home)
    listener_config = config.get("listener") or {}
    host = str(host or (config.get("host") or {}).get("product") or "host")
    send = send or feishu.send_text
    run = run or intents.run
    report = report or _install_report
    spawn = spawn or _spawn
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    timeout = int(
        timeout_seconds
        if timeout_seconds is not None
        else (listener_config.get("derived_timeout_seconds") or 1200)
    )
    reply_target = str(target or _owner(home))
    state: dict = {
        "ok": False,
        "reason": "",
        "intent": intent,
        "host": host,
        "reply": None,
        "reply_text": "",
    }

    def finish(reason: str, text: str, ok: bool, **extra) -> dict:
        state.update(ok=ok, reason=reason, reply=_reply(send, reply_target, text), reply_text=text)
        state.update(extra)
        log_line(home, f"derived run {intent}: {reason}")
        return state

    with file_lock(derived_lock_path(home), blocking=False) as acquired:
        if not acquired:
            return finish("derived_busy", "正在运行一次派生任务，稍后再试。", False)

        report_state = report(home) or {}
        blocked = report_state.get("blocked") or []
        if blocked:
            names = "、".join(
                str(row.get("step") if isinstance(row, dict) else row) for row in blocked
            )
            return finish(
                "install_blocked",
                f"安装检查仍有阻塞项（{names}），派生运行未启动。",
                False,
                blocked=blocked,
            )

        try:
            dsh_path = str(dsh or require_dsh(home))
        except HostRunError as exc:
            return finish(
                "dsh_missing",
                "未记录 dsh 绝对路径，派生运行未启动；先完成 listener install。",
                False,
                error=str(exc),
            )

        if executor.status(home).get("state") == "held":
            return finish("executor_busy", "执行端正忙，本次请求未启动；稍后再试。", False)

        try:
            result = run(home, intent, host=host, minutes=20)
        except HostRunError as exc:
            return finish("run_failed", "有界运行未能启动，请查看日志。", False, error=str(exc))
        if not result.get("ok"):
            reason = str(result.get("reason") or "run_failed")
            return finish(reason, f"有界运行未成功（{reason}）。", False, run=result)

        if intent != "daily" or not result.get("brief"):
            if intent == "daily":
                hint = str(result.get("next") or "")
                text = "本次没有可派生的推送；" + (f"下一步：{hint}" if hint else "队列暂无新题。")
                reason = "no_brief"
            else:
                text = _run_receipt(result)
                reason = "no_derived_session"
            record_derived_run(
                home,
                {
                    "intent": intent,
                    "host": host,
                    "ok": True,
                    "quiet": True,
                    "spawned": False,
                    "reason": reason,
                },
            )
            return finish(reason, text, intent != "daily", run=result)

        argv = derived_argv(dsh_path, str(result["brief"]))
        lease = executor.acquire(home, host=host, minutes=20)
        if not lease.get("ok"):
            return finish("executor_busy", "执行端正忙，本次请求未启动；稍后再试。", False)

        proc = None
        timed_out = False
        stopped = False
        spawn_error = ""
        returncode: int | None = None
        try:
            try:
                proc = spawn(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as exc:
                spawn_error = f"{type(exc).__name__}: {exc}"
            if proc is not None:
                deadline = clock() + timeout
                while proc.poll() is None:
                    if should_stop is not None and should_stop():
                        stopped = True
                        _kill_child(proc)
                        break
                    if clock() >= deadline:
                        timed_out = True
                        _kill_child(proc)
                        break
                    sleep(POLL_INTERVAL_SECONDS)
                    if on_wait is not None:
                        on_wait()
                returncode = proc.poll()
        finally:
            executor.release(home, host=host, ok=True, reason="derived")

        if timed_out:
            reason, ok = "timeout", False
            text = f"派生运行超时（{timeout} 秒），已终止；不会自动重试。"
        elif stopped:
            reason, ok = "stopped", False
            text = "监听进程停止，派生运行已终止。"
        elif spawn_error:
            reason, ok = "spawn_failed", False
            text = f"派生运行启动失败（{spawn_error}），不会自动重试。"
        elif returncode == 0:
            reason, ok = "ok", True
            text = f"已派生一次有界运行（intent={intent}），完成后不再重试。"
        else:
            reason, ok = "child_failed", False
            text = f"派生运行失败（退出码 {returncode}），不会自动重试。"
        record_derived_run(
            home,
            {
                "intent": intent,
                "host": host,
                "ok": ok,
                "quiet": False,
                "spawned": True,
                "reason": reason,
                "returncode": returncode,
                "timed_out": timed_out,
            },
        )
        log_line(home, f"derived run {intent}: {reason} (exit {returncode})")
        state.update(
            ok=ok,
            reason=reason,
            reply=_reply(send, reply_target, text),
            reply_text=text,
            returncode=returncode,
            timed_out=timed_out,
        )
        return state


# --------------------------------------------------------------- dispatching
def dispatch_message(
    home: Path,
    event: dict | None,
    *,
    send=None,
    target: str | None = None,
    status=None,
    run=None,
    spawn=None,
    report=None,
    dsh: str | None = None,
    host: str | None = None,
    clock=None,
    sleep=None,
    on_wait=None,
    should_stop=None,
) -> dict:
    """Execute the action chosen by :func:`classify_message`.

    Ignored messages do nothing (only a log line). Explicit commands reply to
    the owner. ``推一篇`` delegates to :func:`run_derived`, which sends its own
    receipts so the wait never blocks the event loop twice.
    """
    home = Path(home)
    send = send or feishu.send_text
    decision = classify_message(home, event)
    outcome = {**decision, "replied": False, "reply": None, "reply_text": None}
    action = decision["action"]
    if action == "ignored":
        log_line(home, f"ignored message ({decision['reason']})")
        return outcome
    reply_target = str(target or decision.get("target") or "")
    if action == "daily":
        derived = run_derived(
            home,
            "daily",
            target=reply_target,
            send=send,
            run=run,
            spawn=spawn,
            report=report,
            dsh=dsh,
            host=host,
            clock=clock,
            sleep=sleep,
            on_wait=on_wait,
            should_stop=should_stop,
        )
        outcome.update(
            status="derived",
            derived=derived,
            replied=bool(derived.get("reply_text")),
            reply=derived.get("reply"),
            reply_text=derived.get("reply_text"),
        )
        return outcome
    if action == "status":
        text = status_text(status_snapshot(home, status=status))
    elif action == "feedback":
        text = _feedback_receipt(poll_feedback(home, host=host, run=run))
    else:
        text = USAGE_HINT
    reply = _reply(send, reply_target, text)
    outcome.update(replied=True, reply=reply, reply_text=text)
    return outcome


# ---------------------------------------------------------------- serve loop
def _chunk_lifecycle(chunk: dict) -> tuple[str, str]:
    kind = str(chunk.get("kind") or chunk.get("reason") or "consume_failed")
    if chunk.get("ok"):
        return "ok", "ok"
    if chunk.get("retryable") and not chunk.get("fatal"):
        return "transient", kind
    return "fatal", kind


def _sleep_with_heartbeat(seconds: float, *, sleep, heartbeat_seconds: int, beat_write) -> None:
    """Sleep in heartbeat-sized steps so the heartbeat keeps flowing (D9)."""
    remaining = float(seconds)
    step_max = float(max(1, heartbeat_seconds))
    while remaining > 0:
        step = min(remaining, step_max)
        sleep(step)
        remaining -= step
        beat_write()


def serve(
    home: Path,
    *,
    identity: str = "bot",
    event_key: str = MESSAGE_EVENT_TYPE,
    consume=None,
    run=None,
    send=None,
    spawn=None,
    status=None,
    report=None,
    dsh: str | None = None,
    clock=None,
    sleep=None,
    set_title=None,
) -> dict:
    """Run the foreground listener loop until stop sentinel / fatal failure.

    Every dependency is injectable for offline tests. Returns a summary dict;
    ``ok=False`` from exit code 3 (permission scope) or another fatal consume
    failure, and ``{"reason": "already_running"}`` when the lock is held.
    """
    home = Path(home)
    config = load_config(home)
    listener_config = config.get("listener") or {}
    heartbeat_seconds = max(1, int(listener_config.get("heartbeat_seconds") or 60))
    feedback_seconds = max(1, int(listener_config.get("feedback_poll_seconds") or 300))
    host = str((config.get("host") or {}).get("product") or "host")
    title = str(listener_config.get("window_title") or "frontier-listener")
    consume = consume or feishu.listen_events
    run = run or intents.run
    send = send or feishu.send_text
    spawn = spawn or _spawn
    report = report or _install_report
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    title_setter = set_title or set_console_title

    ensure_dir(listener_dir(home))
    with file_lock(lock_path(home), blocking=False) as acquired:
        if not acquired:
            return {"ok": False, "reason": "already_running", "lock": str(lock_path(home))}
        # Only the instance that owns the lock may clear a stale sentinel; a
        # second start must not cancel a stop requested for the running one.
        stop_path(home).unlink(missing_ok=True)

        log_line(home, "listener starting")
        title_setter(title)
        beat = {
            "started_at": now(),
            "pid": os.getpid(),
            "state": "running",
            "last_event_at": None,
            "last_success_at": None,
            "consecutive_failures": 0,
            "last_error": "",
        }

        def write_beat() -> dict:
            return write_heartbeat(home, **beat)

        write_beat()
        last_heartbeat = clock()
        last_feedback = clock()
        events = 0
        ticks = 0
        failures = 0

        def maybe_heartbeat() -> None:
            nonlocal last_heartbeat
            if clock() - last_heartbeat >= heartbeat_seconds:
                write_beat()
                last_heartbeat = clock()

        def on_ready(ready_key) -> None:
            log_line(home, f"event consume ready ({ready_key or event_key})")

        def on_line(line: str) -> None:
            nonlocal events
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                log_line(home, "bad_event_line")
                return
            event = parse_message_event(raw)
            if event is None:
                log_line(home, "ignored non-message event")
                return
            beat["last_event_at"] = now()
            events += 1
            dispatch_message(
                home,
                event,
                send=send,
                run=run,
                spawn=spawn,
                report=report,
                dsh=dsh,
                status=status,
                host=host,
                clock=clock,
                sleep=sleep,
                on_wait=maybe_heartbeat,
                should_stop=lambda: stop_requested(home),
            )

        try:
            while True:
                if stop_requested(home):
                    try:
                        stop_path(home).unlink()
                    except OSError:
                        pass
                    log_line(home, "stop sentinel found; exiting")
                    return {
                        "ok": True,
                        "reason": "stopped",
                        "events": events,
                        "ticks": ticks,
                        "heartbeat": dict(beat),
                    }
                maybe_heartbeat()
                ticks += 1
                chunk = consume(
                    identity=identity,
                    event_key=event_key,
                    max_events=0,
                    timeout=CONSUME_TIMEOUT,
                    on_line=on_line,
                    on_ready=on_ready,
                )
                lifecycle, kind = _chunk_lifecycle(chunk or {})
                if lifecycle == "fatal":
                    beat["state"] = "degraded"
                    beat["last_error"] = f"{kind} (exit {chunk.get('returncode')})"
                    write_beat()
                    log_line(
                        home,
                        f"fatal consume failure: {kind} (exit {chunk.get('returncode')})",
                    )
                    return {
                        "ok": False,
                        "reason": kind,
                        "returncode": chunk.get("returncode"),
                        "events": events,
                        "ticks": ticks,
                        "heartbeat": dict(beat),
                    }
                if lifecycle == "transient":
                    failures += 1
                    beat["consecutive_failures"] = failures
                    beat["last_error"] = f"{kind} (exit {chunk.get('returncode')})"
                    if failures >= DEGRADED_AFTER:
                        beat["state"] = "degraded"
                    write_beat()
                    delay = BACKOFF_SECONDS[min(failures - 1, len(BACKOFF_SECONDS) - 1)]
                    log_line(
                        home,
                        f"transient consume failure {failures}: {kind}; backing off {delay}s",
                    )
                    _sleep_with_heartbeat(
                        delay,
                        sleep=sleep,
                        heartbeat_seconds=heartbeat_seconds,
                        beat_write=write_beat,
                    )
                    last_heartbeat = clock()
                    continue

                was_degraded = beat["state"] != "running" or beat["consecutive_failures"] != 0
                failures = 0
                beat["consecutive_failures"] = 0
                beat["state"] = "running"
                beat["last_error"] = ""
                beat["last_success_at"] = now()
                if was_degraded or clock() - last_heartbeat >= heartbeat_seconds:
                    write_beat()
                    last_heartbeat = clock()
                if clock() - last_feedback >= feedback_seconds:
                    polled = poll_feedback(home, host=host, run=run)
                    last_feedback = clock()
                    if polled.get("skipped"):
                        log_line(home, f"feedback poll skipped ({polled['skipped']})")
                sleep(TICK_PAUSE_SECONDS)
        finally:
            log_line(home, "listener stopped")

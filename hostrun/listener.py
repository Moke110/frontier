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
are injectable, so the whole module is tested offline. The live lark-cli event
envelope and the ``dsh --profile headless "<task>"`` argv were verified against
a real host on 2026-10-30 (the headless profile takes the task positionally and
has no ``--prompt`` flag).
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
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
DEFAULT_HEARTBEAT_STALE_SECONDS = 600
DEFAULT_EVENT_STALE_SECONDS = 3600
# Win32 constants for the pid-liveness check (#70): a usable OpenProcess handle
# is not proof of life; the wait result is.
PROCESS_SYNCHRONIZE = 0x00100000
WAIT_TIMEOUT = 0x102
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
#: Immediate receipts for the background derived run (ADR 0008 §5, #72 item 2).
DERIVED_STARTED_TEXT = "已开始派生的有界运行，完成后会再回执。"
DERIVED_BUSY_TEXT = "正在运行一次派生任务，稍后再试。"
#: Lease for one derived run (prepare + child wait); renewed while the child runs.
DERIVED_LEASE_MINUTES = 20
#: Immediate receipts for the background feedback poll (#73).
FEEDBACK_STARTED_TEXT = "已开始处理反馈，完成后会再回执。"
FEEDBACK_BUSY_TEXT = "正在处理反馈，稍后再试。"
#: Worker appends and the loop's own appends must never interleave (#73).
LOG_LOCK = threading.Lock()


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
    """Append one rolling log line; logging never takes the listener down.

    ``LOG_LOCK`` serialises rotation + the single append, so a worker thread and
    the main loop cannot interleave or truncate each other's lines (#73).
    """
    home = Path(home)
    path = log_path(home)
    ensure_dir(path.parent)
    line = f"{at or now()} {str(message).rstrip()}\n"
    try:
        with LOG_LOCK:
            if path.exists() and path.stat().st_size >= LOG_MAX_BYTES:
                backup = listener_dir(home) / LOG_BACKUP_NAME
                try:
                    backup.unlink()
                except FileNotFoundError:
                    pass
                path.replace(backup)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
    except OSError:
        pass
    return line


# --------------------------------------------------------------- heartbeat
def read_heartbeat(home: Path) -> dict:
    return read_json(heartbeat_path(home)) or {}


def _age_seconds(updated_at, moment: datetime) -> int | None:
    """Seconds between a heartbeat timestamp and ``moment``.

    The listener writes offset-aware timestamps; a naive one is read as UTC,
    the same convention the install probe uses.
    """
    try:
        updated = datetime.fromisoformat(str(updated_at))
    except (TypeError, ValueError):
        return None
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return max(0, int((moment - updated).total_seconds()))


def _read_heartbeat_payload(path: Path) -> tuple[dict | None, str]:
    """Read one heartbeat file, keeping the reason it cannot be used."""
    path = Path(path)
    if not path.exists():
        return None, ""
    try:
        payload = read_json(path)
    except (OSError, ValueError) as exc:
        return None, f"心跳文件不可读：{path}（{type(exc).__name__}）"
    if not isinstance(payload, dict):
        return None, f"心跳文件格式不正确：{path}"
    return payload, ""


def heartbeat_facts(
    home: Path,
    *,
    moment: datetime | None = None,
    stale_seconds: int = DEFAULT_HEARTBEAT_STALE_SECONDS,
) -> dict:
    """One canonical read of the heartbeat: payload, age and freshness (D2).

    Shared by the ``listener-check`` intent and the install probe, so the
    freshness window and the naive-UTC handling cannot drift between callers.
    A missing file is ``present=False`` without a problem; an unreadable or
    malformed one is ``present=True`` plus ``problem``.
    """
    home = Path(home)
    moment = moment or datetime.now().astimezone()
    path = heartbeat_path(home)
    facts = {
        "path": str(path),
        "present": False,
        "problem": "",
        "payload": None,
        "updated_at": None,
        "age_seconds": None,
        "state": "unknown",
        "pid": None,
        "degraded": False,
    }
    if not path.exists():
        return facts
    facts["present"] = True
    payload, problem = _read_heartbeat_payload(path)
    if problem:
        facts["problem"] = problem
        return facts
    payload = payload or {}
    facts["payload"] = payload
    facts["updated_at"] = payload.get("updated_at")
    facts["pid"] = payload.get("pid")
    facts["degraded"] = payload.get("state") == "degraded"
    facts["age_seconds"] = _age_seconds(facts["updated_at"], moment)
    if facts["age_seconds"] is not None:
        facts["state"] = "online" if facts["age_seconds"] <= int(stale_seconds) else "stale"
    return facts


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


# -------------------------------------------------------- process lifecycle
def pid_alive(pid, *, platform: str | None = None, kernel32=None, kill=None) -> bool:
    """Whether ``pid`` names a process that is still running (#70).

    On Windows an already-exited process can still yield a usable handle while
    another handle keeps the process object alive, so ``OpenProcess`` alone is
    not proof of life: after opening, the process is only alive when
    ``WaitForSingleObject(handle, 0)`` returns ``WAIT_TIMEOUT``, and the handle
    is always closed.  POSIX keeps the ``os.kill(pid, 0)`` probe.  ``kernel32``
    and ``kill`` are injectable, so the decision is testable offline without a
    real process table or the real Windows API.
    """
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    if (platform or os.name) == "nt":
        if kernel32 is None:
            import ctypes

            kernel32 = ctypes.windll.kernel32
        try:
            handle = kernel32.OpenProcess(PROCESS_SYNCHRONIZE, False, value)
        except Exception:  # noqa: BLE001 - an unavailable API is not proof of life
            return False
        if not handle:
            return False
        try:
            return int(kernel32.WaitForSingleObject(handle, 0)) == WAIT_TIMEOUT
        except Exception:  # noqa: BLE001 - an unknown wait result is not proof of life
            return False
        finally:
            try:
                kernel32.CloseHandle(handle)
            except Exception:  # noqa: BLE001 - closing must not mask the judgement
                pass
    probe = kill or os.kill
    try:
        probe(value, 0)
    except OSError:
        return False
    return True


def start_argv(command: str) -> list[str]:
    """Spawn argv for the recorded start script (batch files need cmd.exe)."""
    text = str(command)
    if os.name == "nt" and Path(text).suffix.lower() in (".cmd", ".bat"):
        return [os.environ.get("COMSPEC") or "cmd.exe", "/c", text]
    return [text]


def spawn_detached(
    argv: list[str],
    *,
    new_console: bool = False,
    new_session: bool = True,
    **kwargs,
):
    """One detached ``Popen`` contract: no inherited stdio, never blocks.

    ``new_console`` gives the listener start command its own Windows console
    window; ``new_session`` (POSIX) detaches it from the caller's session.  A
    derived model child keeps the listener's console/session so stopping the
    listener still ends it, which is why both toggles exist.
    """
    options = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    options.update(kwargs)
    if os.name == "nt":
        flags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        if new_console:
            flags |= int(getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        options["creationflags"] = flags
    elif new_session:
        options["start_new_session"] = True
    return subprocess.Popen(argv, **options)


# -------------------------------------------------------------- console title
def set_console_title(title: str, *, platform: str | None = None) -> bool:
    """Set the Windows console title; a guarded no-op everywhere else.

    ``platform`` is an intentional injection seam, not test-only production
    surface: the Windows branch cannot be exercised on a POSIX CI host, and
    patching the global ``os.name`` from a test would leak into other modules.
    ``serve`` calls this with the title only.
    """
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
    for key in ("type", "event_type"):
        value = raw.get(key)
        if isinstance(value, str) and value:
            event_type = value
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
def classify_message(home: Path, event: dict | None, *, owner: str | None = None) -> dict:
    """Decide the action for one parsed message; pure apart from the owner read.

    Only the **verified** owner's direct message (``chat_type == "p2p"``) is
    actionable (ADR 0008 §3).  ``intents.verified_owner`` returns ``""`` for a
    missing/unverified record, so everything is ``ignored`` with no reply and no
    action rather than falling back to the unverified config owner.
    """
    resolved_owner = str(
        owner if owner is not None else intents.verified_owner(home)
    ).strip()
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

    ``minutes`` is the executor lease **duration**, not the poll interval: the
    lease must cover a whole maintenance-shaped feedback run (observed up to
    ~13 minutes) or the next 5-minute tick would see a free lease and start a
    second concurrent run (ADR 0008 §8).  ``listener.feedback_lease_minutes``
    (default 45, the bounded-run default) sizes it.

    Never sends a message: the listener stays quiet unless nothing changed
    (decisions D11). The explicit ``处理反馈`` command adds a receipt on top.
    """
    home = Path(home)
    run = run or intents.run
    config = load_config(home)
    if executor.status(home).get("state") == "held":
        return {"ok": True, "skipped": "executor_busy", "quiet": True}
    if not host:
        host = str((config.get("host") or {}).get("product") or "host")
    listener_config = config.get("listener") or {}
    lease_minutes = int(
        listener_config.get("feedback_lease_minutes") or executor.DEFAULT_MINUTES
    )
    result = run(home, "feedback", host=host, minutes=lease_minutes)
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


def _feedback_result_text(polled: dict) -> str | None:
    """Result receipt for an explicit ``处理反馈`` worker (#73).

    ``None`` means "nothing changed": the listener stays quiet, matching the
    automatic poll (decision D11).  Skips and failures are always reported.
    """
    if polled.get("skipped"):
        return "执行端正忙，本轮反馈轮询已跳过。"
    result = polled.get("run") or {}
    if not polled.get("ok", True):
        return f"反馈处理失败（{result.get('reason') or 'failed'}）。"
    if polled.get("quiet"):
        return None
    return _feedback_receipt(polled)


# ------------------------------------------------------------ derived runs
def derived_argv(dsh: str, brief: str) -> list[str]:
    """The recorded-``dsh`` argv for one bounded host run (decisions D5).

    Verified live on 2026-10-30 against DeepSeek Harness 0.2.1-rc.3: the
    headless profile takes the task as a positional argument (``dsh
    --profile headless "task"``) and has no ``--prompt`` flag.  Tests inject
    the spawner; the argv shape is asserted offline.
    """
    return [str(dsh), "--profile", "headless", str(brief)]


def derived_brief(home: Path, brief: str, *, repo: str, python: str = "") -> str:
    """Prefix a pipeline brief with ADR 0008 §5's environment/skill contract.

    A derived run must use the same repository, data root, interpreter and
    ``frontier-run`` skill as the scheduled task.  The live
    ``dsh --profile headless`` prompt/skill-loading behaviour is **untested**
    against a real host; tests inject the spawner and one real derived run must
    still be recorded before this is claimed as working.
    """
    lines = [
        "frontier 派生运行（ADR 0008 §5）：必须加载 frontier-run 技能，"
        "按其正向链路执行，只处理一篇；数据根使用环境变量 KL_HOME。",
        f"- 仓库：{repo}",
        f"- 数据根：{home}（KL_HOME）",
    ]
    if python:
        lines.append(f"- 记录的解释器：{python}")
    lines.extend(["", str(brief)])
    return "\n".join(lines)


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


def _spawn(argv: list[str], **kwargs):
    """Derived-run spawner: canonical contract, listener's session retained."""
    return spawn_detached(argv, new_session=False, **kwargs)


def start_daemon(target) -> threading.Thread:
    """Run one derived run off the event loop (daemon: exit ends it).

    The worker owns the single-flight ``derived.lock`` and its own receipts; the
    main loop keeps consuming events, writing the heartbeat and polling
    feedback meanwhile (ADR 0008 §5, #72 item 2).
    """
    thread = threading.Thread(target=target, name="frontier-derived", daemon=True)
    thread.start()
    return thread


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


def _renew_derived_lease(home: Path, *, host: str) -> None:
    """Extend the derived run's executor lease (#73 follow-up).

    The initial ``DERIVED_LEASE_MINUTES`` window must cover the *prepare* step
    (feedback/maintenance/retrieval can take minutes) plus the child wait (up to
    ``derived_timeout_seconds``).  Renewing before the spawn and on every wait
    tick keeps the same host as the lease holder, so no other host can take over
    mid-run.  A failed renewal is logged, never raised.
    """
    outcome = executor.heartbeat(home, host=host, minutes=DERIVED_LEASE_MINUTES)
    if not outcome.get("ok"):
        log_line(home, f"derived lease renewal failed: {outcome.get('reason')}")


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
    paths = config.get("paths") or {}
    repo_dir = str(paths.get("repo") or home)
    interpreter = str(paths.get("python") or "")
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
    reply_target = str(target or intents.verified_owner(home))
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

        # ADR 0008 §5/§8: take the executor lease *before* preparing the run, so
        # request_push/try_start and the spawned child share one continuous
        # lease, and a failed acquire leaves the queue/cards untouched.  It is
        # released in the finally below for every outcome; the inner bounded run
        # is told `lease=False` so it never releases the listener's lease.
        acquired = executor.acquire(home, host=host, minutes=DERIVED_LEASE_MINUTES)
        if not acquired.get("ok"):
            return finish("executor_busy", "执行端正忙，本次请求未启动；稍后再试。", False)

        timed_out = False
        stopped = False
        spawn_error = ""
        returncode: int | None = None
        try:
            try:
                result = run(home, intent, host=host, minutes=20, lease=False)
            except HostRunError as exc:
                return finish(
                    "run_failed", "有界运行未能启动，请查看日志。", False, error=str(exc)
                )
            if not result.get("ok"):
                reason = str(result.get("reason") or "run_failed")
                return finish(reason, f"有界运行未成功（{reason}）。", False, run=result)

            if intent != "daily" or not result.get("brief"):
                if intent == "daily":
                    hint = str(result.get("next") or "")
                    text = "本次没有可派生的推送；" + (
                        f"下一步：{hint}" if hint else "队列暂无新题。"
                    )
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

            argv = derived_argv(
                dsh_path,
                derived_brief(home, str(result["brief"]), repo=repo_dir, python=interpreter),
            )
            env = {**os.environ, "KL_HOME": str(home)}
            # The prepare step above may itself have consumed minutes; renew the
            # lease before the child starts, then on every wait tick so the
            # 20-minute window never expires mid-run (#73 follow-up).
            _renew_derived_lease(home, host=host)
            proc = None
            try:
                proc = spawn(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=repo_dir,
                    env=env,
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
                    _renew_derived_lease(home, host=host)
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
    inflight: dict | None = None,
    start_worker=None,
) -> dict:
    """Execute the action chosen by :func:`classify_message`.

    Ignored messages do nothing (only a log line). Explicit commands reply to
    the owner. ``推一篇`` replies immediately with "已开始", then starts
    :func:`run_derived` on a daemon worker (``start_worker`` is injectable); the
    worker sends the completion/failure receipt itself, so the event loop never
    waits for the child.  ``inflight`` is the loop-shared single-flight marker:
    a second ``推一篇`` while one is running gets an immediate "正在运行" reply.
    """
    home = Path(home)
    send = send or feishu.send_text
    start_worker = start_worker or start_daemon
    decision = classify_message(home, event)
    outcome = {**decision, "replied": False, "reply": None, "reply_text": None}
    action = decision["action"]
    if action == "ignored":
        log_line(home, f"ignored message ({decision['reason']})")
        return outcome
    reply_target = str(target or decision.get("target") or "")
    if action == "daily":
        if inflight is not None and inflight.get("derived"):
            log_line(home, "derived command ignored: a derived run is already in flight")
            outcome.update(
                status="busy",
                replied=True,
                reply=_reply(send, reply_target, DERIVED_BUSY_TEXT),
                reply_text=DERIVED_BUSY_TEXT,
            )
            return outcome

        def worker() -> None:
            try:
                run_derived(
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
            except Exception as exc:  # noqa: BLE001 - a worker must report, not crash the loop
                log_line(home, f"derived run crashed: {type(exc).__name__}: {exc}")
                _reply(
                    send,
                    reply_target,
                    f"派生运行失败（{type(exc).__name__}），不会自动重试。",
                )
            finally:
                if inflight is not None:
                    inflight.pop("derived", None)

        if inflight is not None:
            inflight["derived"] = True
        started = _reply(send, reply_target, DERIVED_STARTED_TEXT)
        try:
            start_worker(worker)
        except Exception as exc:  # noqa: BLE001 - report a worker start failure
            if inflight is not None:
                inflight.pop("derived", None)
            text = f"派生运行启动失败（{type(exc).__name__}），不会自动重试。"
            log_line(home, f"derived worker start failed: {type(exc).__name__}: {exc}")
            outcome.update(
                status="start_failed",
                replied=True,
                reply=_reply(send, reply_target, text),
                reply_text=text,
            )
            return outcome
        outcome.update(
            status="started",
            background=True,
            replied=True,
            reply=started,
            reply_text=DERIVED_STARTED_TEXT,
        )
        return outcome
    if action == "feedback":
        # #73: the mechanical poll runs ~13 minutes on a bad day, so it must not
        # run on the event loop.  Reply "已开始", then let the worker send the
        # result receipt (changes/failure/skip only; silent when nothing changed).
        if inflight is not None and inflight.get("feedback"):
            log_line(home, "feedback command ignored: a poll is already in flight")
            outcome.update(
                status="busy",
                replied=True,
                reply=_reply(send, reply_target, FEEDBACK_BUSY_TEXT),
                reply_text=FEEDBACK_BUSY_TEXT,
            )
            return outcome

        def feedback_worker() -> None:
            try:
                polled = poll_feedback(home, host=host, run=run)
                text = _feedback_result_text(polled)
                if text:
                    _reply(send, reply_target, text)
            except Exception as exc:  # noqa: BLE001 - a worker must report, not crash the loop
                log_line(home, f"feedback poll crashed: {type(exc).__name__}: {exc}")
                _reply(
                    send,
                    reply_target,
                    f"反馈处理失败（{type(exc).__name__}），稍后再试。",
                )
            finally:
                if inflight is not None:
                    inflight.pop("feedback", None)

        if inflight is not None:
            inflight["feedback"] = True
        started = _reply(send, reply_target, FEEDBACK_STARTED_TEXT)
        try:
            start_worker(feedback_worker)
        except Exception as exc:  # noqa: BLE001 - report a worker start failure
            if inflight is not None:
                inflight.pop("feedback", None)
            text = f"反馈处理启动失败（{type(exc).__name__}），稍后再试。"
            log_line(home, f"feedback worker start failed: {type(exc).__name__}: {exc}")
            outcome.update(
                status="start_failed",
                replied=True,
                reply=_reply(send, reply_target, text),
                reply_text=text,
            )
            return outcome
        outcome.update(
            status="started",
            background=True,
            replied=True,
            reply=started,
            reply_text=FEEDBACK_STARTED_TEXT,
        )
        return outcome
    if action == "status":
        text = status_text(status_snapshot(home, status=status))
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
    start_worker=None,
) -> dict:
    """Run the foreground listener loop until stop sentinel / fatal failure.

    Every dependency is injectable for offline tests.  Derived runs and feedback
    polls execute on daemon workers (``start_worker``) so the loop keeps
    consuming events, heartbeating and answering ``状态`` (ADR 0008 §4/§5, #73).
    Returns a summary dict; ``ok=False`` from exit code 3 (permission scope) or
    another fatal consume failure, and ``{"reason": "already_running"}`` when the
    lock is held.
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
    start_worker = start_worker or start_daemon

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
        # One in-flight derived run max (ADR 0008 §5).  The main loop keeps
        # consuming events/heartbeating/polling while the worker runs.
        inflight: dict = {}

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
                # The worker runs off this thread; the loop itself keeps the
                # heartbeat flowing, so no on_wait callback is needed here.
                on_wait=None,
                should_stop=lambda: stop_requested(home),
                inflight=inflight,
                start_worker=start_worker,
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
                    last_feedback = clock()
                    if inflight.get("feedback"):
                        log_line(home, "feedback poll skipped (already in flight)")
                    else:
                        # #73: schedule the poll on a worker; the loop keeps
                        # consuming events, beating the heartbeat and answering.
                        inflight["feedback"] = True

                        def automatic_feedback_poll() -> None:
                            try:
                                polled = poll_feedback(home, host=host, run=run)
                                if polled.get("skipped"):
                                    log_line(
                                        home,
                                        f"feedback poll skipped ({polled['skipped']})",
                                    )
                            except Exception as exc:  # noqa: BLE001 - never raise into serve
                                log_line(
                                    home,
                                    f"feedback poll crashed: {type(exc).__name__}: {exc}",
                                )
                            finally:
                                inflight.pop("feedback", None)

                        try:
                            start_worker(automatic_feedback_poll)
                        except Exception as exc:  # noqa: BLE001 - report, keep looping
                            inflight.pop("feedback", None)
                            log_line(
                                home,
                                f"feedback worker start failed: {type(exc).__name__}: {exc}",
                            )
                sleep(TICK_PAUSE_SECONDS)
        finally:
            log_line(home, "listener stopped")

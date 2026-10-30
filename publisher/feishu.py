"""Thin lark-cli wrapper. Only module that talks to Feishu."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Any, Callable, Iterator

from common import home as data_home
from common import read_json

BIN = "lark-cli"

# ``lark-cli event consume`` contract (docs/acceptance/README.md:30): stderr
# carries one readiness line before events.  Only the tail of stderr is kept,
# and no argv is echoed, so credentials never end up in an error message.
READY_MARKER = "[event] ready"
READY_KEY_MARKER = "ready event_key="
STDERR_TAIL_LINES = 20
STDERR_TAIL_CHARS = 400

# Exit-code meanings observed on a real host (docs/acceptance/README.md:115).
# ADR 0008 / decision D9: 3 is fatal, 4 and 5 are transient.  The retryable set
# is derived from the kind table below so the two can never disagree.
EXIT_APP_SCOPE_NOT_APPLIED = 3
_TRANSIENT_EXIT_KINDS = {4: "transient", 5: "token_storage_lock"}
EXIT_TRANSIENT = tuple(_TRANSIENT_EXIT_KINDS)
_EXIT_KINDS = {
    EXIT_APP_SCOPE_NOT_APPLIED: "app_scope_not_applied",
    **_TRANSIENT_EXIT_KINDS,
}

# Live acceptance on 2026-10-30 showed exit 3 also arriving when the bot event
# long connection was dropped by a transient network failure (an i/o timeout
# immediately preceded it).  Treating every exit 3 as fatal killed a healthy
# listener and would break the 24 h uptime gate, so only the explicit scope
# marker is fatal; a bare exit 3 is retried with the same backoff as 4 and 5.
_SCOPE_NOT_APPLIED_MARKERS = ("app_scope_not_applied", "app scope not applied")

# A read-back proves a message is gone only through a documented not-found or
# recalled answer.  Anything else is unverifiable and must not be reported as
# clean.
_GONE_CODES = {"230006"}
_GONE_MARKERS = (
    "message not found",
    "message_not_found",
    "message has been recalled",
    "已撤回",
    "消息不存在",
)


class FeishuError(RuntimeError):
    """A lark-cli failure.

    ``returncode`` carries the child exit code when there was one (``None`` for
    local failures such as a stale recorded CLI path), so callers can classify
    a consume failure instead of treating every error as fatal.
    """

    def __init__(self, message: str, *, returncode: int | None = None):
        super().__init__(message)
        self.returncode = returncode


def classify_exit(returncode: int | None, *, detail: str = "") -> dict:
    """Classify one ``event consume`` exit code (ADR 0008 decision D9).

    ``3`` with the explicit ``app_scope_not_applied`` marker = app/permission
    scope not applied: fatal, a human must fix grants.  ``3`` without it =
    the long connection died (transient network failure): retry with backoff,
    same as ``4``/``5``.  ``5`` is the token storage lock: also transient.
    Any other non-zero code is unclassified: report it and do not invent a retry.
    """
    code = 0 if returncode is None else int(returncode)
    if code == 0:
        return {"returncode": 0, "kind": "ok", "fatal": False, "retryable": False}
    if code == EXIT_APP_SCOPE_NOT_APPLIED:
        text = str(detail or "").lower()
        if any(marker in text for marker in _SCOPE_NOT_APPLIED_MARKERS):
            return {
                "returncode": code,
                "kind": "app_scope_not_applied",
                "fatal": True,
                "retryable": False,
            }
        return {
            "returncode": code,
            "kind": "consume_lost",
            "fatal": False,
            "retryable": True,
        }
    kind = _EXIT_KINDS.get(code, "unknown")
    retryable = code in EXIT_TRANSIENT
    return {"returncode": code, "kind": kind, "fatal": not retryable, "retryable": retryable}


def _recorded_executable() -> str:
    """The absolute CLI path recorded by ``hostrun lark discover`` (ADR 0007).

    The data root holds ``install/config.json`` with ``paths.lark_cli``; nothing
    here reads or copies a credential.
    """
    try:
        root = data_home()
    except Exception:  # noqa: BLE001 - no data root means no recorded path
        return ""
    config = read_json(Path(root) / "install" / "config.json", {}) or {}
    recorded = str((config.get("paths") or {}).get("lark_cli") or "").strip()
    if not recorded or not Path(recorded).expanduser().is_absolute():
        # A bare command name is a PATH guess, not a recorded path (ADR 0007).
        return ""
    return recorded


def _cli_command() -> list[str]:
    """argv prefix for lark-cli: the recorded absolute path, PATH only as fallback.

    A recorded path that no longer exists is stale, not a hint to guess another
    CLI.  ``shutil.which`` returns an absolute path (possibly a ``.cmd`` shim),
    which CreateProcess can start; a bare ``lark-cli`` is not resolved through
    PATHEXT the same way, which is why delivery used to fail on Windows.
    """
    recorded = _recorded_executable()
    if recorded:
        path = Path(recorded)
        if not path.is_file():
            raise FeishuError(
                f"记录的飞书 CLI 路径已失效：{recorded}；"
                "请重新运行 `hostrun lark discover --cli <可执行文件绝对路径>`"
            )
        return [str(path)]
    found = shutil.which(BIN)
    if not found:
        raise FeishuError(
            "lark-cli 未找到：未记录可执行文件，PATH 中也没有；"
            "先运行 `hostrun lark discover --cli <绝对路径>`"
        )
    return [found]


def available() -> bool:
    """Whether a CLI path resolves now — an existence check, not a login check."""
    try:
        _cli_command()
    except FeishuError:
        return False
    return True


def _run(
    args: list[str],
    stdin: str | None = None,
    timeout: int = 60,
    cwd: str | None = None,
) -> dict:
    proc = subprocess.run(
        [*_cli_command(), *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )
    if proc.returncode != 0:
        detail = (proc.stdout or proc.stderr or "").strip()
        raise FeishuError(f"lark-cli exited {proc.returncode}: {detail[:500]}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise FeishuError(f"lark-cli returned non-JSON: {proc.stdout[:300]}") from exc
    if payload.get("ok") is False:
        raise FeishuError(json.dumps(payload.get("error", payload), ensure_ascii=False)[:500])
    return payload


def send_card(target: str, card: dict, identity: str = "bot", to_chat: bool = False) -> dict:
    args = ["im", "+messages-send", "--chat-id" if to_chat else "--user-id", target]
    args += [
        "--as",
        identity,
        "--msg-type",
        "interactive",
        "--content",
        json.dumps(card, ensure_ascii=False),
    ]
    payload = _run(args)
    data = payload.get("data") or {}
    if not data.get("message_id"):
        raise FeishuError(f"send succeeded without message_id: {payload}")
    return {"message_id": data["message_id"], "chat_id": data.get("chat_id")}


def send_text(target: str, text: str, identity: str = "bot", to_chat: bool = False) -> dict:
    args = ["im", "+messages-send", "--chat-id" if to_chat else "--user-id", target]
    args += ["--as", identity, "--text", text]
    payload = _run(args)
    data = payload.get("data") or {}
    return {"ok": True, "message_id": data.get("message_id"), "chat_id": data.get("chat_id")}


def send_file(target: str, path: str, identity: str = "bot", to_chat: bool = False) -> dict:
    """Send a local file. lark-cli only accepts cwd-relative paths."""
    file_path = Path(path).resolve()
    if not file_path.is_file():
        raise FeishuError(f"file not found: {file_path}")
    args = ["im", "+messages-send", "--chat-id" if to_chat else "--user-id", target]
    args += ["--as", identity, "--file", file_path.name]
    payload = _run(args, cwd=str(file_path.parent), timeout=120)
    data = payload.get("data") or {}
    if not data.get("message_id"):
        raise FeishuError(f"send succeeded without message_id: {payload}")
    return {"message_id": data["message_id"], "chat_id": data.get("chat_id")}


def update_card(token: str, card: dict, identity: str = "bot") -> dict:
    body = json.dumps({"token": token, "card": card}, ensure_ascii=False)
    return _run(
        [
            "api",
            "POST",
            "/open-apis/interactive/v1/card/update",
            "--as",
            identity,
            "--data",
            "-",
        ],
        stdin=body,
    )


def delete_message(
    message_id: str, identity: str = "bot", executable: str | None = None
) -> dict:
    """Recall one test message using the *recorded* CLI path, not PATH.

    Authority and age limits are the server's; either can legitimately refuse,
    which the caller reports as an unretractable message.
    """
    command = [str(executable)] if executable else _cli_command()
    proc = subprocess.run(
        [
            *command,
            "im",
            "messages",
            "delete",
            "--message-id",
            message_id,
            "--as",
            identity,
            # Recall is a high-risk write: without --yes lark-cli refuses with
            # confirmation_required and cleanup cannot prove the recall.
            "--yes",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    text = (proc.stdout or "").strip()
    try:
        payload = json.loads(text or "{}")
    except json.JSONDecodeError:
        raise FeishuError(
            f"{' '.join(command)} messages delete returned non-JSON: {text[:300]}"
        ) from None
    if proc.returncode != 0 or payload.get("ok") is False:
        raise FeishuError(
            f"{' '.join(command)} messages delete failed: "
            f"{json.dumps(payload.get('error') or payload, ensure_ascii=False)[:400]}"
        )
    return {"ok": True, "message_id": message_id, "payload": payload}


def _gone_error(payload: dict) -> bool:
    error = payload.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    if str(code) in _GONE_CODES:
        return True
    text = json.dumps(error or payload, ensure_ascii=False).lower()
    return any(marker in text for marker in _GONE_MARKERS)


def get_message(
    message_id: str, identity: str = "bot", executable: str | None = None
) -> dict:
    """Read one message back through the recorded CLI path.

    A recall request is not evidence the message is gone.  ``present`` is
    ``False`` only for a documented not-found/recalled answer; any other failure
    raises :class:`FeishuError`, so the caller reports an unverifiable read
    instead of claiming the scope is clean.
    """
    command = [str(executable)] if executable else _cli_command()
    proc = subprocess.run(
        [
            *command,
            "api",
            "GET",
            f"/open-apis/im/v1/messages/{message_id}",
            "--as",
            identity,
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    text = (proc.stdout or "").strip()
    try:
        payload = json.loads(text or "{}")
    except json.JSONDecodeError:
        raise FeishuError(
            f"{' '.join(command)} api GET message returned non-JSON: {text[:300]}"
        ) from None
    if proc.returncode != 0 or payload.get("ok") is False:
        if _gone_error(payload):
            return {"message_id": message_id, "present": False, "payload": payload}
        detail = json.dumps(payload.get("error") or payload, ensure_ascii=False)
        raise FeishuError(f"{' '.join(command)} api GET message failed: {detail[:400]}")
    data = payload.get("data") or {}
    items = [item for item in (data.get("items") or []) if isinstance(item, dict)]
    if not items:
        # A successful GET with no items is a malformed/empty answer, not proof
        # that the message is gone.  Only a documented not-found/recalled answer
        # may report ``present: False``.
        raise FeishuError(
            f"{' '.join(command)} api GET message returned no items; "
            "message presence is unverifiable"
        )
    item = items[0]
    state = str(item.get("status") or "").lower()
    if item.get("deleted") or state in {"recalled", "deleted"}:
        return {"message_id": message_id, "present": False, "payload": payload}
    return {"message_id": message_id, "present": True, "payload": payload}


def _consume_argv(
    event_key: str, identity: str, max_events: int, timeout: str
) -> list[str]:
    args = [*_cli_command(), "event", "consume", event_key, "--as", identity]
    if max_events:
        args += ["--max-events", str(max_events)]
    if timeout and timeout != "0":
        args += ["--timeout", timeout]
    return args


def _new_consume_state() -> dict:
    return {
        "pid": None,
        "returncode": None,
        "events": 0,
        "ready": False,
        "ready_event_key": None,
        "timed_out": False,
        "stopped": False,
        "stderr_tail_lines": deque(maxlen=STDERR_TAIL_LINES),
        "stderr_error": "",
    }


def _ready_event_key(line: str) -> str | None:
    """The event key of a readiness line, ``""`` for a bare marker, else None."""
    index = line.find(READY_KEY_MARKER)
    if index >= 0:
        return line[index + len(READY_KEY_MARKER) :].strip().split(" ", 1)[0]
    return "" if READY_MARKER in line else None


def _drain_stderr(
    stderr: Any,
    tail: deque,
    state: dict,
    event_key: str,
    on_stderr: Callable[[str], Any] | None,
    on_ready: Callable[[str], Any] | None,
) -> None:
    """Drain stderr for the whole run so a full pipe can never deadlock.

    Runs on its own thread: stdout events keep flowing while stderr is read.
    Only a bounded tail is retained; a callback never decides the exit result.
    """
    try:
        for raw in stderr:
            line = str(raw).rstrip("\r\n")
            if not line:
                continue
            tail.append(line)
            if on_stderr is not None:
                on_stderr(line)
            key = _ready_event_key(line)
            if key is None or state["ready"]:
                continue
            if key and event_key and key != event_key:
                # A marker for a different subscription is not our readiness.
                continue
            state["ready"] = True
            state["ready_event_key"] = key
            if on_ready is not None:
                on_ready(key)
    except Exception as exc:  # noqa: BLE001 - a dead reader must not kill consume
        state["stderr_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        _close(stderr)


def _close(stream: Any) -> None:
    if stream is None:
        return
    try:
        stream.close()
    except Exception:  # noqa: BLE001 - a closed pipe is already closed
        pass


def _terminate(proc: Any, *, force: bool = False) -> None:
    try:
        if force or proc.poll() is None:
            proc.terminate()
    except Exception:  # noqa: BLE001 - terminating a dead child must not hide it
        pass


def _wait(proc: Any, seconds: float = 5) -> None:
    try:
        proc.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        _terminate(proc)
        try:
            proc.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            pass


def _consume_lines(
    args: list[str],
    *,
    event_key: str,
    state: dict,
    on_ready: Callable[[str], Any] | None = None,
    on_stderr: Callable[[str], Any] | None = None,
    deadline_seconds: float | None = None,
    popen: Callable[..., Any] | None = None,
    stop_event: Any | None = None,
) -> Iterator[str]:
    """Yield stripped NDJSON stdout lines while draining stderr concurrently.

    ``state`` is mutated so the caller can build a result once the iterator is
    exhausted (or closed early).  ``--max-events``/``--timeout`` bound the child
    itself; ``deadline_seconds`` additionally kills a hung child from this side,
    and ``stop_event`` lets the owner (the Console) terminate a bounded chunk at
    shutdown instead of waiting out its timeout.
    """
    if stop_event is not None and stop_event.is_set():
        state["stopped"] = True
        return
    spawn = subprocess.Popen if popen is None else popen
    # lark-cli treats stdin EOF as "shutdown"; keep the pipe open for the
    # lifetime of the bounded chunk.
    proc = spawn(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    state["pid"] = getattr(proc, "pid", None)
    if proc.stdout is None or proc.stderr is None:
        raise FeishuError("lark-cli event consume 未提供 stdout/stderr 管道")

    drain = threading.Thread(
        target=_drain_stderr,
        args=(
            proc.stderr,
            state["stderr_tail_lines"],
            state,
            event_key,
            on_stderr,
            on_ready,
        ),
        name="feishu-stderr",
        daemon=True,
    )
    drain.start()

    timer = None
    if deadline_seconds is not None and deadline_seconds > 0:

        def _expire() -> None:
            state["timed_out"] = True
            _terminate(proc)

        timer = threading.Timer(float(deadline_seconds), _expire)
        timer.daemon = True
        timer.start()

    finished = threading.Event()
    watcher = None
    if stop_event is not None:

        def _watch_stop() -> None:
            while not finished.is_set():
                if stop_event.wait(timeout=0.1):
                    state["stopped"] = True
                    _terminate(proc)
                    return

        watcher = threading.Thread(target=_watch_stop, name="feishu-stop", daemon=True)
        watcher.start()

    try:
        for raw in proc.stdout:
            line = str(raw).strip()
            if not line:
                continue
            state["events"] += 1
            yield line
    finally:
        finished.set()
        if watcher is not None:
            watcher.join(timeout=1.0)
        if timer is not None:
            timer.cancel()
        _close(proc.stdin)
        if state["stopped"]:
            # The caller walked away mid-stream; the child is still running.
            _terminate(proc, force=True)
        elif state["timed_out"]:
            _terminate(proc)
        _wait(proc)
        state["returncode"] = proc.returncode
        # Join after the child is done: the marker may be the last stderr line.
        drain.join(timeout=2.0)
        _close(proc.stdout)


def _consume_result(state: dict) -> dict:
    returncode = state["returncode"]
    tail = "\n".join(state["stderr_tail_lines"])[-STDERR_TAIL_CHARS:]
    if state["timed_out"]:
        ok, kind, fatal, retryable = False, "timeout", False, True
    elif state["stopped"]:
        ok, kind, fatal, retryable = True, "stopped", False, False
    else:
        classification = classify_exit(returncode, detail=tail)
        kind = classification["kind"]
        ok = kind == "ok"
        fatal = classification["fatal"]
        retryable = classification["retryable"]
    return {
        "ok": ok,
        "reason": kind,
        "kind": kind,
        "returncode": returncode,
        "fatal": fatal,
        "retryable": retryable,
        "ready": state["ready"],
        "ready_event_key": state["ready_event_key"],
        "events": state["events"],
        "stderr_tail": tail.strip(),
        "stderr_error": state["stderr_error"],
        "timed_out": state["timed_out"],
        "stopped": state["stopped"],
        "pid": state["pid"],
    }


def listen_events(
    identity: str = "bot",
    event_key: str = "im.message.receive_v1",
    max_events: int = 0,
    timeout: str = "30s",
    *,
    on_line: Callable[[str], Any] | None = None,
    on_ready: Callable[[str], Any] | None = None,
    on_stderr: Callable[[str], Any] | None = None,
    deadline_seconds: float | None = None,
    popen: Callable[..., Any] | None = None,
    stop_event: Any | None = None,
) -> dict:
    """Consume one bounded ``lark-cli event consume`` chunk (issue #63).

    Reusable by the listener: ``event_key`` is configurable, ``--max-events`` /
    ``--timeout`` bound the chunk, stderr is drained for the whole run, and the
    ``[event] ready event_key=...`` marker is exposed as ``ready`` /
    ``ready_event_key`` (plus ``on_ready``).  ``on_line`` receives each stripped
    stdout line and may return ``False`` to stop early; ``deadline_seconds``
    kills a hung child.  ``on_stderr`` is the diagnostic seam proving the drain
    keeps up (the bounded tail/readiness logic is internal); no production
    caller is required for it to be worth keeping.  ``stop_event`` terminates a
    running chunk during Console shutdown, so closing the Console never waits
    out a full 30-second consume.

    Never raises for a non-zero child exit; returns
    ``{"ok", "reason", "kind", "returncode", "fatal", "retryable", "ready",
    "ready_event_key", "events", "stderr_tail", "stderr_error", "timed_out",
    "stopped", "pid"}`` where ``kind`` comes from :func:`classify_exit`.
    Live lark-cli argv/marker/exit meanings are documented but ``untested``
    here: tests inject ``popen``.
    """
    state = _new_consume_state()
    args = _consume_argv(event_key, identity, max_events, timeout)
    lines = _consume_lines(
        args,
        event_key=event_key,
        state=state,
        on_ready=on_ready,
        on_stderr=on_stderr,
        deadline_seconds=deadline_seconds,
        popen=popen,
        stop_event=stop_event,
    )
    try:
        for line in lines:
            if on_line is not None and on_line(line) is False:
                state["stopped"] = True
                break
    finally:
        lines.close()
    return _consume_result(state)


def consume_events(
    identity: str = "bot",
    max_events: int = 0,
    timeout: str = "0",
    event_key: str = "card.action.trigger",
):
    """Blocking consume, yielded as raw NDJSON lines (for `listen`).

    Legacy positional contract kept for ``publisher.service.listen`` and
    ``trigger.service.listen``.  stderr is now drained concurrently (the old
    implementation could deadlock on a full stderr pipe) and a non-zero exit
    raises :class:`FeishuError` with ``returncode`` attached.
    """
    state = _new_consume_state()
    args = _consume_argv(event_key, identity, max_events, timeout)
    lines = _consume_lines(args, event_key=event_key, state=state)
    try:
        yield from lines
    finally:
        lines.close()
    if state["returncode"] not in (0, None) and not state["stopped"]:
        if state["timed_out"]:
            raise FeishuError("event consume deadline exceeded", returncode=state["returncode"])
        tail = "\n".join(state["stderr_tail_lines"])[-STDERR_TAIL_CHARS:]
        raise FeishuError(
            f"event consume exited {state['returncode']}: {tail.strip()}",
            returncode=state["returncode"],
        )

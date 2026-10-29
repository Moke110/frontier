"""Thin lark-cli wrapper. Only module that talks to Feishu."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from common import home as data_home
from common import read_json

BIN = "lark-cli"

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
    pass


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
        [*command, "im", "messages", "delete", "--message-id", message_id, "--as", identity],
        capture_output=True,
        text=True,
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


def consume_events(
    identity: str = "bot",
    max_events: int = 0,
    timeout: str = "0",
    event_key: str = "card.action.trigger",
):
    """Blocking consume, yielded as raw NDJSON lines (for `listen`)."""
    args = [*_cli_command(), "event", "consume", event_key, "--as", identity]
    if max_events:
        args += ["--max-events", str(max_events)]
    if timeout and timeout != "0":
        args += ["--timeout", timeout]
    # lark-cli treats stdin EOF as "shutdown"; keep the pipe open for the
    # lifetime of the listener (systemd starts services with stdin closed).
    proc = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            line = line.strip()
            if line:
                yield line
    finally:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=5)
    if proc.returncode not in (0, None):
        err = (proc.stderr.read() if proc.stderr else "") or ""
        raise FeishuError(f"event consume exited {proc.returncode}: {err.strip()[:400]}")

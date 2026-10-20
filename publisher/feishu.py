"""Thin lark-cli wrapper. Only module that talks to Feishu."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

BIN = "lark-cli"


class FeishuError(RuntimeError):
    pass


def available() -> bool:
    return shutil.which(BIN) is not None


def _run(args: list[str], stdin: str | None = None, timeout: int = 60) -> dict:
    if not available():
        raise FeishuError("lark-cli not found in PATH")
    proc = subprocess.run(
        [BIN, *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
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


def consume_events(identity: str = "bot", max_events: int = 0, timeout: str = "0"):
    """Blocking consume, yielded as raw NDJSON lines (for `listen`)."""
    if not available():
        raise FeishuError("lark-cli not found in PATH")
    args = [BIN, "event", "consume", "card.action.trigger", "--as", identity]
    if max_events:
        args += ["--max-events", str(max_events)]
    if timeout and timeout != "0":
        args += ["--timeout", timeout]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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

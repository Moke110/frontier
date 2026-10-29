"""Administrative lark-cli calls that do not belong to one Base yet.

Creating a Base, or finding a Base by title before reusing it, happens before
``knowledge/base.json`` exists, so the record client cannot be used.  The
wrapper keeps these few commands in one place and returns only stable IDs and
display names.

Commands follow the installed ``lark-base`` skill::

    lark-cli base +base-create --name <name> --table-name <first> --fields <json>
    lark-cli base +title-resolve --title <name>
"""

from __future__ import annotations

import json
import subprocess


class AdminError(RuntimeError):
    pass


def _run(argv: list[str], *, runner=subprocess.run) -> dict:
    try:
        proc = runner(argv, capture_output=True, text=True, timeout=300)
    except OSError as exc:
        raise AdminError(f"lark-cli 无法执行：{exc}") from exc
    text = (proc.stdout or "").strip()
    try:
        payload = json.loads(text or "{}")
    except json.JSONDecodeError:
        raise AdminError(f"lark-cli {' '.join(argv[:2])} returned non-JSON: {text[:300]}") from None
    if payload.get("ok") is False:
        raise AdminError(
            json.dumps(payload.get("error") or payload, ensure_ascii=False)[:500]
        )
    return payload.get("data") or {}


def _first(data: dict, *keys):
    for key in keys:
        if data.get(key) not in (None, ""):
            return data[key]
    return None


class LarkAdminClient:
    def __init__(self, *, identity: str = "user", bin: str = "lark-cli"):
        self.identity = identity
        self.bin = bin

    def _call(self, *args: str, runner=subprocess.run) -> dict:
        return _run(
            [self.bin, *args, "--as", self.identity, "--format", "json"],
            runner=runner,
        )

    def create_base(
        self,
        name: str,
        *,
        table_name: str,
        fields: list[dict],
        runner=subprocess.run,
    ) -> dict:
        data = self._call(
            "base",
            "+base-create",
            "--name",
            name,
            "--table-name",
            table_name,
            "--fields",
            json.dumps(fields, ensure_ascii=False),
            runner=runner,
        )
        # The current shortcut nests the created Base under ``base`` and the
        # first table under ``table``; older payloads put the token at the top
        # level. Accept both instead of failing after Feishu already created it.
        nested = data.get("base") if isinstance(data.get("base"), dict) else {}
        table = data.get("table") if isinstance(data.get("table"), dict) else {}
        token = _first(data, "app_token", "base_token", "token") or _first(
            nested, "app_token", "base_token", "token"
        )
        table_id = table.get("id") or _first(data, "table_id")
        if not token:
            raise AdminError(f"base-create returned no token: {data}")
        return {
            "base_token": token,
            "table_id": table_id,
            "url": _first(data, "url", "base_url")
            or _first(nested, "url", "base_url")
            or f"https://feishu.cn/base/{token}",
            "name": nested.get("name") or name,
        }

    def resolve_title(self, title: str, *, runner=subprocess.run) -> dict:
        data = self._call("base", "+title-resolve", "--title", title, runner=runner)
        raw = (
            data.get("bases")
            or data.get("items")
            or data.get("base_list")
            or data.get("results")
            or []
        )
        if isinstance(raw, dict):
            raw = [raw]
        matches = []
        for row in raw:
            token = _first(row, "app_token", "base_token", "token")
            if not token:
                continue
            matches.append(
                {
                    "base_token": token,
                    "name": row.get("name") or row.get("title") or title,
                    "url": row.get("url") or f"https://feishu.cn/base/{token}",
                }
            )
        direct = _first(data, "app_token", "base_token")
        if direct and not matches:
            matches.append(
                {
                    "base_token": direct,
                    "name": data.get("name") or title,
                    "url": data.get("url") or f"https://feishu.cn/base/{direct}",
                }
            )
        return {"matches": matches, "count": len(matches)}


def table_names(client, base_token: str) -> list[dict]:
    """List tables through an object exposing ``list_tables()``."""
    return [
        {"id": row.get("id") or row.get("table_id"), "name": row.get("name") or ""}
        for row in client.list_tables()
    ]

"""Thin lark-cli wrappers for the archive tables and Drive folders.

``library`` owns four Base tables (原文 / 推送日志 / 决定 / 配置) and two Drive
folders. It must not import ``knowledge`` (modules exchange files, not code),
so the small lark-cli client is duplicated here on purpose.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

CONFIG_REL = Path("knowledge") / "base.json"

SOURCE = "sources"
PUSH = "pushes"
DECISION = "decisions"
CONFIG = "config"


class LibraryBaseError(RuntimeError):
    pass


def load_base_config(home: Path) -> dict:
    from common import read_json

    path = Path(home) / CONFIG_REL
    cfg = read_json(path)
    if not cfg or not cfg.get("base_token") or not cfg.get("tables"):
        raise LibraryBaseError(f"missing Bitable config: {path}")
    return cfg


def save_base_config(home: Path, config: dict) -> None:
    from common import write_json

    write_json(Path(home) / CONFIG_REL, config)


class LarkBaseClient:
    """List / create / update records, and read a table's field names."""

    def __init__(self, config: dict, *, identity: str = "user"):
        self.config = config
        self.identity = identity
        self.base = config["base_token"]
        self._fields: dict[str, list[str]] = {}

    def _run(self, *args: str, yes: bool = False) -> dict:
        cmd = [
            "lark-cli", *args,
            "--as", self.identity,
            "--base-token", self.base,
            "--format", "json",
        ]
        if yes:
            cmd.append("--yes")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        try:
            payload = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            raise LibraryBaseError(
                f"lark-cli {' '.join(args)} returned non-JSON: {proc.stdout[:300]}"
            ) from None
        if not payload.get("ok"):
            raise LibraryBaseError(
                f"lark-cli {' '.join(args)} failed: "
                f"{payload.get('error') or proc.stderr or 'unknown error'}"
            )
        return payload

    def list(self, table: str) -> list[dict]:
        rows: list[dict] = []
        offset = 0
        while True:
            payload = self._run(
                "base", "+record-list", "--table-id", table,
                "--limit", "200", "--offset", str(offset),
            )
            data = payload.get("data") or {}
            names = data.get("fields") or []
            matrix = data.get("data") or []
            ids = data.get("record_id_list") or []
            rows.extend(
                {"record_id": rid, "fields": dict(zip(names, row))}
                for rid, row in zip(ids, matrix)
            )
            if not data.get("has_more") or not ids:
                break
            offset += len(ids)
        return rows

    def create(self, table: str, rows: list[dict]) -> list[str]:
        if not rows:
            return []
        payload = self._run(
            "base", "+record-batch-create", "--table-id", table,
            "--json", json.dumps({"create_records": rows}, ensure_ascii=False),
        )
        return payload["data"].get("record_id_list") or []

    def update(self, table: str, updates: dict[str, dict]) -> None:
        if not updates:
            return
        self._run(
            "base", "+record-batch-update", "--table-id", table,
            "--json", json.dumps({"update_records": updates}, ensure_ascii=False),
        )

    def field_names(self, table: str) -> list[str]:
        if table not in self._fields:
            payload = self._run("base", "+field-list", "--table-id", table)
            self._fields[table] = [
                f.get("name") for f in payload["data"].get("fields") or []
            ]
        return self._fields[table]

    # ----------------------------------------------------------- admin bits
    def ensure_options(self, table: str, field: str, values: list[str]) -> None:
        payload = self._run("base", "+field-list", "--table-id", table)
        target = next(
            (f for f in payload["data"].get("fields") or [] if f.get("name") == field),
            None,
        )
        if not target or target.get("type") != "select":
            return
        existing = [o.get("name") for o in target.get("options") or []]
        missing = [v for v in values if v and v not in existing]
        if not missing:
            return
        options = [{"name": name, "hue": "Blue"} for name in existing + missing]
        self._run(
            "base", "+field-update", "--table-id", table,
            "--field-id", target["id"],
            "--json", json.dumps(
                {"name": field, "type": "select", "multiple": True, "options": options},
                ensure_ascii=False,
            ),
            yes=True,
        )
        self._fields.pop(table, None)

    def list_tables(self) -> list[dict]:
        payload = self._run("base", "+table-list")
        return payload["data"].get("tables") or []

    def create_table(self, name: str, fields: list[dict]) -> str:
        payload = self._run(
            "base", "+table-create", "--name", name,
            "--fields", json.dumps(fields, ensure_ascii=False),
        )
        data = payload["data"]
        return (
            data.get("table_id")
            or (data.get("table") or {}).get("table_id")
            or (data.get("table") or {}).get("id")
        )

    def create_fields(self, table: str, fields: list[dict]) -> list[dict]:
        payload = self._run(
            "base", "+field-create", "--table-id", table,
            "--json", json.dumps(fields, ensure_ascii=False),
        )
        self._fields.pop(table, None)
        return payload["data"].get("fields") or []

    def rename_table(self, table: str, name: str) -> None:
        self._run("base", "+table-update", "--table-id", table, "--json",
                  json.dumps({"name": name}, ensure_ascii=False))

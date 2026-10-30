"""Persisted offline Drive + Base for ``--offline`` and local demos.

State lives in two JSON files under ``<运行时区>/library/``. They are test/demo
fixtures, not a second source of truth: normal runs never read them.
"""

from __future__ import annotations

import base64
from pathlib import Path

from common import read_json, write_json
from library.drive import FixtureDrive

DRIVE_REL = Path("library") / "offline-drive.json"
BASE_REL = Path("library") / "offline-base.json"


class JsonDrive(FixtureDrive):
    def __init__(self, path: Path):
        super().__init__()
        self.path = Path(path)
        state = read_json(self.path) or {}
        self.entries = {}
        self._counter = int(state.get("counter") or 0)
        for token, row in (state.get("entries") or {}).items():
            self.entries[token] = {
                **row,
                "data": base64.b64decode(row["data"]) if row.get("data") else b"",
            }

    def save(self) -> None:
        write_json(
            self.path,
            {
                "schema_version": 1,
                "counter": self._counter,
                "entries": {
                    token: {
                        **{k: v for k, v in entry.items() if k != "data"},
                        "data": base64.b64encode(entry.get("data") or b"").decode("ascii"),
                    }
                    for token, entry in self.entries.items()
                },
            },
        )

    def ensure_folder(self, parent_token: str, name: str) -> str:
        token = super().ensure_folder(parent_token, name)
        self.save()
        return token

    def upload(self, folder_token: str, name: str, path: Path) -> dict:
        result = super().upload(folder_token, name, path)
        self.save()
        return result

    def delete(self, token: str, *, kind: str = "file") -> None:
        super().delete(token, kind=kind)
        self.save()

    def put_bytes(self, folder_token: str, name: str, data: bytes) -> dict:
        result = super().put_bytes(folder_token, name, data)
        self.save()
        return result


class JsonBase:
    """Minimal persistent Bitable: records plus table/field metadata."""

    def __init__(self, path: Path):
        self.path = Path(path)
        state = read_json(self.path) or {}
        self.tables: dict[str, list[dict]] = state.get("tables") or {}
        self.meta: list[dict] = state.get("meta") or [
            {"id": "tblpapers", "name": "报道"},
            {"id": "tblcards", "name": "知识卡片"},
        ]
        self.fields: dict[str, list[str]] = state.get("fields") or {
            "tblpapers": ["paper_id", "page", "原文"],
            "tblcards": ["卡片 ID"],
        }
        self.counter = int(state.get("counter") or 0)

    def save(self) -> None:
        write_json(
            self.path,
            {
                "schema_version": 1,
                "counter": self.counter,
                "tables": self.tables,
                "meta": self.meta,
                "fields": self.fields,
            },
        )

    def _rows(self, table: str) -> list[dict]:
        return self.tables.setdefault(table, [])

    def list(self, table: str) -> list[dict]:
        return [dict(row, fields=dict(row["fields"])) for row in self._rows(table)]

    def create(self, table: str, rows: list[dict]) -> list[str]:
        ids = []
        for row in rows:
            self.counter += 1
            rid = f"rec{self.counter:04d}"
            self._rows(table).append({"record_id": rid, "fields": dict(row)})
            ids.append(rid)
        self.save()
        return ids

    def update(self, table: str, updates: dict[str, dict]) -> None:
        by_id = {row["record_id"]: row for row in self._rows(table)}
        for rid, fields in updates.items():
            by_id[rid]["fields"].update(fields)
        self.save()

    def ensure_options(self, table: str, field: str, values: list[str]) -> None:
        return None

    def field_names(self, table: str) -> list[str]:
        return list(self.fields.get(table, []))

    def list_tables(self) -> list[dict]:
        return [dict(row) for row in self.meta]

    def create_table(self, name: str, fields: list[dict]) -> str:
        self.counter += 1
        table_id = f"tbloff{self.counter:04d}"
        self.meta.append({"id": table_id, "name": name})
        self.fields[table_id] = [f["name"] for f in fields]
        self.tables.setdefault(table_id, [])
        self.save()
        return table_id

    def create_fields(self, table: str, fields: list[dict]) -> list[dict]:
        self.fields.setdefault(table, []).extend(f["name"] for f in fields)
        self.save()
        return fields

    def delete(self, table: str, record_ids: list[str]) -> dict:
        wanted = {str(record_id) for record_id in record_ids}
        before = len(self._rows(table))
        self.tables[table] = [
            row for row in self._rows(table) if row["record_id"] not in wanted
        ]
        self.save()
        return {
            "ok": True,
            "deleted": sorted(wanted),
            "removed": before - len(self.tables[table]),
        }

    def rename_table(self, table: str, name: str) -> None:
        for row in self.meta:
            if row["id"] == table:
                row["name"] = name
        self.save()

    def record(self, table: str, key: str, value):
        for row in self._rows(table):
            if row["fields"].get(key) == value:
                return row
        return None

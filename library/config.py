"""Runtime settings: Base 「配置」 row is the only source of truth.

The local cache exists so a quota precheck does not hit the network on every
upload. It is disposable: deleting it only costs one extra Base read.
"""

from __future__ import annotations

import time
from pathlib import Path

from common import read_json, write_json
from library import base as base_mod

DEFAULT_LIMIT_GB = 5.0
DEFAULT_THRESHOLD = 80
CACHE_REL = Path("library") / "cache" / "config.json"
TTL_SECONDS = 600


class LibraryConfigError(RuntimeError):
    pass


def _number(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def settings_from_row(row: dict | None, tables: dict) -> dict:
    fields = (row or {}).get("fields") or {}
    limit_gb = _number(fields.get("容量上限（GB）"), DEFAULT_LIMIT_GB)
    threshold = int(_number(fields.get("提醒阈值（%）"), DEFAULT_THRESHOLD))
    return {
        "limit_gb": limit_gb,
        "limit_bytes": int(limit_gb * 1024**3),
        "threshold_pct": threshold,
        "source_folder": str(fields.get("原文目录 token") or ""),
        "push_folder": str(fields.get("推送目录 token") or ""),
        "tables": dict(tables),
        "config_record_id": (row or {}).get("record_id"),
        "config_updated_at": str(fields.get("最近对账") or ""),
    }


def load(
    home: Path,
    *,
    client=None,
    force: bool = False,
    ttl: int = TTL_SECONDS,
) -> dict:
    home = Path(home)
    cache_path = home / CACHE_REL
    cached = read_json(cache_path) or {}
    if (
        not force
        and cached.get("settings")
        and time.time() - float(cached.get("fetched_at") or 0) < ttl
    ):
        return cached["settings"]

    config = base_mod.load_base_config(home)
    tables = config["tables"]
    if not tables.get(base_mod.CONFIG):
        raise LibraryConfigError(
            "Base 配置表缺失；先运行 `python -m library.cli setup`"
        )
    client = client or base_mod.LarkBaseClient(config)
    rows = client.list(tables[base_mod.CONFIG])
    row = next(
        (r for r in rows if str(r["fields"].get("键") or "") == "config"),
        rows[0] if rows else None,
    )
    settings = settings_from_row(row, tables)
    write_json(
        cache_path,
        {"schema_version": 1, "fetched_at": time.time(), "settings": settings},
    )
    return settings


def invalidate(home: Path) -> None:
    (Path(home) / CACHE_REL).unlink(missing_ok=True)

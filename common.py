"""Shared, domain-free helpers for all prototype modules.

Deliberately tiny: path/JSON/YAML IO and time formatting only. No module may
import another module; everything else is exchanged through files.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

DEFAULT_HOME = "data"


def home(override: str | None = None) -> Path:
    """Data root. Every CLI accepts --home, else KL_HOME, else ./data."""
    return Path(override or os.environ.get("KL_HOME") or DEFAULT_HOME).expanduser().resolve()


def now() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def today() -> str:
    return datetime.now().astimezone().date().isoformat()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default


def write_json(path: Path, obj: Any) -> None:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    tmp.replace(path)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def append_jsonl(path: Path, row: dict) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_yaml(path: Path, default: Any = None) -> Any:
    try:
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or default
    except FileNotFoundError:
        return default


def write_yaml(path: Path, obj: Any) -> None:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(obj, fh, allow_unicode=True, sort_keys=False)
    tmp.replace(path)


def emit(obj: Any) -> None:
    """Machine-readable stdout handle."""
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def read_json_arg(value: str) -> Any:
    """Accept inline JSON, '-' (stdin) or an @file path."""
    if value == "-":
        import sys

        return json.load(sys.stdin)
    if value.startswith("@"):
        return read_json(Path(value[1:]))
    return json.loads(value)


_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


def slug(text: str, fallback: str = "x") -> str:
    norm = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    out = _SLUG_RE.sub("_", norm.lower()).strip("_")
    return out or fallback


def paper_id(source: str, source_id: str) -> str:
    return f"{slug(source)}_{slug(source_id)}"


def stable_id(prefix: str, *parts: str) -> str:
    """Short deterministic id from parts (FNV-1a), so reruns are idempotent."""
    h = 0x811C9DC5
    for part in parts:
        for byte in str(part).encode("utf-8"):
            h ^= byte
            h = (h * 0x01000193) & 0xFFFFFFFF
    return f"{prefix}_{h:08x}"


def clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"

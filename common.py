"""Shared, domain-free helpers for all prototype modules.

Deliberately tiny: path/JSON/YAML IO and time formatting only. No module may
import another module; everything else is exchanged through files.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

import yaml

DEFAULT_HOME = "~/knowledge-loop"


def _replace_with_retry(tmp: Path, target: Path, *, attempts: int = 20) -> None:
    """Atomic replace, retrying short Windows sharing violations.

    Antivirus/indexers can hold the destination open for a few milliseconds;
    the temporary file is already complete, so retrying is safe and keeps the
    write atomic. POSIX replaces on the first attempt.
    """
    last: OSError | None = None
    for attempt in range(attempts):
        try:
            tmp.replace(target)
            return
        except PermissionError as exc:  # Windows sharing violation
            last = exc
            time.sleep(0.02 * (attempt + 1))
    raise last or OSError(f"could not replace {target}")



def home(override: str | None = None) -> Path:
    """Data root. Every CLI accepts --home, else KL_HOME, else ~/knowledge-loop."""
    return Path(override or os.environ.get("KL_HOME") or DEFAULT_HOME).expanduser().resolve()


def recorded_lark_cli() -> str:
    """The absolute lark-cli path recorded by ``hostrun lark discover``.

    ADR 0007 makes the recorded absolute path authoritative: a bare
    ``lark-cli`` does not resolve through PATHEXT on Windows and the PATH shim
    is not executable by CreateProcess.  Returns ``""`` when nothing is
    recorded, so callers can decide whether a PATH lookup is acceptable.
    """
    try:
        root = home()
    except Exception:  # noqa: BLE001 - no data root means no recorded path
        return ""
    config = read_json(Path(root) / "install" / "config.json", {}) or {}
    recorded = str((config.get("paths") or {}).get("lark_cli") or "").strip()
    if not recorded or not Path(recorded).expanduser().is_absolute():
        return ""
    return recorded


def now() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def today() -> str:
    return datetime.now().astimezone().date().isoformat()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def temp_dir() -> Path:
    """Scratch directory for intermediate files.

    Agent prompts quote this path, so it must exist on every platform: `/tmp`
    is POSIX-only and is not writable on Windows.
    """
    return Path(tempfile.gettempdir())


def _acquire(handle, blocking: bool) -> None:
    if os.name == "nt":  # pragma: no cover - exercised only on Windows
        import msvcrt

        # msvcrt locks a byte range, not the whole file, so the lock file must
        # contain at least one byte before the range can be claimed.
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))


def _release(handle) -> None:
    if os.name == "nt":  # pragma: no cover - exercised only on Windows
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def file_lock(path: Path, *, blocking: bool = True) -> Iterator[bool]:
    """Exclusive advisory lock on `path`, portable across POSIX and Windows.

    `fcntl` does not exist on Windows, so the POSIX and msvcrt flavours are
    imported lazily. Yields True when the lock was taken; with blocking=False a
    busy lock yields False instead of raising, leaving the policy to the caller.
    """
    path = Path(path)
    ensure_dir(path.parent)
    handle = path.open("a+b")
    acquired = False
    try:
        try:
            _acquire(handle, blocking)
            acquired = True
        except OSError:
            if blocking:
                raise
        yield acquired
    finally:
        if acquired:
            _release(handle)
        handle.close()


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
    _replace_with_retry(tmp, path)


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
    _replace_with_retry(tmp, path)


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

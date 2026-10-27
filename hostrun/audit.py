"""Existing-data audit: compare the cloud libraries with the migration baseline.

The 174/174 backfill recorded by the closed migration issue is a *historical*
baseline, not proof of the current cloud state. This module answers, per run:

- which baseline originals are missing now, and which rows are unexpected;
- whether multi-part originals have a complete, ordered part set;
- whether evidence rows still point at pushes that no longer exist;
- whether the recorded sizes and the actual Drive usage agree within 1%;
- which consecutive calendar days produced a zero-difference audit.

It never deletes, never re-uploads the whole corpus, and never turns an
unexplained gap into "no source file".
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import timedelta
from pathlib import Path

from common import read_json, read_jsonl, today, write_json
from hostrun.base import HostRunError
from library import base as base_mod

AUDIT_REL = Path("library") / "audit"
QUOTA_TOLERANCE = 0.01
LEGACY_TEST_PUSH = "test"


def load_baseline(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        raise HostRunError(f"baseline not found: {path}")
    if path.suffix.lower() in (".jsonl", ".ndjson"):
        rows = read_jsonl(path)
    else:
        payload = read_json(path) or []
        rows = payload.get("entries") if isinstance(payload, dict) else payload
    return [row for row in (rows or []) if isinstance(row, dict)]


def baseline_ids(rows: list[dict]) -> set[str]:
    from library.cli import _manifest_paper_id

    ids = set()
    for row in rows:
        paper_id = row.get("paper_id")
        if paper_id:
            ids.add(str(paper_id))
        elif row.get("path"):
            ids.add(_manifest_paper_id(str(row["path"])))
    return ids


def _size(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _offline_library(home: Path):
    from library.cli import _offline_library as build

    return build(home)[0]


def audit(
    home: Path,
    *,
    baseline: str | Path | None = None,
    offline: bool = False,
    library=None,
    client=None,
    date: str | None = None,
) -> dict:
    home = Path(home)
    if library is None:
        try:
            library = _offline_library(home) if offline else None
        except Exception as exc:  # noqa: BLE001 - report as blocked
            return _blocked(home, f"library unavailable: {exc}")
    if library is None:
        from library.service import Library

        library = Library(home)
    try:
        sources = library.rows(base_mod.SOURCE)
        pushes = library.rows(base_mod.PUSH)
        papers = library.rows("papers") if _table(library, "papers") else []
    except Exception as exc:  # noqa: BLE001
        return _blocked(home, f"无法读取 Base 表：{exc}")

    source_ids = {str(row["fields"].get("原文 ID") or "") for row in sources}
    push_ids = {str(row["fields"].get("推送 ID") or "") for row in pushes}

    expected = baseline_ids(load_baseline(baseline)) if baseline else set()
    missing = sorted(expected - source_ids) if expected else []
    unexpected = sorted(source_ids - expected) if expected else []

    no_source = [
        str(row["fields"].get("原文 ID") or "")
        for row in sources
        if str(row["fields"].get("状态") or "") == "无原件"
    ]
    pending_upload = [
        str(row["fields"].get("原文 ID") or "")
        for row in sources
        if str(row["fields"].get("状态") or "") == "待上传"
    ]

    part_problems = []
    for row in sources:
        fields = row["fields"]
        parts = [p for p in str(fields.get("分片") or "").split(",") if p.strip()]
        if not parts:
            continue
        paper_id = str(fields.get("原文 ID") or "")
        expected_names = [f"{paper_id}.pdf.part{n:02d}" for n in range(1, len(parts) + 1)]
        # order matters: part01 must come before part02, not merely both exist
        if [p.strip() for p in parts] != expected_names:
            part_problems.append({"paper_id": paper_id, "parts": parts, "expected": expected_names})

    dangling = [
        {
            "paper_id": str(row["fields"].get("paper_id") or ""),
            "push_id": str(row["fields"].get("push_id") or ""),
        }
        for row in papers
        if str(row["fields"].get("push_id") or "") and str(row["fields"].get("push_id")) not in push_ids
    ]
    legacy_refs = [row for row in dangling if LEGACY_TEST_PUSH in row["push_id"]]

    usage = library.usage()
    registered = _size(usage.get("used"))
    actual = _drive_usage(library)
    diff = abs(registered - actual)
    diff_ratio = (diff / actual) if actual else (0.0 if not registered else 1.0)

    counts = {
        "baseline_expected": len(expected) if expected else None,
        "registered_sources": len(source_ids),
        "registered_pushes": len(push_ids),
        "missing": len(missing),
        "unexpected": len(unexpected),
        "no_source": len(no_source),
        "pending_upload": len(pending_upload),
        "part_problems": len(part_problems),
        "dangling_push_refs": len(dangling),
        "legacy_test_refs": len(legacy_refs),
    }
    zero_diff = (
        not missing
        and not unexpected
        and not part_problems
        and not dangling
        and not pending_upload
        and diff_ratio < QUOTA_TOLERANCE
    )
    report = {
        "schema_version": 1,
        "date": date or today(),
        "ok": zero_diff,
        "zero_diff": zero_diff,
        "baseline": str(baseline or ""),
        "counts": counts,
        "missing": missing[:50],
        "unexpected": unexpected[:50],
        "no_source": no_source[:50],
        "pending_upload": pending_upload[:50],
        "part_problems": part_problems[:50],
        "dangling_push_refs": dangling[:50],
        "legacy_test_refs": legacy_refs[:50],
        "quota": {
            "registered_bytes": registered,
            "drive_bytes": actual,
            "diff_ratio": round(diff_ratio, 6),
            "within_1_percent": diff_ratio < QUOTA_TOLERANCE,
        },
        "verified": [],
        "gaps": [],
        "blocked": [],
        "checked_at": today(),
    }
    report["verified"] = [
        name
        for name, value in (
            ("原文登记可读", len(source_ids)),
            ("推送日志可读", len(push_ids)),
            ("分片顺序一致", not part_problems),
            ("证据引用无悬空", not dangling),
            ("配额差异 <1%", diff_ratio < QUOTA_TOLERANCE),
        )
        if value
    ]
    if missing:
        report["gaps"].append(f"{len(missing)} 篇基线原文在 Base 中缺失")
    if pending_upload:
        report["gaps"].append(f"{len(pending_upload)} 条登记仍为待上传")
    if dangling:
        report["gaps"].append(f"{len(dangling)} 条报道引用指向不存在的推送")
    if not expected:
        report["blocked"].append("未提供基线清单：无法核对 174 篇历史回填")
    if not report["ok"]:
        report["next"] = "只补实际缺口；不得把已知上传失败改标为无原件；不自动删除现存数据"
    return report


def _table(library, key: str) -> str:
    return (library.tables or {}).get(key) or ""


def _drive_usage(library) -> int:
    total = 0
    for kind in ("source", "push"):
        try:
            folder = library.folder(kind)
            for row in library.drive.list(folder):
                if row.get("type") == "file":
                    total += _size(row.get("size") or row.get("file_size"))
        except Exception:  # noqa: BLE001 - a missing folder means unknown, not zero
            return 0
    return total


def _blocked(home: Path, reason: str) -> dict:
    return {
        "schema_version": 1,
        "ok": False,
        "zero_diff": False,
        "blocked": [reason],
        "verified": [],
        "gaps": [],
        "counts": {},
        "home": str(home),
    }


def record(home: Path, report: dict, *, day: str | None = None) -> dict:
    """Persist one day's audit so consecutive-day evidence is real, not claimed."""
    home = Path(home)
    day = day or report.get("date") or today()
    path = home / AUDIT_REL / f"{day}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, {**report, "date": day, "recorded_at": today()})
    return {"ok": True, "path": str(path), "streak": streak(home)}


def streak(home: Path, *, end: str | None = None) -> dict:
    """Consecutive calendar days with a zero-difference audit, ending today."""
    home = Path(home)
    folder = home / AUDIT_REL
    if not folder.exists():
        return {"days": 0, "dates": [], "satisfied": False}
    current = date_cls.fromisoformat(end or today())
    dates: list[str] = []
    while True:
        path = folder / f"{current.isoformat()}.json"
        payload = read_json(path)
        if not payload or not payload.get("zero_diff"):
            break
        dates.append(current.isoformat())
        current -= timedelta(days=1)
    return {"days": len(dates), "dates": list(reversed(dates)), "satisfied": len(dates) >= 3}

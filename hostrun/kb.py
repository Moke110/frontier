"""Knowledge base: create an empty one, or attach an existing one by link.

Two entry paths, both resumable and neither destructive:

  attach  用户给飞书知识库链接 → 解析 token → 校验权限与结构 → 记录缺口
  create  在用户提供的空 Base 里建齐知识五表 + 库四表 + 反馈三表

``verify`` is the shared answer: which tables exist, which are missing, whether
the base still holds user data (never overwritten), and whether a "new" base is
actually empty. Fixtures are never imported into a real base.
"""

from __future__ import annotations

import re
from pathlib import Path

from common import now, read_json, write_json
from hostrun import feedback as feedback_mod
from hostrun.base import HostRunError, base_client, load_config, update_config

KNOWLEDGE_TABLES = {
    "cards": "知识卡片",
    "propositions": "命题",
    "evidence": "证据",
    "papers": "报道",
    "logs": "变更日志",
}
LIBRARY_TABLES = {"sources": "原文", "pushes": "推送日志", "decisions": "决定", "config": "配置"}
FEEDBACK_TABLES = feedback_mod.TABLE_NAMES
REQUIRED = {**KNOWLEDGE_TABLES, **LIBRARY_TABLES, **FEEDBACK_TABLES}

KNOWLEDGE_SCHEMA = {
    "cards": [
        {"name": "卡片 ID", "type": "text"},
        {"name": "label", "type": "text"},
        {"name": "ontology", "type": "text"},
        {"name": "annotation", "type": "text"},
        {"name": "created_at", "type": "text"},
        {"name": "updated_at", "type": "text"},
    ],
    "propositions": [
        {"name": "命题 ID", "type": "text"},
        {"name": "title", "type": "text"},
        {"name": "review", "type": "text"},
        {"name": "证据更新计数", "type": "number"},
        {"name": "created_at", "type": "text"},
        {"name": "updated_at", "type": "text"},
    ],
    "evidence": [
        {"name": "证据 ID", "type": "text"},
        {"name": "stance", "type": "text"},
        {"name": "conclusion", "type": "text"},
        {"name": "migrated_from_v2", "type": "checkbox"},
        {"name": "created_at", "type": "text"},
        {"name": "updated_at", "type": "text"},
    ],
    "papers": [
        {"name": "paper_id", "type": "text"},
        {"name": "push_id", "type": "text"},
        {"name": "page", "type": "number"},
        {"name": "quote", "type": "text"},
        {"name": "added_at", "type": "text"},
    ],
    "logs": [
        {"name": "变更 ID", "type": "text"},
        {"name": "at", "type": "text"},
        {"name": "action", "type": "text"},
        {"name": "field", "type": "text"},
        {"name": "before", "type": "text"},
        {"name": "after", "type": "text"},
        {"name": "rationale", "type": "text"},
        {"name": "source_kind", "type": "text"},
        {"name": "source_id", "type": "text"},
    ],
}
LINK_SPECS = {
    "propositions": {"关联卡片": "cards", "证据": "evidence", "变更日志": "logs"},
    "evidence": {"报道": "papers"},
    "papers": {"原文": "sources"},
}
INITIAL_REL = Path("install") / "initial-build.json"

_TOKEN = re.compile(r"/(?:base|wiki)/([A-Za-z0-9]+)")
_TABLE = re.compile(r"[?&]table=([A-Za-z0-9]+)")


def parse_link(link: str) -> dict:
    """Accept a Feishu base link, a bare token, or link + ?table=."""
    text = str(link or "").strip()
    if not text:
        raise HostRunError("需要飞书知识库链接或 base token")
    match = _TOKEN.search(text)
    if match:
        token = match.group(1)
    elif re.fullmatch(r"[A-Za-z0-9]{8,}", text):
        token = text
    else:
        raise HostRunError(f"无法从链接解析 base token：{text[:120]}")
    table = _TABLE.search(text)
    return {"base_token": token, "table_id": table.group(1) if table else None, "link": text}


def _existing(base_client_obj) -> dict[str, str]:
    listing = base_client_obj.list_tables()
    out: dict[str, str] = {}
    for row in listing:
        out.setdefault(str(row.get("name") or ""), str(row.get("id") or ""))
    return out


def verify(home: Path, *, client=None, expect_empty: bool = False) -> dict:
    """Structure, permissions and data-preservation facts — no writes."""
    home = Path(home)
    config = read_json(home / "knowledge" / "base.json") or {}
    client = base_client(home, client=client)
    by_name = _existing(client)
    configured = config.get("tables") or {}
    present, missing, count = {}, [], {}
    for key, name in REQUIRED.items():
        table_id = configured.get(key)
        if table_id and table_id in by_name.values():
            present[key] = table_id
            continue
        if name in by_name:
            present[key] = by_name[name]
            continue
        missing.append(name)
    problems: list[str] = []
    for key, table_id in present.items():
        try:
            count[key] = len(client.list(table_id) or [])
        except Exception as exc:  # noqa: BLE001 - permission problems are results
            problems.append(f"{REQUIRED[key]}：读取失败（{exc}）")
    has_data = any(count.get(key) for key in ("cards", "propositions", "papers", "evidence"))
    fixture_titles = []
    if expect_empty and has_data:
        fixture_titles = [
            str(row["fields"].get("title") or row["fields"].get("label") or "")
            for key in ("propositions", "cards")
            for row in (client.list(present[key]) if present.get(key) else [])
        ][:5]
    ok = not missing and not problems and (not expect_empty or not has_data)
    return {
        "ok": ok,
        "base_token": config.get("base_token") or "",
        "base_url": config.get("base_url") or "",
        "present": present,
        "missing": missing,
        "counts": count,
        "has_user_data": has_data,
        "expect_empty": expect_empty,
        "problems": problems,
        "sample_titles": fixture_titles,
        "checked_at": now(),
    }


def attach(
    home: Path,
    link: str,
    *,
    client=None,
    base_url: str | None = None,
    expect_empty: bool = False,
) -> dict:
    """Connect an existing base: resolve the link, inspect, never overwrite."""
    home = Path(home)
    parsed = parse_link(link)
    config = read_json(home / "knowledge" / "base.json") or {}
    previous = config.get("base_token")
    if previous and previous != parsed["base_token"]:
        # Switching bases would orphan the old one; make it an explicit act.
        return {
            "ok": False,
            "reason": "different_base_configured",
            "configured": previous,
            "requested": parsed["base_token"],
            "note": "当前已配置另一个知识库；如确需改用新库，先备份并确认",
        }
    config = {
        **config,
        "schema_version": config.get("schema_version") or 1,
        "base_token": parsed["base_token"],
        "base_url": base_url or config.get("base_url") or parsed["link"],
        "tables": config.get("tables") or {},
    }
    path = home / "knowledge" / "base.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, config)
    client = base_client(home, client=client)
    report = verify(home, client=client, expect_empty=expect_empty)
    if not report["ok"] and report["missing"]:
        report["next"] = "缺少的表由宿主用 hostrun kb create-tables 补齐，或改用 hostrun kb create 新建空库"
    return {**report, "attached": True, "base_token": parsed["base_token"]}


def _drive_for(home: Path, client, drive=None):
    """Offline bases get the fixture Drive, so no tenant is touched by accident."""
    if drive is not None:
        return drive
    from library.offline import JsonBase, JsonDrive

    if isinstance(client, JsonBase):
        return JsonDrive(home / "library" / "offline-drive.json")
    return None


def create_tables(home: Path, *, client=None, dry_run: bool = False, drive=None) -> dict:
    """Create any missing knowledge/base/library/feedback tables in the Base."""
    home = Path(home)
    config = read_json(home / "knowledge" / "base.json") or {}
    if not config.get("base_token"):
        raise HostRunError("先在 knowledge/base.json 配置 base_token（hostrun kb attach/create）")
    client = base_client(home, client=client)
    drive = _drive_for(home, client, drive)
    by_name = _existing(client)
    tables = dict(config.get("tables") or {})
    actions: list[str] = []

    for key, name in KNOWLEDGE_TABLES.items():
        if name in by_name:
            tables.setdefault(key, by_name[name])
            continue
        actions.append(f"create table {name}")
        if dry_run:
            tables[key] = f"tbl_dry_{name}"
            continue
        tables[key] = client.create_table(name, KNOWLEDGE_SCHEMA[key])
        by_name[name] = tables[key]
        for field, target_key in LINK_SPECS.get(key, {}).items():
            target = tables.get(target_key)
            if target and not str(target).startswith("tbl_dry_"):
                client.create_fields(
                    tables[key],
                    [{"name": field, "type": "link", "link_table": target, "bidirectional": False}],
                )

    if not dry_run:
        write_json(home / "knowledge" / "base.json", {**config, "tables": tables})
        config = {**config, "tables": tables}

    if dry_run:
        actions.append("plan library tables (原文/推送日志/决定/配置)")
        actions.append("plan feedback tables (问题/反馈/更正)")
        return {"ok": True, "dry_run": True, "actions": actions, "tables": tables}

    from library.setup import setup as library_setup

    library_report = library_setup(home, client=client, drive=drive)
    actions.extend(library_report.get("actions") or [])
    feedback_report = feedback_mod.setup(home, client=client)
    actions.extend(feedback_report.get("actions") or [])
    return {
        "ok": True,
        "dry_run": False,
        "actions": actions,
        "tables": tables,
        "base_token": config.get("base_token"),
    }


def create_empty(
    home: Path,
    link_or_token: str,
    *,
    client=None,
    dry_run: bool = False,
    name: str = "",
    drive=None,
) -> dict:
    """New knowledge base: tables only, zero cards, zero propositions, no fixtures."""
    home = Path(home)
    parsed = parse_link(link_or_token)
    config = read_json(home / "knowledge" / "base.json") or {}
    previous = config.get("base_token")
    if previous and previous != parsed["base_token"] and not dry_run:
        return {
            "ok": False,
            "reason": "different_base_configured",
            "configured": previous,
            "requested": parsed["base_token"],
        }
    if not dry_run:
        write_json(
            home / "knowledge" / "base.json",
            {
                "schema_version": 1,
                "base_token": parsed["base_token"],
                "base_url": name or parsed["link"],
                "tables": config.get("tables") or {},
            },
        )
    created = create_tables(home, client=client, dry_run=dry_run, drive=drive)
    report = verify(home, client=client, expect_empty=True)
    update_config(home, knowledge_base={
        "state": "ok" if report["ok"] else "blocked",
        "base_token": parsed["base_token"],
        "name": name,
        "at": now(),
    })
    return {"ok": report["ok"], "created": created, "verify": report}


def record_initial_confirmation(
    home: Path,
    themes: list[dict],
    *,
    confirmed_by_user: bool,
    note: str = "",
) -> dict:
    """Themes stay drafts until the user confirms them (initial build gate)."""
    home = Path(home)
    if not confirmed_by_user:
        return {"ok": False, "reason": "needs_user_confirmation", "themes": themes}
    payload = {
        "schema_version": 1,
        "confirmed_at": now(),
        "note": note,
        "themes": [
            {
                "name": str(theme.get("name") or theme.get("theme") or ""),
                "cards": theme.get("cards") or [],
                "propositions": theme.get("propositions") or [],
            }
            for theme in themes
        ],
    }
    path = home / INITIAL_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, payload)
    return {"ok": True, "path": str(path), "confirmed_at": payload["confirmed_at"]}


def initial_confirmed(home: Path, theme: str | None = None) -> dict:
    payload = read_json(Path(home) / INITIAL_REL) or {}
    names = [t.get("name") for t in payload.get("themes") or []]
    if not payload:
        return {"ok": False, "reason": "not_confirmed", "confirmed": [], "note": "初始知识需先按主题确认"}
    if theme and theme not in names:
        return {"ok": False, "reason": "theme_not_confirmed", "confirmed": names, "theme": theme}
    return {"ok": True, "confirmed": names, "confirmed_at": payload.get("confirmed_at")}

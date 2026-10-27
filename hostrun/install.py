"""Installation: capability probes, resumable progress, honest report.

The host agent drives installation (ADR 0005). This module is what it calls so
that "installed" means something checkable:

- every step is recorded with one of ``ok / blocked / untested / pending``;
- a missing capability is *blocked*, never silently "installed";
- re-running reuses recorded components and never touches user data outside
  ``<home>/install/``;
- the report separates what works, what is blocked and what was not tested.

Nothing here writes environment variables, PATH, the registry, services or OS
scheduler entries.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import ensure_dir, now, read_json, write_json
from hostrun.base import (
    HostRunError,
    load_config,
    redact,
    resolve_executable,
    run_json,
    save_config,
    update_config,
)

STATE_STATUSES = ("ok", "blocked", "untested", "pending")
STEPS = (
    "host",
    "dependencies",
    "lark_cli",
    "identity",
    "knowledge_base",
    "schedules",
    "first_run",
)
STEP_NOTES = {
    "host": "宿主产品、版本、本机执行、内置调度与实际权限",
    "dependencies": "私有解释器、PyYAML、仓库副本",
    "lark_cli": "飞书 CLI 由显式私有路径解析（仅可执行，未证明已登录）",
    "identity": "飞书 user / bot 身份与所需访问能力",
    "knowledge_base": "新建空库或连接既有知识库并校验结构",
    "schedules": "每日检索、每小时反馈、每日维护的启用确认",
    "first_run": "一次有界真实运行（推送或反馈处理）",
}
MIN_PYTHON = (3, 11)


def state_path(home: Path) -> Path:
    from hostrun.base import STATE_REL

    return Path(home) / STATE_REL


def load_state(home: Path) -> dict:
    state = read_json(state_path(home)) or {}
    state.setdefault("schema_version", 1)
    state.setdefault("steps", {})
    return state


def save_state(home: Path, state: dict) -> Path:
    state["updated_at"] = now()
    path = state_path(home)
    ensure_dir(path.parent)
    write_json(path, state)
    return path


def step_status(home: Path) -> dict:
    return {name: (load_state(home)["steps"].get(name) or {}).get("status", "pending") for name in STEPS}


def next_step(home: Path) -> str | None:
    status = step_status(home)
    return next((name for name in STEPS if status[name] != "ok"), None)


def record(
    home: Path,
    step: str,
    status: str,
    *,
    note: str = "",
    evidence: dict | None = None,
) -> dict:
    """Record one step result. ``ok`` is terminal for this install."""
    if step not in STEPS:
        raise HostRunError(f"unknown install step: {step}")
    if status not in STATE_STATUSES:
        raise HostRunError(f"unknown install status: {status}")
    state = load_state(home)
    steps = state["steps"]
    previous = steps.get(step) or {}
    if previous.get("status") == "ok" and status != "ok":
        # Re-checking must not erase a verified component.
        return state
    entry = {
        "status": status,
        "note": note,
        "at": now(),
        "evidence": redact(evidence or {}),
    }
    if status == "ok":
        entry["first_ok_at"] = previous.get("first_ok_at") or now()
    steps[step] = entry
    save_state(home, state)
    return state


# ------------------------------------------------------------------- probes
def probe_dependencies(
    repo: str | Path,
    *,
    python: str | None = None,
    platform: str | None = None,
) -> dict:
    """Interpreter, PyYAML and a usable repository checkout."""
    repo = Path(repo)
    python = python or sys.executable
    version = tuple(sys.version_info[:3])
    require = ["SKILL.md", "contracts/README.md", "common.py"]
    missing = [name for name in require if not (repo / name).exists()]
    try:
        import yaml  # noqa: F401

        has_yaml = True
    except ModuleNotFoundError:
        has_yaml = False
    ok = version >= MIN_PYTHON and has_yaml and not missing
    notes = []
    if version < MIN_PYTHON:
        notes.append(f"python {'.'.join(map(str, version))} < 3.11")
    if not has_yaml:
        notes.append("PyYAML missing in this interpreter")
    if missing:
        notes.append("repo missing: " + ", ".join(missing))
    return {
        "status": "ok" if ok else "blocked",
        "note": "；".join(notes) or "解释器与仓库可用",
        "evidence": {
            "python": str(python),
            "python_version": ".".join(map(str, version)),
            "platform": platform or sys.platform,
            "repo": str(repo),
            "yaml": has_yaml,
        },
    }


def probe_lark_cli(home: Path, spec: str | None, *, names: list[str] | None = None) -> dict:
    """Executable presence only — never treated as a logged-in identity."""
    found = resolve_executable(
        spec,
        private_dirs=[Path(home) / "bin"],
        names=names or ["lark-cli"],
    )
    if not found["found"]:
        return {
            "status": "blocked",
            "note": "飞书 CLI 未找到：把它装到私有目录并在 install/config.json 的 paths.lark_cli 指向它",
            "evidence": {"source": found["source"]},
        }
    return {
        "status": "ok",
        "note": f"已解析可执行文件（来源 {found['source']}）；登录状态由 identity 步骤单独验证",
        "evidence": {"path": found["path"], "source": found["source"]},
    }


def parse_auth_status(payload: dict) -> dict:
    """Booleans only: the raw payload can carry tokens."""
    identities = (payload or {}).get("identities") or {}
    user = identities.get("user") or {}
    bot = identities.get("bot") or {}
    user_status = str(user.get("tokenStatus") or "").lower()
    bot_status = str(bot.get("tokenStatus") or "").lower()
    return {
        "user_available": bool(user.get("available")),
        "user_ready": bool(user.get("available")) and user_status in {"valid", "ready"},
        "bot_available": bool(bot.get("available")),
        "bot_ready": bool(bot.get("available")) and bot_status in {"valid", "ready"},
        "user_status": user_status,
        "bot_status": bot_status,
        "user_open_id_present": bool(user.get("userOpenId") or user.get("openId")),
    }


def probe_identity(lark_cli_path: str, *, runner=None, timeout: int = 30) -> dict:
    """Authenticated access, distinguished from mere executable presence."""
    if not lark_cli_path:
        return {"status": "blocked", "note": "缺少 lark-cli 路径", "evidence": {}}
    kwargs = {"timeout": timeout}
    if runner is not None:
        kwargs["runner"] = runner
    result = run_json([lark_cli_path, "auth", "status", "--json"], **kwargs)
    if not result.get("ok"):
        return {
            "status": "blocked",
            "note": f"auth status 无法读取：{result.get('error')}",
            "evidence": {},
        }
    facts = parse_auth_status(result["payload"])
    if facts["user_ready"] and facts["bot_ready"]:
        return {
            "status": "ok",
            "note": "user 与 bot 身份均可用",
            "evidence": {k: v for k, v in facts.items() if k != "user_open_id_present"},
        }
    missing = []
    if not facts["user_ready"]:
        missing.append("user")
    if not facts["bot_ready"]:
        missing.append("bot")
    return {
        "status": "blocked",
        "note": "需要用户完成飞书登录/授权：" + "、".join(missing),
        "evidence": {k: v for k, v in facts.items() if k != "user_open_id_present"},
    }


def probe_host(host: dict | None) -> dict:
    """The agent declares what it actually verified on this product/version."""
    host = host or {}
    product = str(host.get("product") or "").strip()
    version = str(host.get("version") or "").strip()
    local = host.get("local_execution")
    schedules = host.get("schedules")
    missing = [
        name
        for name, value in (
            ("product", product),
            ("version", version),
            ("local_execution", local),
            ("schedules", schedules),
        )
        if value in (None, "", False)
    ]
    if missing:
        return {
            "status": "untested" if product else "pending",
            "note": "未确认宿主能力：" + ("、".join(missing) if missing else "无"),
            "evidence": {
                "product": product,
                "version": version,
                "local_execution": bool(local),
                "schedules": bool(schedules),
                "permissions": host.get("permissions") or [],
            },
        }
    return {
        "status": "ok",
        "note": f"{product} {version} 已确认本机执行与内置调度",
        "evidence": {
            "product": product,
            "version": version,
            "mode": host.get("mode") or "",
            "local_execution": True,
            "schedules": True,
            "permissions": host.get("permissions") or [],
            "checked_at": host.get("checked_at") or now(),
            "source": host.get("source") or "宿主 agent 实测",
        },
    }


def default_timezone() -> str:
    return datetime.now().astimezone().tzname() or "UTC"


# ------------------------------------------------------------------- driver
def check(
    home: Path,
    *,
    repo: str | Path | None = None,
    host: dict | None = None,
    lark_cli: str | None = None,
    python: str | None = None,
    timezone_name: str | None = None,
    runner=None,
    platform: str | None = None,
) -> dict:
    """Run every probe that can run offline, record it, return the summary."""
    home = Path(home)
    config = load_config(home, repo=Path(repo) if repo else None)
    repo_path = Path(repo or config["paths"]["repo"])
    ensure_dir(home / "install")
    ensure_dir(home / "bin")

    results: dict[str, dict] = {}
    results["host"] = probe_host(host)
    results["dependencies"] = probe_dependencies(
        repo_path, python=python or config["paths"].get("python"), platform=platform
    )
    lark_result = probe_lark_cli(home, lark_cli or config["paths"].get("lark_cli"))
    results["lark_cli"] = lark_result
    lark_path = (lark_result.get("evidence") or {}).get("path", "")
    results["identity"] = probe_identity(lark_path, runner=runner)

    for step in ("host", "dependencies", "lark_cli", "identity"):
        result = results[step]
        record(home, step, result["status"], note=result["note"], evidence=result["evidence"])

    update_config(
        home,
        paths={"repo": str(repo_path), "lark_cli": lark_path or config["paths"].get("lark_cli", "")},
        timezone=timezone_name or config.get("timezone") or default_timezone(),
    )
    if host and host.get("product"):
        update_config(
            home,
            host={
                "product": str(host.get("product") or ""),
                "version": str(host.get("version") or ""),
                "mode": str(host.get("mode") or ""),
            },
            permissions={"scope": host.get("permissions") or [], "granted_at": now()},
        )
    return summary(home)


def summary(home: Path) -> dict:
    state = load_state(home)
    status = step_status(home)
    buckets: dict[str, list[dict]] = {"working": [], "blocked": [], "untested": [], "pending": []}
    bucket_of = {"ok": "working", "blocked": "blocked", "untested": "untested", "pending": "pending"}
    for name in STEPS:
        entry = state["steps"].get(name) or {}
        buckets[bucket_of[status[name]]].append(
            {"step": name, "label": STEP_NOTES[name], "note": entry.get("note", "")}
        )
    complete = not buckets["blocked"] and not buckets["pending"] and not buckets["untested"]
    return {
        "ok": complete,
        "partial": not buckets["blocked"] and not buckets["pending"],
        "steps": status,
        "next": next_step(home),
        **buckets,
    }


def report(home: Path) -> dict:
    """Install report: working / blocked / untested, paths, timezone, schedules."""
    home = Path(home)
    config = load_config(home)
    state = load_state(home)
    result = summary(home)
    steps = {}
    for name in STEPS:
        entry = state["steps"].get(name) or {}
        steps[name] = {
            "label": STEP_NOTES[name],
            "status": entry.get("status", "pending"),
            "note": entry.get("note", ""),
            "at": entry.get("at"),
            "evidence": entry.get("evidence") or {},
        }
    limitations = [
        f"{STEP_NOTES[name]}：{entry['note']}"
        for name in STEPS
        for entry in [steps[name]]
        if entry["status"] in ("blocked", "untested")
    ]
    return {
        "schema_version": 1,
        "generated_at": now(),
        "ok": result["ok"],
        "partial": result["partial"],
        "host": config.get("host") or {},
        "paths": config.get("paths") or {},
        "timezone": config.get("timezone") or default_timezone(),
        "schedules": config.get("schedules") or {},
        "permissions": config.get("permissions") or {},
        "working": [s["step"] for s in result["working"]],
        "blocked": result["blocked"],
        "untested": result["untested"],
        "pending": result["pending"],
        "steps": steps,
        "limitations": limitations,
        "next": result["next"],
        "rules": [
            "不修改持久环境变量、PATH 或注册表",
            "不创建服务、系统定时任务或常驻进程",
            "凭据只保存在 CLI 自己的机制里，报告不包含任何 token",
        ],
    }


def stale_evidence(home: Path, *, days: int = 7) -> list[str]:
    """Steps whose evidence is older than ``days`` and should be re-checked."""
    state = load_state(home)
    cutoff = datetime.now().astimezone() - timedelta(days=days)
    stale = []
    for name, entry in state["steps"].items():
        at = entry.get("at")
        if not at:
            continue
        try:
            when = datetime.fromisoformat(at)
        except ValueError:
            stale.append(name)
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when < cutoff:
            stale.append(name)
    return stale

"""Schedule spec for the host's own scheduler.

frontier never registers a service, cron entry or system task (ADR 0005). It
emits the three intents the host should schedule and records the user's
confirmation; the host creates the entries itself.

    daily       本地时间 08:00  一次检索推送请求（错过多天合并为一次）
    feedback    每小时          处理已提交反馈并恢复未完成工作，不创建检索请求
    maintenance 每天 07:30      原文/推送库对账与配额，每天至多一次
"""

from __future__ import annotations

import re
from pathlib import Path

from common import now
from hostrun.base import HostRunError, load_config, update_config
from hostrun.install import default_timezone, record

DEFAULT_DAILY = "08:00"
DEFAULT_MAINTENANCE = "07:30"
DEFAULT_FEEDBACK_MINUTE = 5
INTENTS = ("daily", "feedback", "maintenance")
_CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _clock(value: str, label: str) -> str:
    if not _CLOCK.match(str(value or "")):
        raise HostRunError(f"{label} 时间需为 HH:MM（24 小时制），收到 {value!r}")
    return value


def plan(
    home: Path,
    *,
    repo: str | Path | None = None,
    python: str | None = None,
    timezone_name: str | None = None,
    daily: str = DEFAULT_DAILY,
    maintenance: str = DEFAULT_MAINTENANCE,
    feedback_minute: int = DEFAULT_FEEDBACK_MINUTE,
) -> dict:
    """The exact tasks the user is asked to approve, and nothing else."""
    home = Path(home)
    config = load_config(home, repo=Path(repo) if repo else None)
    repo = str(repo or config["paths"]["repo"])
    python = python or config["paths"].get("python") or "python"
    zone = timezone_name or config.get("timezone") or default_timezone()
    daily = _clock(daily, "每日检索")
    maintenance = _clock(maintenance, "每日维护")
    if not 0 <= int(feedback_minute) < 60:
        raise HostRunError("每小时反馈的分钟需在 0-59")
    base = [python, "-m", "hostrun.cli", "--home", str(home), "run", "--repo", repo]
    tasks = [
        {
            "id": "frontier-daily",
            "intent": "daily",
            "every": "day",
            "at": daily,
            "timezone": zone,
            "command": " ".join([*base, "--intent", "daily"]),
            "effect": "请求一篇推送；队列未清空或已有请求时只合并，不重复推送",
        },
        {
            "id": "frontier-feedback",
            "intent": "feedback",
            "every": "hour",
            "at": f"*:{int(feedback_minute):02d}",
            "timezone": zone,
            "command": " ".join([*base, "--intent", "feedback"]),
            "effect": "处理已提交反馈并恢复未完成工作；不创建检索请求；无变化保持安静",
        },
        {
            "id": "frontier-maintenance",
            "intent": "maintenance",
            "every": "day",
            "at": maintenance,
            "timezone": zone,
            "command": " ".join([*base, "--intent", "maintenance"]),
            "effect": "原文库/推送库对账与配额检查，每天至多一次；只提醒，不删除",
        },
    ]
    return {
        "schema_version": 1,
        "generated_at": now(),
        "timezone": zone,
        "tasks": tasks,
        "host_instructions": [
            "由宿主内置调度创建上述三个任务，不要创建 systemd / 系统任务计划 / 常驻进程",
            "只在用户确认时区与启用状态后创建",
            "电脑或客户端关闭期间不承诺执行；下次运行先补做反馈与未完成工作",
        ],
    }


def confirm(
    home: Path,
    *,
    timezone_name: str | None = None,
    daily: str = DEFAULT_DAILY,
    maintenance: str = DEFAULT_MAINTENANCE,
    feedback_minute: int = DEFAULT_FEEDBACK_MINUTE,
    confirmed_by_user: bool = False,
    host_created: bool = False,
    repo: str | Path | None = None,
    python: str | None = None,
) -> dict:
    """Record the user's confirmation. Without it, schedules stay unconfirmed."""
    home = Path(home)
    spec = plan(
        home,
        repo=repo,
        python=python,
        timezone_name=timezone_name,
        daily=daily,
        maintenance=maintenance,
        feedback_minute=feedback_minute,
    )
    if not confirmed_by_user:
        update_config(home, schedules={"enabled": False, "confirmed_at": None, "tasks": spec["tasks"]})
        record(
            home,
            "schedules",
            "untested",
            note="时区与启用状态待用户确认；确认前不创建任务",
            evidence={"timezone": spec["timezone"], "tasks": [t["id"] for t in spec["tasks"]]},
        )
        return {"ok": False, "reason": "needs_user_confirmation", "plan": spec}

    update_config(
        home,
        timezone=spec["timezone"],
        schedules={
            "enabled": bool(host_created),
            "confirmed_at": now(),
            "timezone": spec["timezone"],
            "tasks": spec["tasks"],
        },
    )
    if host_created:
        record(
            home,
            "schedules",
            "ok",
            note=f"宿主已创建 {len(spec['tasks'])} 个任务（{spec['timezone']}）",
            evidence={"timezone": spec["timezone"], "tasks": [t["id"] for t in spec["tasks"]]},
        )
        return {"ok": True, "timezone": spec["timezone"], "tasks": spec["tasks"], "created": True}

    record(
        home,
        "schedules",
        "untested",
        note="用户已确认时间，但宿主尚未创建任务",
        evidence={"timezone": spec["timezone"], "tasks": [t["id"] for t in spec["tasks"]]},
    )
    return {"ok": True, "created": False, "timezone": spec["timezone"], "tasks": spec["tasks"]}


def status(home: Path) -> dict:
    config = load_config(Path(home))
    schedules = config.get("schedules") or {}
    return {
        "schema_version": 1,
        "timezone": config.get("timezone") or default_timezone(),
        "enabled": bool(schedules.get("enabled")),
        "confirmed_at": schedules.get("confirmed_at"),
        "tasks": schedules.get("tasks") or [],
    }

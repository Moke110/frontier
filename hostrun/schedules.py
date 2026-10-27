"""Two host tasks: the daily push and the hourly feedback check.

The host's own scheduler creates them; frontier never writes a service, cron
entry or OS task.  Maintenance is **not** a third task: the first hourly check
of each day folds it in.  The hourly check never starts a retrieval push.

The command embeds the recorded absolute interpreter, repository, data root and
``frontier-run`` skill, so a wake-up does not depend on PATH or a working
directory.  Task creation is not trigger evidence: a scheduled run counts only
when the host actually invoked the generated command with ``--scheduled``.
"""

from __future__ import annotations

import os
import re
import secrets
import shlex
from pathlib import Path

from common import now, read_json, read_jsonl, write_json
from hostrun.base import HostRunError, load_config, update_config
from hostrun.install import default_timezone, record

DEFAULT_DAILY = "08:00"
DEFAULT_FEEDBACK_MINUTE = 5
TASK_DAILY = "frontier-daily"
TASK_FEEDBACK = "frontier-feedback"
RUNS_REL = Path("hostrun") / "runs.jsonl"
_CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _clock(value: str, label: str) -> str:
    if not _CLOCK.match(str(value or "")):
        raise HostRunError(f"{label} 时间需为 HH:MM（24 小时制），收到 {value!r}")
    return value


def _quote(value: str) -> str:
    text = str(value)
    if os.name == "nt":
        return f'"{text}"' if any(char in text for char in " \t") else text
    return shlex.quote(text)


def _paths(home: Path, *, repo=None, python=None, skill=None) -> dict:
    config = load_config(Path(home), repo=Path(repo) if repo else None)
    paths = config.get("paths") or {}
    return {
        "repo": str(repo or paths.get("repo") or ""),
        "home": str(Path(home).resolve()),
        "python": str(python or paths.get("python") or ""),
        "lark_cli": str(paths.get("lark_cli") or ""),
        "skill": str(
            skill
            or paths.get("skill")
            or (config.get("workspace") or {}).get("skill")
            or (Path(str(repo or paths.get("repo") or ".")) / "skills" / "frontier-run" / "SKILL.md")
        ),
    }


def _path_problem(paths: dict) -> dict | None:
    """Task commands must carry recorded, absolute, resolvable paths.

    A bare ``python`` would make the host's wake-up depend on PATH or its working
    directory, so an unrecorded or missing interpreter blocks the plan instead
    of emitting a command.
    """
    python_path = Path(str(paths.get("python") or "")).expanduser()
    repo_path = Path(str(paths.get("repo") or "")).expanduser()
    home_path = Path(str(paths.get("home") or ""))
    skill_path = Path(str(paths.get("skill") or ""))
    checks = (
        (
            not str(paths.get("python") or "").strip()
            or not python_path.is_absolute(),
            "interpreter_not_absolute",
            "未记录解释器的绝对路径；先运行 install toolchain 并把数据根解释器"
            "写入安装配置 paths.python，再重新生成任务",
        ),
        (
            not python_path.is_file(),
            "interpreter_missing",
            f"记录的解释器不存在：{python_path}；先运行 install toolchain"
            "（必要时加 --clear 重建）后重试",
        ),
        (
            not str(paths.get("repo") or "").strip()
            or not repo_path.is_absolute()
            or not repo_path.is_dir(),
            "repo_missing",
            "代码目录未记录或不可用；先完成 install workspace 记录代码目录绝对路径",
        ),
        (
            not str(paths.get("home") or "").strip()
            or not home_path.is_absolute()
            or not home_path.is_dir(),
            "home_missing",
            "数据根未记录或不可用；先完成 install workspace 创建数据根",
        ),
        (
            not str(paths.get("skill") or "").strip()
            or not skill_path.is_absolute()
            or not skill_path.is_file(),
            "skill_missing",
            "运行技能路径未记录或不可读；先运行 install skill 注册 frontier-run",
        ),
    )
    for failed, reason, note in checks:
        if failed:
            return {"ok": False, "reason": reason, "note": note, "paths": paths}
    return None


def plan(
    home: Path,
    *,
    repo: str | Path | None = None,
    python: str | None = None,
    skill: str | None = None,
    timezone_name: str | None = None,
    daily: str = DEFAULT_DAILY,
    feedback_minute: int = DEFAULT_FEEDBACK_MINUTE,
) -> dict:
    """Exactly two tasks, with the paths each wake-up must reuse."""
    home = Path(home).resolve()
    config = load_config(home, repo=Path(repo) if repo else None)
    paths = _paths(home, repo=repo, python=python, skill=skill)
    problem = _path_problem(paths)
    if problem is not None:
        return problem
    zone = timezone_name or config.get("timezone") or default_timezone()
    daily = _clock(daily, "每日推送")
    if not 0 <= int(feedback_minute) < 60:
        raise HostRunError("每小时反馈的分钟需在 0-59")
    base = [
        _quote(paths["python"]),
        "-m",
        "hostrun.cli",
        "--home",
        _quote(paths["home"]),
        "run",
        "--repo",
        _quote(paths["repo"]),
        "--scheduled",
        "--task",
    ]
    tasks = [
        {
            "id": TASK_DAILY,
            "intent": "daily",
            "every": "day",
            "at": daily,
            "timezone": zone,
            "cwd": paths["repo"],
            "command": " ".join([*base, TASK_DAILY, "--intent", "daily"]),
            "effect": "请求并开始一篇推送；队列未清空或已有请求时合并，不重复推送",
            "load_skill": paths["skill"],
        },
        {
            "id": TASK_FEEDBACK,
            "intent": "feedback",
            "every": "hour",
            "at": f"*:{int(feedback_minute):02d}",
            "timezone": zone,
            "cwd": paths["repo"],
            "command": " ".join([*base, TASK_FEEDBACK, "--intent", "feedback"]),
            "effect": "处理已提交反馈与未完成工作；当天首次执行维护；从不发起新检索",
            "load_skill": paths["skill"],
        },
    ]
    return {
        "schema_version": 2,
        "ok": True,
        "generated_at": now(),
        "timezone": zone,
        "paths": paths,
        "tasks": tasks,
        "host_instructions": [
            "只创建上面两个任务；不要另建维护任务、系统任务或常驻进程",
            "每个任务唤醒时先加载 load_skill 指向的 frontier-run，再以 cwd 为工作目录执行 command",
            "命令已包含解释器、仓库与数据根的绝对路径；含空格的参数已按平台引用",
            "只在用户确认时区、频率与启用状态后创建；创建成功不等于真实触发成功",
        ],
        "dedupe": "任务标识固定；重复安装时按 id 复用，不重复创建",
    }


def _knowledge_ready(home: Path) -> bool:
    from hostrun.install import step_status

    return step_status(home).get("knowledge") == "ok"


def _task_proofs(home: Path, task_ids: list[str]) -> dict:
    """Stable per-task proof embedded only in the confirmed command.

    ``schedules trigger`` accepts a run-log row only when its proof matches;
    a hand-written ``run --scheduled`` invocation without the proof is logged
    as an ordinary run.  This cannot stop someone who copies the configured
    command, but it stops accidental self-certification.
    """
    path = Path(home) / "install" / "schedule-proofs.json"
    data = read_json(path) or {}
    changed = False
    for task_id in task_ids:
        if not data.get(task_id):
            data[task_id] = secrets.token_urlsafe(12)
            changed = True
    if changed or not path.exists():
        write_json(path, data)
    return data


def _merge_tasks(existing: list[dict], planned: list[dict], task_ids: dict) -> list[dict]:
    by_id = {row.get("id"): row for row in existing or []}
    merged = []
    for task in planned:
        previous = by_id.get(task["id"]) or {}
        host_task_id = task_ids.get(task["id"]) or previous.get("host_task_id") or ""
        merged.append(
            {
                **task,
                "host_task_id": host_task_id,
                "proof": previous.get("proof") or "",
                "created_at": previous.get("created_at") or (
                    now() if host_task_id else None
                ),
                "enabled": bool(previous.get("enabled", True)),
                "command_changed": bool(
                    previous.get("command") and previous.get("command") != task["command"]
                ),
            }
        )
    return merged


def confirm(
    home: Path,
    *,
    timezone_name: str | None = None,
    daily: str = DEFAULT_DAILY,
    feedback_minute: int = DEFAULT_FEEDBACK_MINUTE,
    confirmed_by_user: bool = False,
    host_created: bool = False,
    enabled: bool = True,
    task_ids: dict | None = None,
    repo: str | Path | None = None,
    python: str | None = None,
    skill: str | None = None,
) -> dict:
    """Record the user's decision and the host's actual task IDs."""
    home = Path(home).resolve()
    spec = plan(
        home,
        repo=repo,
        python=python,
        skill=skill,
        timezone_name=timezone_name,
        daily=daily,
        feedback_minute=feedback_minute,
    )
    if not spec.get("ok"):
        # No valid command exists, so no task may be recorded.
        return spec
    config = load_config(home)
    existing = (config.get("schedules") or {}).get("tasks") or []
    tasks = _merge_tasks(existing, spec["tasks"], task_ids or {})
    proofs = _task_proofs(home, [task["id"] for task in tasks])
    for task in tasks:
        task["proof"] = proofs[task["id"]]
        if "--proof" not in task["command"]:
            task["command"] += f" --proof {task['proof']}"

    if not confirmed_by_user:
        update_config(
            home,
            schedules={
                "enabled": False,
                "confirmed_at": None,
                "timezone": spec["timezone"],
                "tasks": tasks,
            },
        )
        record(
            home,
            "schedules",
            "untested",
            note="时区、频率与启用状态待用户确认；确认前不创建任务",
            evidence={"timezone": spec["timezone"], "tasks": [task["id"] for task in tasks]},
            recheck=True,
        )
        return {"ok": False, "reason": "needs_user_confirmation", "plan": spec}

    if enabled and host_created and not _knowledge_ready(home):
        update_config(
            home,
            timezone=spec["timezone"],
            schedules={
                "enabled": False,
                "confirmed_at": now(),
                "timezone": spec["timezone"],
                "tasks": tasks,
                "blocked_reason": "knowledge_not_ready",
            },
        )
        record(
            home,
            "schedules",
            "blocked",
            note="正式知识未就绪；每日推送不得启用。可先只保留暂停状态",
            evidence={"tasks": [task["id"] for task in tasks]},
            recheck=True,
        )
        return {
            "ok": False,
            "reason": "knowledge_not_ready",
            "note": "先完成正式知识初始化，再启用每日推送",
            "tasks": tasks,
            "plan": spec,
        }

    created = bool(host_created and all(task.get("host_task_id") for task in tasks))
    update_config(
        home,
        timezone=spec["timezone"],
        schedules={
            "enabled": bool(enabled and created),
            "confirmed_at": now(),
            "timezone": spec["timezone"],
            "tasks": tasks,
            "blocked_reason": None,
        },
    )
    if not host_created:
        record(
            home,
            "schedules",
            "untested",
            note="用户已确认，但宿主尚未创建任务",
            evidence={"timezone": spec["timezone"], "tasks": [task["id"] for task in tasks]},
            recheck=True,
        )
        return {"ok": True, "created": False, "enabled": False, "timezone": spec["timezone"], "tasks": tasks}
    if not all(task.get("host_task_id") for task in tasks):
        record(
            home,
            "schedules",
            "blocked",
            note="宿主创建了任务但未提供两个真实任务标识；无法去重或验证触发",
            evidence={"tasks": tasks},
            recheck=True,
        )
        return {
            "ok": False,
            "reason": "missing_host_task_ids",
            "note": "为每个任务提供宿主中的真实任务 ID",
            "tasks": tasks,
        }
    record(
        home,
        "schedules",
        "ok",
        note=f"宿主已创建 2 个任务（{spec['timezone']}）；真实触发另行验收",
        evidence={
            "timezone": spec["timezone"],
            "tasks": [
                {"id": task["id"], "host_task_id": task["host_task_id"]} for task in tasks
            ],
        },
        recheck=True,
    )
    record(
        home,
        "scheduled_run",
        "untested",
        note="任务已创建，尚未观察到真实到点运行；手动调用不算",
        evidence={"required": [task["id"] for task in tasks]},
        recheck=True,
    )
    return {
        "ok": True,
        "created": True,
        "enabled": bool(enabled),
        "timezone": spec["timezone"],
        "tasks": tasks,
        "next": "等待宿主到点触发后运行 schedules trigger 留证",
    }


def pause(home: Path, *, confirmed_by_user: bool = False, reason: str = "") -> dict:
    home = Path(home).resolve()
    if not confirmed_by_user:
        return {"ok": False, "reason": "needs_user_confirmation"}
    config = load_config(home)
    schedules = config.get("schedules") or {}
    tasks = [
        {**task, "enabled": False}
        for task in (schedules.get("tasks") or [])
    ]
    update_config(
        home,
        schedules={
            **schedules,
            "enabled": False,
            "paused_at": now(),
            "pause_reason": reason,
            "tasks": tasks,
        },
    )
    record(
        home,
        "schedules",
        "untested",
        note="自动任务已暂停；宿主仍需停用实际任务",
        evidence={"tasks": [task.get("id") for task in tasks], "paused": True},
        recheck=True,
    )
    return {
        "ok": True,
        "enabled": False,
        "host_action_required": "在宿主中停用（或禁用）这些任务，并确认不再触发",
        "task_ids": [task.get("host_task_id") for task in tasks if task.get("host_task_id")],
    }


def resume(home: Path, *, confirmed_by_user: bool = False) -> dict:
    home = Path(home).resolve()
    if not confirmed_by_user:
        return {"ok": False, "reason": "needs_user_confirmation"}
    if not _knowledge_ready(home):
        return {"ok": False, "reason": "knowledge_not_ready"}
    config = load_config(home)
    schedules = config.get("schedules") or {}
    tasks = schedules.get("tasks") or []
    if not tasks or not all(task.get("host_task_id") for task in tasks):
        return {"ok": False, "reason": "tasks_not_created"}
    update_config(
        home,
        schedules={
            **schedules,
            "enabled": True,
            "paused_at": None,
            "tasks": [{**task, "enabled": True} for task in tasks],
        },
    )
    record(
        home,
        "schedules",
        "ok",
        note="自动任务已恢复；宿主需重新启用实际任务",
        evidence={"tasks": [task.get("id") for task in tasks]},
        recheck=True,
    )
    return {
        "ok": True,
        "enabled": True,
        "host_action_required": "在宿主中重新启用这些任务",
        "task_ids": [task.get("host_task_id") for task in tasks],
    }


def _scheduled_rows(home: Path, task: dict) -> list[dict]:
    return [
        row
        for row in read_jsonl(Path(home) / RUNS_REL)
        if row.get("scheduled") is True
        and row.get("task") == task.get("id")
        and row.get("intent") == task.get("intent")
        and row.get("ok") is True
        and (not task.get("proof") or row.get("proof") == task.get("proof"))
    ]


def record_trigger(
    home: Path,
    task_id: str,
    *,
    at: str | None = None,
    evidence: dict | None = None,
) -> dict:
    """Accept a trigger only if the run log shows a scheduled invocation."""
    home = Path(home).resolve()
    config = load_config(home)
    schedules = config.get("schedules") or {}
    tasks = schedules.get("tasks") or []
    task = next((row for row in tasks if row.get("id") == task_id), None)
    if not task:
        raise HostRunError(f"未知任务：{task_id}")
    if not schedules.get("enabled") or not task.get("enabled", True):
        return {"ok": False, "reason": "task_disabled", "note": "任务已暂停，不记录触发"}
    rows = _scheduled_rows(home, task)
    if at:
        rows = [row for row in rows if str(row.get("at") or "") >= str(at)]
    if not rows:
        return {
            "ok": False,
            "reason": "no_scheduled_run",
            "note": "运行日志中没有该任务的真实到点记录；手动调用或声明不能作为证据",
            "task_id": task_id,
        }
    row = rows[-1]
    triggers = [
        item
        for item in (schedules.get("triggers") or [])
        if item.get("task_id") != task_id
    ]
    triggers.append(
        {
            "task_id": task_id,
            "intent": task.get("intent"),
            "at": at or row.get("at"),
            "run_at": row.get("at"),
            "evidence": evidence or {},
            "recorded_at": now(),
        }
    )
    update_config(home, schedules={**schedules, "triggers": triggers})
    verified = {item["task_id"] for item in triggers}
    required = {row["id"] for row in tasks}
    complete = required <= verified
    record(
        home,
        "scheduled_run",
        "ok" if complete else "untested",
        note=(
            "两类任务均已真实到点触发并留下运行日志"
            if complete
            else "已有真实触发；仍缺：" + "、".join(sorted(required - verified))
        ),
        evidence={"triggers": triggers, "required": sorted(required)},
        recheck=True,
    )
    return {
        "ok": complete,
        "task_id": task_id,
        "triggers": triggers,
        "remaining": sorted(required - verified),
        "run": row,
    }


def status(home: Path) -> dict:
    home = Path(home).resolve()
    config = load_config(home)
    schedules = config.get("schedules") or {}
    tasks = schedules.get("tasks") or []
    triggers = {item.get("task_id"): item for item in schedules.get("triggers") or []}
    rows = {}
    for task in tasks:
        rows[task.get("id")] = {
            "id": task.get("id"),
            "intent": task.get("intent"),
            "at": task.get("at"),
            "every": task.get("every"),
            "host_task_id": task.get("host_task_id"),
            "enabled": task.get("enabled", True),
            "triggered_at": (triggers.get(task.get("id")) or {}).get("at"),
            "scheduled_runs": len(_scheduled_rows(home, task)),
        }
    verified = [task_id for task_id in rows if rows[task_id]["triggered_at"]]
    return {
        "schema_version": 2,
        "timezone": config.get("timezone") or default_timezone(),
        "enabled": bool(schedules.get("enabled")),
        "confirmed_at": schedules.get("confirmed_at"),
        "paused_at": schedules.get("paused_at"),
        "created": bool(tasks and all(task.get("host_task_id") for task in tasks)),
        "tasks": rows,
        "triggers": verified,
        "scheduled_run_verified": bool(tasks) and len(verified) == len(tasks),
        "plan": plan(home) if not tasks else None,
    }

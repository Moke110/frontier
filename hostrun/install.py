"""Installation: capability probes, resumable progress, honest report.

The host agent drives installation (ADR 0005). This module is what it calls so
that "installed" means something checkable:

- every step is recorded with one of ``ok / blocked / untested / pending``;
- a missing capability is *blocked*, never silently "installed";
- re-running reuses recorded components and never touches user data outside
  ``<home>/install/``;
- the report separates what works, what is blocked and what was not tested.

Nothing here writes environment variables, PATH, the registry, services or OS
scheduler entries. The listener start/stop scripts are generated for the user to
run by hand; installation never starts that process.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import ensure_dir, now, read_json, write_json
from hostrun import lark as lark_mod
from hostrun import layout
from hostrun import listener as listener_mod
from hostrun import workspace as workspace_mod
from hostrun.base import (
    HostRunError,
    dsh_bin,
    load_config,
    redact,
    require_dsh,
    run_json,
    save_config,
    update_config,
)

STATE_STATUSES = ("ok", "blocked", "untested", "pending")
STEPS = (
    "host",
    "workspace",
    "dependencies",
    "skill",
    "lark_cli",
    "identity",
    "permissions",
    "facilities",
    "test_loop",
    "cleanup",
    "knowledge",
    "schedules",
    "scheduled_run",
    "listener",
    "listener_health",
)
STEP_NOTES = {
    "host": "宿主产品、版本、本机执行、内置调度与实际权限",
    "workspace": "代码目录与资料目录分离（运行时区在代码目录内），已有副本检查与续接",
    "dependencies": "私有 uv、解释器、PyYAML/PyMuPDF 导入探针与仓库副本",
    "skill": "frontier-run 入口指针及参考文件可读",
    "lark_cli": "飞书 CLI 由显式私有路径解析（仅可执行，未证明已登录）",
    "identity": "飞书 user / bot 身份与登录有效期",
    "permissions": "运行时区与 CLI 凭据目录写入、Base/Drive 资源读取与消息权限的真实预检",
    "facilities": "Base 本身、各表、原文库与推送库目录的稳定 ID",
    "test_loop": "关键词驱动的临时闭环（推送、评分、采纳、写入）",
    "cleanup": "本次测试副作用的删除与无残留验证",
    "knowledge": "文献库与用户要求确认后的正式知识卡片",
    "schedules": "每日推送与每日监听巡检两类宿主任务",
    "scheduled_run": "至少一次真实到点的本地定时触发",
    "listener": "监听进程启停脚本、记录的 dsh 路径与心跳可读性（不启动进程）",
    "listener_health": "监听巡检：心跳新鲜度、进程存活与最近成功事件",
}
LISTENER_START_SCRIPT = "frontier-listener.cmd"
LISTENER_STOP_SCRIPT = "frontier-listener-stop.cmd"
LISTENER_WINDOW_TITLE = "frontier-listener"
MIN_PYTHON = (3, 11)
REQUIRED_PERMISSION_SCOPES = [
    scope for scopes in lark_mod.REQUIRED_SCOPES.values() for scope in scopes
]


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
    """The most actionable step: a blocked one first, else the first unfinished."""
    status = step_status(home)
    for name in STEPS:
        if status[name] == "blocked":
            return name
    return next((name for name in STEPS if status[name] != "ok"), None)


def record(
    home: Path,
    step: str,
    status: str,
    *,
    note: str = "",
    evidence: dict | None = None,
    recheck: bool = False,
) -> dict:
    """Record one step result.

    ``ok`` is terminal for a declared capability, so a flaky re-check cannot
    erase verified evidence.  ``recheck=True`` is for components that can
    actually break (workspace paths, interpreter, registered skill): it may
    downgrade the status but keeps ``first_ok_at``.
    """
    if step not in STEPS:
        raise HostRunError(f"unknown install step: {step}")
    if status not in STATE_STATUSES:
        raise HostRunError(f"unknown install status: {status}")
    state = load_state(home)
    steps = state["steps"]
    previous = steps.get(step) or {}
    if previous.get("status") == "ok" and status != "ok" and not recheck:
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
    else:
        entry["first_ok_at"] = previous.get("first_ok_at")
    steps[step] = entry
    save_state(home, state)
    return state


# ------------------------------------------------------------------- probes
INTERPRETER_PROBE = (
    "import sys\n"
    "def version(name):\n"
    "    try:\n"
    "        module = __import__(name)\n"
    "        return getattr(module, '__version__', 'installed')\n"
    "    except Exception:\n"
    "        return ''\n"
    "print('%d.%d.%d' % sys.version_info[:3])\n"
    "print(version('yaml'))\n"
    "print(version('fitz'))\n"
)


def _interpreter_facts(python: str, *, runner=subprocess.run) -> dict:
    """Version, PyYAML and PyMuPDF from the *recorded* interpreter.

    The probe imports both dependencies the runtime needs (the same pair the
    toolchain verifies): a YAML-only interpreter is not a usable installation.
    """
    try:
        if Path(python).resolve() == Path(sys.executable).resolve():
            version = tuple(sys.version_info[:3])
            try:
                import yaml  # noqa: F401

                has_yaml = True
            except ModuleNotFoundError:
                has_yaml = False
            try:
                import fitz  # noqa: F401

                has_fitz = True
            except ModuleNotFoundError:
                has_fitz = False
            return {
                "ok": True,
                "version": version,
                "yaml": has_yaml,
                "fitz": has_fitz,
                "error": "",
            }
        proc = runner(
            [python, "-c", INTERPRETER_PROBE],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "ok": False,
            "version": (0, 0, 0),
            "yaml": False,
            "fitz": False,
            "error": str(exc),
        }
    if proc.returncode != 0:
        return {
            "ok": False,
            "version": (0, 0, 0),
            "yaml": False,
            "fitz": False,
            "error": (proc.stderr or proc.stdout or "interpreter failed")[-400:],
        }
    lines = (proc.stdout or "").strip().splitlines()
    try:
        version = tuple(int(part) for part in lines[0].split("."))
    except (IndexError, ValueError):
        version = (0, 0, 0)
    return {
        "ok": bool(lines),
        "version": version,
        "yaml": len(lines) > 1 and bool(lines[1].strip()),
        "fitz": len(lines) > 2 and bool(lines[2].strip()),
        "error": "",
    }


def probe_dependencies(
    repo: str | Path,
    *,
    python: str | None = None,
    platform: str | None = None,
    home: str | Path | None = None,
    repair: str = "",
    runner=None,
) -> dict:
    """The *recorded* interpreter, PyYAML and a usable repository checkout.

    There is deliberately no fallback to this process's interpreter: an
    unrecorded, missing, relative or in-repo interpreter blocks the dependency
    step with the exact toolchain repair command.
    """
    repo = Path(repo)
    repair_hint = repair or "install toolchain --root <workspace> --clear"
    require = [
        "skills/frontier-run/SKILL.md",
        "skills/frontier-run/references/installation.md",
        "skills/frontier-run/references/workflow.md",
        "contracts/README.md",
        "common.py",
    ]
    missing = [name for name in require if not (repo / name).exists()]
    recorded = bool(str(python or "").strip())
    notes: list[str] = []
    version = (0, 0, 0)
    has_yaml = False
    has_fitz = False
    facts = {"ok": False, "error": ""}
    outside_repo = False
    in_data_root = False
    python_path = Path(str(python)).expanduser() if recorded else Path("")
    outside_repo = (
        python_path.is_absolute() and not python_path.is_relative_to(repo)
    )
    if not recorded:
        notes.append("未记录解释器的绝对路径；依赖未验证")
    elif not python_path.is_absolute():
        notes.append(f"解释器路径不是绝对路径：{python}")
    elif not python_path.is_file():
        notes.append(f"解释器不存在：{python}")
    elif not outside_repo:
        notes.append(f"解释器位于代码目录内，无法写运行时区：{python}")
    else:
        facts = _interpreter_facts(str(python), runner=runner or subprocess.run)
        version = facts["version"]
        has_yaml = facts["yaml"]
        has_fitz = facts["fitz"]
        expected = (Path(home) / workspace_mod.ENV_DIRNAME) if home else None
        in_data_root = bool(expected) and python_path.is_relative_to(expected)
        if not facts["ok"]:
            notes.append(f"解释器不可用：{facts['error']}")
        elif version < MIN_PYTHON:
            notes.append(f"python {'.'.join(map(str, version))} < 3.11")
        elif not has_yaml:
            notes.append("PyYAML missing in this interpreter")
        elif not has_fitz:
            notes.append("PyMuPDF (fitz) missing in this interpreter")
    if missing:
        notes.append("repo missing: " + ", ".join(missing))
    ok = (
        recorded
        and facts["ok"]
        and python_path.is_absolute()
        and python_path.is_file()
        and outside_repo
        and version >= MIN_PYTHON
        and has_yaml
        and has_fitz
        and not missing
    )
    if not ok:
        notes.append(f"修复：{repair_hint}")
    return {
        "status": "ok" if ok else "blocked",
        "note": "；".join(notes) or "解释器与仓库可用",
        "evidence": {
            "python": str(python) if recorded else "",
            "python_version": ".".join(map(str, version)),
            "platform": platform or sys.platform,
            "repo": str(repo),
            "yaml": has_yaml,
            "fitz": has_fitz,
            "recorded": recorded,
            "outside_repo": outside_repo,
            "in_data_root": in_data_root,
            "repair": repair_hint,
        },
    }


def probe_lark_cli(home: Path, spec: str | None, *, names: list[str] | None = None) -> dict:
    """Executable presence only — never treated as a logged-in identity.

    A recorded absolute path (``paths.lark_cli``) or explicit ``--lark-cli`` is
    authoritative: when it no longer exists the step is blocked with
    rediscovery guidance, even if another ``lark-cli`` is on PATH (ADR 0007).
    """
    found = lark_mod.resolve_cli(
        spec,
        private_dirs=[Path(home) / "bin", Path(home) / "lark-cli" / "bin"],
        names=names or ["lark-cli"],
    )
    if not found["found"]:
        if found.get("stale"):
            return {
                "status": "blocked",
                "note": found["note"],
                "evidence": {
                    "path": found.get("path"),
                    "source": found.get("source"),
                    "stale": True,
                },
            }
        return {
            "status": "blocked",
            "note": (
                "飞书 CLI 未找到：用 `lark discover --cli <可执行文件绝对路径>` 记录已有 CLI，"
                "或运行 `lark install --root <workspace>` 私有安装"
            ),
            "evidence": {"source": found["source"]},
        }
    return {
        "status": "ok",
        "note": f"已解析可执行文件（来源 {found['source']}）；登录状态由 identity 步骤单独验证",
        "evidence": {"path": found["path"], "source": found["source"]},
    }


# ------------------------------------------------------ listener (ADR 0008)
def _location_flags(code: Path) -> str:
    """The ``--code``/``--archive`` pair a generated command must carry."""
    code = Path(code).expanduser().resolve()
    try:
        archive = layout.resolve(code=code)["archive"]
    except HostRunError:
        archive = str(layout.default_archive(code))
    return f'--code "{code}" --archive "{archive}"'


def _listener_repair_command(repo: Path, home: Path) -> str:
    """The command a user can copy to record a usable ``paths.dsh``."""
    return (
        f"python -m hostrun.cli {_location_flags(repo)} listener install "
        f'--dsh "<dsh 的绝对路径>"'
    )


def _listener_script_text(
    *, title: str, repo: Path, python: str, home: Path, action: str
) -> str:
    """A user-run cmd script: fixed window title, recorded repo/interpreter."""
    return (
        f"title {title}\n"
        f'cd /d "{repo}"\n'
        f'"{python}" -m hostrun.cli {_location_flags(repo)} listener {action}\n'
    )


def _write_listener_scripts(home: Path, repo: Path, python: str) -> dict:
    bin_dir = ensure_dir(Path(home) / "bin")
    start = bin_dir / LISTENER_START_SCRIPT
    stop = bin_dir / LISTENER_STOP_SCRIPT
    start.write_text(
        _listener_script_text(
            title=LISTENER_WINDOW_TITLE, repo=repo, python=python, home=home, action="serve"
        ),
        encoding="utf-8",
    )
    stop.write_text(
        _listener_script_text(
            title=LISTENER_WINDOW_TITLE, repo=repo, python=python, home=home, action="stop"
        ),
        encoding="utf-8",
    )
    return {"start": start, "stop": stop}


def _heartbeat_facts(home: Path, *, stale_seconds: int) -> tuple[dict | None, str]:
    """Read the heartbeat through the canonical listener helper; never starts.

    ``listener.heartbeat_facts`` owns freshness and naive-UTC handling so this
    probe cannot drift from the ``listener-check`` intent; only the reporting
    shape (``None`` when unusable) is adapted here.
    """
    facts = listener_mod.heartbeat_facts(Path(home), stale_seconds=stale_seconds)
    if facts["problem"]:
        return None, facts["problem"]
    if not facts["present"]:
        return None, ""
    return (
        {
            key: facts[key]
            for key in (
                "path",
                "present",
                "state",
                "age_seconds",
                "pid",
                "updated_at",
                "degraded",
            )
        },
        "",
    )


def probe_listener(home: Path, *, dsh: str | None = None) -> dict:
    """Read-only evidence for the ``listener`` install step.

    Checks the two user-run scripts, the recorded absolute ``dsh`` and (when it
    already exists) the heartbeat's readability and freshness. It never starts
    the process, never creates scripts and never writes a heartbeat.
    """
    home = Path(home)
    config = load_config(home)
    stale_seconds = int(
        (config.get("listener") or {}).get("heartbeat_stale_seconds") or 600
    )
    scripts = {}
    problems: list[str] = []
    for name in (LISTENER_START_SCRIPT, LISTENER_STOP_SCRIPT):
        path = Path(home) / "bin" / name
        present = path.is_file()
        scripts[name] = {"path": str(path), "present": present}
        if not present:
            problems.append(f"启停脚本缺失：{path}")

    recorded_dsh = ""
    if dsh is not None:
        candidate = Path(str(dsh)).expanduser()
        if candidate.is_absolute() and candidate.is_file():
            recorded_dsh = str(candidate)
        else:
            problems.append(f"dsh 不可用：{dsh}")
    else:
        recorded_dsh = dsh_bin(home)
        if not recorded_dsh:
            try:
                require_dsh(home)
            except HostRunError as exc:
                problems.append(str(exc))

    heartbeat, heartbeat_problem = _heartbeat_facts(home, stale_seconds=stale_seconds)
    if heartbeat_problem:
        problems.append(heartbeat_problem)
    evidence = {
        "scripts": scripts,
        "dsh": recorded_dsh,
        "heartbeat": heartbeat,
        "processes_started": False,
    }
    if problems:
        return {"status": "blocked", "note": "；".join(problems), "evidence": evidence}
    note = "启停脚本已生成，记录的 dsh 可用；本步骤未启动进程"
    if heartbeat is not None:
        note += f"；心跳 {heartbeat['age_seconds']}s（{heartbeat['state']}）"
    return {"status": "ok", "note": note, "evidence": evidence}


def listener_install(
    home: Path,
    *,
    dsh: str | None = None,
    python: str | None = None,
    repo: str | Path | None = None,
    dsh_args: list[str] | None = None,
) -> dict:
    """Generate the user-run listener scripts and record the ``listener`` step.

    The scripts still get written when ``dsh`` is missing or invalid, so the user
    can start/stop (or regenerate) the listener after fixing ``paths.dsh``; the
    step itself stays ``blocked`` with a copyable repair command. Never starts
    the listener.

    ``dsh_args`` are the extra argv a derived run passes between the headless
    profile and the task text (for example ``["--patch", "<overlay.yml>"]`` when
    this host's headless profile has no model credential of its own). They are
    recorded only when supplied, so a re-install never silently drops them.
    """
    home = Path(home).expanduser()
    home_path = home.resolve()
    config = load_config(home)
    repo_path = Path(repo or config["paths"].get("repo") or ".").expanduser().resolve()
    python_path = str(python or config["paths"].get("python") or sys.executable)
    repair = _listener_repair_command(repo_path, home_path)

    candidate = (
        str(dsh).strip()
        if dsh is not None
        else str(config["paths"].get("dsh") or "").strip()
    )
    dsh_problem = ""
    recorded_dsh = ""
    if not candidate:
        dsh_problem = "dsh 未记录：paths.dsh 为空"
    else:
        path = Path(candidate).expanduser()
        if not path.is_absolute():
            dsh_problem = f"paths.dsh 不是绝对路径：{candidate}"
        elif not path.is_file():
            dsh_problem = f"paths.dsh 指向的文件不存在：{path}"
        else:
            recorded_dsh = str(path)
    if recorded_dsh:
        update_config(home, paths={"dsh": recorded_dsh})

    scripts = _write_listener_scripts(home_path, repo_path, python_path)
    listener_update = {
        "start_command": str(scripts["start"]),
        "stop_command": str(scripts["stop"]),
    }
    recorded_args: list[str] = []
    args_problem = ""
    if dsh_args is not None:
        if isinstance(dsh_args, str) or not all(
            isinstance(arg, str) for arg in dsh_args
        ):
            args_problem = "dsh_args 必须是字符串列表"
        else:
            recorded_args = [arg for arg in dsh_args if arg.strip()]
            if not recorded_args:
                args_problem = "dsh_args 为空"
    if dsh_args is not None and not args_problem:
        listener_update["dsh_args"] = recorded_args
    update_config(home, listener=listener_update)

    probe = probe_listener(home)
    evidence = {**probe["evidence"], "repair": repair if dsh_problem else ""}
    if args_problem:
        evidence["dsh_args"] = {"recorded": [], "problem": args_problem}
    elif dsh_args is not None:
        evidence["dsh_args"] = {"recorded": recorded_args}
    if dsh_problem:
        status = "blocked"
        note = f"{dsh_problem}；修复：{repair}"
    elif args_problem and dsh_args is not None:
        status = "blocked"
        note = f"{args_problem}；派生运行需要合法的 --dsh-arg 序列"
    else:
        status = probe["status"]
        note = probe["note"]
    record(home, "listener", status, note=note, evidence=evidence, recheck=True)
    return {
        "ok": status == "ok",
        "status": status,
        "note": note,
        "scripts": {"start": str(scripts["start"]), "stop": str(scripts["stop"])},
        "dsh": recorded_dsh,
        "dsh_args": recorded_args,
        "repair": "" if status == "ok" else repair,
        "evidence": evidence,
    }


# ------------------------------------------------------ write-permission probe
LARK_STORE_ENV = "LARK_CLI_HOME"


def lark_store_dir(store_dir: str | Path | None = None) -> Path:
    """The Lark CLI credential/config store location, without reading it.

    ``LARK_CLI_HOME`` wins when the CLI is configured to use a non-default
    store; otherwise the CLI's documented home is ``~/.lark-cli``.
    """
    if store_dir:
        return Path(store_dir).expanduser()
    configured = os.environ.get(LARK_STORE_ENV)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".lark-cli"


def _probe_file_writer(path: Path) -> None:
    path.write_text("frontier write probe\n", encoding="utf-8")


def _nearest_existing_dir(target: Path) -> Path | None:
    current = Path(target).expanduser()
    while True:
        if current.is_dir():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _probe_one_write(target: Path, *, writer=None) -> dict:
    """Create and delete one uniquely named file; carry the exact failure.

    The probe never creates the target directory: creating ``~/.lark-cli`` just
    to test writability would itself be the side effect we promise not to have.
    An existing target is probed in place; a missing one is probed in its
    nearest existing ancestor, which is what would receive the directory.
    """
    target = Path(target).expanduser()
    root = _nearest_existing_dir(target)
    if root is None:
        return {
            "status": "blocked",
            "path": str(target),
            "probe": "",
            "error": "Path has no existing ancestor directory to probe",
        }
    probe = root / f".frontier-write-probe-{uuid.uuid4().hex[:8]}"
    try:
        (writer or _probe_file_writer)(probe)
        probe.unlink()
    except OSError as exc:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
        return {
            "status": "blocked",
            "path": str(target),
            "probe": str(probe),
            "probe_root": str(root),
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "status": "ok",
        "path": str(target),
        "probe": str(probe),
        "probe_root": str(root),
    }


def probe_writes(home: str | Path, *, store_dir=None, writer=None) -> dict:
    """Actual write test for the data root and the CLI credential store.

    Interpreter placement says nothing about host write permission, so both
    locations are proved with a real create/delete cycle.  Credentials are
    never read or copied; only a temporary probe file is written and removed.
    A missing store directory is probed through its nearest existing ancestor,
    so the check never creates ``~/.lark-cli`` as a side effect.
    """
    checks = {
        "data_root": _probe_one_write(Path(home), writer=writer),
        "lark_store": _probe_one_write(lark_store_dir(store_dir), writer=writer),
    }
    status = (
        "ok"
        if all(check["status"] == "ok" for check in checks.values())
        else "blocked"
    )
    return {"status": status, **checks}


def parse_auth_status(payload: dict) -> dict:
    """Booleans only: the raw payload can carry tokens.

    Shares one readiness rule with ``hostrun.lark`` so the install report and
    ``lark status`` never disagree: a refreshable identity is usable, an
    expired one is not.
    """
    facts = lark_mod.parse_auth(payload)
    return {
        "user_available": facts["user"]["available"],
        "user_ready": facts["user"]["ready"],
        "bot_available": facts["bot"]["available"],
        "bot_ready": facts["bot"]["ready"],
        "user_status": facts["user"]["status"],
        "bot_status": facts["bot"]["status"],
        "user_open_id_present": facts["user_open_id_present"],
        "dpop_key_status": facts["dpop_key_status"],
        "dpop_mode": facts["dpop_mode"],
        "refresh_pending": [
            name
            for name in ("user", "bot")
            if facts[name]["ready"]
            and facts[name]["status"] in lark_mod.REFRESHABLE_STATUSES
        ],
        "scopes": facts["scopes"],
    }


def probe_identity(lark_cli_path: str, *, runner=None, timeout: int = 30) -> dict:
    """Authenticated access, distinguished from mere executable presence.

    ``--verify`` is passed so this probe and ``lark status`` share one
    readiness rule (refreshable is usable, expired is not).
    """
    if not lark_cli_path:
        return {"status": "blocked", "note": "缺少 lark-cli 路径", "evidence": {}, "scopes": []}
    kwargs = {"timeout": timeout}
    if runner is not None:
        kwargs["runner"] = runner
    result = run_json([lark_cli_path, "auth", "status", "--json", "--verify"], **kwargs)
    if not result.get("ok"):
        return {
            "status": "blocked",
            "note": f"auth status 无法读取：{result.get('error')}",
            "evidence": {},
            "scopes": [],
        }
    facts = parse_auth_status(result["payload"])
    scopes = facts.pop("scopes", [])
    if facts["user_ready"] and facts["bot_ready"]:
        return {
            "status": "ok",
            "note": "user 与 bot 身份均可用",
            "evidence": {k: v for k, v in facts.items() if k != "user_open_id_present"},
            "scopes": scopes,
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
        "scopes": scopes,
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


_TZ_ALIASES = {
    "中国标准时间": "Asia/Shanghai",
    "China Standard Time": "Asia/Shanghai",
    "UTC": "UTC",
    "Coordinated Universal Time": "UTC",
    "Tokyo Standard Time": "Asia/Tokyo",
    "Korea Standard Time": "Asia/Seoul",
    "Pacific Standard Time": "America/Los_Angeles",
    "Eastern Standard Time": "America/New_York",
    "Central European Standard Time": "Europe/Berlin",
    "GMT Standard Time": "Europe/London",
}


def default_timezone() -> str:
    """A stable zone name; Windows ``tzname()`` is localized, so map common ones."""
    name = datetime.now().astimezone().tzname() or "UTC"
    return _TZ_ALIASES.get(name, name)


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
    workspace_root: str | Path | None = None,
    base_token: str | None = None,
    folders: list[str] | None = None,
    store_dir: str | Path | None = None,
    writer=None,
) -> dict:
    """Run every probe that can run offline, record it, return the summary."""
    home = Path(home)
    # A probe that receives ``None`` would fail when it spawns the CLI.  One
    # normalization here keeps every default-runner path (identity, resource
    # preflight) working when the caller leaves ``runner`` unset.
    runner = runner or subprocess.run
    config = load_config(home, repo=Path(repo) if repo else None)
    repo_path = Path(repo or config["paths"]["repo"])
    ensure_dir(home / "install")
    ensure_dir(home / "bin")

    results: dict[str, dict] = {}
    results["host"] = probe_host(host)

    if workspace_root:
        ws = workspace_mod.status(workspace_root)
        repo_ok = bool(ws.get("repo")) and (Path(ws["repo"]) / ".git").exists()
        home_ok = bool(ws.get("home")) and Path(ws["home"]).is_dir()
        layout_ok = repo_ok and home_ok
        layout_problems = []
        if not repo_ok:
            layout_problems.append(f"代码目录不可用：{ws.get('repo') or '<未记录>'}")
        if not home_ok:
            layout_problems.append(f"运行时区不可用：{ws.get('home') or '<未记录>'}")
        results["workspace"] = {
            "status": "ok" if layout_ok else "blocked",
            "note": (
                "代码目录与资料目录已记录且可用"
                if layout_ok
                else "；".join(layout_problems)
            ),
            "evidence": {
                "root": ws.get("root"),
                "repo": ws.get("repo"),
                "home": ws.get("home"),
                "commit": ws.get("commit"),
            },
        }
        skill = workspace_mod.verify_skill(ws)
        results["skill"] = {
            "status": "ok" if skill["ok"] else "blocked",
            "note": f"入口 {skill['skill']}" if skill["ok"] else "；".join(skill["problems"]),
            "evidence": {
                "skill": skill["skill"],
                "entry": skill["entry"],
                "references": skill["references"],
            },
        }
        if ws.get("repo"):
            repo_path = Path(ws["repo"])
        update_config(
            home,
            workspace={
                "root": ws.get("root"),
                "repo": ws.get("repo"),
                "home": ws.get("home"),
                "skill": ws.get("skill"),
            },
        )
        if ws.get("python"):
            update_config(home, paths={"python": ws["python"]})
        if ws.get("uv"):
            update_config(home, paths={"uv": ws["uv"]})
        if ws.get("venv"):
            update_config(home, paths={"venv": ws["venv"]})

    repair = (
        workspace_mod.repair_command(workspace_root, home)
        if workspace_root
        else f"python -m hostrun.cli {_location_flags(repo_path)} install toolchain "
        f"--root <workspace> --clear"
    )
    results["dependencies"] = probe_dependencies(
        repo_path,
        python=python or config["paths"].get("python"),
        platform=platform,
        home=home,
        repair=repair,
    )
    lark_result = probe_lark_cli(home, lark_cli or config["paths"].get("lark_cli"))
    results["lark_cli"] = lark_result
    lark_path = (
        (lark_result.get("evidence") or {}).get("path", "")
        if lark_result["status"] == "ok"
        else ""
    )
    results["identity"] = probe_identity(lark_path, runner=runner)

    # Authorization and real resource reads are a separate fact from login:
    # a successful identity probe never stands in for them.
    facilities = read_json(home / "install" / "facilities.json") or {}
    recorded_folders = facilities.get("folders") or {}
    write_checks = probe_writes(home, store_dir=store_dir, writer=writer)
    authz = lark_mod.authorization(
        results["identity"].get("scopes") or [],
        required=REQUIRED_PERMISSION_SCOPES,
    )
    explicit_folders = list(folders or [])
    if not explicit_folders:
        explicit_folders = [
            folder
            for folder in (recorded_folders.get("source"), recorded_folders.get("push"))
            if folder
        ]
    resources = lark_mod.resource_preflight(
        home,
        lark_path or None,
        base_token=base_token or (facilities.get("base") or {}).get("token"),
        folders=explicit_folders,
        runner=runner,
    )
    write_problems = [
        f"{label} {check['path']}（{check['error']}）"
        for label, check in (
            ("运行时区", write_checks["data_root"]),
            ("飞书 CLI 凭据目录", write_checks["lark_store"]),
        )
        if check["status"] != "ok"
    ]
    if write_problems or authz["status"] == "blocked" or resources["status"] == "blocked":
        permissions_status = "blocked"
    elif authz["status"] == "ok" and resources["status"] == "ok":
        permissions_status = "ok"
    else:
        # ``untested`` = no resource tokens to probe yet, not a pass: #53 stays
        # blocked until a real Base/Drive read succeeds.
        permissions_status = "untested"
    note_parts = []
    if write_problems:
        note_parts.append("写入权限不足：" + "；".join(write_problems))
    if not lark_path:
        note_parts.append("飞书 CLI 不可用，登录、授权范围与资源读取均未验证")
    elif permissions_status == "ok":
        note_parts.append("授权范围与资源读取均已验证")
    else:
        note_parts.append(authz.get("note") or resources.get("note", ""))
    permissions_note = "；".join(part for part in note_parts if part)
    results["permissions"] = {
        "status": permissions_status,
        "note": permissions_note,
        "evidence": {
            "granted": authz.get("granted"),
            "missing": authz.get("missing"),
            "writes": write_checks,
            "base": resources.get("base"),
            "drive": resources.get("drive"),
            "messages": resources.get("messages"),
        },
    }
    # ADR 0008: the listener is the only resident component, started by the
    # user. The probe reads scripts/dsh/heartbeat only — it never starts it.
    results["listener"] = probe_listener(home)

    for step in (
        "host",
        "workspace",
        "dependencies",
        "skill",
        "lark_cli",
        "identity",
        "permissions",
        "listener",
    ):
        result = results.get(step)
        if not result:
            continue
        record(
            home,
            step,
            result["status"],
            note=result["note"],
            evidence=result["evidence"],
            recheck=step
            in {"workspace", "dependencies", "skill", "identity", "permissions", "listener"},
        )

    # The health of a *running* listener is proven by a real listener-check run,
    # not by install; before that it stays honestly untested.
    if not (load_state(home)["steps"].get("listener_health") or {}).get("status"):
        record(
            home,
            "listener_health",
            "untested",
            note="尚未执行真实巡检；证据由 run --intent listener-check 写入",
        )

    host_permissions = (
        list(host.get("permissions") or [])
        if host and host.get("product")
        else None
    )
    permissions_update = {
        "scope": authz.get("granted") or [],
        "missing": authz.get("missing") or [],
        "checked_at": now(),
    }
    if host_permissions is not None:
        permissions_update["host_scope"] = host_permissions
        permissions_update["granted_at"] = now()
    update_config(
        home,
        paths={"repo": str(repo_path), "lark_cli": lark_path or config["paths"].get("lark_cli", "")},
        permissions=permissions_update,
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


def _public_permissions(permissions: dict) -> dict:
    """Permissions for the install report: never the recipient's open id.

    The verified recipient lives in ``install/recipient.json``.  Older configs
    may still carry ``owner``; it is dropped here so a report can never leak a
    user-identifier original (#53).
    """
    return {
        key: value
        for key, value in (permissions or {}).items()
        if key not in {"owner", "owner_verified_at"}
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
    workspace_root = (config.get("workspace") or {}).get("root")
    workspace = (
        workspace_mod.status(workspace_root) if workspace_root else None
    )
    return {
        "schema_version": 1,
        "generated_at": now(),
        "ok": result["ok"],
        "partial": result["partial"],
        "host": config.get("host") or {},
        "paths": config.get("paths") or {},
        "workspace": workspace,
        "timezone": config.get("timezone") or default_timezone(),
        "schedules": config.get("schedules") or {},
        "permissions": _public_permissions(config.get("permissions") or {}),
        "working": [s["step"] for s in result["working"]],
        "blocked": result["blocked"],
        "untested": result["untested"],
        "pending": result["pending"],
        "steps": steps,
        "limitations": limitations,
        "next": result["next"],
        "rules": [
            "不修改持久环境变量、PATH 或注册表",
            "唯一常驻组件是用户手动启停的 listener（不是服务、不登录自启）",
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

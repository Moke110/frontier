"""Console ``/frontier-init`` step machine (ADR 0009 §7).

The initialization is an ordered, resumable state machine executed inside the
Console.  This ticket delivers its skeleton and the first two steps:

1. **archive directory** — confirm the default archive (``Y``/Enter) or open the
   system folder dialog (``N``); a cancelled dialog falls back to the default.
   A directory outside the code directory is accepted only after a real
   create/delete write probe, and a failed probe tells the user to restart the
   Console with full permissions while keeping progress.
2. **executing agent** — show the recorded absolute ``dsh`` path, its ``--patch``
   credential overlay and the authorization scope, and continue only after the
   user confirms.

The remaining ADR §7 steps (Lark CLI, transport test, facility naming, push time,
knowledge-base gate) are registered as explicit not-yet steps owned by #85/#86/
#87; they are shown, never silently skipped.

State lives in the code directory's runtime area at
``<runtime>/install/initial/state.json`` — the ``layout`` category ``init``.
It is deliberately a **separate** file from ``install.STEPS``: installation
probes and console initialization are different state machines (other tests
assert ``install.STEPS``), and the knowledge-card initialization
(:mod:`hostrun.initialize`) already uses sibling files in the same directory.
Every completed step is persisted immediately, so an interruption resumes at the
first unfinished step and never leaves a half-created facility behind (this
ticket creates none).

Everything interactive is injectable (``reader``, ``out``, ``isatty``,
``pick_folder``, ``write_probe``), so the whole flow is offline-testable.  The
real Windows folder dialog and a real folder outside the DSH workspace stay
``untested`` until recorded live.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

from common import ensure_dir, now, read_json, write_json
from hostrun import layout
from hostrun.base import HostRunError, dsh_bin, load_config

#: ``layout`` already declares ``install/initial`` as the code-directory
#: initialization-state category (#76); the console's step state is one file in
#: it, next to — never inside — ``install.STEPS``.
STATE_REL = layout.CATEGORY_RELS["init"] / "state.json"
SCHEMA_VERSION = 1

#: The ADR §7 order.  ``implemented`` flips in later tickets without reordering.
STEPS = (
    {
        "id": "archive",
        "title": "确认资料目录",
        "implemented": True,
        "ticket": "#84",
    },
    {
        "id": "agent",
        "title": "确认执行 Agent",
        "implemented": True,
        "ticket": "#84",
    },
    {
        "id": "lark",
        "title": "Lark CLI 检测与登录",
        "implemented": False,
        "ticket": "#85",
    },
    {
        "id": "transport",
        "title": "飞书测试消息与 owner 验证",
        "implemented": False,
        "ticket": "#86",
    },
    {
        "id": "naming",
        "title": "设施命名",
        "implemented": False,
        "ticket": "#87",
    },
    {
        "id": "push_time",
        "title": "每日推送时刻",
        "implemented": False,
        "ticket": "#87",
    },
    {
        "id": "knowledge",
        "title": "知识库初始化选择",
        "implemented": False,
        "ticket": "#87",
    },
)
STEP_IDS = tuple(step["id"] for step in STEPS)

FULL_PERMISSION_HINT = "以完整权限重启"


# --------------------------------------------------------------------- paths
def state_path(home: Path) -> Path:
    """``<runtime>/install/initial/state.json``: the initialization state."""
    return Path(home) / STATE_REL


def _default_state() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "steps": {},
        "updated_at": None,
    }


def read_state(home: Path) -> dict:
    """The persisted initialization state; a missing file means "nothing done"."""
    stored = read_json(state_path(home)) or {}
    state = _default_state()
    if isinstance(stored, dict):
        state.update(stored)
    if not isinstance(state.get("steps"), dict):
        state["steps"] = {}
    return state


def record_step(home: Path, step: str, value: dict, *, note: str = "") -> dict:
    """Persist one completed step immediately; later steps read it back."""
    if step not in STEP_IDS:
        raise HostRunError(f"unknown initialization step: {step}")
    state = read_state(home)
    state["schema_version"] = SCHEMA_VERSION
    state["steps"][step] = {
        "status": "ok",
        "at": now(),
        "note": str(note or ""),
        "value": dict(value or {}),
    }
    state["updated_at"] = now()
    path = state_path(home)
    ensure_dir(path.parent)
    write_json(path, state)
    return state


def completed_steps(home: Path) -> list[str]:
    state = read_state(home)
    return [step for step in STEP_IDS if (state["steps"].get(step) or {}).get("status") == "ok"]


# ------------------------------------------------------------------- inputs
def _default_isatty() -> bool:
    try:
        return bool(sys.stdin.isatty())
    except (AttributeError, ValueError):
        return False


def _say(out, text: str) -> None:
    try:
        out.write(str(text) + "\n")
        out.flush()
    except (OSError, ValueError, AttributeError):
        pass


def _ask(reader, out, prompt: str) -> str:
    """One prompt line; EOF/None/Ctrl+C aborts the whole flow."""
    _say(out, prompt)
    try:
        answer = reader(prompt)
    except (EOFError, StopIteration) as exc:
        raise _Aborted from exc
    if answer is None:
        raise _Aborted
    return str(answer).strip()


class _Aborted(Exception):
    """The user left the flow (EOF/Ctrl+C); completed steps stay persisted."""


def _code_dir(home: Path, resolved: dict | None) -> Path:
    if isinstance(resolved, dict) and resolved.get("code"):
        return Path(resolved["code"])
    return Path(home).parent


def _default_archive(home: Path, resolved: dict | None) -> Path:
    if isinstance(resolved, dict) and resolved.get("archive"):
        return Path(resolved["archive"])
    return layout.default_archive(_code_dir(home, resolved))


# -------------------------------------------------------------- write probe
def probe_write(directory: str | Path) -> dict:
    """A real create/delete cycle: placement alone never proves writability."""
    path = Path(directory).expanduser()
    try:
        if not path.is_dir():
            return {"ok": False, "path": str(path), "reason": "not_a_directory"}
        probe = path / f".frontier-init-probe-{uuid.uuid4().hex}"
        with probe.open("w", encoding="utf-8") as handle:
            handle.write("frontier init write probe\n")
        probe.unlink()
    except OSError as exc:
        return {
            "ok": False,
            "path": str(path),
            "reason": "unwritable",
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {"ok": True, "path": str(path), "reason": ""}


def folder_dialog(default: str | Path) -> str | None:
    """The Windows system folder dialog; ``None`` means the user cancelled.

    Uses the stdlib ``tkinter`` picker (no extra dependency, no second terminal).
    A host without Tk cannot open it, so the caller falls back to the default
    directory rather than failing the step.
    """
    try:
        import tkinter
        from tkinter import filedialog
    except Exception:  # noqa: BLE001 - no Tk means no dialog, not a crash
        return None
    root = None
    try:
        root = tkinter.Tk()
        root.withdraw()
        chosen = filedialog.askdirectory(
            parent=root,
            title="选择 frontier 资料目录",
            initialdir=str(default),
            mustexist=True,
        )
        return str(chosen) if chosen else None
    except Exception:  # noqa: BLE001 - a closed/broken dialog cancels the choice
        return None
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:  # noqa: BLE001 - teardown must not raise
                pass


# ------------------------------------------------------------------- steps
def _step_archive(home, code: Path, default: Path, *, reader, out, pick_folder, write_probe) -> dict:
    _say(out, "步骤 1/7：确认资料目录（原文与推送件只放在这里）")
    _say(out, f"默认资料目录：{default}")
    while True:
        answer = _ask(
            reader,
            out,
            "使用默认资料目录？[Y] 确认（回车）/ [N] 选择其他文件夹：",
        )
        choice = answer.lower()
        if choice in ("", "y", "yes"):
            chosen, used_default = default, True
            break
        if choice in ("n", "no"):
            picked = pick_folder(str(default))
            if not picked:
                _say(out, "已取消文件夹选择，继续使用默认资料目录。")
                chosen, used_default = default, True
                break
            chosen = Path(picked).expanduser().resolve()
            used_default = False
            try:
                layout.resolve(code=str(code), archive=str(chosen))
            except HostRunError as exc:
                return {
                    "ok": False,
                    "reason": "archive_invalid",
                    "text": f"资料目录不可用：{exc}\n本次已停在“确认资料目录”，进度已保留。",
                }
            break
        _say(out, "请输入 Y 或 N。")

    outside = not _inside(chosen, code)
    if not used_default and outside:
        check = write_probe(chosen)
        if not check.get("ok"):
            launcher = console_launcher_path(code)
            detail = check.get("error") or check.get("reason") or "未知原因"
            return {
                "ok": False,
                "reason": "archive_unwritable",
                "text": (
                    f"资料目录不可写：{chosen}（{detail}）\n"
                    f"请双击 {launcher} {FULL_PERMISSION_HINT}并保留进度；"
                    "本次已停在“确认资料目录”，之后可继续 /frontier-init。"
                ),
                "path": str(chosen),
            }

    record_step(
        home,
        "archive",
        {
            "path": str(chosen),
            "default": used_default,
            "outside_code": outside,
        },
    )
    _say(out, f"[完成] 资料目录：{chosen}")
    return {"ok": True, "path": str(chosen), "default": used_default}


def agent_facts(home: Path, *, code: Path, archive: Path) -> dict:
    """The executing agent, its credential overlay and its authorization scope."""
    home = Path(home)
    config = load_config(home)
    paths = config.get("paths") or {}
    recorded = str(paths.get("dsh") or "").strip()
    usable = dsh_bin(home)
    dsh_args = [str(arg) for arg in ((config.get("listener") or {}).get("dsh_args") or ())]
    patch = ""
    for index, arg in enumerate(dsh_args):
        if arg == "--patch" and index + 1 < len(dsh_args):
            patch = str(dsh_args[index + 1])
            break
    permissions = config.get("permissions") or {}
    host_scope = [str(item) for item in (permissions.get("host_scope") or ())]
    lark_scope = [str(item) for item in (permissions.get("scope") or ())]
    return {
        "profile": "headless",
        "dsh": usable,
        "recorded_dsh": recorded,
        "usable": bool(usable),
        "dsh_args": dsh_args,
        "patch": patch,
        "patch_exists": bool(patch) and Path(patch).expanduser().is_file(),
        "host_scope": host_scope,
        "lark_scope": lark_scope,
        "cwd": str(code),
        "archive": str(archive),
    }


def _step_agent(home: Path, *, code: Path, archive: Path, reader, out) -> dict:
    facts = agent_facts(home, code=code, archive=archive)
    _say(out, "步骤 2/7：确认执行 Agent（v1 只有 DeepSeek Harness 适配器）")
    if facts["usable"]:
        _say(out, f"执行文件：{facts['dsh']}")
    else:
        recorded = facts["recorded_dsh"] or "（未记录）"
        _say(out, f"执行文件：{recorded}（不可用：未记录或文件不存在）")
    if facts["patch"]:
        state_text = "存在" if facts["patch_exists"] else "不存在"
        _say(out, f"凭据补丁：{facts['patch']}（{state_text}）")
    else:
        _say(out, "凭据补丁：未记录 --patch 覆盖层（headless profile 可能没有账号凭据）")
    _say(out, f"运行方式：dsh --profile {facts['profile']} --json（任务作为最后一个位置参数）")
    _say(out, f"工作目录：{facts['cwd']}")
    scope = "、".join(facts["host_scope"]) if facts["host_scope"] else "（安装记录未写入宿主授权范围）"
    _say(out, f"授权范围（宿主）：{scope}")
    lark_scope = (
        "、".join(facts["lark_scope"]) if facts["lark_scope"] else "（安装记录未写入飞书授权范围）"
    )
    _say(out, f"授权范围（飞书）：{lark_scope}")
    _say(out, "边界：只读写代码目录的运行时区与资料目录的 originals/pushes，不修改 frontier 程序本身。")

    if not facts["usable"]:
        return {
            "ok": False,
            "reason": "dsh_missing",
            "text": (
                "执行 Agent 不可用：paths.dsh 未记录、不是绝对路径或文件不存在。"
                "请先完成安装探针（记录 dsh 绝对路径）后再运行 /frontier-init。"
            ),
            "facts": facts,
        }

    answer = _ask(reader, out, "确认使用该执行 Agent？[Y] 确认（回车）/ [N] 取消：")
    if answer.lower() not in ("", "y", "yes"):
        return {
            "ok": False,
            "reason": "declined",
            "text": "已取消执行 Agent 确认；完成的步骤已保留，可再次运行 /frontier-init。",
            "facts": facts,
        }
    record_step(home, "agent", facts)
    _say(out, "[完成] 执行 Agent 已确认。")
    return {"ok": True, "facts": facts}


# --------------------------------------------------------------------- run
def console_launcher_path(code: Path) -> Path:
    return Path(code) / "bin" / "frontier-console.cmd"


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except (OSError, ValueError):
        return False
    return True


def _not_yet(step: dict) -> dict:
    return {
        "step": step["id"],
        "title": step["title"],
        "ticket": step["ticket"],
    }


def run(
    home: Path,
    *,
    resolved: dict | None = None,
    reader=None,
    out=None,
    isatty=None,
    pick_folder=None,
    write_probe=None,
) -> dict:
    """Run the initialization step machine from the first unfinished step.

    The order of guards is deliberate: a running service is refused before any
    prompt or write, then a non-interactive stdin is refused with the launcher
    hint.  Each completed step is persisted before the next question is asked.
    """
    home = Path(home)
    out = sys.stdout if out is None else out
    reader = reader or (lambda prompt="": input())
    pick = pick_folder or folder_dialog
    probe = write_probe or probe_write
    code = _code_dir(home, resolved)
    default_archive = _default_archive(home, resolved)
    state = read_state(home)
    completed = [step for step in STEP_IDS if (state["steps"].get(step) or {}).get("status") == "ok"]
    base = {
        "action": "init",
        "state_path": str(state_path(home)),
        "completed": completed,
    }

    console_state = read_console_state(home)
    if console_state.get("service") == "running":
        return {
            **base,
            "ok": False,
            "reason": "service_running",
            "text": (
                "服务正在运行，拒绝重跑初始化。"
                "请先停止服务：执行 /frontier-stop 暂停后即可继续 /frontier-init。"
            ),
        }

    tty = False
    try:
        tty = bool((isatty or _default_isatty)())
    except Exception:  # noqa: BLE001 - an undetectable stdin is not a TTY
        tty = False
    if not tty:
        launcher = console_launcher_path(code)
        return {
            **base,
            "ok": False,
            "reason": "not_a_tty",
            "text": (
                "初始化需要交互式终端；请双击 "
                f"{launcher} 启动控制台，或在一个真实的终端窗口里运行 "
                "python -m hostrun.cli console。"
            ),
        }

    not_yet: list[dict] = []
    try:
        for step in STEPS:
            step_id = step["id"]
            if not step["implemented"]:
                not_yet.append(_not_yet(step))
                _say(out, f"[尚未实现] {step['title']}（由 {step['ticket']} 接入，本次不执行）")
                continue
            entry = state["steps"].get(step_id) or {}
            if entry.get("status") == "ok":
                value = entry.get("value") or {}
                completed_line = _completed_line(step_id, value)
                _say(out, f"[已完成] {step['title']}：{completed_line}")
                continue
            if step_id == "archive":
                outcome = _step_archive(
                    home,
                    code,
                    default_archive,
                    reader=reader,
                    out=out,
                    pick_folder=pick,
                    write_probe=probe,
                )
            else:
                archive = Path(
                    (state["steps"].get("archive") or {}).get("value", {}).get("path")
                    or default_archive
                )
                outcome = _step_agent(home, code=code, archive=archive, reader=reader, out=out)
            if not outcome.get("ok"):
                return {
                    **base,
                    "ok": False,
                    "reason": outcome.get("reason") or "step_failed",
                    "text": outcome.get("text") or "初始化未完成。",
                    "completed": completed_steps(home),
                    "next_step": step_id,
                    "not_yet": not_yet,
                    "step": outcome,
                }
            state = read_state(home)
    except _Aborted:
        return {
            **base,
            "ok": False,
            "reason": "aborted",
            "text": "初始化已中止；已完成的步骤已保存，下次 /frontier-init 从下一步继续。",
            "completed": completed_steps(home),
            "next_step": next(
                (
                    step["id"]
                    for step in STEPS
                    if step["implemented"]
                    and (read_state(home)["steps"].get(step["id"]) or {}).get("status") != "ok"
                ),
                None,
            ),
            "not_yet": not_yet,
        }
    except KeyboardInterrupt:
        return {
            **base,
            "ok": False,
            "reason": "interrupted",
            "text": "初始化已中止；已完成的步骤已保存，下次 /frontier-init 从下一步继续。",
            "completed": completed_steps(home),
            "not_yet": not_yet,
        }

    state = read_state(home)
    completed = [step for step in STEP_IDS if (state["steps"].get(step) or {}).get("status") == "ok"]
    next_step = next((item["step"] for item in not_yet), None)
    reason = "not_yet" if not_yet else ""
    if next_step:
        text = (
            "前两步已完成并保存；后续步骤尚未接入："
            + "、".join(f"{item['title']}（{item['ticket']}）" for item in not_yet)
            + "。再次运行 /frontier-init 会跳过已完成的步骤。"
        )
    else:
        text = "初始化步骤已全部完成。"
    return {
        **base,
        "ok": True,
        "reason": reason,
        "completed": completed,
        "next_step": next_step,
        "not_yet": not_yet,
        "text": text,
    }


def read_console_state(home: Path) -> dict:
    """Late import keeps this module importable without the console's seams."""
    from hostrun import console

    return console.read_state(Path(home))


def _completed_line(step_id: str, value: dict) -> str:
    if step_id == "archive":
        suffix = "（默认）" if value.get("default") else ""
        return f"{value.get('path') or '未知'}{suffix}"
    if step_id == "agent":
        return f"{value.get('dsh') or '未记录'}（profile {value.get('profile') or 'headless'}）"
    return "已完成"

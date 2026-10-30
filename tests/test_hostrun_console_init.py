"""Offline tests for console ``/frontier-init`` (issue #84, ADR 0009 §7).

The step machine is driven through its injectable seams only: a fake line reader,
a fake folder dialog, a fake write probe and an explicit TTY answer.  No real
terminal, no real Windows shell dialog, no network and no ``dsh`` run is touched.

The initialization state lives in the code directory's runtime area
(``<code>/.frontier/install/initial/state.json``), separately from
``install.STEPS``; these tests assert that separation and the resume behaviour.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from common import write_json
from hostrun import console, console_init, install


# ------------------------------------------------------------------ fixtures
def make_home(tmp_path: Path, *, service: str = "stopped", permissions: dict | None = None):
    """A code directory with a runtime area and a recorded dsh + patch overlay."""
    code = tmp_path / "code"
    home = code / ".frontier"
    (home / "install").mkdir(parents=True)
    dsh = tmp_path / "bin" / "dsh.cmd"
    dsh.parent.mkdir(parents=True)
    dsh.write_text("@echo off\n", encoding="utf-8")
    patch = home / "install" / "dsh-headless-account.patch.yml"
    patch.write_text("authorization: true\n", encoding="utf-8")
    write_json(
        home / "install" / "config.json",
        {
            "schema_version": 1,
            "host": {"product": "dsh", "version": "0.2.1-rc.5"},
            "paths": {"repo": str(code), "dsh": str(dsh)},
            "listener": {"dsh_args": ["--patch", str(patch)]},
            "permissions": permissions
            if permissions is not None
            else {"scope": ["base:read"], "host_scope": ["filesystem"]},
        },
    )
    if service != "stopped":
        console.write_state(home, service=service, paused=service == "paused")
    return home


def reader(*answers: str):
    """A line reader that yields the scripted answers then reports EOF."""
    remaining = list(answers)

    def read(prompt: str = "") -> str:
        if not remaining:
            raise EOFError
        return remaining.pop(0)

    return read


def init_run(home, answers, **kwargs):
    out = io.StringIO()
    kwargs.setdefault("isatty", lambda: True)
    kwargs.setdefault("pick_folder", lambda default: None)
    result = console_init.run(
        home,
        reader=reader(*answers),
        out=out,
        **kwargs,
    )
    return result, out.getvalue()


# -------------------------------------------------------------- run guards
def test_init_is_refused_while_the_service_is_running(tmp_path):
    home = make_home(tmp_path, service="running")

    result, rendered = init_run(home, [""])

    assert result["ok"] is False
    assert result["reason"] == "service_running"
    assert "先停止服务" in result["text"]
    assert "/frontier-stop" in result["text"]
    # A refusal changes nothing and asks nothing.
    assert not console_init.state_path(home).exists()
    assert rendered == ""


def test_init_is_allowed_while_the_service_is_paused(tmp_path):
    home = make_home(tmp_path, service="paused")

    result, _rendered = init_run(home, ["", ""])

    assert result["ok"] is True
    assert result["completed"] == ["archive", "agent"]


def test_init_refuses_a_non_tty_with_the_launcher_hint(tmp_path):
    home = make_home(tmp_path)

    result, rendered = init_run(home, [""], isatty=lambda: False)

    assert result["ok"] is False
    assert result["reason"] == "not_a_tty"
    assert "frontier-console.cmd" in result["text"]
    assert rendered == ""
    assert not console_init.state_path(home).exists()


# --------------------------------------------------------- first run / state
def test_first_run_confirms_the_default_archive_then_the_agent(tmp_path):
    home = make_home(tmp_path)
    default_archive = tmp_path / "frontier-archive"

    result, rendered = init_run(home, ["", ""])

    assert result["ok"] is True
    assert result["completed"] == ["archive", "agent"]
    state = json.loads(console_init.state_path(home).read_text(encoding="utf-8"))
    assert state["steps"]["archive"]["status"] == "ok"
    assert state["steps"]["archive"]["value"]["path"] == str(default_archive)
    assert state["steps"]["archive"]["value"]["default"] is True
    assert state["steps"]["agent"]["status"] == "ok"
    assert state["steps"]["agent"]["value"]["dsh"].endswith("dsh.cmd")
    assert "dsh-headless-account.patch.yml" in state["steps"]["agent"]["value"]["patch"]
    # The remaining ADR §7 steps are explicit not-yet steps, not silent skips.
    assert result["next_step"] == "lark"
    assert [item["step"] for item in result["not_yet"]] == [
        "lark",
        "transport",
        "naming",
        "push_time",
        "knowledge",
    ]
    assert "尚未实现" in rendered
    # The agent confirmation shows the absolute dsh path, the --patch overlay
    # and the authorization scope before asking.
    assert str(tmp_path / "bin" / "dsh.cmd") in rendered
    assert "dsh-headless-account.patch.yml" in rendered
    assert "filesystem" in rendered


def test_init_state_lives_in_the_code_runtime_area_not_install_steps(tmp_path):
    home = make_home(tmp_path)

    init_run(home, ["", ""])

    assert console_init.state_path(home) == home / "install" / "initial" / "state.json"
    assert not (home / "install" / "state.json").exists()
    # install.STEPS is asserted by other tests; /frontier-init must not stretch it.
    assert "init" not in install.STEPS
    assert install.load_state(home)["steps"] == {}


# ------------------------------------------------------- archive directory choice
def test_y_uses_the_default_archive_directory(tmp_path):
    home = make_home(tmp_path)

    def pick(default):  # pragma: no cover - must never open the dialog
        raise AssertionError("the folder dialog must not open for Y/y")

    result, rendered = init_run(home, ["y", ""], pick_folder=pick)

    state = json.loads(console_init.state_path(home).read_text(encoding="utf-8"))
    assert state["steps"]["archive"]["value"]["path"] == str(tmp_path / "frontier-archive")
    assert state["steps"]["archive"]["value"]["default"] is True
    assert result["completed"] == ["archive", "agent"]
    assert "默认资料目录" in rendered


def test_n_opens_the_folder_dialog_and_a_cancel_falls_back_to_the_default(tmp_path):
    home = make_home(tmp_path)
    seen: list[str] = []

    def pick(default):
        seen.append(str(default))
        return None  # the user cancelled the system dialog

    result, rendered = init_run(home, ["n", ""], pick_folder=pick)

    assert seen == [str(tmp_path / "frontier-archive")]
    state = json.loads(console_init.state_path(home).read_text(encoding="utf-8"))
    assert state["steps"]["archive"]["value"] == {
        "path": str(tmp_path / "frontier-archive"),
        "default": True,
        "outside_code": True,
    }
    assert "已取消" in rendered
    assert result["completed"] == ["archive", "agent"]


def test_a_directory_outside_the_code_directory_is_accepted_after_a_write_probe(tmp_path):
    home = make_home(tmp_path)
    chosen = tmp_path / "custom-archive"
    chosen.mkdir()
    probed: list[Path] = []

    def probe(path):
        probed.append(Path(path))
        return {"ok": True, "path": str(path), "reason": ""}

    result, _rendered = init_run(home, ["n", ""], pick_folder=lambda default: str(chosen), write_probe=probe)

    assert probed == [chosen]
    state = json.loads(console_init.state_path(home).read_text(encoding="utf-8"))
    assert state["steps"]["archive"]["value"] == {
        "path": str(chosen),
        "default": False,
        "outside_code": True,
    }
    assert result["completed"] == ["archive", "agent"]


def test_a_chosen_directory_inside_the_code_directory_is_refused(tmp_path):
    home = make_home(tmp_path)
    inside = home.parent / "papers"

    result, _rendered = init_run(home, ["n"], pick_folder=lambda default: str(inside))

    assert result["ok"] is False
    assert result["reason"] == "archive_invalid"
    assert "资料目录不能放在代码目录内" in result["text"]
    assert not console_init.state_path(home).exists()


def test_the_real_write_probe_accepts_a_writable_directory_and_removes_its_file(tmp_path):
    chosen = tmp_path / "papers"
    chosen.mkdir()

    result = console_init.probe_write(chosen)

    assert result["ok"] is True
    assert result["path"] == str(chosen)
    assert list(chosen.iterdir()) == []


def test_the_real_write_probe_reports_a_missing_directory(tmp_path):
    result = console_init.probe_write(tmp_path / "missing")

    assert result["ok"] is False
    assert result["reason"] == "not_a_directory"


def test_an_unwritable_outside_directory_asks_for_a_full_permission_restart(tmp_path):
    home = make_home(tmp_path)
    chosen = tmp_path / "readonly-archive"
    chosen.mkdir()

    result, _rendered = init_run(
        home,
        ["n"],
        pick_folder=lambda default: str(chosen),
        write_probe=lambda path: {"ok": False, "path": str(path), "reason": "unwritable", "error": "PermissionError"},
    )

    assert result["ok"] is False
    assert result["reason"] == "archive_unwritable"
    assert "资料目录不可写" in result["text"]
    assert str(home.parent / "bin" / "frontier-console.cmd") in result["text"]
    assert "以完整权限重启" in result["text"]
    assert "保留进度" in result["text"]
    # Nothing was recorded, so a later run starts the same step again.
    assert not console_init.state_path(home).exists()


# --------------------------------------------------------------- agent confirm
def test_declining_the_agent_keeps_the_archive_progress(tmp_path):
    home = make_home(tmp_path)

    result, _rendered = init_run(home, ["", "n"])

    assert result["ok"] is False
    assert result["reason"] == "declined"
    assert "已保留" in result["text"]
    state = json.loads(console_init.state_path(home).read_text(encoding="utf-8"))
    assert state["steps"]["archive"]["status"] == "ok"
    assert "agent" not in state["steps"]


def test_a_missing_dsh_blocks_the_agent_step_without_recording_it(tmp_path):
    home = make_home(tmp_path)
    config_path = home / "install" / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["paths"]["dsh"] = ""
    write_json(config_path, config)

    result, rendered = init_run(home, [""])

    assert result["ok"] is False
    assert result["reason"] == "dsh_missing"
    assert "paths.dsh" in result["text"]
    assert "不可用" in rendered
    state = json.loads(console_init.state_path(home).read_text(encoding="utf-8"))
    assert state["steps"]["archive"]["status"] == "ok"
    assert "agent" not in state["steps"]


# ------------------------------------------------------------- resume behaviour
def test_an_interruption_resumes_at_the_unfinished_step(tmp_path):
    home = make_home(tmp_path)

    first, _rendered = init_run(home, [""], )  # EOF at the agent question
    assert first["ok"] is False
    assert first["reason"] == "aborted"
    state = json.loads(console_init.state_path(home).read_text(encoding="utf-8"))
    assert state["steps"]["archive"]["status"] == "ok"
    assert "agent" not in state["steps"]

    second, rendered = init_run(home, [""])

    assert second["ok"] is True
    assert second["completed"] == ["archive", "agent"]
    assert "[已完成] 确认资料目录" in rendered
    # The archive step is not asked again.
    assert "使用默认资料目录" not in rendered


def test_a_rerun_skips_every_completed_step_and_shows_done(tmp_path):
    home = make_home(tmp_path)
    init_run(home, ["", ""])

    result, rendered = init_run(home, [])

    assert result["ok"] is True
    assert result["completed"] == ["archive", "agent"]
    assert rendered.count("[已完成]") == 2
    assert "尚未实现" in rendered


# ------------------------------------------------------------------ dispatch
def test_console_dispatch_runs_the_init_state_machine(tmp_path):
    home = make_home(tmp_path)
    calls: list[Path] = []

    def fake_init():
        calls.append(home)
        return {"ok": True, "reason": "not_yet", "text": "初始化骨架已运行。"}

    result = console.dispatch(home, "/frontier-init", init=fake_init)

    assert calls == [home]
    assert result["ok"] is True
    assert result["action"] == "init"
    assert result["text"] == "初始化骨架已运行。"
    assert result["init"]["reason"] == "not_yet"


def test_frontier_init_is_no_longer_a_stub_in_the_help(tmp_path):
    text = console.dispatch(make_home(tmp_path), "/frontier-help")["text"]

    assert console.COMMANDS["/frontier-init"]["implemented"] is True
    assert "/frontier-init" in text
    assert "/frontier-init（尚未实现）" not in text


def test_serve_wires_the_init_step_machine_to_the_prompt_reader(tmp_path):
    home = make_home(tmp_path)
    console.write_state(home, paused=True, service="paused")
    resolved = {
        "code": str(home.parent),
        "runtime": str(home),
        "archive": str(tmp_path / "frontier-archive"),
    }
    lines = iter(["/frontier-init", "", "", "/exit"])
    out = io.StringIO()

    result = console.serve(
        home,
        resolved=resolved,
        isatty=lambda: True,
        reader=lambda prompt: next(lines),
        out=out,
        set_title=lambda title: True,
        start_worker=lambda function: None,
    )

    assert result["ok"] is True
    rendered = out.getvalue()
    assert "[完成] 资料目录" in rendered
    assert "[完成] 执行 Agent 已确认" in rendered
    state = json.loads(console_init.state_path(home).read_text(encoding="utf-8"))
    assert state["steps"]["archive"]["status"] == "ok"
    assert state["steps"]["agent"]["status"] == "ok"



"""Console CLI surface: the installer, control, dispatch, exit codes and docs.

Everything here is offline: no real ``dsh``, no lark-cli and no process is
started.  The retired listener/smoke/schedules/cleanup subcommands are checked
to be gone (#91), not to keep working.
"""

import json
import os
from pathlib import Path

import pytest

import hostrun
from hostrun import cli
from hostrun.base import HostRunError, load_config
from conftest import cli_locations

ROOT = Path(__file__).resolve().parents[1]


def _dsh_file(tmp_path):
    dsh = tmp_path / "tools" / ("dsh.cmd" if os.name == "nt" else "dsh")
    dsh.parent.mkdir(parents=True, exist_ok=True)
    dsh.write_text("", encoding="utf-8")
    return dsh


def _home(tmp_path):
    home = tmp_path / "code" / ".frontier"
    home.mkdir(parents=True, exist_ok=True)
    return home


# ------------------------------------------------------------------- parser
def test_console_control_actions_are_parsed_after_the_location_flags():
    parser = cli.build_parser()

    for action in ("start", "stop", "status", "push"):
        args = parser.parse_args(
            cli._normalize(
                ["--code", "C", "--archive", "A", "console", "control", action]
            )
        )
        assert args.cmd == "console"
        assert args.action == "control"
        assert args.control_action == action

    after = parser.parse_args(
        cli._normalize(["console", "control", "status", "--code", "C", "--archive", "A"])
    )
    assert after.code == "C"
    assert after.archive == "A"


def test_console_install_flags_are_parsed():
    parser = cli.build_parser()

    args = parser.parse_args(
        cli._normalize(
            [
                "console",
                "install",
                "--dsh",
                "D:/dsh.cmd",
                "--python",
                "P",
                "--dsh-arg=--patch",
                "--dsh-arg",
                "C:/overlay.yml",
            ]
        )
    )

    assert args.cmd == "console"
    assert args.action == "install"
    assert args.dsh == "D:/dsh.cmd"
    assert args.python_path == "P"
    assert args.dsh_args == ["--patch", "C:/overlay.yml"]


@pytest.mark.parametrize("command", ["listener", "smoke", "cleanup", "schedules"])
def test_retired_subcommands_are_gone(command):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(cli._normalize([command]))


def test_run_rejects_the_retired_listener_check_intent():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            cli._normalize(["run", "--intent", "listener-check"])
        )


# ---------------------------------------------------------- console install
def test_console_install_records_dsh_writes_the_launcher_and_starts_nothing(
    tmp_path, capsys
):
    home = _home(tmp_path)
    dsh = _dsh_file(tmp_path)

    code = cli.main(
        [*cli_locations(home), "console", "install", "--dsh", str(dsh)]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["dsh"] == str(dsh)
    assert payload["processes_started"] is False
    script = home.parent / "bin" / "frontier-console.cmd"
    assert script.is_file()
    assert script.read_text(encoding="utf-8").splitlines()[0] == "title frontier-console"
    config = load_config(home)
    assert config["paths"]["dsh"] == str(dsh)


def test_console_install_records_the_agent_run_overlay(tmp_path, capsys):
    home = _home(tmp_path)
    dsh = _dsh_file(tmp_path)

    code = cli.main(
        [
            *cli_locations(home),
            "console",
            "install",
            "--dsh",
            str(dsh),
            "--dsh-arg=--patch",
            "--dsh-arg",
            "C:/overlay.yml",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dsh_args"] == ["--patch", "C:/overlay.yml"]
    assert load_config(home)["agent_run"]["dsh_args"] == ["--patch", "C:/overlay.yml"]


def test_console_install_blocks_without_dsh_but_still_writes_the_launcher(
    tmp_path, capsys
):
    home = _home(tmp_path)

    code = cli.main([*cli_locations(home), "console", "install"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert "paths.dsh" in payload["note"]
    assert "console install --dsh" in payload["note"]
    assert (home.parent / "bin" / "frontier-console.cmd").is_file()
    assert load_config(home)["paths"]["dsh"] == ""


def test_console_install_blocks_on_a_relative_or_missing_dsh(tmp_path, capsys):
    home = _home(tmp_path)

    relative = cli.main(
        [*cli_locations(home), "console", "install", "--dsh", "tools/dsh.cmd"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert relative == 1
    assert "不是绝对路径" in payload["note"]

    missing = cli.main(
        [
            *cli_locations(home),
            "console",
            "install",
            "--dsh",
            str(tmp_path / "tools" / "gone.cmd"),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert missing == 1
    assert "不存在" in payload["note"]


def test_console_install_rejects_an_empty_overlay(tmp_path, capsys):
    home = _home(tmp_path)
    dsh = _dsh_file(tmp_path)

    code = cli.main(
        [
            *cli_locations(home),
            "console",
            "install",
            "--dsh",
            str(dsh),
            "--dsh-arg",
            " ",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["dsh_args"] == []
    assert "dsh_args 为空" in payload["note"]


def test_console_install_reuses_the_recorded_dsh(tmp_path, capsys):
    home = _home(tmp_path)
    dsh = _dsh_file(tmp_path)
    from hostrun.base import update_config

    update_config(home, paths={"dsh": str(dsh)})

    code = cli.main([*cli_locations(home), "console", "install"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["dsh"] == str(dsh)


# ------------------------------------------------------------------- serve
def test_console_serve_dispatches_the_resolved_layout(tmp_path, monkeypatch, capsys):
    home = _home(tmp_path)
    seen = {}

    def fake_serve(home_arg, **kwargs):
        seen["home"] = Path(home_arg)
        seen["resolved"] = kwargs.get("resolved")
        return {"ok": True, "reason": "stopped"}

    monkeypatch.setattr(cli.console_mod, "serve", fake_serve)

    code = cli.main([*cli_locations(home), "console"])

    assert code == 0
    assert seen["home"] == home.resolve()
    assert seen["resolved"]["code"] == str(home.parent.resolve())
    assert json.loads(capsys.readouterr().out)["reason"] == "stopped"


# ----------------------------------------------------------------- failures
def test_dispatch_errors_are_json_not_tracebacks(tmp_path, monkeypatch, capsys):
    home = _home(tmp_path)

    def exploding_serve(home_arg, **kwargs):
        raise HostRunError("boom")

    monkeypatch.setattr(cli.console_mod, "serve", exploding_serve)

    code = cli.main([*cli_locations(home), "console"])

    captured = capsys.readouterr()
    assert code == 1
    payload = json.loads(captured.err)
    assert payload["ok"] is False
    assert "boom" in payload["error"]
    assert "Traceback" not in captured.err


# ---------------------------------------------------------------- docstrings
def test_cli_docstring_names_the_console_as_the_only_resident_component():
    doc = cli.__doc__ or ""

    assert "Console" in doc
    assert "only resident component is the Console" in doc
    assert "listener serve" not in doc


def test_package_docstring_drops_the_retired_modules():
    doc = hostrun.__doc__ or ""

    assert "user-started Console" in doc
    for retired in ("``listener``", "``smoke``", "``cleanup``", "``schedules``"):
        assert retired not in doc
    assert "listener-check" not in doc

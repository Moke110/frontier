"""Listener CLI surface: six subcommands, dispatch, exit codes and docs.

Everything here is offline: the detached spawner and polling sleep are replaced
by injected fakes, so no listener process, no lark-cli and no network is touched.
"""

import json
import os
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import hostrun
from hostrun import cli, executor, install, intents, listener
from hostrun.base import HostRunError, load_config

ROOT = Path(__file__).resolve().parents[1]


def _dsh_file(tmp_path):
    dsh = tmp_path / "tools" / ("dsh.cmd" if os.name == "nt" else "dsh")
    dsh.parent.mkdir(parents=True, exist_ok=True)
    dsh.write_text("", encoding="utf-8")
    return dsh


def _fresh_heartbeat(home, *, pid=None):
    listener.write_heartbeat(home, pid=pid or os.getpid())


def _old_heartbeat(home, *, hours=1, pid=424242):
    at = (datetime.now().astimezone() - timedelta(hours=hours)).isoformat()
    listener.write_heartbeat(home, pid=pid, at=at)


# ------------------------------------------------------------------- parser
def test_parser_accepts_the_six_listener_actions():
    parser = cli.build_parser()

    for action in ("install", "start", "stop", "status", "serve", "health"):
        args = parser.parse_args(cli._normalize(["listener", action]))
        assert args.cmd == "listener"
        assert args.action == action


def test_listener_commands_accept_home_after_the_subcommand():
    parser = cli.build_parser()

    before = parser.parse_args(cli._normalize(["--home", "H", "listener", "status"]))
    after = parser.parse_args(cli._normalize(["listener", "status", "--home", "H"]))

    assert before.home == "H"
    assert after.home == "H"


def test_install_flags_are_parsed():
    parser = cli.build_parser()

    args = parser.parse_args(
        cli._normalize(
            ["listener", "install", "--dsh", "D:/dsh.cmd", "--python", "P", "--repo", "R"]
        )
    )

    assert args.dsh == "D:/dsh.cmd"
    assert args.python_path == "P"
    assert args.repo == "R"


# ------------------------------------------------------------------ install
def test_listener_install_generates_scripts_through_the_install_helper(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    dsh = _dsh_file(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()

    code = cli.main(
        [
            "--home",
            str(home),
            "listener",
            "install",
            "--dsh",
            str(dsh),
            "--python",
            sys.executable,
            "--repo",
            str(repo),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    start = home / "bin" / "frontier-listener.cmd"
    stop = home / "bin" / "frontier-listener-stop.cmd"
    assert start.is_file() and stop.is_file()
    config = load_config(home)
    assert config["paths"]["dsh"] == str(dsh)
    assert config["listener"]["start_command"] == str(start)
    assert config["listener"]["stop_command"] == str(stop)
    assert install.load_state(home)["steps"]["listener"]["status"] == "ok"


def test_listener_install_without_dsh_exits_one_with_json(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()

    code = cli.main(["--home", str(home), "listener", "install"])

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert "paths.dsh" in payload["note"]
    assert (home / "bin" / "frontier-listener.cmd").is_file()


# -------------------------------------------------------------------- start
def test_listener_start_spawns_the_recorded_command_once(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    dsh = _dsh_file(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    install.listener_install(home, dsh=str(dsh), python=sys.executable, repo=repo)
    command = load_config(home)["listener"]["start_command"]
    spawned = []

    def fake_spawn(argv):
        spawned.append(argv)
        return types.SimpleNamespace(pid=4242)

    monkeypatch.setattr(cli, "_spawn_detached", fake_spawn)

    code = cli.main(["--home", str(home), "listener", "start"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "started"
    assert payload["pid"] == 4242
    assert len(spawned) == 1
    assert command in spawned[0]


def test_listener_start_reports_already_running_without_spawning(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    install.listener_install(
        home, dsh=str(_dsh_file(tmp_path)), python=sys.executable, repo=ROOT
    )
    _fresh_heartbeat(home)
    monkeypatch.setattr(
        cli,
        "_spawn_detached",
        lambda argv: pytest.fail("an online listener must not be started again"),
    )

    code = cli.main(["--home", str(home), "listener", "start"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "already_running"
    assert payload["pid"] == os.getpid()


def test_listener_start_blocks_without_a_recorded_command(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(
        cli, "_spawn_detached", lambda argv: pytest.fail("nothing recorded to spawn")
    )

    code = cli.main(["--home", str(home), "listener", "start"])

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["reason"] == "listener_start_command_missing"


def test_listener_start_reports_a_spawn_failure_as_json(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    install.listener_install(
        home, dsh=str(_dsh_file(tmp_path)), python=sys.executable, repo=ROOT
    )

    def failing_spawn(argv):
        raise OSError("cannot spawn")

    monkeypatch.setattr(cli, "_spawn_detached", failing_spawn)

    code = cli.main(["--home", str(home), "listener", "start"])

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == "spawn_failed"
    assert "cannot spawn" in payload["error"]


# --------------------------------------------------------------------- stop
def _fake_health_sequence(monkeypatch, states):
    calls = {"count": 0}

    def fake_health(home, **kwargs):
        index = min(calls["count"], len(states) - 1)
        calls["count"] += 1
        state = states[index]
        return {
            "ok": state == "online",
            "state": state,
            "problems": [],
            "evidence": {"pid": 4242, "age_seconds": 1},
        }

    monkeypatch.setattr(intents, "listener_health", fake_health)
    return calls


def test_listener_stop_writes_the_sentinel_and_waits_for_exit(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    _fake_health_sequence(monkeypatch, ["online", "offline"])
    slept = []
    monkeypatch.setattr(cli, "_listener_sleep", lambda seconds: slept.append(seconds))

    code = cli.main(["--home", str(home), "listener", "stop"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "stopped"
    assert listener.stop_requested(home) is True
    assert slept == [cli.LISTENER_STOP_POLL_SECONDS]


def test_listener_stop_reports_not_running_without_a_sentinel(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    _fake_health_sequence(monkeypatch, ["offline"])
    monkeypatch.setattr(
        cli, "_listener_sleep", lambda seconds: pytest.fail("nothing to wait for")
    )

    code = cli.main(["--home", str(home), "listener", "stop"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "not_running"
    assert listener.stop_requested(home) is False


def test_listener_stop_reports_timeout_after_the_bounded_wait(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    _fake_health_sequence(monkeypatch, ["online"])
    slept = []
    monkeypatch.setattr(cli, "_listener_sleep", lambda seconds: slept.append(seconds))

    code = cli.main(["--home", str(home), "listener", "stop"])

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["state"] == "stop_timeout"
    assert len(slept) == int(cli.LISTENER_STOP_WAIT_SECONDS / cli.LISTENER_STOP_POLL_SECONDS)
    assert listener.stop_requested(home) is True


def test_listener_stop_waits_for_a_stale_but_live_process(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    answers = [("stale", True), ("offline", False)]
    calls = {"count": 0}

    def fake_health(home_arg, **kwargs):
        index = min(calls["count"], len(answers) - 1)
        calls["count"] += 1
        state, alive = answers[index]
        return {
            "ok": state == "online",
            "state": state,
            "problems": [],
            "evidence": {"pid": 4242, "pid_alive": alive},
        }

    monkeypatch.setattr(intents, "listener_health", fake_health)
    slept = []
    monkeypatch.setattr(cli, "_listener_sleep", lambda seconds: slept.append(seconds))

    code = cli.main(["--home", str(home), "listener", "stop"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "stopped"
    assert listener.stop_requested(home) is True
    assert slept == [cli.LISTENER_STOP_POLL_SECONDS]


def test_listener_status_survives_an_unreadable_heartbeat(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    heartbeat = listener.heartbeat_path(home)
    heartbeat.parent.mkdir(parents=True)
    heartbeat.write_text("{not json", encoding="utf-8")

    code = cli.main(["--home", str(home), "listener", "status"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 0
    assert payload["state"] == "offline"
    assert "心跳" in " ".join(payload["problems"])
    assert "Traceback" not in captured.err


def test_listener_status_survives_a_non_object_heartbeat(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    heartbeat = listener.heartbeat_path(home)
    heartbeat.parent.mkdir(parents=True)
    heartbeat.write_text("[]", encoding="utf-8")

    code = cli.main(["--home", str(home), "listener", "status"])

    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out)["state"] == "offline"
    assert "Traceback" not in captured.err


def test_listener_status_accepts_home_after_the_subcommand(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()

    code = cli.main(["listener", "status", "--home", str(home)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert Path(payload["heartbeat_path"]) == listener.heartbeat_path(home.resolve())


# ------------------------------------------------------------- status/health
def test_listener_status_reports_offline_without_creating_a_heartbeat(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()

    code = cli.main(["--home", str(home), "listener", "status"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["state"] == "offline"
    assert payload["heartbeat_path"].endswith("heartbeat.json")
    assert listener.heartbeat_path(home).exists() is False


def test_listener_status_reports_a_live_pid(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    _fresh_heartbeat(home)

    code = cli.main(["--home", str(home), "listener", "status"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "online"
    assert payload["pid"] == os.getpid()
    assert payload["pid_alive"] is True
    assert payload["age_seconds"] is not None


def test_listener_health_is_read_only_and_exits_by_online_state(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(
        cli, "_spawn_detached", lambda argv: pytest.fail("health never restarts")
    )

    offline_code = cli.main(["--home", str(home), "listener", "health"])
    offline = json.loads(capsys.readouterr().out)
    assert offline_code == 1
    assert offline["ok"] is False
    assert offline["state"] == "offline"
    assert offline["action"] == "none"

    _fresh_heartbeat(home)
    online_code = cli.main(["--home", str(home), "listener", "health"])
    online = json.loads(capsys.readouterr().out)
    assert online_code == 0
    assert online["ok"] is True
    assert online["state"] == "online"


def test_listener_health_does_not_restart_even_with_a_recorded_command(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    install.listener_install(
        home, dsh=str(_dsh_file(tmp_path)), python=sys.executable, repo=ROOT
    )
    monkeypatch.setattr(
        cli, "_spawn_detached", lambda argv: pytest.fail("health never restarts")
    )

    code = cli.main(["--home", str(home), "listener", "health"])

    assert code == 1
    assert json.loads(capsys.readouterr().out)["action"] == "none"


# ------------------------------------------------------------------- serve
def test_listener_serve_runs_the_foreground_loop(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    seen = {}

    def fake_serve(home_arg, **kwargs):
        seen["home"] = Path(home_arg)
        return {"ok": True, "reason": "stopped", "events": 0}

    monkeypatch.setattr(listener, "serve", fake_serve)

    code = cli.main(["--home", str(home), "listener", "serve"])

    assert code == 0
    assert seen["home"] == home.resolve()
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == "stopped"


def test_listener_serve_exits_one_on_a_fatal_consume_failure(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(
        listener,
        "serve",
        lambda home_arg, **kwargs: {"ok": False, "reason": "app_scope_not_applied"},
    )

    code = cli.main(["--home", str(home), "listener", "serve"])

    assert code == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


# ----------------------------------------------------------------- failures
def test_dispatch_errors_are_json_not_tracebacks(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()

    def exploding_serve(home_arg, **kwargs):
        raise HostRunError("boom")

    monkeypatch.setattr(listener, "serve", exploding_serve)

    code = cli.main(["--home", str(home), "listener", "serve"])

    captured = capsys.readouterr()
    assert code == 1
    payload = json.loads(captured.err)
    assert payload["ok"] is False
    assert "boom" in payload["error"]
    assert "Traceback" not in captured.err


# ------------------------------------------------- run --intent listener-check
def test_run_listener_check_is_available_without_the_executor_lease(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    lease = executor.acquire(home, host="other-host", minutes=45)
    assert lease["ok"] is True

    code = cli.main(["--home", str(home), "run", "--intent", "listener-check"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 1  # offline listener: honest failure
    assert payload["ok"] is False
    assert payload.get("reason") != "executor_busy"
    assert payload["action"] == "listener_start_command_missing"
    assert executor.status(home)["state"] == "held"


def test_run_listener_check_records_listener_health_evidence(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    _fresh_heartbeat(home)

    code = cli.main(["--home", str(home), "run", "--intent", "listener-check"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] is True
    assert payload["state"] == "online"
    entry = install.load_state(home)["steps"]["listener_health"]
    assert entry["status"] == "ok"
    assert entry["evidence"]["pid_alive"] is True


# ------------------------------------------------------------------ docstrings
def test_cli_docstring_names_the_only_resident_component():
    doc = cli.__doc__ or ""

    assert "listener" in doc
    assert "user-started listener" in doc
    assert "background listener" not in doc


def test_package_docstring_drops_no_detached_listeners():
    doc = hostrun.__doc__ or ""

    assert "no detached listeners" not in doc
    assert "user-started listener" in doc
    assert "listener" in doc

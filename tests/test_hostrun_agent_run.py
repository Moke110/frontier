"""Offline tests for the agent-run adapter (issue #78, ADR 0009 §10).

No real ``dsh``, network, credentials or sleeps: the spawner, clock, sleep,
install report and process streams are injected.  The recorded-``dsh`` argv
shape is asserted offline; its live headless behaviour is verified manually and
recorded in the ticket report as ``untested`` for a real model run.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from common import file_lock
from hostrun import agent_run, executor

HOST = "workbuddy"


# ------------------------------------------------------------------ fixtures
def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / "install").mkdir(parents=True)
    return home


def _config(
    home: Path,
    *,
    dsh: str | None = None,
    dsh_args=None,
    timeout_seconds: int = 1200,
) -> dict:
    config = {
        "schema_version": 1,
        "host": {"product": HOST},
        "paths": {"home": str(home), "repo": str(home)},
        "listener": {"derived_timeout_seconds": timeout_seconds},
    }
    if dsh:
        config["paths"]["dsh"] = dsh
    if dsh_args is not None:
        config["listener"]["dsh_args"] = dsh_args
    (home / "install" / "config.json").write_text(
        json.dumps(config, ensure_ascii=False), encoding="utf-8"
    )
    return config


def _report(blocked=None):
    return lambda home: {"ok": not blocked, "blocked": list(blocked or [])}


def _event_line(**payload) -> str:
    return json.dumps(payload, ensure_ascii=False)


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.value = start
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(float(seconds))
        self.value += float(seconds)


class FakeProc:
    """A child with scripted pipes that exits after simulated time."""

    def __init__(
        self,
        *,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
        clock: FakeClock | None = None,
        exit_after: float = 0.0,
    ):
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)
        self.clock = clock
        self.started = clock.value if clock is not None else 0.0
        self.exit_after = exit_after
        self.final = returncode
        self.returncode: int | None = None
        self.killed = False

    def poll(self):
        if self.returncode is None:
            if self.clock is None or self.clock.value - self.started >= self.exit_after:
                self.returncode = self.final
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = self.final
        return self.returncode


def _runs(home: Path) -> list[dict]:
    path = home / "hostrun" / "runs.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# ------------------------------------------------------------------- argv
def test_agent_argv_keeps_the_recorded_patch_and_the_task_last():
    argv = agent_run.agent_argv(
        "C:/dsh/dsh.cmd", "the task", ["--patch", "C:/overlay.yml"]
    )

    assert argv == [
        "C:/dsh/dsh.cmd",
        "--profile",
        "headless",
        "--patch",
        "C:/overlay.yml",
        "--json",
        "the task",
    ]
    assert argv[-1] == "the task"


# ----------------------------------------------------------------- happy path
def test_run_parses_the_stream_records_the_session_and_writes_the_full_log(tmp_path):
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh), dsh_args=["--patch", "C:/overlay.yml"])
    spawns = []
    seen_events = []
    proc = FakeProc(
        stdout="\n".join(
            [
                _event_line(type="session", sessionId="session-abc", cwd=str(home)),
                _event_line(type="status", phase="turn_start", turn=1),
                _event_line(type="text", text="working"),
                _event_line(type="final", text="done"),
            ]
        )
        + "\n",
        stderr="dsh: warning: noisy provider\n",
    )

    def spawn(argv, **kwargs):
        spawns.append((argv, kwargs))
        return proc

    result = agent_run.run(
        home,
        "write one push",
        spawn=spawn,
        report=_report(),
        on_event=seen_events.append,
        clock=lambda: 0.0,
        sleep=lambda seconds: None,
    )

    assert result["ok"] is True
    assert result["reason"] == "ok"
    assert result["session_id"] == "session-abc"
    assert result["returncode"] == 0
    assert result["timed_out"] is False
    assert result["final_text"] == "done"

    argv, kwargs = spawns[0]
    assert argv == [
        str(dsh),
        "--profile",
        "headless",
        "--patch",
        "C:/overlay.yml",
        "--json",
        "write one push",
    ]
    assert kwargs["stdin"] is not None
    assert kwargs["stdout"] is not None
    assert kwargs["stderr"] is not None
    assert kwargs["cwd"] == str(home)

    log = Path(result["log_path"]).read_text(encoding="utf-8")
    assert Path(result["log_path"]).name == f"agent-{result['run_id']}.log"
    for fragment in ('"sessionId": "session-abc"', '"text": "working"', '"type": "final"', "noisy provider"):
        assert fragment in log

    rows = _runs(home)
    assert rows[-1]["session_id"] == "session-abc"
    assert rows[-1]["ok"] is True
    assert rows[-1]["run_id"] == result["run_id"]
    assert rows[-1]["log_path"] == result["log_path"]
    assert executor.status(home)["state"] == "free"
    assert [event["type"] for event in seen_events] == [
        "session",
        "status",
        "text",
        "final",
    ]


# -------------------------------------------------------------------- guards
def test_missing_recorded_dsh_refuses_without_spawning_or_recording(tmp_path):
    home = _home(tmp_path)
    _config(home)

    result = agent_run.run(
        home,
        "the task",
        spawn=lambda *a, **k: pytest.fail("must not spawn without a recorded dsh"),
        report=_report(),
    )

    assert result["ok"] is False
    assert result["reason"] == "dsh_missing"
    assert "dsh" in result["error"]
    assert _runs(home) == []


def test_install_blocked_refuses_before_spawning(tmp_path):
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))

    result = agent_run.run(
        home,
        "the task",
        spawn=lambda *a, **k: pytest.fail("must not spawn with a blocked install"),
        report=_report(blocked=[{"step": "lark_cli", "note": "missing"}]),
    )

    assert result["ok"] is False
    assert result["reason"] == "install_blocked"
    assert result["blocked"] == [{"step": "lark_cli", "note": "missing"}]
    assert _runs(home) == []


def test_a_held_executor_lease_returns_the_holder_without_queueing(tmp_path):
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))
    executor.acquire(home, host="other-host", minutes=30)

    result = agent_run.run(
        home,
        "the task",
        spawn=lambda *a, **k: pytest.fail("must not spawn under another host's lease"),
        report=_report(),
    )

    assert result["ok"] is False
    assert result["reason"] == "executor_busy"
    assert result["holder"] == "other-host"
    assert result["lease_until"]
    assert executor.status(home)["state"] == "held"
    assert _runs(home) == []


def test_single_flight_returns_busy_immediately(tmp_path):
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))

    with file_lock(agent_run.lock_path(home), blocking=False) as held:
        assert held is True
        result = agent_run.run(
            home,
            "the task",
            spawn=lambda *a, **k: pytest.fail("must not spawn during a live run"),
            report=_report(),
        )

    assert result["ok"] is False
    assert result["reason"] == "agent_busy"
    assert _runs(home) == []


# ---------------------------------------------------------- timeout and failure
def test_timeout_kills_the_child_and_records_it_without_retrying(tmp_path):
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))
    clock = FakeClock()
    procs = []

    def spawn(argv, **kwargs):
        proc = FakeProc(clock=clock, exit_after=10_000.0)
        procs.append(proc)
        return proc

    result = agent_run.run(
        home,
        "the task",
        spawn=spawn,
        report=_report(),
        clock=clock.clock,
        sleep=clock.sleep,
        timeout_seconds=20,
    )

    assert result["ok"] is False
    assert result["reason"] == "timeout"
    assert result["timed_out"] is True
    assert len(procs) == 1
    assert procs[0].killed is True
    assert executor.status(home)["state"] == "free"
    rows = _runs(home)
    assert len(rows) == 1
    assert rows[0]["timed_out"] is True and rows[0]["ok"] is False
    log = Path(result["log_path"]).read_text(encoding="utf-8")
    assert "timed_out=True" in log


def test_a_child_failure_records_the_exit_code_and_never_retries(tmp_path):
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))
    clock = FakeClock()
    spawns = []

    def spawn(argv, **kwargs):
        spawns.append(argv)
        return FakeProc(clock=clock, exit_after=1.0, returncode=2)

    result = agent_run.run(
        home,
        "the task",
        spawn=spawn,
        report=_report(),
        clock=clock.clock,
        sleep=clock.sleep,
        timeout_seconds=20,
    )

    assert result["ok"] is False
    assert result["reason"] == "child_failed"
    assert result["returncode"] == 2
    assert len(spawns) == 1
    assert executor.status(home)["state"] == "free"
    rows = _runs(home)
    assert rows[-1]["returncode"] == 2 and rows[-1]["ok"] is False


def test_a_stop_request_kills_the_child_and_records_it(tmp_path):
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))
    clock = FakeClock()
    procs = []

    def spawn(argv, **kwargs):
        proc = FakeProc(clock=clock, exit_after=10_000.0)
        procs.append(proc)
        return proc

    result = agent_run.run(
        home,
        "the task",
        spawn=spawn,
        report=_report(),
        clock=clock.clock,
        sleep=clock.sleep,
        should_stop=lambda: True,
        timeout_seconds=1200,
    )

    assert result["ok"] is False
    assert result["reason"] == "stopped"
    assert procs[0].killed is True
    assert _runs(home)[-1]["stopped"] is True


def test_a_spawn_error_is_recorded_and_the_lease_is_released(tmp_path):
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))

    def spawn(argv, **kwargs):
        raise OSError("cannot execute")

    result = agent_run.run(home, "the task", spawn=spawn, report=_report())

    assert result["ok"] is False
    assert result["reason"] == "spawn_failed"
    assert "cannot execute" in result["error"]
    assert executor.status(home)["state"] == "free"
    assert _runs(home)[-1]["reason"] == "spawn_failed"
    assert Path(result["log_path"]).exists()


# -------------------------------------------------------------- event stream
def test_malformed_stream_lines_are_kept_in_the_log_but_skipped(tmp_path):
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))
    proc = FakeProc(
        stdout="not json at all\n"
        + _event_line(type="session", sessionId="session-x")
        + "\n"
        + _event_line(type="final", text="done")
        + "\n"
    )

    result = agent_run.run(
        home,
        "the task",
        spawn=lambda argv, **kwargs: proc,
        report=_report(),
    )

    assert result["ok"] is True
    assert result["events"] == 2
    assert result["summary"]["malformed_lines"] == 1
    assert "not json at all" in Path(result["log_path"]).read_text(encoding="utf-8")


def test_an_error_event_stream_is_a_failed_run_with_the_message(tmp_path):
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))
    proc = FakeProc(
        stdout=_event_line(type="error", message="a task is required") + "\n",
        returncode=1,
    )

    result = agent_run.run(
        home,
        "the task",
        spawn=lambda argv, **kwargs: proc,
        report=_report(),
    )

    assert result["ok"] is False
    assert result["reason"] == "child_failed"
    assert result["returncode"] == 1
    assert result["summary"]["error"] == "a task is required"


# ----------------------------------------------------------- read-only runs
def test_a_read_only_run_skips_the_lease_and_the_single_flight_lock(tmp_path):
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))
    executor.acquire(home, host="other-host", minutes=30)
    proc = FakeProc(
        stdout=_event_line(type="session", sessionId="session-r")
        + "\n"
        + _event_line(type="final", text='{"op":"status"}')
        + "\n"
    )

    result = agent_run.run(
        home,
        "judge the intent",
        spawn=lambda argv, **kwargs: proc,
        report=_report(),
        lease=False,
        single_flight=False,
    )

    assert result["ok"] is True
    assert result["final_text"] == '{"op":"status"}'
    assert executor.status(home)["state"] == "held"
    assert executor.status(home)["host"] == "other-host"
    assert agent_run.lock_path(home).exists() is False


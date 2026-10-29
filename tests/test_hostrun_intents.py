"""listener-check: read-only listener health judgement, at most one restart."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hostrun import executor, install, intents, listener
from hostrun.base import update_config

TZ = timezone(timedelta(hours=8))
CHECK_AT = datetime(2026, 10, 29, 9, 0, tzinfo=TZ)
EVIDENCE_KEYS = {
    "checked_at",
    "heartbeat_at",
    "age_seconds",
    "pid",
    "pid_alive",
    "last_event_at",
    "action",
    "problems",
}


def _home(tmp_path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


def _heartbeat(home, *, updated_at, pid=4242, last_event_at=None):
    path = Path(home) / "listener" / "heartbeat.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pid": pid,
                "started_at": updated_at,
                "updated_at": updated_at,
                "state": "running",
                "last_event_at": last_event_at,
                "last_success_at": None,
                "consecutive_failures": 0,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _listener_health_entry(home) -> dict:
    return (install.load_state(home).get("steps") or {}).get("listener_health") or {}


def test_listener_check_is_a_registered_intent():
    assert "listener-check" in intents.INTENTS


def test_a_fresh_heartbeat_with_a_live_pid_is_online(tmp_path):
    home = _home(tmp_path)
    _heartbeat(
        home,
        updated_at=(CHECK_AT - timedelta(seconds=30)).isoformat(),
        pid=4242,
        last_event_at="2026-10-29T08:55:00+08:00",
    )
    spawns = []

    result = intents.run_listener_check(
        home,
        clock=lambda: CHECK_AT,
        pid_check=lambda pid: True,
        spawn=lambda argv: spawns.append(argv),
        sleep=lambda seconds: None,
    )

    assert result["ok"] is True
    assert result["state"] == "online"
    assert result["problems"] == []
    assert result["action"] == "none"
    assert spawns == []
    evidence = result["evidence"]
    assert EVIDENCE_KEYS <= set(evidence)
    assert evidence["checked_at"] == CHECK_AT.isoformat(timespec="seconds")
    assert evidence["heartbeat_at"] == (CHECK_AT - timedelta(seconds=30)).isoformat()
    assert evidence["age_seconds"] == 30
    assert evidence["pid"] == 4242
    assert evidence["pid_alive"] is True
    assert evidence["last_event_at"] == "2026-10-29T08:55:00+08:00"
    assert evidence["action"] == "none"
    assert evidence["problems"] == []

    entry = _listener_health_entry(home)
    assert entry["status"] == "ok"
    assert entry["evidence"]["action"] == "none"
    assert entry["evidence"]["age_seconds"] == 30


def test_a_fresh_heartbeat_with_a_dead_pid_is_not_online(tmp_path):
    home = _home(tmp_path)
    _heartbeat(home, updated_at=(CHECK_AT - timedelta(seconds=10)).isoformat(), pid=111)

    health = intents.listener_health(
        home, clock=lambda: CHECK_AT, pid_check=lambda pid: False
    )

    assert health["ok"] is False
    assert health["state"] == "offline"
    assert any("pid" in problem for problem in health["problems"])
    assert health["evidence"]["pid_alive"] is False


def test_a_stale_heartbeat_is_reported_stale(tmp_path):
    home = _home(tmp_path)
    _heartbeat(home, updated_at=(CHECK_AT - timedelta(hours=1)).isoformat(), pid=4242)

    health = intents.listener_health(
        home, clock=lambda: CHECK_AT, pid_check=lambda pid: True
    )

    assert health["ok"] is False
    assert health["state"] == "stale"
    assert health["evidence"]["age_seconds"] == 3600
    assert any("心跳" in problem or "stale" in problem for problem in health["problems"])


def test_an_unreadable_heartbeat_is_not_online(tmp_path):
    home = _home(tmp_path)
    path = home / "listener" / "heartbeat.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    health = intents.listener_health(home, clock=lambda: CHECK_AT)

    assert health["ok"] is False
    assert health["state"] == "offline"
    assert any("心跳" in problem for problem in health["problems"])


class _Clock:
    """A test clock whose sleep advances time and records the requested wait."""

    def __init__(self, moment):
        self.moment = moment
        self.sleeps = []

    def now(self):
        return self.moment

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.moment = self.moment + timedelta(seconds=seconds)


def _start_command(tmp_path) -> Path:
    command = tmp_path / "bin" / "frontier-listener.cmd"
    command.parent.mkdir(parents=True, exist_ok=True)
    command.write_text("", encoding="utf-8")
    return command


def _recording_spawn(spawns, *, raises=None):
    def spawn(argv):
        spawns.append([str(item) for item in argv])
        if raises is not None:
            raise raises
        return None

    return spawn


def test_offline_listener_is_restarted_once_and_rechecked(tmp_path):
    home = _home(tmp_path)
    command = _start_command(tmp_path)
    update_config(
        home,
        listener={"start_command": str(command), "recovery_recheck_seconds": 30},
    )
    _heartbeat(home, updated_at=(CHECK_AT - timedelta(hours=1)).isoformat(), pid=111)
    clock = _Clock(CHECK_AT)
    spawns = []

    def sleep(seconds):
        clock.sleep(seconds)
        # The restarted listener writes a fresh heartbeat with a new pid.
        _heartbeat(home, updated_at=clock.moment.isoformat(), pid=222)

    result = intents.run_listener_check(
        home,
        clock=clock.now,
        sleep=sleep,
        spawn=_recording_spawn(spawns),
        pid_check=lambda pid: pid == 222,
    )

    assert result["ok"] is True
    assert result["state"] == "online"
    assert result["problems"] == []
    assert result["action"] == "restart_ok"
    assert len(spawns) == 1
    assert any(str(command) in item for item in spawns[0])
    assert clock.sleeps == [30]
    evidence = result["evidence"]
    assert evidence["action"] == "restart_ok"
    assert evidence["pid"] == 222
    assert evidence["pid_alive"] is True
    entry = _listener_health_entry(home)
    assert entry["status"] == "ok"
    assert "拉起" in entry["note"]


def test_a_restart_that_does_not_recover_is_reported_without_retry(tmp_path):
    home = _home(tmp_path)
    command = _start_command(tmp_path)
    update_config(
        home,
        listener={"start_command": str(command), "recovery_recheck_seconds": 30},
    )
    clock = _Clock(CHECK_AT)
    spawns = []

    result = intents.run_listener_check(
        home,
        clock=clock.now,
        sleep=clock.sleep,  # no new heartbeat: the restart did not recover
        spawn=_recording_spawn(spawns),
        pid_check=lambda pid: False,
    )

    assert result["ok"] is False
    assert result["state"] == "offline"
    assert result["action"] == "restart_failed"
    assert len(spawns) == 1  # at most one attempt, never a retry loop
    assert clock.sleeps == [30]
    assert any("心跳文件不存在" in problem for problem in result["problems"])
    assert any("重启" in problem for problem in result["problems"])
    entry = _listener_health_entry(home)
    assert entry["status"] == "blocked"
    assert entry["evidence"]["action"] == "restart_failed"
    assert entry["evidence"]["problems"]


def test_a_spawn_failure_is_reported_without_waiting_or_retrying(tmp_path):
    home = _home(tmp_path)
    command = _start_command(tmp_path)
    update_config(home, listener={"start_command": str(command)})
    _heartbeat(home, updated_at=(CHECK_AT - timedelta(hours=1)).isoformat(), pid=111)
    clock = _Clock(CHECK_AT)
    spawns = []

    result = intents.run_listener_check(
        home,
        clock=clock.now,
        sleep=clock.sleep,
        spawn=_recording_spawn(spawns, raises=OSError("no console")),
        pid_check=lambda pid: False,
    )

    assert result["ok"] is False
    assert result["action"] == "restart_failed"
    assert len(spawns) == 1
    assert clock.sleeps == []
    assert any("no console" in problem for problem in result["problems"])
    assert _listener_health_entry(home)["status"] == "blocked"


def test_a_missing_start_command_is_reported_without_spawning(tmp_path):
    home = _home(tmp_path)
    _heartbeat(home, updated_at=(CHECK_AT - timedelta(hours=1)).isoformat(), pid=111)
    clock = _Clock(CHECK_AT)
    spawns = []

    result = intents.run_listener_check(
        home,
        clock=clock.now,
        sleep=clock.sleep,
        spawn=_recording_spawn(spawns),
        pid_check=lambda pid: False,
    )

    assert result["ok"] is False
    assert result["action"] == "listener_start_command_missing"
    assert spawns == []
    assert clock.sleeps == []
    assert any("listener install" in problem for problem in result["problems"])
    entry = _listener_health_entry(home)
    assert entry["status"] == "blocked"
    assert entry["evidence"]["action"] == "listener_start_command_missing"
    assert any(
        "listener_start_command_missing" in problem
        for problem in entry["evidence"]["problems"]
    )


def test_listener_check_runs_while_another_host_holds_the_lease(tmp_path, monkeypatch):
    home = _home(tmp_path)
    executor.acquire(home, host="08:00-push", minutes=45)
    _heartbeat(home, updated_at=CHECK_AT.isoformat(), pid=4242)
    acquire_calls = []

    def refuse_acquire(*args, **kwargs):
        acquire_calls.append((args, kwargs))
        raise AssertionError("listener-check must not take the executor lease")

    monkeypatch.setattr(intents.executor, "acquire", refuse_acquire)
    monkeypatch.setattr(intents, "_clock_now", lambda: CHECK_AT)
    monkeypatch.setattr(intents, "_pid_alive", lambda pid: True)

    result = intents.run(
        home,
        "listener-check",
        scheduled=True,
        task="frontier-listener-check",
        proof="whatever",
    )

    assert result["ok"] is True
    assert result["state"] == "online"
    assert result["action"] == "none"
    assert acquire_calls == []
    assert executor.status(home)["state"] == "held"  # the push lease is untouched
    assert not (home / "hostrun" / "runs.jsonl").exists()


def test_listener_check_writes_no_scheduled_run_evidence(tmp_path, monkeypatch):
    home = _home(tmp_path)
    _heartbeat(home, updated_at=CHECK_AT.isoformat(), pid=4242)
    monkeypatch.setattr(intents, "_clock_now", lambda: CHECK_AT)
    monkeypatch.setattr(intents, "_pid_alive", lambda pid: True)

    result = intents.run(home, "listener-check")

    assert set(result) == {"ok", "state", "problems", "action", "evidence"}
    assert not (home / "hostrun" / "runs.jsonl").exists()
    steps = install.load_state(home).get("steps") or {}
    assert "scheduled_run" not in steps
    assert steps["listener_health"]["status"] == "ok"
    assert "scheduled" not in json.dumps(steps["listener_health"])


# ---------------------------------------------------------------- pid liveness
# Regression for #70: on Windows a process that has already exited can still
# yield a usable handle while another handle keeps the object alive.  Liveness
# therefore has to be decided on the wait result, not on OpenProcess.
WAIT_TIMEOUT = 0x102
WAIT_OBJECT_0 = 0x0


class _FakeKernel32:
    """Fake kernel32 whose handle always opens; only the wait result decides."""

    PROCESS_SYNCHRONIZE = 0x00100000

    def __init__(self, *, opened=True, wait=WAIT_TIMEOUT):
        self.opened = opened
        self.wait = wait
        self.opened_pids = []
        self.waited = []
        self.closed = []

    def OpenProcess(self, access, inherit, pid):
        self.opened_pids.append((access, inherit, pid))
        return 1234 if self.opened else 0

    def WaitForSingleObject(self, handle, timeout):
        self.waited.append((handle, timeout))
        return self.wait

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return 1


def test_windows_pid_liveness_treats_an_exited_process_with_an_open_handle_as_dead():
    kernel32 = _FakeKernel32(wait=WAIT_OBJECT_0)  # already signalled = exited

    assert listener.pid_alive(4242, platform="nt", kernel32=kernel32) is False
    assert kernel32.opened_pids == [(0x00100000, False, 4242)]
    assert kernel32.waited == [(1234, 0)]
    assert kernel32.closed == [1234]


def test_windows_pid_liveness_accepts_a_running_process():
    kernel32 = _FakeKernel32(wait=WAIT_TIMEOUT)  # still running

    assert listener.pid_alive(4242, platform="nt", kernel32=kernel32) is True
    assert kernel32.closed == [1234]


def test_windows_pid_liveness_handles_an_unopenable_pid():
    kernel32 = _FakeKernel32(opened=False)

    assert listener.pid_alive(4242, platform="nt", kernel32=kernel32) is False
    assert kernel32.waited == []
    assert kernel32.closed == []


def test_pid_liveness_rejects_invalid_pids_without_opening_a_handle():
    for pid in (None, "", 0, -3, "abc"):
        kernel32 = _FakeKernel32()
        assert listener.pid_alive(pid, platform="nt", kernel32=kernel32) is False
        assert kernel32.opened_pids == []


def test_windows_pid_liveness_closes_the_handle_when_the_wait_fails():
    class Exploding(_FakeKernel32):
        def WaitForSingleObject(self, handle, timeout):
            raise OSError("kernel32 exploded")

    kernel32 = Exploding()

    assert listener.pid_alive(4242, platform="nt", kernel32=kernel32) is False
    assert kernel32.closed == [1234]


def test_posix_pid_liveness_keeps_the_os_kill_semantics():
    calls = []

    def kill(pid, signal_number):
        calls.append((pid, signal_number))

    assert listener.pid_alive(4242, platform="posix", kill=kill) is True
    assert calls == [(4242, 0)]

    def missing(pid, signal_number):
        raise ProcessLookupError

    assert listener.pid_alive(4242, platform="posix", kill=missing) is False


def test_listener_health_uses_the_shared_pid_judgement(tmp_path, monkeypatch):
    home = _home(tmp_path)
    _heartbeat(home, updated_at=CHECK_AT.isoformat(), pid=4242)
    monkeypatch.setattr(listener, "pid_alive", lambda pid: False)

    health = intents.listener_health(home, clock=lambda: CHECK_AT)

    assert health["ok"] is False
    assert health["state"] == "offline"
    assert health["evidence"]["pid_alive"] is False
    assert any("pid" in problem for problem in health["problems"])


def test_a_fresh_heartbeat_whose_pid_is_dead_restarts_the_listener(tmp_path, monkeypatch):
    home = _home(tmp_path)
    command = _start_command(tmp_path)
    update_config(
        home,
        listener={"start_command": str(command), "recovery_recheck_seconds": 30},
    )
    _heartbeat(home, updated_at=(CHECK_AT - timedelta(seconds=10)).isoformat(), pid=111)
    clock = _Clock(CHECK_AT)
    spawns = []

    def sleep(seconds):
        clock.sleep(seconds)
        _heartbeat(home, updated_at=clock.moment.isoformat(), pid=222)

    monkeypatch.setattr(listener, "pid_alive", lambda pid: int(pid) == 222)

    result = intents.run_listener_check(
        home, clock=clock.now, sleep=sleep, spawn=_recording_spawn(spawns)
    )

    assert result["ok"] is True
    assert result["action"] == "restart_ok"
    assert len(spawns) == 1


def test_heartbeat_facts_read_a_naive_timestamp_as_utc(tmp_path):
    home = _home(tmp_path)
    _heartbeat(home, updated_at="2026-10-29T00:59:00", pid=4242)

    facts = listener.heartbeat_facts(home, moment=CHECK_AT, stale_seconds=600)

    assert facts["present"] is True
    assert facts["age_seconds"] == 60
    assert facts["state"] == "online"


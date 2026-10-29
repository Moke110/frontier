"""listener-check: read-only listener health judgement, at most one restart."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hostrun import executor, install, intents
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


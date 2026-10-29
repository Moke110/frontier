"""Two host tasks, hourly maintenance, and real-trigger evidence."""

import json
import os
import shlex
from pathlib import Path

import pytest

from hostrun import install, intents, schedules
from hostrun.base import HostRunError, update_config
from question_queue.store import QueueStore

ROOT = Path(__file__).resolve().parents[1]


class FakeLibrary:
    def __init__(self):
        self.calls = []

    def reconcile(self, dry_run=False):
        self.calls.append("reconcile")
        return {"ok": True, "counts": {"orphans": 0}}

    def usage(self):
        return {"used": 0, "limit": 100, "percent": 0, "level": "ok"}

    def maybe_alert(self, reason=""):
        return False


def _home(tmp_path) -> Path:
    home = tmp_path / "home"
    (home / "knowledge").mkdir(parents=True)
    (home / "knowledge" / "base.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "base_token": "basoffline",
                "base_url": "https://example.feishu.cn/base/basoffline",
                "tables": {},
            }
        ),
        encoding="utf-8",
    )
    return home


def test_plan_has_exactly_two_tasks_and_no_maintenance(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    spec = schedules.plan(home, timezone_name="Asia/Shanghai")

    assert [task["id"] for task in spec["tasks"]] == ["frontier-daily", "frontier-feedback"]
    assert [task["intent"] for task in spec["tasks"]] == ["daily", "feedback"]
    assert all(task["load_skill"] for task in spec["tasks"])
    assert "maintenance" not in {task["intent"] for task in spec["tasks"]}
    assert "08:00" == spec["tasks"][0]["at"]
    assert spec["tasks"][1]["at"].startswith("*:")
    offsets = {task["utc_offset_seconds"] for task in spec["tasks"]}
    assert len(offsets) == 1
    assert next(iter(offsets)) == schedules._local_utc_offset_seconds()


def test_hourly_feedback_runs_maintenance_but_never_starts_retrieval(tmp_path):
    home = _home(tmp_path)
    queue = QueueStore(home)
    queue.init()
    queue.request_push("manual")
    library = FakeLibrary()

    result = intents.run(
        home,
        "feedback",
        offline=True,
        library=library,
        date="2026-10-27",
    )

    assert result["maintenance"]["ok"] is True
    assert "reconcile" in library.calls
    assert result["retrieval"]["started"] is False
    assert result["retrieval"]["requested"] is False
    assert "retrieval:skipped" in result["actions"]
    assert queue.active() is None


def test_daily_still_starts_a_retrieval(tmp_path):
    home = _home(tmp_path)
    install.record(home, "knowledge", "ok")
    library = FakeLibrary()

    result = intents.run(home, "daily", offline=True, library=library, date="2026-10-27")

    assert result["retrieval"]["started"] is True
    assert result["brief"]


def test_daily_is_blocked_until_knowledge_is_ready(tmp_path):
    home = _home(tmp_path)

    result = intents.run(home, "daily", offline=True, library=FakeLibrary(), date="2026-10-27")

    assert result["retrieval"]["started"] is False
    assert result["retrieval"]["reason"] == "knowledge_not_ready"
    assert "retrieval:blocked(knowledge_not_ready)" in result["actions"]


def test_scheduled_flag_needs_the_confirmed_task_proof(tmp_path):
    home = _home(tmp_path)
    intents.run(
        home,
        "feedback",
        offline=True,
        library=FakeLibrary(),
        date="2026-10-27",
        scheduled=True,
        task="frontier-feedback",
    )
    rows = [
        json.loads(line)
        for line in (home / "hostrun" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert not any(row.get("scheduled") is True for row in rows)
    assert any(row.get("scheduled_rejected") is True for row in rows)

    install.record(home, "knowledge", "ok")
    schedules.confirm(
        home,
        confirmed_by_user=True,
        host_created=True,
        task_ids={"frontier-daily": "d1", "frontier-feedback": "f1"},
    )
    config = json.loads((home / "install" / "config.json").read_text(encoding="utf-8"))
    task = next(
        row
        for row in config["schedules"]["tasks"]
        if row["id"] == "frontier-feedback"
    )
    intents.run(
        home,
        "feedback",
        offline=True,
        library=FakeLibrary(),
        date="2026-10-27",
        scheduled=True,
        task="frontier-feedback",
        proof=task["proof"],
    )
    rows = [
        json.loads(line)
        for line in (home / "hostrun" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(
        row.get("scheduled") is True
        and row.get("task") == "frontier-feedback"
        and row.get("proof") == task["proof"]
        for row in rows
    )


def test_enabling_requires_initialized_knowledge(tmp_path):
    home = _home(tmp_path)

    result = schedules.confirm(
        home,
        confirmed_by_user=True,
        host_created=True,
        task_ids={"frontier-daily": "d1", "frontier-feedback": "f1"},
    )

    assert result["ok"] is False
    assert result["reason"] == "knowledge_not_ready"
    assert schedules.status(home)["enabled"] is False
    assert schedules.status(home)["tasks"] == {}


def test_paused_confirmation_still_requires_initialized_knowledge(tmp_path):
    home = _home(tmp_path)

    result = schedules.confirm(
        home,
        confirmed_by_user=True,
        host_created=True,
        enabled=False,
        task_ids={"frontier-daily": "d1", "frontier-feedback": "f1"},
    )

    assert result["ok"] is False
    assert result["reason"] == "knowledge_not_ready"
    assert "知识" in result["note"]
    config_path = home / "install" / "config.json"
    config = (
        json.loads(config_path.read_text(encoding="utf-8"))
        if config_path.exists()
        else {}
    )
    assert not (config.get("schedules") or {}).get("tasks")
    status = schedules.status(home)
    assert status["tasks"] == {}
    assert status["created"] is False


def _pin_offset(home, seconds=8 * 3600):
    """Pin the planned offset so wall-clock fixtures don't depend on the host zone."""
    config = json.loads((home / "install" / "config.json").read_text(encoding="utf-8"))
    schedules_config = config["schedules"]
    for task in schedules_config["tasks"]:
        task["utc_offset_seconds"] = seconds
    update_config(home, schedules=schedules_config)
    return schedules_config


def _confirmed_home(tmp_path):
    home = _home(tmp_path)
    install.record(home, "knowledge", "ok")
    schedules.confirm(
        home,
        confirmed_by_user=True,
        host_created=True,
        task_ids={"frontier-daily": "d1", "frontier-feedback": "f1"},
    )
    config = _pin_offset(home)
    proofs = {row["id"]: row["proof"] for row in config["tasks"]}
    return home, proofs


def _write_runs(home, task_id, intent, proof, *at_values):
    path = home / "hostrun" / "runs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for at in at_values:
        row = {
            "intent": intent,
            "task": task_id,
            "proof": proof,
            "scheduled": True,
            "ok": True,
        }
        if at is not None:
            row["at"] = at
        rows.append(json.dumps(row))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_daily_trigger_accepts_a_run_inside_the_startup_window(tmp_path):
    home, proofs = _confirmed_home(tmp_path)
    _write_runs(
        home,
        "frontier-daily",
        "daily",
        proofs["frontier-daily"],
        "2026-10-28T08:03:00+08:00",
    )

    result = schedules.record_trigger(home, "frontier-daily")

    assert result["run"]["at"] == "2026-10-28T08:03:00+08:00"
    assert result["remaining"] == ["frontier-feedback"]


def test_daily_trigger_rejects_a_run_outside_the_startup_window(tmp_path):
    home, proofs = _confirmed_home(tmp_path)
    _write_runs(
        home,
        "frontier-daily",
        "daily",
        proofs["frontier-daily"],
        "2026-10-28T09:00:00+08:00",
    )

    result = schedules.record_trigger(home, "frontier-daily")

    assert result["ok"] is False
    assert result["reason"] == "no_scheduled_run"
    assert "计划" in result["note"]
    status = schedules.status(home)
    assert status["tasks"]["frontier-daily"]["scheduled_runs"] == 0


def test_daily_trigger_rejects_a_run_in_another_planned_offset(tmp_path):
    home, proofs = _confirmed_home(tmp_path)
    _write_runs(
        home,
        "frontier-daily",
        "daily",
        proofs["frontier-daily"],
        "2026-10-28T08:03:00+00:00",
    )

    result = schedules.record_trigger(home, "frontier-daily")

    assert result["ok"] is False
    assert result["reason"] == "no_scheduled_run"


def test_daily_trigger_rejects_a_run_beyond_the_five_minute_window(tmp_path):
    home, proofs = _confirmed_home(tmp_path)
    _write_runs(
        home,
        "frontier-daily",
        "daily",
        proofs["frontier-daily"],
        "2026-10-28T08:06:00+08:00",
    )

    result = schedules.record_trigger(home, "frontier-daily")

    assert result["ok"] is False
    assert result["reason"] == "no_scheduled_run"


def test_feedback_trigger_accepts_the_configured_minute_window(tmp_path):
    home, proofs = _confirmed_home(tmp_path)
    _write_runs(
        home,
        "frontier-feedback",
        "feedback",
        proofs["frontier-feedback"],
        "2026-10-28T09:06:00+08:00",
    )

    result = schedules.record_trigger(home, "frontier-feedback")

    assert result["run"]["at"] == "2026-10-28T09:06:00+08:00"
    assert result["remaining"] == ["frontier-daily"]


def test_feedback_trigger_rejects_a_run_outside_the_minute_window(tmp_path):
    home, proofs = _confirmed_home(tmp_path)
    _write_runs(
        home,
        "frontier-feedback",
        "feedback",
        proofs["frontier-feedback"],
        "2026-10-28T09:30:00+08:00",
    )

    result = schedules.record_trigger(home, "frontier-feedback")

    assert result["ok"] is False
    assert result["reason"] == "no_scheduled_run"


@pytest.mark.parametrize("stamp", [None, "not-a-time", "2026-10-28T08:03:00"])
def test_trigger_rejects_a_run_without_a_parseable_local_timestamp(tmp_path, stamp):
    home, proofs = _confirmed_home(tmp_path)
    _write_runs(
        home,
        "frontier-daily",
        "daily",
        proofs["frontier-daily"],
        stamp,
    )

    result = schedules.record_trigger(home, "frontier-daily")

    assert result["ok"] is False
    assert result["reason"] == "no_scheduled_run"


def test_trigger_rejects_an_on_time_run_with_a_wrong_proof(tmp_path):
    home, proofs = _confirmed_home(tmp_path)
    _write_runs(
        home,
        "frontier-daily",
        "daily",
        "copied-or-guessed",
        "2026-10-28T08:03:00+08:00",
    )

    result = schedules.record_trigger(home, "frontier-daily")

    assert result["ok"] is False
    assert result["reason"] == "no_scheduled_run"


def test_created_tasks_keep_ids_and_do_not_duplicate(tmp_path):
    home = _home(tmp_path)
    install.record(home, "knowledge", "ok")
    ids = {"frontier-daily": "d1", "frontier-feedback": "f1"}

    first = schedules.confirm(
        home, confirmed_by_user=True, host_created=True, task_ids=ids
    )
    second = schedules.confirm(
        home, confirmed_by_user=True, host_created=True, task_ids=ids
    )

    assert first["created"] is True
    assert second["created"] is True
    status = schedules.status(home)
    assert len(status["tasks"]) == 2
    assert {task["host_task_id"] for task in status["tasks"].values()} == {"d1", "f1"}
    assert status["enabled"] is True


def test_host_created_without_task_ids_is_not_a_created_task(tmp_path):
    home = _home(tmp_path)
    install.record(home, "knowledge", "ok")

    result = schedules.confirm(home, confirmed_by_user=True, host_created=True)

    assert result["ok"] is False
    assert result["reason"] == "missing_host_task_ids"


def test_manual_run_does_not_count_and_scheduled_runs_do(tmp_path):
    home = _home(tmp_path)
    install.record(home, "knowledge", "ok")
    ids = {"frontier-daily": "d1", "frontier-feedback": "f1"}
    schedules.confirm(home, confirmed_by_user=True, host_created=True, task_ids=ids)
    config = _pin_offset(home)
    proofs = {row["id"]: row["proof"] for row in config["tasks"]}
    (home / "hostrun").mkdir(parents=True, exist_ok=True)
    runs = home / "hostrun" / "runs.jsonl"
    runs.write_text(
        json.dumps({"intent": "daily", "task": "frontier-daily", "scheduled": False, "ok": True, "at": "2026-10-27T08:00:00+08:00"})
        + "\n",
        encoding="utf-8",
    )

    manual = schedules.record_trigger(home, "frontier-daily")
    assert manual["ok"] is False
    assert manual["reason"] == "no_scheduled_run"

    runs.write_text(
        runs.read_text(encoding="utf-8")
        + json.dumps({"intent": "daily", "task": "frontier-daily", "proof": proofs["frontier-daily"], "scheduled": True, "ok": True, "at": "2026-10-28T08:00:00+08:00"})
        + "\n",
        encoding="utf-8",
    )
    daily = schedules.record_trigger(home, "frontier-daily", at="2026-10-28T08:00:00+08:00")
    assert daily["ok"] is False  # feedback still missing
    assert daily["remaining"] == ["frontier-feedback"]

    runs.write_text(
        runs.read_text(encoding="utf-8")
        + json.dumps({"intent": "feedback", "task": "frontier-feedback", "proof": proofs["frontier-feedback"], "scheduled": True, "ok": True, "at": "2026-10-28T09:05:00+08:00"})
        + "\n",
        encoding="utf-8",
    )
    feedback = schedules.record_trigger(home, "frontier-feedback", at="2026-10-28T09:05:00+08:00")
    assert feedback["ok"] is True
    assert schedules.status(home)["scheduled_run_verified"] is True
    state = json.loads((home / "install" / "state.json").read_text(encoding="utf-8"))
    assert state["steps"]["scheduled_run"]["status"] == "ok"


def test_pause_stops_trigger_recording_and_resume_requires_tasks(tmp_path):
    home = _home(tmp_path)
    install.record(home, "knowledge", "ok")
    schedules.confirm(
        home,
        confirmed_by_user=True,
        host_created=True,
        task_ids={"frontier-daily": "d1", "frontier-feedback": "f1"},
    )
    paused = schedules.pause(home, confirmed_by_user=True, reason="travel")

    assert paused["ok"] is True
    assert schedules.status(home)["enabled"] is False
    refused = schedules.record_trigger(home, "frontier-daily")
    assert refused["reason"] == "task_disabled"

    resumed = schedules.resume(home, confirmed_by_user=True)
    assert resumed["ok"] is True
    assert schedules.status(home)["enabled"] is True


# --------------------------------------------- recorded absolute command paths
def _quoted(path: Path) -> str:
    text = str(path)
    if os.name == "nt":
        return f'"{text}"' if any(char in text for char in " \t") else text
    return shlex.quote(text)


def test_plan_refuses_without_a_recorded_absolute_interpreter(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    update_config(home, paths={"python": ""})
    empty = schedules.plan(home, timezone_name="Asia/Shanghai")

    assert empty["ok"] is False
    assert empty["reason"] == "interpreter_not_absolute"
    assert "install toolchain" in empty["note"]
    assert "tasks" not in empty

    update_config(home, paths={"python": "python"})
    relative = schedules.plan(home, timezone_name="Asia/Shanghai")

    assert relative["ok"] is False
    assert relative["reason"] == "interpreter_not_absolute"
    assert "tasks" not in relative


def test_plan_refuses_when_the_recorded_interpreter_is_gone(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    update_config(home, paths={"python": str(tmp_path / "gone" / "python")})

    blocked = schedules.plan(home, timezone_name="Asia/Shanghai")

    assert blocked["ok"] is False
    assert blocked["reason"] == "interpreter_missing"
    assert "install toolchain" in blocked["note"]
    assert "tasks" not in blocked


def test_plan_embeds_the_recorded_absolute_interpreter_in_both_commands(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    interpreter = tmp_path / "env with space" / (
        "python.exe" if os.name == "nt" else "bin/python"
    )
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text("", encoding="utf-8")
    repo = tmp_path / "frontier"
    repo.mkdir()
    skill = repo / "skills" / "frontier-run" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: frontier-run\n---\n", encoding="utf-8")
    update_config(
        home,
        paths={
            "python": str(interpreter),
            "repo": str(repo),
            "skill": str(skill),
        },
    )

    spec = schedules.plan(home, timezone_name="Asia/Shanghai")

    assert spec["ok"] is True
    assert [task["id"] for task in spec["tasks"]] == [
        "frontier-daily",
        "frontier-feedback",
    ]
    for task in spec["tasks"]:
        command = task["command"]
        assert command.startswith(_quoted(interpreter))
        assert str(home) in command
        assert str(repo) in command
        assert f"--intent {task['intent']}" in command
        assert task["load_skill"] == str(skill)
        assert "python -m hostrun.cli" not in command
    assert "maintenance" not in {task["intent"] for task in spec["tasks"]}


def test_confirm_refuses_to_create_tasks_without_a_recorded_interpreter(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    update_config(home, paths={"python": ""})

    result = schedules.confirm(
        home,
        confirmed_by_user=True,
        host_created=True,
        task_ids={"frontier-daily": "d1", "frontier-feedback": "f1"},
    )

    assert result["ok"] is False
    assert result["reason"] == "interpreter_not_absolute"
    config = json.loads((home / "install" / "config.json").read_text(encoding="utf-8"))
    assert not (config.get("schedules") or {}).get("tasks")

def test_scheduled_run_logs_its_start_time_not_the_completion_time(tmp_path, monkeypatch):
    """A long maintenance must not push the on-time evidence out of its window."""
    home = _home(tmp_path)
    install.record(home, "knowledge", "ok")
    schedules.confirm(
        home,
        confirmed_by_user=True,
        host_created=True,
        task_ids={"frontier-daily": "d1", "frontier-feedback": "f1"},
    )
    config = json.loads((home / "install" / "config.json").read_text(encoding="utf-8"))
    task = next(
        row for row in config["schedules"]["tasks"] if row["id"] == "frontier-feedback"
    )
    start = "2026-10-27T08:00:04+08:00"
    calls = {"n": 0}

    def fake_now():
        calls["n"] += 1
        return start if calls["n"] == 1 else "2026-10-27T08:19:44+08:00"

    monkeypatch.setattr(intents, "now", fake_now)
    captured = {}
    monkeypatch.setattr(intents, "_runlog", lambda home_, row: captured.update(row))

    intents.run(
        home,
        "feedback",
        offline=True,
        library=FakeLibrary(),
        date="2026-10-27",
        scheduled=True,
        task="frontier-feedback",
        proof=task["proof"],
    )

    assert captured["scheduled"] is True
    assert captured["at"] == start

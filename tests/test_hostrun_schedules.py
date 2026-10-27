"""Two host tasks, hourly maintenance, and real-trigger evidence."""

import json
from pathlib import Path

import pytest

from hostrun import install, intents, schedules
from hostrun.base import HostRunError
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
    config = json.loads((home / "install" / "config.json").read_text(encoding="utf-8"))
    proofs = {row["id"]: row["proof"] for row in config["schedules"]["tasks"]}
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

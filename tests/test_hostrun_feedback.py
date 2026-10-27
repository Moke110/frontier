"""Persistent feedback: explicit submission, active-only processing, traceable corrections."""

import json
import shutil

import pytest

from conftest import seed_queue
from hostrun import feedback
from question_queue.store import QueueStore


def _rating(item_id="q_01", status="active", **over):
    item = {
        "id": item_id,
        "kind": "rating",
        "push_id": "2026-10-21_card_hmbs_01",
        "card_id": "card_hmbs",
        "status": status,
        "created_at": "2026-10-21T08:00:00+08:00",
        "sent_at": "2026-10-21T08:01:00+08:00",
        "answered_at": None,
        "message_id": "om_1",
        "attempts": 0,
        "answer": None,
        "payload": {
            "target_type": "push",
            "target_id": "2026-10-21_card_hmbs_01",
            "target_label": "HMBS 推送",
            "proposals": [],
            "proposal_ids": [],
            "ready": True,
        },
    }
    item.update(over)
    return item


def _ready(home, base, items):
    feedback.setup(home, client=base)
    seed_queue(home, items)
    return feedback.sync(home, client=base)


# ------------------------------------------------------------------- setup
def test_setup_creates_the_three_tables_once(configured_home, offline_base):
    first = feedback.setup(configured_home, client=offline_base)
    second = feedback.setup(configured_home, client=offline_base)

    names = [row["name"] for row in offline_base.list_tables()]
    for name in feedback.TABLE_NAMES.values():
        assert names.count(name) == 1
    assert first["tables"]["questions"]
    assert [a for a in second["actions"] if a.startswith("create table")] == []


# -------------------------------------------------------------------- sync
def test_sync_mirrors_the_queue_without_duplicates(configured_home, offline_base):
    queue = [_rating(), _rating("q_02", status="pending", card_id="card_aip")]

    first = _ready(configured_home, offline_base, queue)
    assert first["created"] == 2

    second = feedback.sync(configured_home, client=offline_base)
    assert second["created"] == 0
    rows = feedback.status(configured_home, client=offline_base)
    assert rows["questions"] == 2
    assert rows["by_state"][feedback.ACTIVE] == 1
    assert rows["by_state"][feedback.OPEN] == 1


def test_sync_keeps_a_submission_made_in_feishu(configured_home, offline_base):
    _ready(configured_home, offline_base, [_rating()])
    feedback.submit(configured_home, "q_01", {"verdict": "great"}, client=offline_base)

    # another machine syncs before this one processes the answer
    result = feedback.sync(configured_home, client=offline_base)

    assert result["kept_submitted"] == 1
    tables = feedback.load_tables(configured_home)
    row = next(r for r in offline_base.list(tables[feedback.QUESTIONS]))
    assert row["fields"]["状态"] == feedback.SUBMITTED
    assert json.loads(row["fields"]["当前答案"]) == {"verdict": "great"}


# ------------------------------------------------------------------ submit
def test_submit_is_the_boundary_nothing_applies_before_it(configured_home, offline_base):
    _ready(configured_home, offline_base, [_rating()])

    queue = QueueStore(configured_home)
    assert queue.get("q_01")["status"] == "active"
    assert feedback.status(configured_home, client=offline_base)["pending_submissions"] == 0

    bad = feedback.submit(configured_home, "q_01", {"verdict": "idiot"}, client=offline_base)
    assert bad["ok"] is False
    assert bad["problems"]

    ok = feedback.submit(configured_home, "q_01", {"verdict": "ok"}, client=offline_base)
    assert ok["ok"] is True
    assert queue.get("q_01")["status"] == "active"  # still only submitted
    assert feedback.status(configured_home, client=offline_base)["pending_submissions"] == 1


def test_submit_is_idempotent(configured_home, offline_base):
    _ready(configured_home, offline_base, [_rating()])

    first = feedback.submit(configured_home, "q_01", {"verdict": "ok"}, client=offline_base)
    again = feedback.submit(configured_home, "q_01", {"verdict": "ok"}, client=offline_base)

    assert again["deduped"] is True
    assert again["submission_id"] == first["submission_id"]
    assert feedback.status(configured_home, client=offline_base)["pending_submissions"] == 1


# ----------------------------------------------------------------- process
def test_process_applies_once_and_reports_quiet_next_time(configured_home, offline_base):
    _ready(configured_home, offline_base, [_rating()])
    feedback.submit(configured_home, "q_01", {"verdict": "great", "comment": "有用"}, client=offline_base)

    result = feedback.process(configured_home, client=offline_base)

    assert result["processed"] == 1
    assert result["quiet"] is False
    item = QueueStore(configured_home).get("q_01")
    assert item["status"] == "answered"
    assert item["answer"]["verdict"] == "great"

    second = feedback.process(configured_home, client=offline_base)
    assert second["processed"] == 0
    assert second["quiet"] is True

    tables = feedback.load_tables(configured_home)
    question = next(r for r in offline_base.list(tables[feedback.QUESTIONS]))
    assert question["fields"]["状态"] == feedback.PROCESSED
    assert "评分 great" in question["fields"]["处理结果"]


def test_process_does_not_apply_a_question_that_is_not_active(configured_home, offline_base):
    _ready(configured_home, offline_base, [_rating("q_02", status="pending")])
    tables = feedback.load_tables(configured_home)
    offline_base.create(
        tables[feedback.SUBMISSIONS],
        [
            {
                "反馈 ID": "fb_01_x",
                "问题 ID": "q_02",
                "答案": json.dumps({"verdict": "ok"}),
                "提交时间": "2026-10-21T09:00:00+08:00",
                "处理状态": feedback.PENDING,
                "处理时间": "",
                "结果": "",
            }
        ],
    )

    result = feedback.process(configured_home, client=offline_base)

    assert result["processed"] == 0
    assert result["skipped"] == 1
    assert QueueStore(configured_home).get("q_02")["status"] == "pending"


# ------------------------------------------------------------- corrections
def test_correction_is_recorded_and_queued_but_not_applied(configured_home, offline_base):
    _ready(configured_home, offline_base, [_rating()])

    needs_reason = feedback.correct(configured_home, "q_01", "  ", client=offline_base)
    assert needs_reason["ok"] is False
    assert needs_reason["reason"] == "reason_required"

    result = feedback.correct(configured_home, "q_01", "康替唑胺的机制写错了", client=offline_base)

    assert result["ok"] is True
    queue = QueueStore(configured_home)
    correction = queue.get(result["item_id"])
    assert correction["kind"] == "correction"
    assert correction["payload"]["reason"] == "康替唑胺的机制写错了"
    assert correction["payload"]["ready"] is False  # needs new proposals first
    assert correction["status"] in ("pending", "active")

    # recording a correction applies nothing: the original question is untouched
    assert queue.get("q_01")["status"] == "active"
    assert feedback.status(configured_home, client=offline_base)["pending_corrections"] == 1

    again = feedback.correct(configured_home, "q_01", "同样的原因", client=offline_base)
    assert again["ok"] is True


def test_correction_becomes_askable_only_after_proposals_exist(configured_home, offline_base):
    _ready(configured_home, offline_base, [_rating()])
    result = feedback.correct(configured_home, "q_01", "需要更正", client=offline_base)
    queue = QueueStore(configured_home)

    queue.mark_correction_ready(result["item_id"], [{"proposal_id": "p_fix_1", "op": "update_card"}])

    item = queue.get(result["item_id"])
    assert item["payload"]["ready"] is True
    assert item["payload"]["proposal_ids"] == ["p_fix_1"]


# ----------------------------------------------------------------- rebuild
def test_rebuild_restores_ids_and_never_reopens_a_processed_decision(configured_home, offline_base):
    _ready(configured_home, offline_base, [_rating()])
    feedback.submit(configured_home, "q_01", {"verdict": "ok"}, client=offline_base)
    feedback.process(configured_home, client=offline_base)

    shutil.rmtree(configured_home / "queue")  # fresh machine

    result = feedback.rebuild(configured_home, client=offline_base)

    assert result["ok"] is True
    assert result["rebuilt"] == 1
    item = QueueStore(configured_home).get("q_01")
    assert item["status"] == "answered"
    assert QueueStore(configured_home).has_unfinished() is False


def test_rebuild_with_no_remote_rows_says_so(configured_home, offline_base):
    feedback.setup(configured_home, client=offline_base)

    result = feedback.rebuild(configured_home, client=offline_base)

    assert result["items"] == 0
    assert "飞书" in result["note"]

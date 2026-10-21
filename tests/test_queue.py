import json
from pathlib import Path

import pytest

from archive.store import Archive, ArchiveError
from publisher.service import handle_event, replay, send_rating
from question_queue.store import QueueStore


def _push(home: Path, push_id: str = "2026-10-21_card_hmbs_01") -> dict:
    store = Archive(home)
    card = store.get_card("card_hmbs")
    other = store.get_card("card_aip")
    prop = store.get_prop("prop_hmbs_aip")
    evidence = {
        "paper_id": "europepmc_42900001",
        "page": 3,
        "quote": "Knockout of HMBS reduced heme biosynthesis and caused porphyrin precursor accumulation.",
    }

    def proposal(pid, op, target_type, target_id, path, value, before, after):
        return {
            "schema_version": 2,
            "proposal_id": pid,
            "push_id": push_id,
            "op": op,
            "target_type": target_type,
            "target_id": target_id,
            "diff": {"op": "add" if op in {"add_card_ontology", "add_proposition_evidence"} else "replace", "path": path, "value": value},
            "before": before,
            "after": after,
            "rationale": "A rationale long enough for the queue test.",
            "confidence": 0.7,
            "evidence": evidence,
            "status": "draft",
        }

    new_prop = {
        "id": "prop_hmbs_mitochondria",
        "title": "HMBS loss impairs mitochondrial function",
        "content": "HMBS loss increases ALA and impairs mitochondrial function in hepatocytes.",
        "related_knowledge": ["card_hmbs", "card_heme_biosynthesis"],
    }
    return {
        "schema_version": 2,
        "format": "pdf",
        "push_id": push_id,
        "date": "2026-10-21",
        "checkpoint_id": "card_hmbs",
        "card_id": "card_hmbs",
        "paper_ids": ["europepmc_42900001"],
        "paper": {"paper_id": "europepmc_42900001", "title": "HMBS loss impairs heme biosynthesis"},
        "sections": {"takeaway": "HMBS loss hurts mitochondria."},
        "proposals": [
            proposal(
                f"p_{push_id}_01",
                "add_card_ontology",
                "card",
                "card_hmbs",
                "ontology",
                "PBG deaminase",
                card["ontology"],
                card["ontology"] + ["PBG deaminase"],
            ),
            proposal(
                f"p_{push_id}_02",
                "update_card_annotation",
                "card",
                "card_aip",
                "annotation",
                other["annotation"] + "\n新证据：HMBS 缺失可触发 AIP 表型。",
                other["annotation"],
                other["annotation"] + "\n新证据：HMBS 缺失可触发 AIP 表型。",
            ),
            proposal(
                f"p_{push_id}_03",
                "update_proposition_title",
                "proposition",
                "prop_hmbs_aip",
                "title",
                "HMBS 缺失导致 AIP（修订）",
                prop["title"],
                "HMBS 缺失导致 AIP（修订）",
            ),
            {
                **proposal(
                    f"p_{push_id}_04",
                    "create_proposition",
                    "none",
                    None,
                    "proposition",
                    new_prop,
                    None,
                    new_prop,
                ),
                "before": None,
            },
        ],
    }


def _enqueue(home: Path, push: dict) -> QueueStore:
    store = Archive(home)
    store.add_push(push)
    queue = QueueStore(home)
    queue.init()
    queue.enqueue_push(push)
    return queue


def _next_message_id(result: dict) -> str | None:
    return result.get("next_message_id")


def _event(message_id: str, action: str, token: str = "") -> dict:
    return {
        "message_id": message_id,
        "action_name": action,
        "form_value": json.dumps({"comment": ""}),
        "operator_id": "ou_test",
        "token": token,
        "chat_id": "oc_test",
    }


def test_enqueue_groups_two_cards_and_two_propositions(kl_home):
    push = _push(kl_home)
    queue = _enqueue(kl_home, push)
    items = queue.items(push["push_id"])
    assert [item["kind"] for item in items] == [
        "rating",
        "card_update",
        "card_update",
        "proposition_update",
        "proposition_update",
    ]
    assert items[0]["status"] == "active"
    assert [item["status"] for item in items[1:]] == ["pending"] * 4
    assert len(items[1]["payload"]["proposals"]) == 1
    # Enqueue is idempotent per push.
    again = queue.enqueue_push(push)
    assert again["deduped"] is True
    assert len(queue.items(push["push_id"])) == 5


def test_card_overflow_is_logged_not_enqueued(kl_home):
    push = _push(kl_home)
    archive = Archive(kl_home)
    extra = archive.get_card("card_heme_biosynthesis")
    push["proposals"].append(
        {
            "schema_version": 2,
            "proposal_id": "p_overflow",
            "push_id": push["push_id"],
            "op": "add_card_ontology",
            "target_type": "card",
            "target_id": "card_heme_biosynthesis",
            "diff": {"op": "add", "path": "ontology", "value": "heme synthesis"},
            "before": extra["ontology"],
            "after": extra["ontology"] + ["heme synthesis"],
            "rationale": "A rationale long enough for the queue test.",
            "confidence": 0.5,
            "evidence": {
                "paper_id": "europepmc_42900001",
                "page": 1,
                "quote": "A quote long enough for evidence.",
            },
            "status": "draft",
        }
    )
    queue = _enqueue(kl_home, push)
    items = queue.items(push["push_id"])
    assert sum(1 for item in items if item["kind"] == "card_update") == 2
    events = [json.loads(line) for line in (kl_home / "queue" / "events.jsonl").read_text().splitlines()]
    assert any(event["kind"] == "overflow" and event["reason"] == "card_limit" for event in events)


def test_offline_replay_walks_rating_then_all_updates(kl_home):
    push = _push(kl_home)
    _enqueue(kl_home, push)
    sent = send_rating(kl_home, push, "ou_demo", dry_run=True)
    assert sent["kind"] == "rating"
    assert sent["item_id"].endswith("_rating")

    result = handle_event(kl_home, _event(sent["message_id"], "score_high"), offline=True)
    assert result["ok"] is True
    assert result["verdict"] == "great"
    assert _next_message_id(result)

    seen = 0
    while result.get("next_message_id"):
        seen += 1
        assert seen <= 4
        message_id = result["next_message_id"]
        result = handle_event(kl_home, _event(message_id, "agree_all"), offline=True)
        assert result["ok"] is True, result

    queue = QueueStore(kl_home)
    items = queue.items(push["push_id"])
    assert all(item["status"] == "answered" for item in items), [item["status"] for item in items]
    assert result["queue_empty"] is True
    assert seen == 4

    archive = Archive(kl_home)
    assert "PBG deaminase" in archive.get_card("card_hmbs")["ontology"]
    assert "新证据" in archive.get_card("card_aip")["annotation"]
    assert archive.get_prop("prop_hmbs_aip")["title"].endswith("（修订）")
    assert archive.get_prop("prop_hmbs_mitochondria")["related_knowledge"] == [
        "card_hmbs",
        "card_heme_biosynthesis",
    ]


def test_irrelevant_rating_drops_all_updates(kl_home):
    push = _push(kl_home)
    _enqueue(kl_home, push)
    sent = send_rating(kl_home, push, "ou_demo", dry_run=True)
    before = Archive(kl_home).get_card("card_hmbs")["ontology"]
    result = handle_event(kl_home, _event(sent["message_id"], "score_low"), offline=True)
    assert result["verdict"] == "irrelevant"
    assert result["queue_empty"] is True
    assert result["next_message_id"] is None
    queue = QueueStore(kl_home)
    kinds = {item["kind"]: item["status"] for item in queue.items(push["push_id"])}
    assert kinds["rating"] == "answered"
    assert all(kinds[k] == "dropped" for k in ("card_update", "proposition_update"))
    assert Archive(kl_home).get_card("card_hmbs")["ontology"] == before


def test_reject_all_keeps_archive_and_records_decision(kl_home):
    push = _push(kl_home)
    _enqueue(kl_home, push)
    sent = send_rating(kl_home, push, "ou_demo", dry_run=True)
    result = handle_event(kl_home, _event(sent["message_id"], "score_high"), offline=True)
    before = Archive(kl_home).get_card("card_hmbs")["ontology"]
    result = handle_event(kl_home, _event(result["next_message_id"], "reject_all"), offline=True)
    assert result["ok"] is True
    assert result["decision"] == "reject_all"
    assert Archive(kl_home).get_card("card_hmbs")["ontology"] == before
    decisions = [
        json.loads(line)
        for line in (kl_home / "publisher" / "decisions.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert decisions[-1]["decision"] == "reject_all"


def test_duplicate_callbacks_are_idempotent(kl_home):
    push = _push(kl_home)
    _enqueue(kl_home, push)
    sent = send_rating(kl_home, push, "ou_demo", dry_run=True)
    first = handle_event(kl_home, _event(sent["message_id"], "score_high"), offline=True)
    second = handle_event(kl_home, _event(sent["message_id"], "score_high"), offline=True)
    assert second["deduped"] is True
    assert second.get("next_message_id") is None
    ratings = (kl_home / "ratings.jsonl").read_text().strip().splitlines()
    assert len(ratings) == 1
    first_update = handle_event(
        kl_home, _event(first["next_message_id"], "agree_all"), offline=True
    )
    again = handle_event(
        kl_home, _event(first["next_message_id"], "agree_all"), offline=True
    )
    assert again["deduped"] is True
    assert first_update["ok"] is True


def test_failed_apply_rolls_back_and_blocks_queue(kl_home):
    archive = Archive(kl_home)
    card = archive.get_card("card_hmbs")
    evidence = {
        "paper_id": "europepmc_42900001",
        "page": 1,
        "quote": "A quote long enough for evidence.",
    }
    valid = {
        "schema_version": 2,
        "proposal_id": "p_group_01",
        "push_id": "group_test",
        "op": "add_card_ontology",
        "target_type": "card",
        "target_id": "card_hmbs",
        "diff": {"op": "add", "path": "ontology", "value": "should-not-persist"},
        "before": card["ontology"],
        "after": card["ontology"] + ["should-not-persist"],
        "rationale": "A rationale long enough for the queue test.",
        "confidence": 0.5,
        "evidence": evidence,
        "status": "draft",
    }
    invalid = {
        **valid,
        "proposal_id": "p_group_02",
        "op": "update_proposition_title",
        "target_type": "proposition",
        "target_id": "prop_does_not_exist",
        "diff": {"op": "replace", "path": "title", "value": "x"},
        "before": "old",
        "after": "x",
    }
    with pytest.raises(ArchiveError):
        archive.apply_group([valid, invalid], group_id="group_rollback")
    assert archive.get_card("card_hmbs")["ontology"] == card["ontology"]

    push = _push(kl_home)
    _enqueue(kl_home, push)
    sent = send_rating(kl_home, push, "ou_demo", dry_run=True)
    first = handle_event(kl_home, _event(sent["message_id"], "score_high"), offline=True)
    (kl_home / "archive" / "cards" / "card_aip.json").unlink()
    result = handle_event(
        kl_home, _event(first["next_message_id"], "agree_all"), offline=True
    )
    assert result["ok"] is True  # first card group (card_hmbs) succeeds
    second = handle_event(
        kl_home, _event(result["next_message_id"], "agree_all"), offline=True
    )
    assert second["ok"] is False
    assert second["reason"] == "apply_failed"
    queue = QueueStore(kl_home)
    assert queue.has_failed() is True
    assert queue.next_active() is None


def test_callback_action_value_routes_to_queue(kl_home):
    push = _push(kl_home)
    _enqueue(kl_home, push)
    sent = send_rating(kl_home, push, "ou_demo", dry_run=True)
    first = handle_event(kl_home, _event(sent["message_id"], "score_high"), offline=True)
    event = {
        "message_id": first["next_message_id"],
        "action_value": json.dumps(
            {
                "decision": "reject_all",
                "queue_item_id": first["item_id"] if first.get("item_id") else "",
                "proposal_ids": ["p_2026-10-21_card_hmbs_01_01"],
            }
        ),
        "operator_id": "ou_test",
        "token": "",
        "chat_id": "oc_test",
    }
    # action_value carries the decision; message_id still routes to the queue item.
    result = handle_event(kl_home, event, offline=True)
    assert result["ok"] is True
    assert result["decision"] == "reject_all"


def test_ndjson_replay_finishes_rating_and_four_updates(kl_home, tmp_path):
    push = _push(kl_home)
    _enqueue(kl_home, push)
    sent = send_rating(kl_home, push, "ou_demo", dry_run=True)
    prefix = "offline_q_2026_10_21_card_hmbs_01"
    events = [
        {"message_id": sent["message_id"], "action_name": "score_high", "operator_id": "ou_test"},
        {"message_id": f"{prefix}_card_card_hmbs", "action_name": "agree_all", "operator_id": "ou_test"},
        {"message_id": f"{prefix}_card_card_aip", "action_name": "agree_all", "operator_id": "ou_test"},
        {"message_id": f"{prefix}_prop_prop_hmbs_aip", "action_name": "agree_all", "operator_id": "ou_test"},
        {"message_id": f"{prefix}_prop_prop_hmbs_mitochondria", "action_name": "agree_all", "operator_id": "ou_test"},
    ]
    path = tmp_path / "events.ndjson"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    results = replay(kl_home, path, offline=True, identity="bot")
    assert len(results) == 5
    assert all(result["ok"] for result in results), results
    assert results[-1]["queue_empty"] is True
    queue = QueueStore(kl_home)
    assert not queue.has_unfinished()
    assert Archive(kl_home).get_prop("prop_hmbs_mitochondria")


def test_pending_request_coalesces_and_waits_for_empty_queue(kl_home):
    push = _push(kl_home)
    queue = _enqueue(kl_home, push)
    first = queue.request_push("manual", "card_hmbs")
    second = queue.request_push("scheduled")
    assert second["request"]["sources"] == ["manual", "scheduled"]
    assert second["request"]["count"] == 2
    assert second["request"]["card_id"] == "card_hmbs"
    assert queue.try_start()["reason"] == "queue_busy"

    # Empty the queue without driving every card through publisher.
    sent = send_rating(kl_home, push, "ou_demo", dry_run=True)
    result = handle_event(kl_home, _event(sent["message_id"], "score_low"), offline=True)
    assert result["queue_empty"] is True
    assert result["start"]["start"] is True
    assert queue.request_push("manual")["request"]["count"] == 3
    started = json.loads((kl_home / "queue" / "request.json").read_text())
    assert started["lease_until"]

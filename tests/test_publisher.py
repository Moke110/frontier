import json

from publisher.cards import build_approval_card, build_confirmation_card, build_rating_card
from publisher.service import handle_event, send_rating


PUSH = {
    "push_id": "2026-10-20_hmbs_01",
    "date": "2026-10-20",
    "checkpoint_id": "hmbs",
    "title": "HMBS：test",
    "body_md": "### HMBS\n\n**发现** something",
    "proposals": [
        {
            "proposal_id": "p1",
            "push_id": "2026-10-20_hmbs_01",
            "kind": "add_evidence",
            "target_id": "prop_hmbs_aip",
            "diff": {"op": "add", "path": "evidence", "value": {"note": "n"}},
            "rationale": "r",
            "confidence": 0.7,
        },
        {
            "proposal_id": "p2",
            "push_id": "2026-10-20_hmbs_01",
            "kind": "add_alias",
            "target_id": "kg_hmbs",
            "diff": {"op": "add", "path": "aliases", "value": "HMBS alias"},
            "rationale": "r",
            "confidence": 0.4,
        },
    ],
}


def _buttons(card):
    form = card["body"]["elements"][1]
    columns = form["elements"][1]["columns"]
    return [c["elements"][0] for c in columns]


def test_rating_card_has_three_submit_buttons_and_comment():
    card = build_rating_card(PUSH)
    assert card["schema"] == "2.0"
    form = card["body"]["elements"][1]
    assert form["tag"] == "form"
    assert form["elements"][0]["tag"] == "input"
    buttons = _buttons(card)
    assert [b["text"]["content"] for b in buttons] == ["不相关", "一般", "很好"]
    assert [b["name"] for b in buttons] == ["score_low", "score_mid", "score_high"]
    assert all(b["form_action_type"] == "submit" for b in buttons)


def test_confirmation_and_approval_cards():
    confirm = build_confirmation_card(PUSH, "great", "好看")
    assert confirm["header"]["title"]["content"] == "反馈已记录"
    approval = build_approval_card(PUSH, PUSH["proposals"])
    text = approval["body"]["elements"][0]["content"]
    assert "补一条证据" in text
    assert "增加别名" in text
    buttons = approval["body"]["elements"][1]["columns"]
    assert buttons[0]["elements"][0]["behaviors"][0]["value"]["decision"] == "approve"


def test_dry_run_then_rating_and_approval(kl_home, tmp_path):
    (kl_home / "archive" / "pushes").mkdir(parents=True, exist_ok=True)
    (kl_home / "archive" / "pushes" / f"{PUSH['push_id']}.json").write_text(
        json.dumps(PUSH, ensure_ascii=False), encoding="utf-8"
    )
    sent = send_rating(kl_home, PUSH, "ou_demo", dry_run=True)
    assert sent["message_id"] == f"offline_rating_{PUSH['push_id']}"

    rating = handle_event(
        kl_home,
        {
            "message_id": sent["message_id"],
            "action_name": "score_high",
            "form_value": json.dumps({"comment": "很好"}, ensure_ascii=False),
            "operator_id": "ou_demo",
            "token": "",
        },
        offline=True,
    )
    assert rating["verdict"] == "great"
    assert rating["approval_message_id"]
    ratings = (kl_home / "ratings.jsonl").read_text().strip().splitlines()
    assert json.loads(ratings[0])["comment"] == "很好"
    assert len(list((kl_home / "publisher" / "pending").glob("*.json"))) == 2

    approval = handle_event(
        kl_home,
        {
            "message_id": rating["approval_message_id"],
            "action_name": "approve",
            "form_value": "{}",
            "operator_id": "ou_demo",
            "token": "",
        },
        offline=True,
    )
    assert approval["decision"] == "approve"
    assert len(approval["proposal_ids"]) == 2
    decisions = (kl_home / "publisher" / "decisions.jsonl").read_text().strip().splitlines()
    assert len(decisions) == 2


def test_irrelevant_rating_skips_approval(kl_home):
    (kl_home / "archive" / "pushes").mkdir(parents=True, exist_ok=True)
    (kl_home / "archive" / "pushes" / f"{PUSH['push_id']}.json").write_text(
        json.dumps(PUSH, ensure_ascii=False), encoding="utf-8"
    )
    sent = send_rating(kl_home, PUSH, "ou_demo", dry_run=True)
    result = handle_event(
        kl_home,
        {
            "message_id": sent["message_id"],
            "action_name": "score_low",
            "form_value": "{}",
            "operator_id": "ou_demo",
            "token": "",
        },
        offline=True,
    )
    assert result["verdict"] == "irrelevant"
    assert "approval_message_id" not in result
    assert not list((kl_home / "publisher" / "pending").glob("*.json"))

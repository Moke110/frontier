import json

import pytest

from publisher.cards import build_approval_card, build_confirmation_card, build_rating_card
from publisher.service import handle_event, send_push, send_rating


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


PUSH_PDF = {
    "schema_version": 1,
    "format": "pdf",
    "push_id": "2026-10-20_hmbs_02",
    "date": "2026-10-20",
    "checkpoint_id": "hmbs",
    "title": "HMBS：长文 PDF",
    "paper_ids": ["europepmc_42900001"],
    "sections": {"takeaway": "一句话结论：HMBS 缺失影响血红素合成。"},
}


def _buttons(card):
    form = card["body"]["elements"][1]
    return [e for e in form["elements"] if e["tag"] == "button"]


def test_rating_card_has_three_submit_buttons_and_comment():
    card = build_rating_card(PUSH)
    assert card["schema"] == "2.0"
    form = card["body"]["elements"][1]
    assert form["tag"] == "form"
    assert form["elements"][0]["tag"] == "input"
    buttons = _buttons(card)
    assert [b["text"]["content"] for b in buttons] == [
        "质量差/不在关注领域",
        "质量一般",
        "质量优秀",
    ]
    assert [b["name"] for b in buttons] == ["score_low", "score_mid", "score_high"]
    assert all(b["form_action_type"] == "submit" for b in buttons)
    # 每行一个按钮：按钮直接排在 form 的纵向流里，不再用 column_set 并排
    assert [e["tag"] for e in form["elements"][1:]] == ["button", "button", "button"]


def test_confirmation_and_approval_cards():
    confirm = build_confirmation_card(PUSH, "great", "好看")
    assert confirm["header"]["title"]["content"] == "反馈已记录"
    approval = build_approval_card(PUSH, PUSH["proposals"])
    text = approval["body"]["elements"][0]["content"]
    assert "补一条证据" in text
    assert "增加别名" in text
    buttons = approval["body"]["elements"][1]["columns"]
    assert buttons[0]["elements"][0]["behaviors"][0]["value"]["decision"] == "approve"


def test_pdf_rating_card_uses_takeaway():
    card = build_rating_card(PUSH_PDF)
    body = card["body"]["elements"][0]["content"]
    assert "一句话结论" in body
    assert "长文 PDF 已单独发送" in body


def test_send_pdf_dry_run_sends_file_then_rating(kl_home, tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    result = send_push(kl_home, PUSH_PDF, pdf, "ou_demo", dry_run=True)
    assert result["ok"] is True
    assert result["pdf_message_id"] == f"offline_file_{PUSH_PDF['push_id']}"
    assert result["rating_message_id"] == "offline_q_2026_10_20_hmbs_02_rating"
    rows = [json.loads(x) for x in (kl_home / "publisher" / "messages.jsonl").read_text().splitlines()]
    assert [r["kind"] for r in rows] == ["push_file", "rating"]
    assert (kl_home / "publisher" / "outbox" / f"file_{PUSH_PDF['push_id']}.json").exists()


def test_send_pdf_rejects_duplicate_paper(kl_home, tmp_path):
    (kl_home / "archive" / "pushes").mkdir(parents=True, exist_ok=True)
    other = {**PUSH_PDF, "push_id": "2026-10-19_hmbs_01"}
    (kl_home / "archive" / "pushes" / f"{other['push_id']}.json").write_text(
        json.dumps(other, ensure_ascii=False), encoding="utf-8"
    )
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    result = send_push(kl_home, PUSH_PDF, pdf, "ou_demo", dry_run=True)
    assert result["ok"] is False
    assert result["reason"] == "duplicate_paper"
    assert result["existing_push_id"] == other["push_id"]


def test_dry_run_then_rating_without_approval(kl_home, tmp_path):
    (kl_home / "archive" / "pushes").mkdir(parents=True, exist_ok=True)
    (kl_home / "archive" / "pushes" / f"{PUSH['push_id']}.json").write_text(
        json.dumps(PUSH, ensure_ascii=False), encoding="utf-8"
    )
    sent = send_rating(kl_home, PUSH, "ou_demo", dry_run=True)
    assert sent["message_id"] == "offline_q_2026_10_20_hmbs_01_rating"

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
    assert "approval_message_id" not in rating
    ratings = (kl_home / "ratings.jsonl").read_text().strip().splitlines()
    assert json.loads(ratings[0])["comment"] == "很好"
    assert not list((kl_home / "publisher" / "pending").glob("*.json"))


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


def test_send_cli_exits_non_zero_on_duplicate(kl_home, tmp_path):
    from publisher.cli import main

    (kl_home / "archive" / "pushes").mkdir(parents=True, exist_ok=True)
    other = {**PUSH_PDF, "push_id": "2026-10-19_hmbs_01"}
    (kl_home / "archive" / "pushes" / f"{other['push_id']}.json").write_text(
        json.dumps(other, ensure_ascii=False), encoding="utf-8"
    )
    push_path = tmp_path / "push.json"
    push_path.write_text(json.dumps(PUSH_PDF, ensure_ascii=False), encoding="utf-8")
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")

    code = main(
        [
            "--home",
            str(kl_home),
            "send",
            "--push",
            str(push_path),
            "--pdf",
            str(pdf),
            "--to",
            "ou_demo",
            "--dry-run",
        ]
    )
    assert code == 1


def test_send_push_accepts_a_self_contained_html_file(kl_home, tmp_path):
    html_path = tmp_path / "2026-10-20_hmbs_02.html"
    html_path.write_text("<!doctype html><p>hello</p>", encoding="utf-8")
    push = {**PUSH_PDF, "push_id": "2026-10-20_hmbs_03", "paper_ids": ["p_html"]}
    result = send_push(kl_home, push, html_path, "ou_demo", dry_run=True)
    assert result["ok"] is True
    assert result["file_type"] == "html"
    assert result["html"].endswith(".html")
    assert result["html_message_id"].startswith("offline_file_")
    outbox = kl_home / "publisher" / "outbox"
    assert any(
        json.loads(path.read_text()).get("file_type") == "html"
        for path in outbox.glob("*.json")
    )


def test_library_alerts_are_delivered_as_copyable_text(kl_home):
    from publisher import alerts
    from common import read_json, write_json

    alert = {
        "schema_version": 1,
        "level": "warn",
        "used_bytes": 4 * 1024**3,
        "limit_bytes": 5 * 1024**3,
        "percent": 80.0,
        "candidates": {"count": 3, "bytes": 200 * 1024**2},
        "instruction": "清理 frontier 原文库：把 3 篇下载到 ~/frontier-offline/2026-10-26/。",
    }
    write_json(kl_home / "library" / "alerts" / "a1.json", alert)

    result = alerts.deliver(kl_home, "ou_owner", dry_run=True)
    assert result["ok"] is True
    assert result["count"] == 1
    assert alerts.alert_paths(kl_home)  # dry-run keeps the alert for a real send

    outbox = list((kl_home / "publisher" / "outbox").glob("alert_a1.json"))
    assert outbox
    text = read_json(outbox[0])["text"]
    assert "80.0%" in text
    assert "4.00 GB / 5.00 GB" in text
    assert "清理 frontier 原文库" in text


def test_put_push_is_skipped_without_library_config(kl_home, tmp_path):
    from publisher.service import _spawn_put_push

    html = tmp_path / "push.html"
    html.write_text("<html></html>", encoding="utf-8")
    assert _spawn_put_push(kl_home, {"push_id": "p1"}, html) == {
        "ok": True,
        "skipped": "no_config",
    }
    assert _spawn_put_push(kl_home, {"push_id": "p1"}, tmp_path / "p.pdf") == {
        "ok": True,
        "skipped": "legacy_pdf",
    }


# ------------------------------------------------- message read-back (recall)
class _Proc:
    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def _fake_api(monkeypatch, payload, *, returncode=0):
    from publisher import feishu

    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return _Proc(json.dumps(payload, ensure_ascii=False), returncode)

    monkeypatch.setattr(feishu.subprocess, "run", run)
    return calls


def test_get_message_reads_a_present_message_by_id(monkeypatch):
    from publisher import feishu

    calls = _fake_api(
        monkeypatch, {"ok": True, "data": {"items": [{"message_id": "om_1"}]}}
    )

    result = feishu.get_message("om_1", executable="C:/bin/lark-cli")

    assert result["present"] is True
    assert result["message_id"] == "om_1"
    assert calls[0][:4] == [
        "C:/bin/lark-cli",
        "api",
        "GET",
        "/open-apis/im/v1/messages/om_1",
    ]


def test_get_message_treats_a_recalled_message_as_gone(monkeypatch):
    from publisher import feishu

    _fake_api(
        monkeypatch,
        {"ok": True, "data": {"items": [{"message_id": "om_1", "deleted": True}]}},
    )

    assert feishu.get_message("om_1")["present"] is False


def test_get_message_treats_a_documented_not_found_as_gone(monkeypatch):
    from publisher import feishu

    _fake_api(
        monkeypatch,
        {"ok": False, "error": {"code": 230006, "msg": "message not found"}},
        returncode=1,
    )

    result = feishu.get_message("om_1")

    assert result["present"] is False
    assert result["message_id"] == "om_1"


def test_get_message_raises_when_the_read_cannot_prove_absence(monkeypatch):
    from publisher import feishu

    _fake_api(
        monkeypatch,
        {"ok": False, "error": {"code": 99991663, "msg": "permission denied"}},
        returncode=1,
    )

    with pytest.raises(feishu.FeishuError):
        feishu.get_message("om_1")


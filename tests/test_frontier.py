import json

import pytest

from frontier import model


def _write_temporary_card(home, card_id="card_smoke_20261029_deadbe"):
    card = {
        "id": card_id,
        "label": "[临时验收] single-cell perturbation prediction benchmark",
        "ontology": ["single-cell perturbation prediction benchmark"],
        "annotation": "⛔ 仅用于安装验收；⚠️ 清理时必须删除。",
    }
    path = home / "archive" / "cards" / f"{card_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    return card


def test_plan_reads_cards_not_frontier_yaml(kl_home):
    plan = model.plan(kl_home, day="2026-10-20", days=7)
    assert plan["window"] == {"start": "2026-10-14", "end": "2026-10-20"}
    by_id = {q["query_id"]: q for q in plan["queries"]}
    arxiv = by_id["q_card_hmbs_arxiv"]
    epmc = by_id["q_card_hmbs_europepmc"]
    assert 'abs:"HMBS"' in arxiv["query"]
    assert "submittedDate:[202610140000 TO 202610202359]" in arxiv["query"]
    assert "-" not in arxiv["query"].split("submittedDate:")[1]
    assert 'TITLE_ABS:"HMBS"' in epmc["query"]
    assert "FIRST_PDATE:[2026-10-14 TO 2026-10-20]" in epmc["query"]
    assert epmc["annotation"].startswith("血红素合成")
    assert epmc["card_id"] == "card_hmbs"

    # The retirement is real: retrieval no longer needs frontier.yaml.
    (kl_home / "frontier.yaml").unlink(missing_ok=True)
    assert model.plan(kl_home, day="2026-10-20", days=7)["queries"]


def test_plan_uses_only_formal_cards(kl_home):
    temporary = _write_temporary_card(kl_home)

    cards = model.load_cards(kl_home)
    card_ids = {card["id"] for card in cards}
    assert "card_hmbs" in card_ids
    assert temporary["id"] not in card_ids

    result = model.plan(kl_home, day="2026-10-20", days=7)
    assert result["queries"]
    assert {query["card_id"] for query in result["queries"]} <= card_ids
    assert all(query["card_id"] != temporary["id"] for query in result["queries"])
    assert all(temporary["ontology"][0] not in query["query"] for query in result["queries"])


def test_load_cards_rejects_an_archive_of_only_temporary_cards(tmp_path):
    home = tmp_path / "home"
    _write_temporary_card(home)

    with pytest.raises(model.FrontierError, match="no knowledge cards"):
        model.load_cards(home)


def test_validate_can_opt_in_to_temporary_cards(tmp_path):
    home = tmp_path / "home"
    card = _write_temporary_card(home)

    result = model.validate(home, include_temporary=True)
    assert result["ok"] is True
    assert [row["card_id"] for row in result["cards"]] == [card["id"]]

    # The formal command still treats the archive as empty.
    with pytest.raises(model.FrontierError, match="no knowledge cards"):
        model.validate(home)


def test_validate_detects_broken_card(kl_home):
    assert model.validate(kl_home)["ok"] is True
    path = kl_home / "archive" / "cards" / "card_hmbs.json"
    card = json.loads(path.read_text(encoding="utf-8"))
    card["annotation"] = ""
    path.write_text(json.dumps(card), encoding="utf-8")
    result = model.validate(kl_home)
    assert result["ok"] is False
    assert "annotation" in result["problems"][0]


def test_record_updates_ema_and_weight(kl_home):
    out = model.record(kl_home, "card_hmbs", "great", pushed=True)
    assert out["ema"] == 0.72
    assert out["weight"] == 7
    assert out["hit_rate"]["scored_total"] == 4
    assert out["hit_rate"]["pushed"] == 5

    after = model.record(kl_home, "card_hmbs", "irrelevant")
    assert after["ema"] < 0.72
    assert after["weight"] < 7

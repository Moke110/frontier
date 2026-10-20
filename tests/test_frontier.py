import json

from frontier import model


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

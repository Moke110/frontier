import json
from pathlib import Path

import pytest

from publisher.update_cards import build_update_card

SAMPLES = Path(__file__).resolve().parents[1] / "fixtures" / "update-cards"


def _load(name: str):
    push = json.loads((SAMPLES / "sample-push.json").read_text(encoding="utf-8"))
    item = json.loads((SAMPLES / f"{name}.item.json").read_text(encoding="utf-8"))
    index, total = item.pop("_index"), item.pop("_total")
    card = build_update_card(push, item, index, total)
    return index, total, card


def _buttons(card):
    column_set = next(e for e in card["body"]["elements"] if e["tag"] == "column_set")
    return [column["elements"][0] for column in column_set["columns"]]


def _markdown(card):
    return "\n".join(e["content"] for e in card["body"]["elements"] if e["tag"] == "markdown")


def test_every_sample_has_two_buttons_and_one_entity():
    for name in ("card-update", "proposition-update", "create-proposition"):
        index, total, card = _load(name)
        assert card["schema"] == "2.0"
        assert f"第 {index} / {total} 题" in card["header"]["title"]["content"]
        buttons = _buttons(card)
        assert [b["text"]["content"] for b in buttons] == ["同意全部", "拒绝全部"]
        assert [b["name"] for b in buttons] == ["agree_all", "reject_all"]
        for button in buttons:
            value = button["behaviors"][0]["value"]
            assert value["proposal_ids"]
            assert value["queue_item_id"]
        # One entity per card: the subtitle references at most one target id.
        assert card["header"]["subtitle"]["content"].count("`") <= 2


def test_card_update_shows_ontology_and_line_level_annotation_diff():
    _, _, card = _load("card-update")
    text = _markdown(card)
    assert "知识卡片 `card_hmbs`" in card["header"]["subtitle"]["content"]
    assert "PBG deaminase" in text
    assert "+ 📌 新证据" in text
    assert "第 3 页" in text
    assert "答完这一题才会发下一题" in text


def test_proposition_update_shows_page_and_does_not_repeat_evidence():
    _, _, card = _load("proposition-update")
    text = _markdown(card)
    assert "命题 `prop_hmbs_aip`" in card["header"]["subtitle"]["content"]
    assert "改写命题标题" in text
    assert "改写命题内容" in text
    assert "补充证据" in text
    assert "第 6 页" in text
    quote = "We show that HMBS loss increases delta-aminolevulinic acid"
    assert text.count(quote) == 1
    assert "第 3 页" in text


def test_create_proposition_shows_related_knowledge():
    _, _, card = _load("create-proposition")
    text = _markdown(card)
    assert card["header"]["subtitle"]["content"].startswith("新建命题")
    assert "card_hmbs" in text
    assert "card_heme_biosynthesis" in text
    assert "card_aip" in text


def test_empty_item_is_rejected():
    with pytest.raises(ValueError):
        build_update_card(
            {"push_id": "p", "paper_ids": []}, {"kind": "card_update"}, 1, 2
        )


def test_flat_item_shape_is_accepted():
    push = {
        "push_id": "p",
        "paper_ids": ["paper_1"],
        "paper": {"title": "A paper"},
    }
    item = {
        "kind": "card_update",
        "id": "q_demo",
        "target_type": "card",
        "target_id": "card_demo",
        "proposals": [
            {
                "proposal_id": "p_demo_01",
                "op": "add_card_ontology",
                "diff": {"op": "add", "path": "ontology", "value": "demo term"},
                "before": ["demo"],
                "after": ["demo", "demo term"],
                "rationale": "demo rationale",
                "confidence": 0.5,
                "evidence": {"paper_id": "paper_1", "page": None, "quote": "A quote from the abstract."},
            }
        ],
    }
    card = build_update_card(push, item, 2, 3)
    assert "第 2 / 3 题" in card["header"]["title"]["content"]
    assert "摘要" in _markdown(card)
    assert _buttons(card)[0]["behaviors"][0]["value"]["queue_item_id"] == "q_demo"

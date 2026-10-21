import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
THEMES = ROOT / "fixtures" / "theme-inventory.jsonl"
SAMPLE = ROOT / "drafts" / "initial-build" / "evaluation-credibility"


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_theme_inventory_covers_every_paper_once():
    themes = _rows(THEMES)
    assert len(themes) == 11
    assert sum(row["paper_count"] for row in themes) == 174
    paper_ids = [paper["paper_id"] for row in themes for paper in row["papers"]]
    assert len(paper_ids) == 174
    assert len(set(paper_ids)) == 174
    for row in themes:
        assert row["proposed_cards"]
        assert row["proposed_propositions"] >= 1
        assert row["evidence_strength"] in {"strong", "medium", "weak"}
        assert row["paper_count"] == len(row["papers"])


def test_sample_cards_follow_the_card_contract():
    cards = _rows(SAMPLE / "cards.jsonl")
    assert 2 <= len(cards) <= 5
    ids = {card["id"] for card in cards}
    assert len(ids) == len(cards)
    for card in cards:
        assert card["schema_version"] == 2
        assert card["id"].startswith("card_")
        assert card["label"]
        assert len(card["ontology"]) >= 3
        assert "⛔" in card["annotation"] and "⚠️" in card["annotation"]


def test_sample_propositions_link_cards_and_have_verified_evidence():
    cards = {card["id"] for card in _rows(SAMPLE / "cards.jsonl")}
    sources = {row["paper_id"]: row for row in _rows(SAMPLE / "sources.jsonl")}
    props = _rows(SAMPLE / "propositions.jsonl")
    assert 3 <= len(props) <= 5
    for prop in props:
        assert prop["schema_version"] == 2
        assert prop["id"].startswith("prop_")
        assert len(set(prop["related_knowledge"])) >= 2
        assert set(prop["related_knowledge"]) <= cards
        assert prop["history"]
        entry = prop["history"][0]
        assert entry["action"] == "created"
        assert entry["source"]["kind"] == "initial-build-draft"
        assert len(entry["evidence"]) >= 2
        for evidence in entry["evidence"]:
            assert evidence["paper_id"] in sources
            assert isinstance(evidence["page"], int) and evidence["page"] >= 1
            assert 8 <= len(evidence["quote"]) <= 500


def test_sample_evidence_quotes_match_pdf_pages():
    pytest.importorskip("fitz")
    import fitz

    sources = {row["paper_id"]: row for row in _rows(SAMPLE / "sources.jsonl")}
    for prop in _rows(SAMPLE / "propositions.jsonl"):
        for entry in prop["history"]:
            for evidence in entry["evidence"]:
                pdf = Path(os.path.expanduser(sources[evidence["paper_id"]]["pdf_path"]))
                if not pdf.exists():
                    pytest.skip(f"PDF not available: {pdf}")
                doc = fitz.open(pdf)
                try:
                    text = " ".join(doc[evidence["page"] - 1].get_text().split())
                finally:
                    doc.close()
                assert " ".join(evidence["quote"].split()) in text, (
                    prop["id"],
                    evidence["paper_id"],
                    evidence["page"],
                )


def test_sample_is_draft_only():
    assert not (SAMPLE / "archive").exists()
    assert not (SAMPLE / ".." / ".." / "archive").resolve().is_relative_to(SAMPLE)

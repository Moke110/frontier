import json
from pathlib import Path

import fitz

from archive.store import Archive
from initial_build import build as initial_build
from pdf_ingest import ingest as pdf_ingest


ROOT = Path(__file__).resolve().parents[1]
APPROVED_DRAFT = ROOT / "drafts" / "initial-build" / "evaluation-credibility"


def _make_pdf(path: Path, pages: list[str]) -> None:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=10)
    doc.save(path)
    doc.close()


def _paper(tmp_path: Path, name: str, doi: str, pages: list[str]) -> Path:
    pdf = tmp_path / f"{name}.pdf"
    _make_pdf(pdf, pages)
    return pdf


def _manifest_row(pdf: Path, doi: str) -> dict:
    return {
        "path": str(pdf),
        "category": "method",
        "title": f"Test paper {pdf.stem}",
        "year": 2026,
        "doi": doi,
        "pmid": "",
        "pmcid": "",
        "journal": "Test Journal",
        "pages": 1,
        "text_status": "text_ok",
        "doi_status": "verified",
        "arxiv": "",
        "md5": "",
        "size_bytes": pdf.stat().st_size,
        "notes": "",
    }


def _write_draft(
    tmp_path: Path,
    *,
    quote: str = "The treatment changes the outcome",
    evidence_papers: int = 2,
    related_cards: list[str] | None = None,
) -> Path:
    draft = tmp_path / "draft"
    draft.mkdir()
    cards = [
        {
            "schema_version": 2,
            "id": "card_topic",
            "label": "Topic",
            "ontology": ["topic", "主题", "topic modelling"],
            "annotation": "A topic.\n⛔ not that.\n⚠️ not this.",
        },
        {
            "schema_version": 2,
            "id": "card_other",
            "label": "Other",
            "ontology": ["other", "其他", "other concept"],
            "annotation": "Another topic.\n⛔ not that.\n⚠️ not this.",
        },
    ]
    evidence = [
        {
            "paper_id": f"pdf_2026_doe_{name}",
            "page": 1,
            "quote": quote,
            "pdf_path": f"~/papers/{name}.pdf",
        }
        for name in ("one", "two")[:evidence_papers]
    ]
    prop = {
        "schema_version": 2,
        "id": "prop_topic_claim",
        "title": "Topic claim",
        "content": "A synthetic cross-paper claim.",
        "related_knowledge": related_cards or ["card_topic", "card_other"],
        "history": [
            {
                "at": "2026-10-21T11:00:00+08:00",
                "action": "created",
                "source": {"kind": "initial-build-draft", "id": "theme:test"},
                "before": None,
                "after": {
                    "title": "Topic claim",
                    "content": "A synthetic cross-paper claim.",
                    "related_knowledge": related_cards or ["card_topic", "card_other"],
                },
                "rationale": "Synthetic test evidence.",
                "evidence": evidence,
            }
        ],
    }
    for name, rows in (("cards.jsonl", cards), ("propositions.jsonl", [prop]), ("sources.jsonl", [])):
        (draft / name).write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )
    return draft


def _seed_papers(kl_home: Path, tmp_path: Path) -> None:
    pdfs = [
        _paper(tmp_path, "2026_Doe_one", "10.1000/one", ["The treatment changes the outcome."]),
        _paper(tmp_path, "2026_Doe_two", "10.1000/two", ["The treatment changes the outcome."]),
    ]
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "\n".join(json.dumps(_manifest_row(p, f"10.1000/{p.stem[-3:]}")) for p in pdfs)
        + "\n",
        encoding="utf-8",
    )
    report = pdf_ingest.run(kl_home, manifest)
    assert report["counts"]["ingested"] == 2


def test_apply_writes_cards_propositions_and_report(kl_home, tmp_path):
    _seed_papers(kl_home, tmp_path)
    draft = _write_draft(tmp_path)

    report = initial_build.apply(kl_home, draft)

    assert report["counts"]["cards"]["created"] == 2
    assert report["counts"]["propositions"]["created"] == 1
    assert report["counts"]["evidence"] == {"checked": 2, "located": 2}
    store = Archive(kl_home)
    assert store.get_card("card_topic")["label"] == "Topic"
    prop = store.get_prop("prop_topic_claim")
    assert prop["related_knowledge"] == ["card_topic", "card_other"]
    assert len(prop["evidence"]) == 1
    assert len(prop["evidence"][0]["papers"]) == 2
    assert report["report_path"]
    assert Path(report["report_path"]).exists()


def test_apply_is_idempotent(kl_home, tmp_path):
    _seed_papers(kl_home, tmp_path)
    draft = _write_draft(tmp_path)

    initial_build.apply(kl_home, draft)
    second = initial_build.apply(kl_home, draft)

    assert second["counts"]["cards"] == {"created": 0, "updated": 0, "skipped": 2}
    assert second["counts"]["propositions"] == {
        "created": 0,
        "updated": 0,
        "skipped": 1,
        "held": 0,
    }
    assert len(list((kl_home / "archive" / "cards").glob("card_topic*.json"))) == 1
    assert len(list((kl_home / "archive" / "cards").glob("card_other*.json"))) == 1
    assert len(list((kl_home / "archive" / "propositions").glob("prop_topic*.json"))) == 1


def test_unlocatable_quote_blocks_the_whole_batch(kl_home, tmp_path):
    _seed_papers(kl_home, tmp_path)
    draft = _write_draft(tmp_path, quote="a quote that is not in the paper")

    report = initial_build.apply(kl_home, draft)

    assert report["ok"] is False
    assert report["failures"]
    assert not list((kl_home / "archive" / "cards").glob("card_topic*.json"))
    assert not list((kl_home / "archive" / "propositions").glob("prop_topic*.json"))


def test_single_paper_proposition_is_held_not_written(kl_home, tmp_path):
    _seed_papers(kl_home, tmp_path)
    draft = _write_draft(tmp_path, evidence_papers=1)

    report = initial_build.apply(kl_home, draft)

    assert report["ok"] is True
    assert report["held"][0]["id"] == "prop_topic_claim"
    assert "2 independent papers" in report["held"][0]["reason"]
    assert report["counts"]["cards"]["created"] == 2
    assert report["counts"]["propositions"] == {
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "held": 1,
    }
    assert not list((kl_home / "archive" / "propositions").glob("prop_topic*.json"))


def test_approved_draft_passes_structural_validation():
    draft = initial_build.load_draft(APPROVED_DRAFT)
    assert initial_build.validate_structure(draft) == []
    assert len(draft["cards"]) == 5
    assert len(draft["propositions"]) == 5
    held = [
        prop["id"] for prop in draft["propositions"] if initial_build.hold_reasons(prop)
    ]
    assert held == ["prop_systematic_variation_inflates_scores"]


def test_dry_run_writes_nothing(kl_home, tmp_path):
    _seed_papers(kl_home, tmp_path)
    draft = _write_draft(tmp_path)

    report = initial_build.apply(kl_home, draft, dry_run=True)

    assert report["counts"]["cards"]["planned"] == 2
    assert not list((kl_home / "archive" / "cards").glob("card_topic*.json"))
    assert report["report_path"] is None

import json
from pathlib import Path

import fitz

from archive.store import Archive
from pdf_ingest import ingest as pdf_ingest
from pdf_ingest.anchors import locate_quote


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "fixtures" / "pdf-manifest.jsonl"
THEMES = ROOT / "fixtures" / "theme-inventory.jsonl"


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _make_pdf(path: Path, pages: list[str]) -> None:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=10)
    doc.save(path)
    doc.close()


def _manifest_row(pdf: Path, **overrides) -> dict:
    row = {
        "path": str(pdf),
        "category": "method",
        "title": f"Test paper {pdf.stem}",
        "year": 2026,
        "doi": "10.1000/test.1",
        "pmid": "",
        "pmcid": "",
        "journal": "Test Journal",
        "pages": 2,
        "text_status": "text_ok",
        "doi_status": "verified",
        "arxiv": "",
        "md5": "",
        "size_bytes": pdf.stat().st_size if pdf.exists() else 0,
        "notes": "",
    }
    row.update(overrides)
    return row


def test_paper_ids_match_the_approved_theme_inventory():
    manifest_ids = {
        pdf_ingest.paper_id_for(row["path"]) for row in _rows(MANIFEST)
    }
    theme_ids = {
        paper["paper_id"] for row in _rows(THEMES) for paper in row["papers"]
    }
    assert len(manifest_ids) == 174
    assert manifest_ids == theme_ids


def test_locate_quote_ignores_pdf_line_breaks():
    text, anchors = pdf_ingest.build_text_and_anchors(
        ["before\nfirst half of a claim\nand its second half", "other page"]
    )
    located = locate_quote(text, anchors, 1, "first half of a claim and its second half")
    assert located == {"page": 1, "start": anchors[0]["start"], "end": anchors[0]["end"]}
    assert locate_quote(text, anchors, 2, "first half of a claim") is None


def test_source_id_prefers_doi_then_pmid_then_arxiv_then_md5():
    rows = _rows(MANIFEST)
    by_stem = {Path(row["path"]).stem: row for row in rows}

    assert (
        pdf_ingest.source_id_for(by_stem["2024_Jiang_scPRAM"])
        == "10.1093/bioinformatics/btae265"
    )
    assert pdf_ingest.source_id_for(by_stem["2026_Zhang_Stable-Shift"]) == (
        "arxiv:2606.24940v1"
    )
    assert pdf_ingest.source_id_for(by_stem["2025_Jin_CrossDomain"]) == (
        "md5:fe5e676fb56a16ad2e32c9105f5a5bc6"
    )
    assert pdf_ingest.source_id_for(by_stem["2022_App_DeepCE_Ibudilast_09"]) == (
        "10.1093/brain/awac136"
    )


def test_ingest_writes_metadata_text_and_page_anchors(kl_home, tmp_path):
    pdf = tmp_path / "2026_Doe_TestPaper.pdf"
    _make_pdf(
        pdf,
        [
            "Abstract: first page claims a strong effect.",
            "Results: the second page repeats the claim with a number.",
        ],
    )
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(_manifest_row(pdf, doi="10.1000/TEST.1")) + "\n", encoding="utf-8"
    )

    report = pdf_ingest.run(kl_home, manifest)

    assert report["counts"]["ingested"] == 1
    paper_id = "pdf_2026_doe_testpaper"
    raw = Archive(kl_home).get_paper(paper_id)
    assert raw["source"] == "pdf"
    assert raw["source_id"] == "10.1000/test.1"
    assert raw["title"] == "Test paper 2026_Doe_TestPaper"
    assert raw["doi"] == "10.1000/test.1"
    assert raw["pages"] == 2

    text = (kl_home / "archive" / "raw" / "text" / f"{paper_id}.txt").read_text()
    sidecar = json.loads(
        (kl_home / "archive" / "raw" / "pages" / f"{paper_id}.json").read_text()
    )
    assert sidecar["paper_id"] == paper_id
    assert len(sidecar["page_anchors"]) == 2
    assert "first page claims" in text
    page_two = sidecar["page_anchors"][1]
    assert page_two["page"] == 2
    assert "second page repeats" in text[page_two["start"] : page_two["end"]]
    assert "first page claims" not in text[page_two["start"] : page_two["end"]]

    located = locate_quote(text, sidecar["page_anchors"], 2, "second page repeats")
    assert located == {
        "page": 2,
        "start": page_two["start"],
        "end": page_two["end"],
    }
    assert locate_quote(text, sidecar["page_anchors"], 1, "second page repeats") is None

    reports = list((kl_home / "archive" / "reports").glob("pdf-ingest-*.json"))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text())["counts"]["ingested"] == 1


def test_rerun_is_idempotent_and_repairs_missing_text(kl_home, tmp_path):
    pdf = tmp_path / "2026_Roe_Repair.pdf"
    _make_pdf(pdf, ["Page one body.", "Page two body."])
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(_manifest_row(pdf, doi="10.1000/repair.1")) + "\n", encoding="utf-8"
    )

    pdf_ingest.run(kl_home, manifest)
    second = pdf_ingest.run(kl_home, manifest)
    assert second["counts"]["skipped"] == 1
    assert second["counts"]["ingested"] == 0
    assert len(list((kl_home / "archive" / "raw").glob("*.json"))) == 1

    text_path = kl_home / "archive" / "raw" / "text" / "pdf_2026_roe_repair.txt"
    text_path.write_text("", encoding="utf-8")
    third = pdf_ingest.run(kl_home, manifest)
    assert third["counts"]["repaired"] == 1
    assert "Page one body" in text_path.read_text()
    assert len(list((kl_home / "archive" / "raw").glob("*.json"))) == 1


def test_missing_pdf_is_reported_and_other_rows_still_ingest(kl_home, tmp_path):
    good = tmp_path / "2026_Lee_Good.pdf"
    _make_pdf(good, ["Only page."])
    missing = tmp_path / "2026_Lee_Missing.pdf"
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "\n".join(
            [
                json.dumps(_manifest_row(good, doi="10.1000/good.1")),
                json.dumps(_manifest_row(missing, doi="10.1000/missing.1")),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = pdf_ingest.run(kl_home, manifest)
    assert report["counts"]["ingested"] == 1
    assert report["counts"]["failed"] == 1
    assert report["failures"][0]["path"] == str(missing)
    assert "missing" in report["failures"][0]["reason"]


def test_dry_run_writes_nothing(kl_home, tmp_path):
    pdf = tmp_path / "2026_Poe_Dry.pdf"
    _make_pdf(pdf, ["Dry run page."])
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps(_manifest_row(pdf)) + "\n", encoding="utf-8")

    report = pdf_ingest.run(kl_home, manifest, dry_run=True)
    assert report["counts"]["planned"] == 1
    assert not list((kl_home / "archive" / "raw").glob("*.json"))
    assert not list((kl_home / "archive" / "reports").glob("*.json"))


def test_limit_only_processes_the_requested_prefix(kl_home, tmp_path):
    rows = []
    for name in ("2026_A_First", "2026_B_Second"):
        pdf = tmp_path / f"{name}.pdf"
        _make_pdf(pdf, ["Body."])
        rows.append(_manifest_row(pdf, doi=f"10.1000/{name.lower()}"))
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    report = pdf_ingest.run(kl_home, manifest, limit=1)
    assert report["counts"]["total"] == 1
    assert report["counts"]["ingested"] == 1
    assert len(list((kl_home / "archive" / "raw").glob("*.json"))) == 1

import importlib.util
import json
from pathlib import Path

import pytest

from writer.figures import fetch_for_paper
from writer.render import inspect, render_push
from writer.tasks import validate as validate_outbox


def _push(push_dir: Path, *, body: str | None = None, asset_source: str = "paper") -> Path:
    push_id = "2026-10-20_hmbs_01"
    asset_dir = push_dir / "assets" / push_id
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "fig-1.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200">'
        '<rect width="400" height="200" fill="#0f4c5c"/></svg>',
        encoding="utf-8",
    )
    push = {
        "schema_version": 1,
        "format": "pdf",
        "push_id": push_id,
        "date": "2026-10-20",
        "checkpoint_id": "hmbs",
        "checkpoint_label": "HMBS / 羟甲基胆素合酶",
        "paper_ids": ["europepmc_1"],
        "paper": {
            "paper_id": "europepmc_1",
            "source": "europepmc",
            "title": "A test paper",
            "authors": ["Alice", "Bob"],
            "journal": "Journal of Tests",
            "published": "2026-10-16",
            "url": "https://example.org/paper",
            "is_preprint": False,
        },
        "title": "HMBS：一篇用于渲染测试的论文",
        "sections": {
            "takeaway": "一句话结论。",
            "background": "背景。",
            "methods": "方法。",
            "results": "结果。",
            "why": "与知识卡的关系。",
            "limits": "局限。",
            "sources": "原文：https://example.org/paper",
        },
        "body_html": body
        if body is not None
        else '<h2>背景</h2><p>正文。</p><figure data-asset="fig-1"></figure><h2>结果</h2><p>结果。</p>',
        "assets": [
            {
                "id": "fig-1",
                "path": f"assets/{push_id}/fig-1.svg",
                "caption": "图 1. 测试图。",
                "source": asset_source,
                "origin_url": "https://example.org/figure",
            }
        ],
        "proposals": [],
        "status": "written",
        "created_at": "2026-10-20T10:00:00+08:00",
    }
    path = push_dir / f"{push_id}.json"
    path.write_text(json.dumps(push, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_pdf_push_inspect_accepts_complete_push(tmp_path):
    path = _push(tmp_path)
    push = json.loads(path.read_text())
    assert inspect(push, tmp_path) == []


def test_pdf_push_rejects_missing_figure_and_bad_asset(tmp_path):
    path = _push(tmp_path, body="<h2>背景</h2><p>没有图。</p>")
    push = json.loads(path.read_text())
    errors = inspect(push, tmp_path)
    assert any("at least one" in e for e in errors)

    path = _push(tmp_path)
    push = json.loads(path.read_text())
    push["assets"][0]["path"] = "../outside.png"
    errors = inspect(push, tmp_path)
    assert any("inside the outbox" in e for e in errors)

    path = _push(tmp_path, asset_source="generated")
    push = json.loads(path.read_text())
    assert inspect(push, tmp_path) == []


def test_pdf_push_rejects_script(tmp_path):
    path = _push(tmp_path, body='<p>x</p><script>alert(1)</script><figure data-asset="fig-1"></figure>')
    push = json.loads(path.read_text())
    errors = inspect(push, tmp_path)
    assert any("forbidden tag" in e for e in errors)


HAS_WEASYPRINT = importlib.util.find_spec("weasyprint") is not None


@pytest.mark.skipif(
    not HAS_WEASYPRINT,
    reason="legacy PDF rendering needs WeasyPrint (optional; the push format is HTML)",
)
def test_render_produces_pdf(tmp_path):
    path = _push(tmp_path)
    result = render_push(path)
    assert result["ok"] is True
    pdf = Path(result["pdf"])
    assert pdf.exists()
    assert pdf.read_bytes().startswith(b"%PDF")
    assert result["pages"] >= 1
    assert result["figures"] == 1


def test_pdf_push_passes_writer_task_validation(tmp_path):
    outbox = tmp_path / "outbox"
    push_dir = outbox / "pushes"
    push_dir.mkdir(parents=True)
    _push(push_dir)
    task = {
        "schema_version": 1,
        "kind": "writer-task",
        "format": "pdf",
        "date": "2026-10-20",
        "items": [{"paper": {"paper_id": "europepmc_1"}}],
    }
    result = validate_outbox(task, outbox)
    assert result["ok"] is True, result["errors"]


def test_figures_falls_back_to_generated_svg(tmp_path):
    paper = {
        "paper_id": "fixture_1",
        "source": "fixture",
        "source_id": "1",
        "title": "无网络时也要有图",
        "journal": "Fixture",
        "published": "2026-10-16",
    }
    assets = fetch_for_paper(paper, "2026-10-20_hmbs_01", tmp_path)
    assert len(assets) == 1
    assert assets[0]["source"] == "generated"
    assert (tmp_path / assets[0]["path"]).exists()
    assert "<svg" in (tmp_path / assets[0]["path"]).read_text()


def test_render_produces_standalone_responsive_html(tmp_path):
    path = _push(tmp_path)
    out = tmp_path / "push.html"
    result = render_push(path, out)
    text = out.read_text(encoding="utf-8")
    assert result["ok"] is True
    assert result["html"] == str(out)
    assert "data:image/svg+xml;base64," in text
    assert "file://" not in text
    assert "clamp(16px, 1.1vw + 12px, 20px)" in text
    assert "prefers-color-scheme: dark" in text


def test_render_cli_defaults_to_self_contained_html(tmp_path):
    from writer.cli import main

    path = _push(tmp_path)
    assert main(["render", "--push", str(path)]) == 0
    out = path.with_suffix(".html")
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert 'src="http' not in text
    assert "<link" not in text
    assert "data:image/svg+xml;base64," in text


def test_render_html_is_byte_stable(tmp_path):
    path = _push(tmp_path)
    first = tmp_path / "a.html"
    second = tmp_path / "b.html"
    render_push(path, first, fmt="html")
    render_push(path, second, fmt="html")
    assert first.read_bytes() == second.read_bytes()

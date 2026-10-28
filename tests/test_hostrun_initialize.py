"""Formal initialization: gates, inputs, confirmation, Base write and retrieval."""

import json
from pathlib import Path

import pytest

from hostrun import cleanup, facilities, initialize, kb
from hostrun.base import HostRunError
from library.drive import FixtureDrive
from library.offline import JsonBase


def _fresh_base(tmp_path) -> JsonBase:
    base = JsonBase(tmp_path / "home" / "library" / "offline-base.json")
    base.meta = []
    base.fields = {}
    base.tables = {}
    return base


class Admin:
    def __init__(self, base):
        self.base = base

    def resolve_title(self, title):
        return {"matches": [], "count": 0}

    def create_base(self, name, *, table_name, fields):
        table_id = self.base.create_table(table_name, fields)
        return {
            "base_token": "basoffline",
            "table_id": table_id,
            "url": "https://example.feishu.cn/base/basoffline",
            "name": name,
        }


def _home(tmp_path, *, gate=True):
    home = tmp_path / "home"
    home.mkdir()
    base = _fresh_base(tmp_path)
    drive = FixtureDrive()
    facilities.create(home, confirmed=True, admin=Admin(base), client=base, drive=drive)
    if gate:
        (home / "install").mkdir(parents=True, exist_ok=True)
        (home / "install" / "smoke.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "test_id": "smoke_test",
                    "test_status": "complete",
                    "status": "cleaned",
                    "created_at": "2026-10-27T10:00:00+08:00",
                    "cleaned_at": "2026-10-27T10:30:00+08:00",
                }
            ),
            encoding="utf-8",
        )
    return home, base, drive


def _card(card_id="card_virtual_cell", label="虚拟细胞"):
    return {
        "id": card_id,
        "label": label,
        "ontology": ["virtual cell", "虚拟细胞", "in silico"],
        "annotation": "⛔ 不是数字孪生；⚠️ 与类器官混淆。",
    }


def _intake(home, tmp_path, *, text="虚拟细胞研究笔记，包含可读的全文内容。"):
    """A real intake: one readable text file plus non-empty requirements."""
    path = tmp_path / "notes.txt"
    path.write_text(text, encoding="utf-8")
    return initialize.intake(
        home, texts=[str(path)], requirements="关注虚拟细胞与类器官的边界"
    )


def test_intake_text_index_and_gaps(tmp_path, monkeypatch):
    home, base, _ = _home(tmp_path)
    text = tmp_path / "notes.txt"
    text.write_text("虚拟细胞研究笔记", encoding="utf-8")
    index = tmp_path / "index.json"
    index.write_text(
        json.dumps([{"title": "A paper", "doi": "10.1/x"}]), encoding="utf-8"
    )
    missing = tmp_path / "missing.pdf"

    result = initialize.intake(
        home,
        texts=[str(text)],
        indexes=[str(index)],
        pdfs=[str(missing)],
        requirements="关注虚拟细胞与类器官的边界",
    )

    assert result["ok"] is True
    assert result["readable"] == 2
    assert any(gap["path"] == str(missing) for gap in result["gaps"])
    record = json.loads((home / "install" / "initial" / "literature.json").read_text(encoding="utf-8"))
    assert record["requirements"] == "关注虚拟细胞与类器官的边界"
    assert any(row["kind"] == "index" and row["entry_count"] == 1 for row in record["records"])


def test_unreadable_pdf_is_reported_not_invented(tmp_path, monkeypatch):
    home, base, _ = _home(tmp_path)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(
        initialize,
        "_extract_pdf",
        lambda path: {"readable": False, "reason": "PDF 提取器不可用：no fitz", "pages": 0, "chars": 0},
    )

    result = initialize.intake(
        home, pdfs=[str(pdf)], requirements="virtual cell"
    )

    assert result["fulltext"] == 0
    assert result["gaps"][0]["reason"].startswith("PDF 提取器不可用")


def test_readable_pdf_text_is_cached_for_the_agent(tmp_path, monkeypatch):
    home, base, _ = _home(tmp_path)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(
        initialize,
        "_extract_pdf",
        lambda path: {"readable": True, "pages": 2, "chars": 12, "text": "虚拟细胞正文"},
    )

    result = initialize.intake(home, pdfs=[str(pdf)], requirements="virtual cell")

    assert result["fulltext"] == 1
    entry = result["records"][0]
    assert Path(entry["text_path"]).read_text(encoding="utf-8") == "虚拟细胞正文"
    assert entry["pages"] == 2


def test_propose_rejects_cards_that_violate_the_model(tmp_path):
    home, base, _ = _home(tmp_path)
    _intake(home, tmp_path)
    bad = {"id": "nope", "label": "", "ontology": [], "annotation": ""}

    result = initialize.propose(home, [bad], client=base)

    assert result["ok"] is False
    assert result["reason"] == "invalid_cards"


def test_apply_requires_test_and_cleanup_gate(tmp_path):
    home, base, _ = _home(tmp_path, gate=False)
    (home / "install").mkdir(parents=True, exist_ok=True)
    _intake(home, tmp_path)

    initialize.propose(home, [_card()], client=base)
    initialize.confirm(home, confirmed_by_user=True)

    with pytest.raises(HostRunError):
        initialize.apply_draft(home, client=base)


def test_apply_requires_confirmation_of_the_current_draft(tmp_path):
    home, base, _ = _home(tmp_path)
    _intake(home, tmp_path)
    initialize.propose(home, [_card()], client=base)

    result = initialize.apply_draft(home, client=base)

    assert result["ok"] is False
    assert result["reason"] == "needs_user_confirmation"

    initialize.confirm(home, confirmed_by_user=True)
    initialize.propose(home, [_card(label="改名后的卡片")], client=base)

    stale = initialize.apply_draft(home, client=base)
    assert stale["ok"] is False
    assert stale["reason"] == "needs_user_confirmation"


def test_confirmed_cards_are_written_to_base_and_retrieval_runs(tmp_path):
    home, base, _ = _home(tmp_path)
    _intake(home, tmp_path)
    initialize.propose(home, [_card()], rationale="来自用户要求", client=base)
    initialize.confirm(home, confirmed_by_user=True)

    result = initialize.apply_draft(home, client=base)

    assert result["ok"] is True
    assert result["counts"]["created"] == 1
    assert (home / "archive" / "cards" / "card_virtual_cell.json").exists()
    config = json.loads((home / "knowledge" / "base.json").read_text(encoding="utf-8"))
    rows = base.list(config["tables"]["cards"])
    assert {row["fields"]["卡片 ID"] for row in rows} == {"card_virtual_cell"}
    assert result["retrieval"]["queries"] >= 1
    state = json.loads((home / "install" / "state.json").read_text(encoding="utf-8"))
    assert state["steps"]["knowledge"]["status"] == "ok"
    assert initialize.status(home)["ok"] is True


def test_apply_is_idempotent_and_does_not_duplicate_cards(tmp_path):
    home, base, _ = _home(tmp_path)
    _intake(home, tmp_path)
    initialize.propose(home, [_card()], client=base)
    initialize.confirm(home, confirmed_by_user=True)
    first = initialize.apply_draft(home, client=base)
    second = initialize.apply_draft(home, client=base)

    assert first["ok"] and second["ok"]
    assert second["counts"]["skipped"] == 1
    config = json.loads((home / "knowledge" / "base.json").read_text(encoding="utf-8"))
    rows = base.list(config["tables"]["cards"])
    assert len([row for row in rows if row["fields"].get("卡片 ID") == "card_virtual_cell"]) == 1


def test_existing_base_cards_are_imported_not_rebuilt(tmp_path):
    home, base, _ = _home(tmp_path)
    config = json.loads((home / "knowledge" / "base.json").read_text(encoding="utf-8"))
    base.create(
        config["tables"]["cards"],
        [
            {
                "卡片 ID": "card_keep",
                "label": "已有卡片",
                "ontology": ["hmbs", "急性间歇性卟啉病", "porphyria"],
                "annotation": "⛔ x；⚠️ y",
            }
        ],
    )

    result = initialize.adopt_existing(home, client=base, confirmed=True)

    assert result["ok"] is True
    assert result["imported"]["imported"] == ["card_keep"]
    assert (home / "archive" / "cards" / "card_keep.json").exists()
    assert result["retrieval"]["queries"] >= 1


def test_standard_retrieval_refuses_leftover_smoke_card(tmp_path):
    home, base, _ = _home(tmp_path)
    _intake(home, tmp_path)
    initialize.propose(home, [_card()], client=base)
    initialize.confirm(home, confirmed_by_user=True)
    initialize.apply_draft(home, client=base)
    plan_path = home / initialize.PLAN_REL
    plan_path.unlink()
    smoke_card = home / "archive" / "cards" / "card_smoke_leftover.json"
    smoke_card.write_text(
        json.dumps(
            {
                "id": "card_smoke_leftover",
                "label": "临时",
                "ontology": ["x", "y", "z"],
                "annotation": "⛔ x；⚠️ y",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(HostRunError):
        initialize.standard_retrieval(home)

    # The standard path never writes a formal plan containing the test card.
    assert not plan_path.exists()


def test_status_next_action_mentions_cleanup_when_gate_is_closed(tmp_path):
    home, base, _ = _home(tmp_path, gate=False)
    (home / "install").mkdir(parents=True, exist_ok=True)

    result = initialize.status(home)

    assert result["gate"]["test_and_cleanup_passed"] is False
    assert "临时闭环" in result["next"]


# ------------------------------------------------- intake gate and draft binding
def test_propose_requires_a_real_readable_intake(tmp_path, monkeypatch):
    home, base, _ = _home(tmp_path)

    missing = initialize.propose(home, [_card()], client=base)
    assert missing["ok"] is False
    assert missing["reason"] == "intake_missing"
    assert missing["note"]

    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(
        initialize,
        "_extract_pdf",
        lambda path: {
            "readable": False,
            "reason": "PDF 提取器不可用：no fitz",
            "pages": 0,
            "chars": 0,
        },
    )
    initialize.intake(home, pdfs=[str(pdf)], requirements="virtual cell")

    unreadable = initialize.propose(home, [_card()], client=base)
    assert unreadable["ok"] is False
    assert unreadable["reason"] == "intake_not_readable"
    assert any("PDF" in gap["reason"] for gap in unreadable["gaps"])

    index = tmp_path / "index.json"
    index.write_text(json.dumps([{"title": "A paper"}]), encoding="utf-8")
    initialize.intake(home, indexes=[str(index)], requirements="virtual cell")

    no_fulltext = initialize.propose(home, [_card()], client=base)
    assert no_fulltext["ok"] is False
    assert no_fulltext["reason"] == "intake_no_fulltext"

    _intake(home, tmp_path)
    ok = initialize.propose(home, [_card()], client=base)
    assert ok["ok"] is True


def test_apply_refuses_a_card_that_existed_before_the_draft(tmp_path):
    home, base, _ = _home(tmp_path)
    _intake(home, tmp_path)
    config = json.loads((home / "knowledge" / "base.json").read_text(encoding="utf-8"))
    cards_table = config["tables"]["cards"]
    base.create(
        cards_table,
        [
            {
                "卡片 ID": "card_virtual_cell",
                "label": "既有正式卡片",
                "ontology": ["已有本体"],
                "annotation": "既有注释",
            }
        ],
    )
    initialize.propose(home, [_card(label="新标签")], client=base)
    draft_meta = json.loads(
        (home / "install" / "initial" / "draft" / "draft.json").read_text(
            encoding="utf-8"
        )
    )
    assert draft_meta["pre_existing_ids"] == ["card_virtual_cell"]
    initialize.confirm(home, confirmed_by_user=True)

    refused = initialize.apply_draft(home, client=base)

    assert refused["ok"] is False
    assert refused["reason"] == "pre_existing_card"
    assert refused["conflicts"] == ["card_virtual_cell"]
    assert "overwrite" not in json.dumps(refused, ensure_ascii=False)
    rows = base.list(cards_table)
    assert [row["fields"]["label"] for row in rows] == ["既有正式卡片"]
    assert not (home / "archive" / "cards" / "card_virtual_cell.json").exists()

    # there is no escape hatch: the collision is refused again, unchanged
    again = initialize.apply_draft(home, client=base)
    assert again["ok"] is False
    assert again["reason"] == "pre_existing_card"
    assert [row["fields"]["label"] for row in base.list(cards_table)] == ["既有正式卡片"]


def test_propose_refuses_when_the_preexisting_snapshot_cannot_be_read(tmp_path):
    home, base, _ = _home(tmp_path)
    _intake(home, tmp_path)

    class Broken(JsonBase):
        def list(self, table):
            raise RuntimeError("permission denied")

    broken = Broken(tmp_path / "home" / "library" / "offline-base.json")
    broken.meta = base.meta
    broken.fields = base.fields
    broken.tables = base.tables

    result = initialize.propose(home, [_card()], client=broken)

    assert result["ok"] is False
    assert result["reason"] == "pre_existing_snapshot_failed"
    assert "Base" in result["note"]
    assert not (home / "install" / "initial" / "draft" / "cards.jsonl").exists()


def test_apply_normalises_before_comparing_read_back(tmp_path, monkeypatch):
    home, base, _ = _home(tmp_path)
    _intake(home, tmp_path)
    initialize.propose(home, [_card()], client=base)
    initialize.confirm(home, confirmed_by_user=True)
    config = json.loads((home / "knowledge" / "base.json").read_text(encoding="utf-8"))
    cards_table = config["tables"]["cards"]
    from knowledge import bitable

    real_sync = bitable.sync
    card = _card()

    def messy_sync(home_path, *, client):
        result = real_sync(home_path, client=client)
        row = client.list(cards_table)[0]
        client.update(
            cards_table,
            {
                row["record_id"]: {
                    "label": f"  {card['label']}  ",
                    "ontology": list(reversed(card["ontology"])) + [" virtual cell "],
                    "annotation": f" {card['annotation']} ",
                }
            },
        )
        return result

    monkeypatch.setattr(bitable, "sync", messy_sync)

    result = initialize.apply_draft(home, client=base)

    assert result["ok"] is True, result.get("reason")
    assert result["readback"]["verified"] is True


def test_cli_propose_exits_nonzero_when_refused(tmp_path):
    from hostrun import cli

    home, base, _ = _home(tmp_path)
    cards_file = tmp_path / "cards.json"
    cards_file.write_text(json.dumps([_card()]), encoding="utf-8")

    code = cli.main(
        ["--home", str(home), "init", "propose", "--cards", str(cards_file)]
    )

    assert code == 1


def test_apply_detects_a_tampered_remote_card_on_read_back(tmp_path, monkeypatch):
    home, base, _ = _home(tmp_path)
    _intake(home, tmp_path)
    initialize.propose(home, [_card()], client=base)
    initialize.confirm(home, confirmed_by_user=True)
    config = json.loads((home / "knowledge" / "base.json").read_text(encoding="utf-8"))
    cards_table = config["tables"]["cards"]
    from knowledge import bitable

    real_sync = bitable.sync

    def tampering_sync(home_path, *, client):
        result = real_sync(home_path, client=client)
        row = client.list(cards_table)[0]
        client.update(cards_table, {row["record_id"]: {"label": "远程被篡改"}})
        return result

    monkeypatch.setattr(bitable, "sync", tampering_sync)

    result = initialize.apply_draft(home, client=base)

    assert result["ok"] is False
    assert result["reason"] == "base_readback_mismatch"
    assert result["mismatched"] == ["card_virtual_cell"]

"""Knowledge-base onboarding: link parsing, structure check, no fixture pollution."""

import json

import pytest

from hostrun import kb
from hostrun.base import HostRunError


def test_parse_link_accepts_the_forms_users_paste():
    base = kb.parse_link("https://example.feishu.cn/base/bascnABC123?table=tblXyZ9")
    assert base["base_token"] == "bascnABC123"
    assert base["table_id"] == "tblXyZ9"

    wiki = kb.parse_link("https://example.feishu.cn/wiki/wikcnAAA111")
    assert wiki["base_token"] == "wikcnAAA111"

    bare = kb.parse_link("bascnABC123")
    assert bare["base_token"] == "bascnABC123"

    with pytest.raises(HostRunError):
        kb.parse_link("")
    with pytest.raises(HostRunError):
        kb.parse_link("这不是链接")


def test_attach_reports_missing_tables_and_writes_nothing(offline_home, offline_base):
    before = [row["name"] for row in offline_base.list_tables()]

    result = kb.attach(offline_home, "bascnABC123", client=offline_base)

    assert result["ok"] is False
    assert result["attached"] is True
    assert "命题" in result["missing"]
    assert "next" in result
    saved = json.loads((offline_home / "knowledge" / "base.json").read_text(encoding="utf-8"))
    assert saved["base_token"] == "bascnABC123"
    # nothing was created by merely attaching
    assert [row["name"] for row in offline_base.list_tables()] == before


def test_create_tables_fills_every_required_table(configured_home, offline_base):
    result = kb.create_tables(configured_home, client=offline_base)

    names = {row["name"] for row in offline_base.list_tables()}
    assert set(kb.REQUIRED.values()) <= names, names - set(kb.REQUIRED.values())

    report = kb.verify(configured_home, client=offline_base)
    assert report["ok"] is True
    assert report["missing"] == []
    assert report["has_user_data"] is False
    assert result["actions"]


def test_create_tables_is_idempotent(configured_home, offline_base):
    kb.create_tables(configured_home, client=offline_base)
    before = len(offline_base.list_tables())

    again = kb.create_tables(configured_home, client=offline_base)

    assert len(offline_base.list_tables()) == before
    assert not [a for a in again["actions"] if a.startswith("create table")]


def test_create_tables_dry_run_writes_nothing(configured_home, offline_base):
    before = {row["name"] for row in offline_base.list_tables()}

    result = kb.create_tables(configured_home, client=offline_base, dry_run=True)

    assert result["dry_run"] is True
    assert result["ok"] is True
    assert {row["name"] for row in offline_base.list_tables()} == before
    assert result["tables"]["propositions"].startswith("tbl_dry_")


def test_new_base_must_be_empty_and_says_what_it_found(configured_home, offline_base):
    kb.create_tables(configured_home, client=offline_base)
    tables = {row["name"]: row["id"] for row in offline_base.list_tables()}
    card_id = offline_base.create(
        tables["知识卡片"],
        [{"卡片 ID": "card_hmbs", "label": "HMBS", "ontology": "gene", "annotation": "x"}],
    )[0]

    report = kb.verify(configured_home, client=offline_base, expect_empty=True)

    assert report["ok"] is False
    assert report["has_user_data"] is True
    assert card_id
    assert any("HMBS" in title for title in report["sample_titles"])


def test_create_empty_refuses_to_switch_a_configured_base(offline_home, offline_base):
    kb.create_empty(offline_home, "bascnABC123", client=offline_base)
    saved = json.loads((offline_home / "knowledge" / "base.json").read_text(encoding="utf-8"))
    assert saved["base_token"] == "bascnABC123"

    blocked = kb.create_empty(offline_home, "bascnOTHER99", client=offline_base)

    assert blocked["ok"] is False
    assert blocked["reason"] == "different_base_configured"
    assert blocked["configured"] == "bascnABC123"


def test_create_empty_does_not_copy_fixtures_into_the_base(offline_home, offline_base):
    result = kb.create_empty(offline_home, "bascnABC123", client=offline_base)

    assert result["verify"]["ok"] is True
    # only the library's own config row exists; no cards, propositions or papers
    for key in ("cards", "propositions", "evidence", "papers", "sources", "pushes", "decisions"):
        assert offline_base.list(result["verify"]["present"][key]) == [], key


def test_initial_themes_are_drafts_until_the_user_confirms(offline_home):
    themes = [{"name": "血红素合成", "cards": ["card_hmbs"], "propositions": []}]

    blocked = kb.record_initial_confirmation(offline_home, themes, confirmed_by_user=False)
    assert blocked["ok"] is False
    assert blocked["reason"] == "needs_user_confirmation"
    assert kb.initial_confirmed(offline_home)["ok"] is False

    ok = kb.record_initial_confirmation(offline_home, themes, confirmed_by_user=True)
    assert ok["ok"] is True
    assert kb.initial_confirmed(offline_home)["confirmed"] == ["血红素合成"]
    assert kb.initial_confirmed(offline_home, theme="别的主题")["ok"] is False

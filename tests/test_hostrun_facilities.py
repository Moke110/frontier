"""Facilities: create by confirmed names, reuse stable IDs, attach safely."""

import json
import shutil
from pathlib import Path

import pytest

from hostrun import facilities, kb
from library.drive import FixtureDrive
from library.offline import JsonBase

ROOT = Path(__file__).resolve().parents[1]


def _fresh_base(tmp_path) -> JsonBase:
    base = JsonBase(tmp_path / "home" / "library" / "offline-base.json")
    base.meta = []
    base.fields = {}
    base.tables = {}
    return base


class FakeAdmin:
    def __init__(self, base: JsonBase, matches=None):
        self.base = base
        self.created = 0
        self.matches = matches or []
        self.created_names = []

    def resolve_title(self, title: str) -> dict:
        return {"matches": self.matches, "count": len(self.matches)}

    def create_base(self, name: str, *, table_name: str, fields: list[dict]) -> dict:
        self.created += 1
        self.created_names.append(name)
        table_id = self.base.create_table(table_name, fields)
        return {
            "base_token": "basoffline",
            "table_id": table_id,
            "url": f"https://example.feishu.cn/base/basoffline",
            "name": name,
        }


def _names(**over):
    names = facilities.default_names()
    names["base"] = over.pop("base", "研究库")
    names["tables"].update(over.pop("tables", {}))
    names["folders"].update(over.pop("folders", {}))
    return names


def test_create_builds_base_tables_and_folders_from_confirmed_names(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    base = _fresh_base(tmp_path)
    drive = FixtureDrive()
    admin = FakeAdmin(base)
    names = _names(
        tables={"cards": "我的卡片", "sources": "我的原文"},
        folders={"root": "研究根目录", "source": "原文目录", "push": "推送目录"},
    )

    result = facilities.create(
        home,
        names=names,
        confirmed=True,
        admin=admin,
        client=base,
        drive=drive,
    )

    assert result["ok"] is True
    assert admin.created == 1
    names_present = {row["name"] for row in base.list_tables()}
    assert "我的卡片" in names_present
    assert "我的原文" in names_present
    config = json.loads((home / "knowledge" / "base.json").read_text(encoding="utf-8"))
    assert config["base_token"] == "basoffline"
    record = facilities.load_facilities(home)
    assert record["names"]["base"] == "研究库"
    assert record["tables"]["cards"]["name"] == "我的卡片"
    assert record["folders"]["source"]
    root_entries = {entry["name"] for entry in drive.list(drive.root)}
    assert "研究根目录" in root_entries
    assert len(record["tables"]) == len(facilities.KEYS)
    install_state = json.loads((home / "install" / "state.json").read_text(encoding="utf-8"))
    assert install_state["steps"]["facilities"]["status"] == "ok"


def test_repeat_create_reuses_ids_and_never_creates_a_second_base(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    base = _fresh_base(tmp_path)
    drive = FixtureDrive()
    admin = FakeAdmin(base)
    names = _names()

    first = facilities.create(home, names=names, confirmed=True, admin=admin, client=base, drive=drive)
    table_count = len(base.list_tables())
    second = facilities.create(home, names=names, confirmed=True, admin=admin, client=base, drive=drive)

    assert first["ok"] and second["ok"]
    assert admin.created == 1
    assert second["reused"] is True
    assert len(base.list_tables()) == table_count


def test_created_names_must_be_confirmed_before_writing(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    base = _fresh_base(tmp_path)
    admin = FakeAdmin(base)

    result = facilities.create(home, names=_names(), confirmed=False, admin=admin, client=base)

    assert result["ok"] is False
    assert result["reason"] == "needs_user_confirmation"
    assert admin.created == 0
    assert not (home / "knowledge" / "base.json").exists()


def test_dry_run_writes_nothing(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    result = facilities.create(home, names=_names(), confirmed=True, dry_run=True)

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert not (home / "install" / "facilities-names.json").exists()
    assert not (home / "install" / "facilities.json").exists()


def test_ambiguous_same_name_blocks_instead_of_switching(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    base = _fresh_base(tmp_path)
    admin = FakeAdmin(
        base,
        matches=[
            {"base_token": "bas_one", "name": "研究库"},
            {"base_token": "bas_two", "name": "研究库"},
        ],
    )

    result = facilities.create(home, names=_names(), confirmed=True, admin=admin, client=base)

    assert result["ok"] is False
    assert result["reason"] == "ambiguous_base"
    assert admin.created == 0


def test_same_name_without_frontier_table_is_not_reused(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    base = _fresh_base(tmp_path)
    base.create_table("别人的表", [{"name": "x", "type": "text"}])
    admin = FakeAdmin(base, matches=[{"base_token": "bas_other", "name": "研究库"}])

    class Probe(JsonBase):
        pass

    import library.base

    monkeypatch.setattr(
        library.base,
        "LarkBaseClient",
        lambda config, **kwargs: JsonBase(tmp_path / "home" / "library" / "offline-base.json"),
    )

    result = facilities.create(home, names=_names(), confirmed=True, admin=admin, client=base)

    assert result["ok"] is False
    assert result["reason"] == "unrelated_base"
    assert admin.created == 0


def test_rename_keeps_the_stable_table_id_usable(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    base = _fresh_base(tmp_path)
    drive = FixtureDrive()
    facilities.create(
        home, names=_names(), confirmed=True, admin=FakeAdmin(base), client=base, drive=drive
    )
    original_id = facilities.load_facilities(home)["tables"]["cards"]["id"]

    facilities.rename(home, "cards", "改名后的卡片", client=base)

    record = facilities.load_facilities(home)
    assert record["tables"]["cards"]["id"] == original_id
    assert record["tables"]["cards"]["name"] == "改名后的卡片"
    status = facilities.status(home, client=base)
    assert status["ok"] is True
    assert status["tables"]["cards"]["id"] == original_id


def test_attach_preserves_existing_records_and_reports_structure(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    base = _fresh_base(tmp_path)
    drive = FixtureDrive()
    facilities.create(
        home, names=_names(), confirmed=True, admin=FakeAdmin(base), client=base, drive=drive
    )
    cards_id = facilities.load_facilities(home)["tables"]["cards"]["id"]
    base.create(cards_id, [{"卡片 ID": "card_keep", "label": "保留"}])
    (home / "install" / "facilities.json").unlink()
    (home / "knowledge" / "base.json").unlink()

    result = facilities.attach(
        home,
        "https://example.feishu.cn/base/basoffline",
        names=_names(),
        confirmed=True,
        client=base,
        drive=drive,
    )

    assert result["ok"] is True
    assert result["attached"] is True
    assert result["has_user_data"] is True
    assert base.list(cards_id)[0]["fields"]["label"] == "保留"


def test_partial_creation_can_resume_without_duplicates(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    base = _fresh_base(tmp_path)
    drive = FixtureDrive()
    admin = FakeAdmin(base)
    created = {"count": 0}
    original = base.create_table

    def flaky(name, fields):
        created["count"] += 1
        if created["count"] == 3:
            raise RuntimeError("network dropped")
        return original(name, fields)

    base.create_table = flaky

    first = facilities.create(home, names=_names(), confirmed=True, admin=admin, client=base, drive=drive)

    assert first["ok"] is False
    assert first["reason"] == "facility_create_partial"
    assert first["missing"]
    tables_before = [row["name"] for row in base.list_tables()]

    base.create_table = original
    second = facilities.create(home, names=_names(), confirmed=True, admin=admin, client=base, drive=drive)

    assert second["ok"] is True
    tables_after = [row["name"] for row in base.list_tables()]
    assert len(tables_after) == len(set(tables_after))
    assert set(tables_before) <= set(tables_after)
    assert admin.created == 1


def test_names_must_be_unique_and_valid():
    with pytest.raises(Exception):
        facilities.normalize({"tables": {"cards": "重复", "propositions": "重复"}})
    with pytest.raises(Exception):
        facilities.normalize({"base": "bad/name"})
    with pytest.raises(Exception):
        facilities.normalize({"folders": {"root": ""}})


def test_status_without_any_facility_is_pending(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    result = facilities.status(home)

    assert result["ok"] is False
    assert result["status"] == "pending"


# --------------------------------------------- field read-back and stable IDs
def test_precreated_table_with_missing_fields_blocks_with_exact_names(
    configured_home, offline_base
):
    result = facilities.create(
        configured_home,
        names=_names(),
        confirmed=True,
        admin=FakeAdmin(offline_base),
        client=offline_base,
        drive=FixtureDrive(),
    )

    assert result["ok"] is False
    assert "annotation" in result["missing_fields"]["cards"]
    state = json.loads(
        (configured_home / "install" / "state.json").read_text(encoding="utf-8")
    )
    assert state["steps"]["facilities"]["status"] == "blocked"
    assert "annotation" in state["steps"]["facilities"]["note"]
    assert "知识卡片" in state["steps"]["facilities"]["note"]

    status = facilities.status(configured_home, client=offline_base)

    assert status["ok"] is False
    assert status["status"] == "blocked"
    assert "annotation" in status["missing_fields"]["cards"]


def test_second_create_with_changed_display_names_creates_nothing_new(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    base = _fresh_base(tmp_path)
    drive = FixtureDrive()
    admin = FakeAdmin(base)
    facilities.create(
        home, names=_names(), confirmed=True, admin=admin, client=base, drive=drive
    )
    record = facilities.load_facilities(home)
    cards_id = record["tables"]["cards"]["id"]
    table_count = len(base.list_tables())
    root_entries = len(drive.list(drive.root))

    changed = _names(
        tables={"cards": "改名卡片", "sources": "改名原文"},
        folders={"root": "新根目录", "source": "新原文目录", "push": "新推送目录"},
    )
    second = facilities.create(
        home, names=changed, confirmed=True, admin=admin, client=base, drive=drive
    )

    assert second["ok"] is True
    assert admin.created == 1
    assert len(base.list_tables()) == table_count
    assert len(drive.list(drive.root)) == root_entries
    saved = facilities.load_facilities(home)
    assert saved["tables"]["cards"]["id"] == cards_id
    assert saved["tables"]["cards"]["name"] == facilities.DEFAULT_TABLES["cards"]
    assert any("facilities rename" in action for action in second["actions"])

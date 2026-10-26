import json

from archive.store import Archive
from knowledge import bitable


class FakeClient:
    def __init__(self):
        self.tables = {}
        self.counter = 0

    def _rows(self, table):
        return self.tables.setdefault(table, [])

    def list(self, table):
        return [dict(row, fields=dict(row["fields"])) for row in self._rows(table)]

    def create(self, table, rows):
        ids = []
        for row in rows:
            self.counter += 1
            rid = f"rec{self.counter:03d}"
            self._rows(table).append({"record_id": rid, "fields": dict(row)})
            ids.append(rid)
        return ids

    def update(self, table, updates):
        by_id = {row["record_id"]: row for row in self._rows(table)}
        for rid, fields in updates.items():
            by_id[rid]["fields"].update(fields)

    def ensure_options(self, table, field, values):
        return None


def _config(home):
    path = home / "knowledge" / "base.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "base_token": "fake",
                "base_url": "https://example.feishu.cn/base/fake",
                "tables": {
                    "cards": "cards",
                    "propositions": "props",
                    "evidence": "evidence",
                    "papers": "papers",
                    "logs": "logs",
                },
            }
        ),
        encoding="utf-8",
    )


def test_sync_creates_then_is_idempotent(kl_home):
    _config(kl_home)
    client = FakeClient()
    first = bitable.sync(kl_home, client)
    assert first["created"]["cards"] == len(Archive(kl_home).list_cards())
    assert first["created"]["propositions"] >= 1
    second = bitable.sync(kl_home, client)
    assert second["created"] == {
        "cards": 0,
        "papers": 0,
        "evidence": 0,
        "logs": 0,
        "propositions": 0,
    }
    assert second["updated"] == {
        "cards": 0,
        "evidence": 0,
        "logs": 0,
        "propositions": 0,
    }
    assert bitable.compare(kl_home, client)["ok"] is True


def test_compare_detects_and_sync_repairs_manual_edit(kl_home):
    _config(kl_home)
    client = FakeClient()
    bitable.sync(kl_home, client)

    card = Archive(kl_home).get_card("card_hmbs")
    card["annotation"] = card["annotation"] + "\n微信端补充。"
    Archive(kl_home).put_card(card)
    drift = bitable.compare(kl_home, client)
    assert drift["ok"] is False
    assert any(d["id"] == "card_hmbs" for d in drift["diffs"])

    repaired = bitable.sync(kl_home, client)
    assert repaired["updated"]["cards"] == 1
    assert bitable.compare(kl_home, client)["ok"] is True


def test_sync_links_evidence_and_papers(kl_home):
    _config(kl_home)
    store = Archive(kl_home)
    prop = store.get_prop("prop_virtual_cell_perturbation")
    prop["evidence"] = [
        {
            "id": "ev_virtual_cell_perturbation_01",
            "stance": "supports",
            "conclusion": "A benchmark supports the claim.",
            "papers": [
                {
                    "paper_id": "p1",
                    "push_id": "push1",
                    "page": 3,
                    "quote": "A benchmark supports the claim in single cells.",
                }
            ],
            "created_at": "2026-10-20T09:00:00+08:00",
            "updated_at": "2026-10-20T09:00:00+08:00",
        }
    ]
    store.put_prop(prop)
    client = FakeClient()
    bitable.sync(kl_home, client)
    prop = next(
        row for row in client.list("props")
        if row["fields"]["命题 ID"] == "prop_virtual_cell_perturbation"
    )
    assert len(prop["fields"]["关联卡片"]) == 2
    assert len(prop["fields"]["证据"]) >= 1
    ev = client.list("evidence")[0]
    assert ev["fields"]["报道"]
    assert ev["fields"]["stance"] in (["supports"], ["contradicts"])


def _record(client, table, key, value):
    return next(
        row for row in client.list(table) if row["fields"].get(key) == value
    )


def test_pull_applies_text_edits_and_flags_invalid_ones(kl_home):
    _config(kl_home)
    store = Archive(kl_home)
    prop = store.get_prop("prop_virtual_cell_perturbation")
    prop["evidence"] = [
        {
            "id": "ev_virtual_cell_perturbation_01",
            "stance": "supports",
            "conclusion": "A benchmark supports the claim.",
            "papers": [
                {
                    "paper_id": "p1",
                    "push_id": "push1",
                    "page": 3,
                    "quote": "A benchmark supports the claim in single cells.",
                }
            ],
            "created_at": "2026-10-20T09:00:00+08:00",
            "updated_at": "2026-10-20T09:00:00+08:00",
        }
    ]
    store.put_prop(prop)
    client = FakeClient()
    bitable.sync(kl_home, client)

    card = _record(client, "cards", "卡片 ID", "card_hmbs")
    client.update("cards", {card["record_id"]: {
        "annotation": "用户在飞书改写的注释。\n⛔ 排除项。\n⚠️ 易混项。"
    }})
    prop = _record(client, "props", "命题 ID", "prop_virtual_cell_perturbation")
    new_review = (
        "## 结论\n用户在飞书改写的综述。\n"
        "## 支持证据\n一项。\n"
        "## 反证与边界\n无。\n"
        "## 待验证\n无。"
    )
    client.update("props", {prop["record_id"]: {"review": new_review}})
    ev = _record(client, "evidence", "证据 ID", "ev_virtual_cell_perturbation_01")
    client.update("evidence", {ev["record_id"]: {"conclusion": "x" * 201}})

    result = bitable.pull(kl_home, client)
    assert {row["kind"] for row in result["applied"]} == {"card", "proposition"}
    assert result["notes"] and result["notes"][0]["kind"] == "evidence"

    store = Archive(kl_home)
    assert store.get_card("card_hmbs")["annotation"].startswith("用户在飞书")
    updated = store.get_prop("prop_virtual_cell_perturbation")
    assert updated["review"].startswith("## 结论\n用户在飞书")
    assert updated["changelog"][-1]["source"]["kind"] == "bitable"
    flagged = _record(client, "evidence", "证据 ID", "ev_virtual_cell_perturbation_01")
    assert "1..200" in (flagged["fields"].get("待修正") or "")


class SourceAwareClient(FakeClient):
    def field_names(self, table):
        return ["原文"]


def test_sync_links_reports_to_the_matching_source_row(kl_home):
    _config(kl_home)
    path = kl_home / "knowledge" / "base.json"
    config = json.loads(path.read_text())
    config["tables"]["sources"] = "sources"
    path.write_text(json.dumps(config), encoding="utf-8")

    store = Archive(kl_home)
    paper_ids = sorted(
        {
            paper["paper_id"]
            for prop in store.list_props()
            for ev in prop.get("evidence", [])
            for paper in ev.get("papers", [])
        }
    )
    client = SourceAwareClient()
    client.create("sources", [{"原文 ID": pid} for pid in paper_ids])

    result = bitable.sync(kl_home, client)
    assert result["updated"]["papers"] == 0

    sources = {row["fields"]["原文 ID"]: row["record_id"] for row in client.list("sources")}
    for row in client.list("papers"):
        assert row["fields"]["原文"] == [{"id": sources[row["fields"]["paper_id"]]}]

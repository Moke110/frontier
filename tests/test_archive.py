from pathlib import Path

from archive.store import Archive


def test_add_paper_dedupes_by_source_id(kl_home):
    store = Archive(kl_home)
    store.init()
    rec = {
        "source": "europepmc",
        "source_id": "42900001",
        "title": "HMBS loss",
        "abstract": "abstract",
        "checkpoint_id": "hmbs",
    }
    first = store.add_paper(dict(rec))
    second = store.add_paper(dict(rec))
    assert first["deduped"] is False
    assert second["deduped"] is True
    assert second["paper_id"] == first["paper_id"]
    assert store.get_paper(first["paper_id"])["title"] == "HMBS loss"
    assert (kl_home / "archive" / "raw" / "text" / f"{first['paper_id']}.txt").exists()


def test_context_aggregates_kg_props_and_history(kl_home):
    store = Archive(kl_home)
    store.init()
    store.add_paper(
        {
            "source": "europepmc",
            "source_id": "1",
            "title": "t",
            "abstract": "a",
            "checkpoint_id": "hmbs",
        }
    )
    ctx = store.context("kg_hmbs", "hmbs")
    assert ctx["node"]["node_id"] == "kg_hmbs"
    assert ctx["archived_count"] == 1
    assert {p["prop_id"] for p in ctx["propositions"]} == {"prop_hmbs_aip"}
    assert ctx["related_edges"]


def test_apply_three_proposal_kinds(kl_home):
    store = Archive(kl_home)
    store.init()
    push = {
        "push_id": "push_1",
        "checkpoint_id": "hmbs",
        "paper_ids": ["p1"],
        "proposals": [
            {
                "proposal_id": "p1",
                "push_id": "push_1",
                "kind": "add_evidence",
                "target_type": "proposition",
                "target_id": "prop_hmbs_aip",
                "diff": {"op": "add", "path": "evidence", "value": {"paper_id": "p1", "note": "n"}},
            },
            {
                "proposal_id": "p2",
                "push_id": "push_1",
                "kind": "add_alias",
                "target_type": "kg_node",
                "target_id": "kg_hmbs",
                "diff": {"op": "add", "path": "aliases", "value": "HMBS enzyme 2"},
            },
            {
                "proposal_id": "p3",
                "push_id": "push_1",
                "kind": "add_proposition",
                "target_type": "none",
                "target_id": "",
                "diff": {
                    "op": "add",
                    "path": "proposition",
                    "value": {"text": "new claim", "node_ids": ["kg_hmbs", "kg_heme"], "paper_id": "p1"},
                },
            },
        ],
    }
    store.add_push(push)
    for pid in ("p1", "p2", "p3"):
        store.apply_proposal("push_1", pid)
    prop = store.get_prop("prop_hmbs_aip")
    assert [e["paper_id"] for e in prop["evidence"]] == ["p1"]
    assert "HMBS enzyme 2" in store.get_node("kg_hmbs")["aliases"]
    assert len(store.list_props("kg_heme")) == 1


def test_apply_decisions_is_idempotent_and_handles_reject(kl_home, tmp_path):
    store = Archive(kl_home)
    store.init()
    store.add_push(
        {
            "push_id": "push_2",
            "checkpoint_id": "hmbs",
            "proposals": [
                {
                    "proposal_id": "px",
                    "push_id": "push_2",
                    "kind": "add_alias",
                    "target_type": "kg_node",
                    "target_id": "kg_hmbs",
                    "diff": {"op": "add", "path": "aliases", "value": "alias-x"},
                }
            ],
        }
    )
    pending = tmp_path / "pending"
    pending.mkdir()
    (pending / "px.json").write_text(
        '{"proposal_id":"px","push_id":"push_2","kind":"add_alias",'
        '"target_type":"kg_node","target_id":"kg_hmbs",'
        '"diff":{"op":"add","path":"aliases","value":"alias-x"}}',
        encoding="utf-8",
    )
    decisions = tmp_path / "decisions.jsonl"
    decisions.write_text('{"proposal_id":"px","decision":"approve"}\n', encoding="utf-8")
    first = store.apply_decisions(pending, decisions)
    second = store.apply_decisions(pending, decisions)
    assert first["applied"] == ["px"]
    assert second["skipped"] == ["px"]
    assert "alias-x" in store.get_node("kg_hmbs")["aliases"]

    decisions.write_text('{"proposal_id":"py","decision":"reject"}\n', encoding="utf-8")
    out = store.apply_decisions(pending, decisions)
    assert out["rejected"] == ["py"]
    assert (kl_home / "archive" / "applied" / "py.json").exists()

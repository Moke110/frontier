"""Cleanup: exact test scope, read-back verification, failure honesty."""

import json
from pathlib import Path

import pytest

from hostrun import cleanup, facilities, kb, smoke
from hostrun.base import HostRunError
from library.drive import FixtureDrive
from library.offline import JsonBase
from question_queue.store import QueueStore
from writer.render import CAPTION_LABELS, SECTION_LABELS


def _plan_file(directory):
    path = Path(directory) / "candidates.jsonl"
    path.write_text(json.dumps({"paper_id": "p1"}) + "\n", encoding="utf-8")
    return path


def _rendered_file(directory):
    path = Path(directory) / "push.html"
    text = "".join(f"<h2>{label}</h2>" for label in SECTION_LABELS.values())
    text += "".join(
        f'<span class="source-pill">{label}</span>'
        for label in CAPTION_LABELS.values()
    )
    path.write_text(text, encoding="utf-8")
    return path


def _gone(message_id):
    """A checker that confirms the recalled message can no longer be read."""
    return False


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


OWNER = "ou_owner"


def _verifier(open_id: str = OWNER):
    return lambda cli: {"ok": True, "open_id": open_id}


def _seed_queue(home, push_id, question, decision_item):
    """The user's own card submissions: rating, then adoption."""
    root = Path(home) / "queue"
    items = [
        {
            "id": question,
            "kind": "rating",
            "push_id": push_id,
            "status": "answered",
            "answer": {"verdict": "great", "operator_id": OWNER},
        },
        {
            "id": decision_item,
            "kind": "card_update",
            "push_id": push_id,
            "status": "answered",
            "answer": {"decision": "agree_all", "operator_id": OWNER},
        },
    ]
    (root / "state.json").write_text(
        json.dumps({"schema_version": 1, "active_id": None, "items": items}),
        encoding="utf-8",
    )


def _ready(tmp_path, *, with_artifacts=True):
    home = tmp_path / "home"
    home.mkdir()
    base = _fresh_base(tmp_path)
    drive = FixtureDrive()
    facilities.create(
        home, confirmed=True, admin=Admin(base), client=base, drive=drive
    )
    started = smoke.start(
        home,
        "虚拟细胞",
        owner=OWNER,
        confirmed=True,
        client=base,
        verifier=_verifier(),
    )
    card_id = started["card"]["id"]
    test_id = started["test_id"]
    push_id = f"push_{test_id}"
    message = "om_test_message"
    question = f"q_{push_id}_rating"
    decision_item = f"q_{push_id}_decision"
    paper_id = f"paper_{test_id}"
    smoke.record(home, "retrieved", plan=str(_plan_file(tmp_path)))
    smoke.record(home, "written", papers=[paper_id])
    push_path = home / "archive" / "pushes" / f"{push_id}.json"
    push_path.parent.mkdir(parents=True, exist_ok=True)
    push_path.write_text(
        json.dumps({"push_id": push_id, "paper_ids": [paper_id]}), encoding="utf-8"
    )
    smoke.record(home, "rendered", push=push_id, html=str(_rendered_file(tmp_path)))
    smoke.record(
        home, "sent", push=push_id, message=message, question=question
    )
    queue = QueueStore(home)
    queue.init()
    _seed_queue(home, push_id, question, decision_item)
    smoke.record(home, "rated", item=question, verdict="great")
    smoke.record(home, "decided", item=decision_item, decision="agree_all")
    smoke.record(home, "applied")

    config = json.loads((home / "knowledge" / "base.json").read_text(encoding="utf-8"))
    tables = config["tables"]
    record = json.loads((home / "install" / "facilities.json").read_text(encoding="utf-8"))

    # a formal card and question must survive
    formal_card = base.create(tables["cards"], [{"卡片 ID": "card_formal", "label": "正式"}])[0]
    formal_question = base.create(tables["questions"], [{"问题 ID": "q_formal"}])[0]

    if with_artifacts:
        base.create(tables["questions"], [{"问题 ID": question, "推送 ID": push_id}])
        base.create(tables["submissions"], [{"问题 ID": question}])
        # the temporary loop records selected paper ids; the 报道 row may carry
        # no push id at all, so it must be selected by paper id
        base.create(tables["papers"], [{"paper_id": f"paper_{test_id}"}])
        base.create(tables["papers"], [{"paper_id": "paper_formal"}])
        base.create(tables["pushes"], [{"推送 ID": push_id}])
        base.create(tables["sources"], [{"原文 ID": f"src_{test_id}"}])
        base.create(tables["logs"], [{"source_id": test_id}])
        drive.put_bytes(record["folders"]["source"], "smoke.pdf", b"%PDF-1.4")
        token = drive.find(record["folders"]["source"], "smoke.pdf")["token"]
        (home / "install" / "smoke-plan.json").write_text("{}", encoding="utf-8")
        state = smoke.load(home)
        state["artifacts"]["file_ids"].append(token)
        state["artifacts"]["source_ids"].append(f"src_{test_id}")
        state["artifacts"]["message_ids"].append(message)
        smoke.save(home, state)

    # accept a real change on the temporary card
    base.update(tables["cards"], {started["card"]["remote_record_id"]: {"label": "[已采纳]"}})
    smoke.verify(
        home,
        target_key="cards",
        target_id=card_id,
        field="label",
        expected="[已采纳]",
        client=base,
    )
    return {
        "home": home,
        "base": base,
        "drive": drive,
        "tables": tables,
        "card_id": card_id,
        "test_id": test_id,
        "push_id": push_id,
        "question": question,
        "message": message,
        "paper_id": f"paper_{test_id}",
        "formal_card": formal_card,
        "formal_question": formal_question,
    }


def test_cleanup_removes_exact_artifacts_and_keeps_formal_data(tmp_path):
    ctx = _ready(tmp_path)
    home, base, drive = ctx["home"], ctx["base"], ctx["drive"]
    record = json.loads((home / "install" / "facilities.json").read_text(encoding="utf-8"))
    source_folder = record["folders"]["source"]
    messages = []

    result = cleanup.run(
        home,
        confirmed=True,
        client=base,
        drive=drive,
        messenger=lambda message_id: messages.append(message_id),
        message_checker=_gone,
    )

    assert result["ok"] is True
    assert result["status"] == "cleaned"
    assert messages == [ctx["message"]]
    assert not (home / "archive" / "cards" / f"{ctx['card_id']}.json").exists()
    remaining_cards = base.list(ctx["tables"]["cards"])
    assert {row["fields"]["卡片 ID"] for row in remaining_cards} == {"card_formal"}
    assert any(row["record_id"] == ctx["formal_card"] for row in base.list(ctx["tables"]["cards"]))
    assert any(
        row["record_id"] == ctx["formal_question"] for row in base.list(ctx["tables"]["questions"])
    )
    assert not [
        row
        for row in base.list(ctx["tables"]["questions"])
        if row["fields"].get("推送 ID") == ctx["push_id"]
    ]
    assert {row["fields"].get("paper_id") for row in base.list(ctx["tables"]["papers"])} == {
        "paper_formal"
    }
    assert drive.find(source_folder, "smoke.pdf") is None
    queue = QueueStore(home)
    assert not [item for item in queue.items() if item.get("push_id") == ctx["push_id"]]
    assert not (home / "archive" / "pushes" / f"{ctx['push_id']}.json").exists()

    state = smoke.load(home)
    assert state["cleaned_at"]
    assert state["test_status"] == "complete"
    assert "keyword" not in state
    assert "card" not in state
    assert state["cleanup"]["removed_counts"]
    state_file = json.loads((home / "install" / "state.json").read_text(encoding="utf-8"))
    assert state_file["steps"]["cleanup"]["status"] == "ok"
    assert cleanup.require_cleaned(home)["ok"] is True
    assert smoke.status(home)["ok"] is True


def test_cleanup_is_idempotent(tmp_path):
    ctx = _ready(tmp_path)
    first = cleanup.run(
        ctx["home"],
        confirmed=True,
        client=ctx["base"],
        drive=ctx["drive"],
        messenger=lambda x: None,
        message_checker=_gone,
    )
    second = cleanup.run(
        ctx["home"],
        confirmed=True,
        client=ctx["base"],
        drive=ctx["drive"],
        messenger=lambda x: None,
        message_checker=_gone,
    )

    assert first["ok"] is True
    assert second["already_cleaned"] is True
    assert second["ok"] is True


def test_message_recall_uses_the_recorded_cli_path(tmp_path, monkeypatch):
    ctx = _ready(tmp_path)
    calls = []
    checks = []

    def recall(message_id, *, executable):
        calls.append((message_id, executable))
        return {"ok": True}

    def read_back(message_id, *, executable):
        checks.append((message_id, executable))
        return {"message_id": message_id, "present": False}

    monkeypatch.setattr("publisher.feishu.delete_message", recall)
    monkeypatch.setattr("publisher.feishu.get_message", read_back)

    result = cleanup.run(
        ctx["home"],
        confirmed=True,
        client=ctx["base"],
        drive=ctx["drive"],
        lark_cli=str(tmp_path / "private-bin" / "lark-cli"),
    )

    executable = str(tmp_path / "private-bin" / "lark-cli")
    assert result["ok"] is True
    assert calls == [(ctx["message"], executable)]
    assert checks == [(ctx["message"], executable)]


def test_unretractable_message_keeps_the_gate_closed(tmp_path):
    ctx = _ready(tmp_path)
    home = ctx["home"]

    def refuse(message_id):
        raise RuntimeError("message too old")

    result = cleanup.run(
        home,
        confirmed=True,
        client=ctx["base"],
        drive=ctx["drive"],
        messenger=refuse,
        message_checker=_gone,
    )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["cleanup"]["unretractable"]
    assert smoke.load(home).get("cleaned_at") is None
    with pytest.raises(HostRunError):
        cleanup.require_cleaned(home)

    # fix the cause and rerun: only the remaining recall is attempted
    called = []

    def recall(message_id):
        called.append(message_id)

    again = cleanup.run(
        home,
        confirmed=True,
        client=ctx["base"],
        drive=ctx["drive"],
        messenger=recall,
        message_checker=_gone,
    )
    assert again["ok"] is True
    assert called == [ctx["message"]]


def test_failed_test_cannot_be_reported_as_cleaned_success(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    base = _fresh_base(tmp_path)
    drive = FixtureDrive()
    facilities.create(home, confirmed=True, admin=Admin(base), client=base, drive=drive)
    smoke.start(
        home,
        "虚拟细胞",
        owner=OWNER,
        confirmed=True,
        client=base,
        verifier=_verifier(),
    )
    smoke.record(home, "retrieved", plan=str(_plan_file(tmp_path)))
    smoke.fail(home, "send_timeout")

    refused = cleanup.run(
        home,
        confirmed=True,
        client=base,
        drive=drive,
        messenger=lambda x: None,
        message_checker=_gone,
    )
    assert refused["ok"] is False
    assert refused["reason"] == "test_not_successful"

    aborted = cleanup.run(
        home,
        confirmed=True,
        allow_failed=True,
        client=base,
        drive=drive,
        messenger=lambda x: None,
        message_checker=_gone,
    )
    assert aborted["ok"] is False
    state = smoke.load(home)
    assert state["cleaned_at"]
    assert state["test_status"] == "failed"
    state_file = json.loads((home / "install" / "state.json").read_text(encoding="utf-8"))
    assert state_file["steps"]["cleanup"]["status"] == "blocked"
    with pytest.raises(HostRunError):
        cleanup.require_cleaned(home)


def test_deletion_request_without_effect_is_reported_as_residue(tmp_path):
    ctx = _ready(tmp_path)
    home, base = ctx["home"], ctx["base"]

    class NoOpDelete(JsonBase):
        def delete(self, table, record_ids):
            return {"ok": True, "deleted": list(record_ids)}

    noop = NoOpDelete(tmp_path / "home" / "library" / "offline-base.json")
    noop.meta = base.meta
    noop.fields = base.fields
    noop.tables = base.tables

    result = cleanup.run(
        home,
        confirmed=True,
        client=noop,
        drive=ctx["drive"],
        messenger=lambda x: None,
        message_checker=_gone,
    )

    assert result["ok"] is False
    assert result["cleanup"]["residue"]
    assert smoke.load(home).get("cleaned_at") is None


def test_unreadable_table_blocks_cleanup_instead_of_claiming_success(tmp_path):
    ctx = _ready(tmp_path)
    home, base = ctx["home"], ctx["base"]
    questions_table = ctx["tables"]["questions"]

    class Unreadable(JsonBase):
        def list(self, table):
            if table == questions_table:
                raise RuntimeError("permission denied")
            return super().list(table)

    broken = Unreadable(tmp_path / "home" / "library" / "offline-base.json")
    broken.meta = base.meta
    broken.fields = base.fields
    broken.tables = base.tables

    result = cleanup.run(
        home,
        confirmed=True,
        client=broken,
        drive=ctx["drive"],
        messenger=lambda x: None,
        message_checker=_gone,
    )

    assert result["ok"] is False
    assert result["cleanup"]["read_errors"]
    assert smoke.load(home).get("cleaned_at") is None


def test_plan_is_read_only(tmp_path):
    ctx = _ready(tmp_path)
    before = len(ctx["base"].list(ctx["tables"]["cards"]))
    result = cleanup.plan(ctx["home"], client=ctx["base"])

    assert result["ok"] is True
    assert result["records"]["cards"] >= 1
    assert len(ctx["base"].list(ctx["tables"]["cards"])) == before


# ------------------------------------------------------- 报道 (papers) scope
def test_cleanup_removes_the_selected_test_paper_and_reports_the_count(tmp_path):
    ctx = _ready(tmp_path)
    home, base = ctx["home"], ctx["base"]

    planned = cleanup.plan(home, client=base)
    assert planned["records"]["papers"] == 1

    result = cleanup.run(
        home,
        confirmed=True,
        client=base,
        drive=ctx["drive"],
        messenger=lambda x: None,
        message_checker=_gone,
    )

    assert result["ok"] is True
    state = smoke.load(home)
    assert state["cleanup"]["removed_counts"]["papers"] == 1
    remaining = {
        row["fields"].get("paper_id") for row in base.list(ctx["tables"]["papers"])
    }
    assert remaining == {"paper_formal"}


def test_remaining_test_paper_row_blocks_cleanup(tmp_path):
    ctx = _ready(tmp_path)
    home, base = ctx["home"], ctx["base"]

    class StubbornPapers(JsonBase):
        def delete(self, table, record_ids):
            if table == ctx["tables"]["papers"]:
                return {"ok": True, "deleted": []}
            return super().delete(table, record_ids)

    stubborn = StubbornPapers(tmp_path / "home" / "library" / "offline-base.json")
    stubborn.meta = base.meta
    stubborn.fields = base.fields
    stubborn.tables = base.tables

    result = cleanup.run(
        home,
        confirmed=True,
        client=stubborn,
        drive=ctx["drive"],
        messenger=lambda x: None,
        message_checker=_gone,
    )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert any("papers" in line for line in result["cleanup"]["residue"])
    assert smoke.load(home).get("cleaned_at") is None
    with pytest.raises(HostRunError):
        cleanup.require_cleaned(home)


def test_undeletable_test_paper_row_blocks_cleanup(tmp_path):
    ctx = _ready(tmp_path)
    home, base = ctx["home"], ctx["base"]

    class RefusePapers(JsonBase):
        def delete(self, table, record_ids):
            if table == ctx["tables"]["papers"]:
                raise RuntimeError("permission denied")
            return super().delete(table, record_ids)

    refusing = RefusePapers(tmp_path / "home" / "library" / "offline-base.json")
    refusing.meta = base.meta
    refusing.fields = base.fields
    refusing.tables = base.tables

    result = cleanup.run(
        home,
        confirmed=True,
        client=refusing,
        drive=ctx["drive"],
        messenger=lambda x: None,
        message_checker=_gone,
    )

    assert result["ok"] is False
    assert any("papers" in line for line in result["cleanup"]["failed"])
    assert smoke.load(home).get("cleaned_at") is None


# --------------------------------------------- message recall read-back scope
def test_recalled_message_still_readable_blocks_cleanup(tmp_path):
    ctx = _ready(tmp_path)
    home = ctx["home"]
    checked = []

    def still_there(message_id):
        checked.append(message_id)
        return True

    result = cleanup.run(
        home,
        confirmed=True,
        client=ctx["base"],
        drive=ctx["drive"],
        messenger=lambda message_id: None,
        message_checker=still_there,
    )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert checked == [ctx["message"]]
    assert any(ctx["message"] in line for line in result["cleanup"]["residue"])
    assert smoke.load(home).get("cleaned_at") is None
    with pytest.raises(HostRunError):
        cleanup.require_cleaned(home)


def test_unverifiable_message_readback_blocks_cleanup(tmp_path):
    ctx = _ready(tmp_path)
    home = ctx["home"]

    def broken(message_id):
        raise RuntimeError("message read failed")

    result = cleanup.run(
        home,
        confirmed=True,
        client=ctx["base"],
        drive=ctx["drive"],
        messenger=lambda message_id: None,
        message_checker=broken,
    )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert any(ctx["message"] in line for line in result["cleanup"]["failed"])
    assert smoke.load(home).get("cleaned_at") is None
    with pytest.raises(HostRunError):
        cleanup.require_cleaned(home)


def test_cleanup_reports_per_scope_delete_counts(tmp_path):
    ctx = _ready(tmp_path)
    home = ctx["home"]

    result = cleanup.run(
        home,
        confirmed=True,
        client=ctx["base"],
        drive=ctx["drive"],
        messenger=lambda message_id: None,
        message_checker=_gone,
    )

    assert result["ok"] is True
    counts = result["cleanup"]["counts"]
    assert counts["base_records"] == 7
    assert counts["messages"] == 1
    assert counts["drive_files"] == 1
    assert counts["local_files"] == 3
    assert counts["queue_items"] == 2
    # per-table detail survives next to the per-scope totals
    assert result["cleanup"]["removed"]["papers"]["record_ids"]

    state = smoke.load(home)
    assert state["cleanup"]["counts"] == counts
    state_file = json.loads((home / "install" / "state.json").read_text(encoding="utf-8"))
    evidence = state_file["steps"]["cleanup"]["evidence"]
    assert evidence["counts"] == counts

    # rerun after success deletes nothing and keeps the recorded counts
    again = cleanup.run(
        home,
        confirmed=True,
        client=ctx["base"],
        drive=ctx["drive"],
        messenger=lambda message_id: None,
        message_checker=_gone,
    )
    assert again["already_cleaned"] is True
    assert again["ok"] is True
    assert smoke.load(home)["cleanup"]["counts"] == counts


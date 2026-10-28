"""Temporary acceptance: tagged card, ordered steps, verification, failure gate."""

import json
from pathlib import Path

import pytest

from hostrun import smoke
from hostrun.base import HostRunError
from library.drive import FixtureDrive
from library.offline import JsonBase
from writer.render import CAPTION_LABELS, SECTION_LABELS


def _plan_file(directory, count: int = 2):
    path = Path(directory) / "candidates.jsonl"
    path.write_text(
        "\n".join(json.dumps({"paper_id": f"p{index}"}) for index in range(count))
        + "\n",
        encoding="utf-8",
    )
    return path


def _rendered_file(directory, name: str = "push.html"):
    path = Path(directory) / name
    sections = "".join(f"<h2>{label}</h2>" for label in SECTION_LABELS.values())
    captions = "".join(
        f'<span class="source-pill">{label}</span>'
        for label in CAPTION_LABELS.values()
    )
    path.write_text(sections + captions, encoding="utf-8")
    return path


def _home(tmp_path) -> Path:

    home = tmp_path / "home"
    (home / "knowledge").mkdir(parents=True)
    (home / "knowledge" / "base.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "base_token": "basoffline",
                "base_url": "https://example.feishu.cn/base/basoffline",
                "tables": {},
            }
        ),
        encoding="utf-8",
    )
    return home


OWNER = "ou_owner"


def _verifier(open_id: str = OWNER):
    """Offline stand-in for lark.user_open_id: never spawns the real CLI."""
    return lambda cli: {"ok": True, "open_id": open_id}


def _start(home, client=None, keyword="虚拟细胞", *, owner=OWNER, verifier=None, confirmed=True):
    return smoke.start(
        home,
        keyword,
        owner=owner,
        confirmed=confirmed,
        client=client,
        verifier=verifier or _verifier(owner),
    )


def _write_push(home, push_id="push_1", papers=("paper_1",), **extra) -> Path:
    path = Path(home) / "archive" / "pushes" / f"{push_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"push_id": push_id, "paper_ids": list(papers), **extra}),
        encoding="utf-8",
    )
    return path


def _seed_answer(home, item="q_1", *, verdict="great", decision="agree_all", owner=OWNER):
    """The unified queue holds the user's own card submission."""
    root = Path(home) / "queue"
    root.mkdir(parents=True, exist_ok=True)
    (root / "state.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_id": None,
                "items": [
                    {
                        "id": item,
                        "kind": "rating",
                        "push_id": "p_1",
                        "status": "answered",
                        "answer": {
                            "verdict": verdict,
                            "decision": decision,
                            "operator_id": owner,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "events.jsonl").touch()


def _record_rendered(home, directory, *, push="push_1", papers=("paper_1",), html=None):
    _write_push(home, push, papers)
    return smoke.record(
        home,
        "rendered",
        push=push,
        html=str(html if html is not None else _rendered_file(directory)),
    )


def _base(tmp_path) -> JsonBase:
    base = JsonBase(tmp_path / "home" / "library" / "offline-base.json")
    base.meta = []
    base.fields = {}
    base.tables = {}
    return base


def _seed_tables(home: Path, base: JsonBase) -> dict:
    from hostrun import kb

    drive = FixtureDrive()
    report = kb.create_tables(home, client=base, drive=drive)
    return json.loads((home / "knowledge" / "base.json").read_text(encoding="utf-8"))


def test_start_creates_tagged_card_locally_and_in_base(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)

    result = _start(home, base)

    assert result["ok"] is True
    card_id = result["card"]["id"]
    assert card_id.startswith("card_smoke_")
    assert (home / "archive" / "cards" / f"{card_id}.json").exists()
    cards_table = json.loads((home / "knowledge" / "base.json").read_text(encoding="utf-8"))["tables"]["cards"]
    rows = base.list(cards_table)
    assert rows[0]["fields"]["卡片 ID"] == card_id
    state = smoke.load(home)
    assert state["test_id"].startswith("smoke_")
    assert state["artifacts"]["record_ids"] == [rows[0]["record_id"]]


def test_start_requires_confirmation_and_a_keyword(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)

    assert _start(home, base, keyword="x", confirmed=False)["reason"] == "needs_user_confirmation"
    with pytest.raises(HostRunError):
        smoke.start(home, "  ", owner=OWNER, confirmed=True, client=base, verifier=_verifier())


def test_start_blocks_when_formal_queue_is_unfinished(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    queue_dir = home / "queue"
    queue_dir.mkdir(parents=True)
    (queue_dir / "state.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_id": "q_formal",
                "items": [
                    {
                        "id": "q_formal",
                        "kind": "push_rating",
                        "status": "active",
                        "push_id": "push_formal",
                        "payload": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = _start(home, base, keyword="x")

    assert result["ok"] is False
    assert result["reason"] == "queue_busy"


def test_plan_contains_only_the_temporary_card(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    # a formal local card must not be re-scoped by the test plan
    formal = home / "archive" / "cards" / "card_formal.json"
    formal.parent.mkdir(parents=True, exist_ok=True)
    formal.write_text(
        json.dumps(
            {
                "id": "card_formal",
                "label": "正式卡片",
                "ontology": ["hmbs"],
                "annotation": "⛔ x ⚠️ y",
            }
        ),
        encoding="utf-8",
    )
    started = _start(home, base)

    plan = smoke.plan(home)

    assert plan["queries"]
    assert {row["card_id"] for row in plan["queries"]} == {started["card"]["id"]}
    assert plan["smoke"] == started["test_id"]


def test_steps_are_ordered_and_success_needs_a_real_read_back(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    config = _seed_tables(home, base)
    started = _start(home, base)
    card_id = started["card"]["id"]

    with pytest.raises(HostRunError):
        smoke.record(home, "sent", push="push_1", message="om_1", question="q_1")
    smoke.record(home, "retrieved", plan=str(_plan_file(tmp_path, 3)))
    smoke.record(home, "written", papers=["paper_1"])
    _record_rendered(home, tmp_path)
    with pytest.raises(HostRunError):
        smoke.record(home, "sent", push="push_1")
    smoke.record(home, "sent", push="push_1", message="om_1", question="q_1")
    _seed_answer(home)
    smoke.record(home, "rated", item="q_1", verdict="great")
    smoke.record(home, "decided", item="q_1", decision="agree_all")
    smoke.record(home, "applied")
    with pytest.raises(HostRunError):
        smoke.require_success(home)

    cards_table = config["tables"]["cards"]
    row = base.list(cards_table)[0]
    base.update(cards_table, {row["record_id"]: {"label": "[已采纳] 虚拟细胞"}})

    result = smoke.verify(
        home,
        target_key="cards",
        target_id=card_id,
        field="label",
        expected="[已采纳] 虚拟细胞",
        client=base,
    )

    assert result["ok"] is True
    assert result["status"] == "complete"
    state = smoke.load(home)
    assert state["artifacts"]["push_ids"] == ["push_1"]
    assert smoke.status(home)["ok"] is True


def test_verification_mismatch_fails_and_never_opens_formal_init(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    started = _start(home, base)
    smoke.record(home, "retrieved", plan=str(_plan_file(tmp_path)))
    smoke.record(home, "written", papers=["paper_1"])
    _record_rendered(home, tmp_path)
    smoke.record(home, "sent", push="p", message="m", question="q")
    _seed_answer(home, "q", verdict="ok", decision="adopt")
    smoke.record(home, "rated", item="q", verdict="ok")
    smoke.record(home, "decided", item="q", decision="adopt")
    smoke.record(home, "applied")

    result = smoke.verify(
        home,
        target_key="cards",
        target_id=started["card"]["id"],
        field="label",
        expected="并未写入的内容",
        client=base,
    )

    assert result["ok"] is False
    assert smoke.load(home)["status"] == "failed"
    with pytest.raises(HostRunError):
        smoke.require_success(home)
    state = json.loads((home / "install" / "state.json").read_text(encoding="utf-8"))
    assert state["steps"]["test_loop"]["status"] == "blocked"


def test_verification_refuses_to_touch_formal_knowledge(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    _start(home, base)
    smoke.record(home, "retrieved", plan=str(_plan_file(tmp_path)))
    smoke.record(home, "written", papers=["paper_1"])
    _record_rendered(home, tmp_path)
    smoke.record(home, "sent", push="p", message="m", question="q")
    _seed_answer(home, "q", verdict="ok", decision="adopt")
    smoke.record(home, "rated", item="q", verdict="ok")
    smoke.record(home, "decided", item="q", decision="adopt")
    smoke.record(home, "applied")

    result = smoke.verify(
        home,
        target_key="cards",
        target_id="card_formal_existing",
        field="label",
        expected="x",
        client=base,
    )

    assert result["ok"] is False
    assert smoke.load(home)["status"] == "failed"


def test_failed_base_write_removes_the_local_card(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)

    class Broken(JsonBase):
        def create(self, table, rows):
            raise RuntimeError("permission denied")

    result = _start(home, Broken(tmp_path / "broken.json"))

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert not list((home / "archive" / "cards").glob("card_smoke_*.json"))
    with pytest.raises(HostRunError):
        smoke.require_success(home)


def test_second_start_is_refused_until_the_first_is_cleaned(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    _start(home, base)

    second = _start(home, base, keyword="另一个")

    assert second["ok"] is False
    assert second["reason"] == "test_in_progress"


# ------------------------------------------------ real retrieval and selection
def test_retrieved_requires_a_real_retrieval_artifact(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    _start(home, base)

    with pytest.raises(HostRunError):
        smoke.record(home, "retrieved")
    with pytest.raises(HostRunError):
        smoke.record(home, "retrieved", plan=str(tmp_path / "missing.jsonl"))
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(HostRunError):
        smoke.record(home, "retrieved", plan=str(empty))

    plan = _plan_file(tmp_path, 3)
    with pytest.raises(HostRunError):
        smoke.record(home, "retrieved", plan=str(plan), candidates=2)

    result = smoke.record(home, "retrieved", plan=str(plan))

    assert result["ok"] is True
    state = smoke.load(home)
    assert state["artifacts"]["candidates"] == 3
    assert state["artifacts"]["plan"] == str(plan)
    evidence = state["steps"]["retrieved"]["evidence"]
    assert evidence["candidates"] == 3
    assert evidence["plan"] == str(plan)


def test_written_requires_a_selected_paper_id(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    _start(home, base)
    smoke.record(home, "retrieved", plan=str(_plan_file(tmp_path)))

    with pytest.raises(HostRunError):
        smoke.record(home, "written")
    with pytest.raises(HostRunError):
        smoke.record(home, "written", papers=[])

    result = smoke.record(home, "written", papers=["paper_a", "paper_b"])

    assert result["ok"] is True
    state = smoke.load(home)
    assert state["artifacts"]["paper_ids"] == ["paper_a", "paper_b"]
    assert state["steps"]["written"]["evidence"]["papers"] == ["paper_a", "paper_b"]


def test_missing_facilities_is_reported_and_retryable(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    base = _base(tmp_path)

    first = _start(home, base)

    assert first["ok"] is False
    assert first["reason"] == "facilities_missing"
    assert first["retryable"] is True
    assert first["note"]
    assert not (home / "install" / "smoke.json").exists()
    assert not (home / "install" / "state.json").exists()

    (home / "knowledge").mkdir(parents=True)
    (home / "knowledge" / "base.json").write_text(
        json.dumps({"schema_version": 1, "base_token": "basoffline", "tables": {}}),
        encoding="utf-8",
    )
    _seed_tables(home, base)

    second = _start(home, base)

    assert second["ok"] is True
    assert second["status"] == "running"


def test_cli_record_accepts_retrieval_and_selection_evidence(tmp_path):
    from hostrun import cli

    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    _start(home, base)

    refused = cli.main(
        ["--home", str(home), "smoke", "record", "--step", "retrieved"]
    )
    assert refused == 1

    plan = _plan_file(tmp_path, 2)
    assert (
        cli.main(
            [
                "--home",
                str(home),
                "smoke",
                "record",
                "--step",
                "retrieved",
                "--candidates",
                "2",
                "--plan",
                str(plan),
            ]
        )
        == 0
    )
    assert (
        cli.main(
            [
                "--home",
                str(home),
                "smoke",
                "record",
                "--step",
                "written",
                "--paper",
                "paper_1",
            ]
        )
        == 0
    )
    state = smoke.load(home)
    assert state["artifacts"]["paper_ids"] == ["paper_1"]
    assert state["steps"]["retrieved"]["evidence"]["candidates"] == 2


# ------------------------------------------------- rendered / verify evidence
def _run_to_applied(home, base, *, applied_fields=None, targets=None):
    started = _start(home, base)
    smoke.record(home, "retrieved", plan=str(_plan_file(home.parent)))
    smoke.record(home, "written", papers=["paper_1"])
    _record_rendered(home, home.parent)
    smoke.record(home, "sent", push="p_1", message="m_1", question="q_1")
    _seed_answer(home)
    smoke.record(home, "rated", item="q_1", verdict="great")
    smoke.record(home, "decided", item="q_1", decision="agree_all")
    applied_kwargs = {}
    if applied_fields:
        applied_kwargs["applied_fields"] = applied_fields
    if targets:
        applied_kwargs["targets"] = targets
    smoke.record(home, "applied", **applied_kwargs)
    return started


def _accepted_card(config, base):
    cards_table = config["tables"]["cards"]
    row = base.list(cards_table)[0]
    base.update(
        cards_table,
        {
            row["record_id"]: {
                "label": "[已采纳] 虚拟细胞",
                "annotation": "[已采纳] 注释",
            }
        },
    )
    return row


def test_rendered_requires_a_valid_render_artifact(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    _start(home, base)
    smoke.record(home, "retrieved", plan=str(_plan_file(tmp_path)))
    smoke.record(home, "written", papers=["paper_1"])

    with pytest.raises(HostRunError):
        smoke.record(home, "rendered")
    good = _rendered_file(tmp_path)
    with pytest.raises(HostRunError):
        smoke.record(home, "rendered", html=str(good))
    with pytest.raises(HostRunError):
        smoke.record(home, "rendered", push="push_1")
    with pytest.raises(HostRunError):
        smoke.record(home, "rendered", push="push_1", html=str(tmp_path / "gone.html"))
    incomplete = tmp_path / "incomplete.html"
    incomplete.write_text("<h2>一句话结论</h2><span>原文图</span>", encoding="utf-8")
    with pytest.raises(HostRunError):
        smoke.record(home, "rendered", push="push_1", html=str(incomplete))

    missing = smoke.record(home, "rendered", push="push_1", html=str(good))
    assert missing["ok"] is False
    assert missing["reason"] == "push_record_missing"

    _write_push(home, "push_1", ["paper_1"])
    result = smoke.record(home, "rendered", push="push_1", html=str(good))

    assert result["ok"] is True
    state = smoke.load(home)
    assert state["artifacts"]["push_ids"] == ["push_1"]
    assert state["artifacts"]["push_html"] == str(good)
    assert state["steps"]["rendered"]["evidence"]["html"] == str(good)


def test_decided_cannot_be_recorded_before_the_user_rates(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    _start(home, base)
    smoke.record(home, "retrieved", plan=str(_plan_file(tmp_path)))
    smoke.record(home, "written", papers=["paper_1"])
    _record_rendered(home, tmp_path)
    smoke.record(home, "sent", push="p_1", message="m_1", question="q_1")

    with pytest.raises(HostRunError):
        smoke.record(home, "decided", item="q_1", decision="agree_all")

    _seed_answer(home)
    smoke.record(home, "rated", item="q_1", verdict="great")
    smoke.record(home, "decided", item="q_1", decision="agree_all")

    assert "decided" in smoke.load(home)["steps"]


def test_verify_retains_every_field_check_and_fails_on_a_later_mismatch(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    config = _seed_tables(home, base)
    started = _run_to_applied(home, base)
    card_id = started["card"]["id"]
    _accepted_card(config, base)

    first = smoke.verify(
        home,
        target_key="cards",
        target_id=card_id,
        field="label",
        expected="[已采纳] 虚拟细胞",
        client=base,
    )
    second = smoke.verify(
        home,
        target_key="cards",
        target_id=card_id,
        checks=[("annotation", "[已采纳] 注释")],
        client=base,
    )

    assert first["ok"] is True and second["ok"] is True
    checks = smoke.load(home)["steps"]["verified"]["checks"]
    assert [check["field"] for check in checks] == ["label", "annotation"]
    assert all(check["ok"] for check in checks)

    mismatch = smoke.verify(
        home,
        target_key="cards",
        target_id=card_id,
        checks=[("annotation", "不同值")],
        client=base,
    )

    assert mismatch["ok"] is False
    state = smoke.load(home)
    assert state["status"] == "failed"
    assert [check["field"] for check in state["steps"]["verified"]["checks"]] == [
        "label",
        "annotation",
    ]


def test_cli_verify_accepts_repeated_field_checks(tmp_path):
    from hostrun import cli

    home = _home(tmp_path)
    base = _base(tmp_path)
    config = _seed_tables(home, base)
    started = _run_to_applied(home, base)
    card_id = started["card"]["id"]
    _accepted_card(config, base)

    code = cli.main(
        [
            "--home",
            str(home),
            "--offline",
            "smoke",
            "verify",
            "--target-key",
            "cards",
            "--target-id",
            card_id,
            "--field",
            "label=[已采纳] 虚拟细胞",
            "--field",
            "annotation=[已采纳] 注释",
        ]
    )

    assert code == 0
    checks = smoke.load(home)["steps"]["verified"]["checks"]
    assert [check["field"] for check in checks] == ["label", "annotation"]
    assert [check["expected"] for check in checks] == [
        "[已采纳] 虚拟细胞",
        "[已采纳] 注释",
    ]

    # legacy --field/--expected remains accepted and updates that field in place
    assert (
        cli.main(
            [
                "--home",
                str(home),
                "--offline",
                "smoke",
                "verify",
                "--target-key",
                "cards",
                "--target-id",
                card_id,
                "--field",
                "label",
                "--expected",
                "[已采纳] 虚拟细胞",
            ]
        )
        == 0
    )
    checks = smoke.load(home)["steps"]["verified"]["checks"]
    assert len(checks) == 2


# --------------------------------------- applied target/field coverage (spec #56)
def test_applied_fields_must_all_be_verified_for_the_loop_to_complete(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    config = _seed_tables(home, base)
    started = _run_to_applied(
        home, base, applied_fields=["label", "annotation"]
    )
    card_id = started["card"]["id"]
    _accepted_card(config, base)

    partial = smoke.verify(
        home,
        target_key="cards",
        target_id=card_id,
        field="label",
        expected="[已采纳] 虚拟细胞",
        client=base,
    )

    assert partial["ok"] is False
    assert partial["reason"] == "verification_incomplete"
    assert any(row["field"] == "annotation" for row in partial["missing_checks"])
    assert smoke.status(home)["ok"] is False
    assert smoke.load(home)["steps"]["verified"]["complete"] is False
    state_file = json.loads((home / "install" / "state.json").read_text(encoding="utf-8"))
    assert state_file["steps"]["test_loop"]["status"] != "ok"

    both = smoke.verify(
        home,
        target_key="cards",
        target_id=card_id,
        checks=[("annotation", "[已采纳] 注释")],
        client=base,
    )

    assert both["ok"] is True
    assert both["status"] == "complete"
    assert both["applied_fields"] == ["label", "annotation"]
    assert smoke.load(home)["steps"]["verified"]["complete"] is True
    assert smoke.status(home)["ok"] is True
    state_file = json.loads((home / "install" / "state.json").read_text(encoding="utf-8"))
    assert state_file["steps"]["test_loop"]["status"] == "ok"


def test_applied_target_without_fields_needs_at_least_one_check(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    config = _seed_tables(home, base)
    started = _run_to_applied(home, base)
    card_id = started["card"]["id"]
    _accepted_card(config, base)

    state = smoke.load(home)
    assert state["artifacts"]["applied_targets"] == [
        {"target": card_id, "fields": []}
    ]

    result = smoke.verify(
        home,
        target_key="cards",
        target_id=card_id,
        field="label",
        expected="[已采纳] 虚拟细胞",
        client=base,
    )

    assert result["ok"] is True
    assert result["status"] == "complete"


def test_cli_record_applied_captures_targets_and_fields(tmp_path):
    from hostrun import cli

    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    started = _start(home, base)
    card_id = started["card"]["id"]
    smoke.record(home, "retrieved", plan=str(_plan_file(tmp_path)))
    smoke.record(home, "written", papers=["paper_1"])
    _record_rendered(home, tmp_path)
    smoke.record(home, "sent", push="p_1", message="m_1", question="q_1")
    _seed_answer(home)
    smoke.record(home, "rated", item="q_1", verdict="great")
    smoke.record(home, "decided", item="q_1", decision="agree_all")

    code = cli.main(
        [
            "--home",
            str(home),
            "smoke",
            "record",
            "--step",
            "applied",
            "--target",
            card_id,
            "--applied-field",
            "label",
            "--applied-field",
            "annotation",
        ]
    )

    assert code == 0
    state = smoke.load(home)
    assert state["artifacts"]["applied_targets"] == [
        {"target": card_id, "fields": ["label", "annotation"]}
    ]


# ------------------------------------------- recipient verification (spec #56)
def test_start_requires_a_verified_owner_and_persists_the_recipient(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)

    empty = smoke.start(home, "虚拟细胞", confirmed=True, client=base, verifier=_verifier())
    assert empty["ok"] is False
    assert empty["reason"] == "recipient_unverified"
    assert not (home / "install" / "smoke.json").exists()

    unready = _start(home, base, verifier=lambda cli: {"ok": False, "open_id": ""})
    assert unready["reason"] == "recipient_unverified"
    assert not (home / "install" / "smoke.json").exists()

    mismatch = _start(home, base, verifier=_verifier("ou_someone_else"))
    assert mismatch["reason"] == "recipient_mismatch"
    assert mismatch["mismatch"] is True
    # the authenticated open id is never echoed back
    assert "ou_someone_else" not in json.dumps(mismatch, ensure_ascii=False)
    assert not (home / "install" / "smoke.json").exists()

    result = _start(home, base)
    assert result["ok"] is True
    assert result["owner"] == OWNER
    assert result["owner_verified"] is True
    config = json.loads((home / "install" / "config.json").read_text(encoding="utf-8"))
    assert config["permissions"]["owner"] == OWNER


def test_start_verifies_with_the_recorded_cli_and_never_guesses(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    binary = tmp_path / "private-bin" / "lark-cli"
    binary.parent.mkdir(parents=True)
    binary.write_text("", encoding="utf-8")
    (home / "install").mkdir(parents=True, exist_ok=True)
    (home / "install" / "config.json").write_text(
        json.dumps({"schema_version": 1, "paths": {"lark_cli": str(binary)}}),
        encoding="utf-8",
    )
    seen = {}

    def verifier(cli):
        seen["cli"] = cli
        return {"ok": True, "open_id": OWNER}

    assert _start(home, base, verifier=verifier)["ok"] is True
    assert seen["cli"] == str(binary)

    other = _home(tmp_path / "bare")
    other_base = _base(tmp_path / "bare")
    _seed_tables(other, other_base)
    (other / "install").mkdir(parents=True, exist_ok=True)
    (other / "install" / "config.json").write_text(
        json.dumps({"schema_version": 1, "paths": {"lark_cli": "lark-cli"}}),
        encoding="utf-8",
    )
    bare_seen = {}

    def bare_verifier(cli):
        bare_seen["cli"] = cli
        return {"ok": True, "open_id": OWNER}

    _start(other, other_base, verifier=bare_verifier)
    # a bare name would be a silent PATH guess, so no CLI is passed through
    assert bare_seen["cli"] is None


def test_brief_uses_the_verified_recipient_and_registers_the_push_first(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    _start(home, base)

    brief = smoke.brief(home)
    text = "\n".join(brief["steps"])

    assert brief["recipient"] == OWNER
    assert "<owner>" not in text
    assert f"--to {OWNER}" in text
    assert text.index("archive.cli add-push") < text.index("--step rendered")
    assert "feedback submit --item" not in text


# ------------------------------------------- user submission gate (spec #56)
def _to_sent(home, base, tmp_path):
    started = _start(home, base)
    smoke.record(home, "retrieved", plan=str(_plan_file(tmp_path)))
    smoke.record(home, "written", papers=["paper_1"])
    _record_rendered(home, tmp_path)
    smoke.record(home, "sent", push="p_1", message="m_1", question="q_1")
    return started


def test_rated_requires_the_owner_to_have_answered(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    _to_sent(home, base, tmp_path)

    unanswered = smoke.record(home, "rated", item="q_1", verdict="great")

    assert unanswered["ok"] is False
    assert unanswered["reason"] == "rating_not_submitted"
    assert "rated" not in smoke.load(home)["steps"]

    _seed_answer(home, owner="ou_other")
    other = smoke.record(home, "rated", item="q_1", verdict="great")
    assert other["reason"] == "rating_not_by_user"

    _seed_answer(home, verdict="ok")
    mismatch = smoke.record(home, "rated", item="q_1", verdict="great")
    assert mismatch["reason"] == "rating_mismatch"

    _seed_answer(home, verdict="great")
    accepted = smoke.record(home, "rated", item="q_1", verdict="great")
    assert accepted["ok"] is True
    assert "rated" in smoke.load(home)["steps"]


def test_decided_requires_the_owner_to_have_adopted(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    _to_sent(home, base, tmp_path)
    _seed_answer(home, verdict="great", decision="agree_all")
    smoke.record(home, "rated", item="q_1", verdict="great")

    unanswered = smoke.record(home, "decided", item="missing_item", decision="agree_all")
    assert unanswered["reason"] == "decision_not_submitted"

    _seed_answer(home, decision="reject_all")
    mismatch = smoke.record(home, "decided", item="q_1", decision="agree_all")
    assert mismatch["reason"] == "decision_mismatch"

    _seed_answer(home, decision="agree_all")
    accepted = smoke.record(home, "decided", item="q_1", decision="agree_all")
    assert accepted["ok"] is True


def test_decided_refuses_an_answer_from_someone_else(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    _to_sent(home, base, tmp_path)
    _seed_answer(home, owner=OWNER)
    smoke.record(home, "rated", item="q_1", verdict="great")

    _seed_answer(home, owner="ou_other")
    result = smoke.record(home, "decided", item="q_1", decision="agree_all")

    assert result["reason"] == "decision_not_by_user"


# ------------------------------------- rendered push registration (spec #56)
def test_rendered_refuses_an_unregistered_push_id(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    _start(home, base)
    smoke.record(home, "retrieved", plan=str(_plan_file(tmp_path)))
    smoke.record(home, "written", papers=["paper_1"])

    result = smoke.record(
        home, "rendered", push="push_unknown", html=str(_rendered_file(tmp_path))
    )

    assert result["ok"] is False
    assert result["reason"] == "push_record_missing"
    assert "rendered" not in smoke.load(home)["steps"]


def test_rendered_refuses_a_push_record_for_another_test(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    _start(home, base)
    smoke.record(home, "retrieved", plan=str(_plan_file(tmp_path)))
    smoke.record(home, "written", papers=["paper_1"])
    _write_push(home, "push_other", ["paper_unrelated"])

    result = smoke.record(
        home, "rendered", push="push_other", html=str(_rendered_file(tmp_path))
    )

    assert result["ok"] is False
    assert result["reason"] == "push_record_mismatch"
    assert "rendered" not in smoke.load(home)["steps"]


def test_rendered_accepts_the_registered_push_for_this_test(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    started = _start(home, base)
    smoke.record(home, "retrieved", plan=str(_plan_file(tmp_path)))
    smoke.record(home, "written", papers=["paper_1"])
    # a test-id marker is enough even without overlapping paper ids
    _write_push(home, "push_new", ["paper_elsewhere"], test_id=started["test_id"])

    result = smoke.record(
        home, "rendered", push="push_new", html=str(_rendered_file(tmp_path))
    )

    assert result["ok"] is True

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

    result = smoke.start(home, "虚拟细胞", owner="ou_owner", confirmed=True, client=base)

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

    assert smoke.start(home, "x", confirmed=False, client=base)["reason"] == "needs_user_confirmation"
    with pytest.raises(HostRunError):
        smoke.start(home, "  ", confirmed=True, client=base)


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
    result = smoke.start(home, "x", confirmed=True, client=base)

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
    started = smoke.start(home, "虚拟细胞", confirmed=True, client=base)

    plan = smoke.plan(home)

    assert plan["queries"]
    assert {row["card_id"] for row in plan["queries"]} == {started["card"]["id"]}
    assert plan["smoke"] == started["test_id"]


def test_steps_are_ordered_and_success_needs_a_real_read_back(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    config = _seed_tables(home, base)
    started = smoke.start(home, "虚拟细胞", confirmed=True, client=base)
    card_id = started["card"]["id"]

    with pytest.raises(HostRunError):
        smoke.record(home, "sent", push="push_1", message="om_1", question="q_1")
    smoke.record(home, "retrieved", plan=str(_plan_file(tmp_path, 3)))
    smoke.record(home, "written", papers=["paper_1"])
    smoke.record(home, "rendered", push="push_1", html=str(_rendered_file(tmp_path)))
    with pytest.raises(HostRunError):
        smoke.record(home, "sent", push="push_1")
    smoke.record(home, "sent", push="push_1", message="om_1", question="q_1")
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
    started = smoke.start(home, "虚拟细胞", confirmed=True, client=base)
    smoke.record(home, "retrieved", plan=str(_plan_file(tmp_path)))
    smoke.record(home, "written", papers=["paper_1"])
    smoke.record(home, "rendered", push="push_1", html=str(_rendered_file(tmp_path)))
    smoke.record(home, "sent", push="p", message="m", question="q")
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
    smoke.start(home, "虚拟细胞", confirmed=True, client=base)
    smoke.record(home, "retrieved", plan=str(_plan_file(tmp_path)))
    smoke.record(home, "written", papers=["paper_1"])
    smoke.record(home, "rendered", push="push_1", html=str(_rendered_file(tmp_path)))
    smoke.record(home, "sent", push="p", message="m", question="q")
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

    result = smoke.start(home, "虚拟细胞", confirmed=True, client=Broken(tmp_path / "broken.json"))

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert not list((home / "archive" / "cards").glob("card_smoke_*.json"))
    with pytest.raises(HostRunError):
        smoke.require_success(home)


def test_second_start_is_refused_until_the_first_is_cleaned(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    smoke.start(home, "虚拟细胞", confirmed=True, client=base)

    second = smoke.start(home, "另一个", confirmed=True, client=base)

    assert second["ok"] is False
    assert second["reason"] == "test_in_progress"


# ------------------------------------------------ real retrieval and selection
def test_retrieved_requires_a_real_retrieval_artifact(tmp_path):
    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    smoke.start(home, "虚拟细胞", confirmed=True, client=base)

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
    smoke.start(home, "虚拟细胞", confirmed=True, client=base)
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

    first = smoke.start(home, "虚拟细胞", confirmed=True, client=base)

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

    second = smoke.start(home, "虚拟细胞", confirmed=True, client=base)

    assert second["ok"] is True
    assert second["status"] == "running"


def test_cli_record_accepts_retrieval_and_selection_evidence(tmp_path):
    from hostrun import cli

    home = _home(tmp_path)
    base = _base(tmp_path)
    _seed_tables(home, base)
    smoke.start(home, "虚拟细胞", confirmed=True, client=base)

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
def _run_to_applied(home, base):
    started = smoke.start(home, "虚拟细胞", confirmed=True, client=base)
    smoke.record(home, "retrieved", plan=str(_plan_file(home.parent)))
    smoke.record(home, "written", papers=["paper_1"])
    smoke.record(home, "rendered", push="push_1", html=str(_rendered_file(home.parent)))
    smoke.record(home, "sent", push="p_1", message="m_1", question="q_1")
    smoke.record(home, "rated", item="q_1", verdict="great")
    smoke.record(home, "decided", item="q_1", decision="agree_all")
    smoke.record(home, "applied")
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
    smoke.start(home, "虚拟细胞", confirmed=True, client=base)
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
    smoke.start(home, "虚拟细胞", confirmed=True, client=base)
    smoke.record(home, "retrieved", plan=str(_plan_file(tmp_path)))
    smoke.record(home, "written", papers=["paper_1"])
    smoke.record(home, "rendered", push="push_1", html=str(_rendered_file(tmp_path)))
    smoke.record(home, "sent", push="p_1", message="m_1", question="q_1")

    with pytest.raises(HostRunError):
        smoke.record(home, "decided", item="q_1", decision="agree_all")

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

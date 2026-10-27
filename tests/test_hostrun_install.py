"""Install self-check: honest statuses, resumable state, no credential leakage."""

import json
import os
from pathlib import Path

import pytest

from hostrun import cli, install
from hostrun import workspace as workspace_mod
from hostrun.base import HostRunError, resolve_executable


def _host(**over):
    payload = {
        "product": "WorkBuddy",
        "version": "1.6.110",
        "mode": "desktop",
        "local_execution": True,
        "schedules": True,
        "permissions": ["shell", "file_write"],
    }
    payload.update(over)
    return payload


# ------------------------------------------------------------------ record
def test_ok_is_terminal_and_rechecks_do_not_erase_it(tmp_path):
    install.record(tmp_path, "host", "ok", note="首次确认")
    install.record(tmp_path, "host", "blocked", note="复检失败")

    entry = install.load_state(tmp_path)["steps"]["host"]
    assert entry["status"] == "ok"
    assert entry["note"] == "首次确认"
    assert entry["first_ok_at"]


def test_record_rejects_unknown_step_and_status(tmp_path):
    with pytest.raises(HostRunError):
        install.record(tmp_path, "nope", "ok")
    with pytest.raises(HostRunError):
        install.record(tmp_path, "host", "probably")


def test_state_is_resumable_across_calls(tmp_path):
    install.record(tmp_path, "host", "ok")
    install.record(tmp_path, "workspace", "ok")
    install.record(tmp_path, "dependencies", "ok")
    install.record(tmp_path, "skill", "ok")
    install.record(tmp_path, "lark_cli", "blocked", note="未安装")

    assert install.next_step(tmp_path) == "lark_cli"
    status = install.step_status(tmp_path)
    assert status["host"] == "ok"
    assert status["facilities"] == "pending"

    # a fresh call reads the same state from disk
    assert install.summary(tmp_path)["steps"]["lark_cli"] == "blocked"


def test_report_separates_working_blocked_untested(tmp_path):
    install.record(tmp_path, "host", "ok")
    install.record(tmp_path, "dependencies", "ok")
    install.record(tmp_path, "lark_cli", "blocked", note="飞书 CLI 未找到")
    install.record(tmp_path, "identity", "untested", note="未验证")

    report = install.report(tmp_path)
    assert report["ok"] is False
    assert report["partial"] is False
    assert report["working"] == ["host", "dependencies"]
    assert [row["step"] for row in report["blocked"]] == ["lark_cli"]
    assert [row["step"] for row in report["untested"]] == ["identity"]
    assert any("飞书 CLI" in line for line in report["limitations"])


def test_report_never_contains_credentials(tmp_path):
    install.record(
        tmp_path,
        "identity",
        "ok",
        note="user 与 bot 身份均可用",
        evidence={"user_token": "u-secret", "bot_secret": "b-secret", "user_ready": True},
    )
    report = install.report(tmp_path)
    blob = json.dumps(report, ensure_ascii=False)
    assert "u-secret" not in blob and "b-secret" not in blob
    assert report["steps"]["identity"]["evidence"]["user_ready"] is True


# ------------------------------------------------------------------ probes
def test_probe_host_asks_instead_of_assuming(tmp_path):
    pending = install.probe_host(None)
    assert pending["status"] == "pending"

    untested = install.probe_host({"product": "ChatGPT"})
    assert untested["status"] == "untested"

    ok = install.probe_host(_host())
    assert ok["status"] == "ok"
    assert ok["evidence"]["local_execution"] is True


def test_probe_dependencies_reports_the_missing_piece(tmp_path, monkeypatch):
    empty = tmp_path / "empty-repo"
    empty.mkdir()
    result = install.probe_dependencies(empty, python="python")
    assert result["status"] == "blocked"
    assert "skills/frontier-run/SKILL.md" in result["note"]

    good = Path(__file__).resolve().parents[1]
    result = install.probe_dependencies(good)
    assert result["status"] == "ok"
    assert result["evidence"]["python_version"].count(".") == 2
    assert isinstance(result["evidence"]["yaml"], bool)


def test_probe_identity_reads_booleans_only():
    payload = {
        "identities": {
            "user": {"available": True, "tokenStatus": "valid", "userOpenId": "ou_x"},
            "bot": {"available": True, "tokenStatus": "expired"},
        }
    }

    class Proc:
        returncode = 0
        stdout = json.dumps(payload)

    result = install.probe_identity("lark-cli", runner=lambda *a, **k: Proc())
    assert result["status"] == "blocked"
    assert "bot" in result["note"]
    assert result["evidence"]["user_ready"] is True
    assert result["evidence"]["bot_ready"] is False


def test_probe_identity_handles_unreadable_output():
    class Proc:
        returncode = 1
        stdout = "not json"

    result = install.probe_identity("lark-cli", runner=lambda *a, **k: Proc())
    assert result["status"] == "blocked"
    assert "auth status" in result["note"]


def test_resolve_executable_prefers_explicit_then_private(tmp_path, monkeypatch):
    private = tmp_path / "bin"
    private.mkdir()
    (private / "lark-cli").write_text("#!/bin/sh\n", encoding="utf-8")
    explicit = tmp_path / "explicit-cli"
    explicit.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setenv("PATH", "")
    assert resolve_executable(str(explicit), private_dirs=[private])["source"] == "explicit"
    assert resolve_executable(None, private_dirs=[private], names=["lark-cli"])["source"] == "private"
    assert resolve_executable(str(tmp_path / "missing"), private_dirs=[], names=["nope"])["found"] is False


# ------------------------------------------------------------------- check
def test_check_works_with_chinese_and_space_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    home = tmp_path / "我的 数据" / "home"
    home.mkdir(parents=True)

    result = install.check(home, repo=Path(__file__).resolve().parents[1], host=_host())

    assert result["steps"]["host"] == "ok"
    assert result["steps"]["dependencies"] == "ok"
    assert result["steps"]["lark_cli"] == "blocked"
    config = json.loads((home / "install" / "config.json").read_text(encoding="utf-8"))
    assert config["host"]["product"] == "WorkBuddy"
    assert config["timezone"]


def test_stale_evidence_flags_old_steps(tmp_path):
    install.record(tmp_path, "host", "ok")
    state = install.load_state(tmp_path)
    state["steps"]["host"]["at"] = "2020-01-01T00:00:00+00:00"
    install.save_state(tmp_path, state)

    assert "host" in install.stale_evidence(tmp_path, days=7)


# -------------------------------------------------- install toolchain step
def _fake_workspace(tmp_path):
    root = tmp_path / "ws"
    repo = root / "frontier"
    (repo / ".git").mkdir(parents=True)
    home = root / "frontier-archive"
    home.mkdir()
    workspace_mod.save_record(
        root,
        {
            "schema_version": 1,
            "root": str(root),
            "repo": str(repo),
            "home": str(home),
            "repo_url": workspace_mod.DEFAULT_REPO_URL,
            "commit": "abc123",
        },
    )
    return root, repo, home


def test_toolchain_step_blocks_with_a_repair_command_then_recovers(
    tmp_path, monkeypatch
):
    root, repo, home = _fake_workspace(tmp_path)
    repair = (
        f'python -m hostrun.cli --home "{home}" install toolchain '
        f'--root "{root}" --clear'
    )
    blocked = {
        "ok": False,
        "status": "blocked",
        "note": "数据根私有解释器不可用；修复：" + repair,
    }
    monkeypatch.setattr(workspace_mod, "toolchain", lambda *a, **k: blocked)

    assert cli.main(["--home", str(home), "install", "toolchain", "--root", str(root)]) == 1

    entry = install.load_state(home)["steps"]["dependencies"]
    assert entry["status"] == "blocked"
    assert "--clear" in entry["note"]
    report = install.report(home)
    assert [row["step"] for row in report["blocked"]] == ["dependencies"]
    assert any("--clear" in line for line in report["limitations"])

    python = home / ".venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    ok = {
        "ok": True,
        "status": "ok",
        "note": "",
        "uv": {"path": "uv"},
        "environment": {"python": str(python), "probe": {"ok": True}},
    }
    monkeypatch.setattr(workspace_mod, "toolchain", lambda *a, **k: ok)

    assert (
        cli.main(
            [
                "--home",
                str(home),
                "install",
                "toolchain",
                "--root",
                str(root),
                "--clear",
            ]
        )
        == 0
    )
    assert install.step_status(home)["dependencies"] == "ok"
    config = json.loads((home / "install" / "config.json").read_text(encoding="utf-8"))
    assert config["paths"]["python"] == str(python)
    assert config["paths"]["uv"] == "uv"


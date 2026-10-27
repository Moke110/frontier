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


def _seed_repo_files(repo: Path) -> None:
    for rel in (
        "common.py",
        "contracts/README.md",
        "skills/frontier-run/SKILL.md",
        "skills/frontier-run/references/installation.md",
        "skills/frontier-run/references/workflow.md",
    ):
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# {rel}\n", encoding="utf-8")


def test_probe_dependencies_never_falls_back_to_this_process(tmp_path):
    repo = tmp_path / "repo"
    _seed_repo_files(repo)

    result = install.probe_dependencies(repo)

    assert result["status"] == "blocked"
    assert "解释器" in result["note"]
    assert "install toolchain" in result["note"]
    assert "--clear" in result["note"]
    assert result["evidence"]["recorded"] is False


def test_probe_dependencies_blocks_an_interpreter_inside_the_repo(tmp_path):
    repo = tmp_path / "repo"
    _seed_repo_files(repo)
    inside = repo / ".venv" / "python"
    inside.parent.mkdir(parents=True)
    inside.write_text("", encoding="utf-8")

    result = install.probe_dependencies(repo, python=str(inside))

    assert result["status"] == "blocked"
    assert result["evidence"]["outside_repo"] is False
    assert "代码目录" in result["note"]
    assert "--clear" in result["note"]


def test_probe_dependencies_accepts_an_existing_outside_interpreter(tmp_path):
    import sys

    repo = tmp_path / "repo"
    _seed_repo_files(repo)

    result = install.probe_dependencies(repo, python=sys.executable)

    assert result["status"] == "ok"
    assert result["evidence"]["outside_repo"] is True
    assert result["evidence"]["recorded"] is True
    assert result["evidence"]["python_version"].count(".") == 2


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
    repo = Path(__file__).resolve().parents[1]

    result = install.check(home, repo=repo, host=_host())

    assert result["steps"]["host"] == "ok"
    assert result["steps"]["dependencies"] == "ok"
    assert install.load_state(home)["steps"]["dependencies"]["evidence"]["outside_repo"] is True
    assert result["steps"]["lark_cli"] == "blocked"
    assert result["steps"]["permissions"] == "blocked"
    config = json.loads((home / "install" / "config.json").read_text(encoding="utf-8"))
    assert config["host"]["product"] == "WorkBuddy"
    assert config["timezone"]


def test_check_never_falls_back_to_the_running_interpreter(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    root, repo, home = _fake_workspace(tmp_path)
    _seed_repo_files(repo)
    workspace_mod.save_record(
        root,
        {
            **workspace_mod.load_record(root),
            "python": "",
        },
    )
    from hostrun.base import update_config

    update_config(home, paths={"python": ""})

    result = install.check(home, host=_host(), workspace_root=root)

    assert result["steps"]["dependencies"] == "blocked"
    note = install.load_state(home)["steps"]["dependencies"]["note"]
    assert "install toolchain" in note
    assert "--clear" in note
    assert str(root) in note
    assert install.load_state(home)["steps"]["dependencies"]["evidence"]["recorded"] is False


def test_check_merges_host_and_lark_permissions_once(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    home = tmp_path / "home"
    binary = home / "bin" / "lark-cli"
    binary.parent.mkdir(parents=True)
    binary.write_text("", encoding="utf-8")
    _seed_repo_files(tmp_path / "repo")

    def runner(argv, **kwargs):
        if "auth" in argv:
            return _Proc(stdout=json.dumps(_auth_payload()))
        return _Proc(stdout="{}")

    install.check(
        home,
        repo=tmp_path / "repo",
        host=_host(),
        python=__import__("sys").executable,
        runner=runner,
    )

    config = json.loads((home / "install" / "config.json").read_text(encoding="utf-8"))
    permissions = config["permissions"]
    assert permissions["scope"] == sorted(GRANULAR_SCOPES)
    assert permissions["host_scope"] == ["shell", "file_write"]
    assert permissions["granted_at"]


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


# --------------------------------------------- Lark CLI / identity / permissions
GRANULAR_SCOPES = [
    "base:app:read",
    "base:table:read",
    "base:field:read",
    "base:record:read",
    "base:record:create",
    "base:record:update",
    "base:record:delete",
    "drive:file:upload",
    "drive:file:download",
    "space:folder:create",
    "space:document:delete",
    "im:message",
]


class _Proc:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _auth_payload(**over):
    payload = {
        "identities": {
            "user": {
                "available": True,
                "tokenStatus": "valid",
                "userOpenId": "ou_x",
                "accessToken": "secret-access",
            },
            "bot": {"available": True, "tokenStatus": "valid", "refreshToken": "secret-refresh"},
            "tenant": {"matched": True},
        },
        "scopes": list(GRANULAR_SCOPES),
    }
    payload.update(over)
    return payload


def test_probe_lark_cli_blocks_a_stale_recorded_path_without_path_fallback(
    tmp_path, monkeypatch
):
    path_dir = tmp_path / "pathbin"
    path_dir.mkdir()
    (path_dir / ("lark-cli.cmd" if os.name == "nt" else "lark-cli")).write_text(
        "", encoding="utf-8"
    )
    monkeypatch.setenv("PATH", str(path_dir))
    stale = tmp_path / "retired" / "lark-cli"

    result = install.probe_lark_cli(tmp_path / "home", str(stale))

    assert result["status"] == "blocked"
    assert result["evidence"]["stale"] is True
    assert result["evidence"]["path"] == str(stale)
    assert "discover --cli" in result["note"]
    assert "重装" in result["note"]


def test_probe_identity_requests_verify(tmp_path):
    calls = []

    def runner(argv, **kwargs):
        calls.append([str(item) for item in argv])
        return _Proc(stdout=json.dumps(_auth_payload()))

    result = install.probe_identity("lark-cli", runner=runner)

    assert result["status"] == "ok"
    assert "--verify" in calls[0]
    assert result["scopes"] == GRANULAR_SCOPES
    assert "ou_x" not in json.dumps(result)


def test_check_records_the_permissions_step_from_the_real_preflight(tmp_path):
    home = tmp_path / "home"
    binary = home / "bin" / "lark-cli"
    binary.parent.mkdir(parents=True)
    binary.write_text("", encoding="utf-8")
    calls = []

    def runner(argv, **kwargs):
        calls.append([str(item) for item in argv])
        if "auth" in argv:
            return _Proc(stdout=json.dumps(_auth_payload()))
        return _Proc(stdout="{}")

    result = install.check(
        home, repo=Path(__file__).resolve().parents[1], host=_host(), runner=runner
    )

    assert result["steps"]["permissions"] == "untested"
    entry = install.load_state(home)["steps"]["permissions"]
    assert entry["note"]
    assert entry["evidence"]["granted"] == sorted(GRANULAR_SCOPES)
    assert entry["evidence"]["missing"] == []
    assert entry["evidence"]["base"]["status"] == "untested"
    assert entry["evidence"]["drive"]["status"] == "untested"
    assert any("--verify" in call for call in calls)
    report = install.report(home)
    assert "permissions" in [row["step"] for row in report["untested"]]
    blob = json.dumps(report, ensure_ascii=False)
    assert "secret-access" not in blob
    assert "secret-refresh" not in blob


def test_check_reads_facilities_folders_for_the_resource_preflight(tmp_path):
    home = tmp_path / "home"
    binary = home / "bin" / "lark-cli"
    binary.parent.mkdir(parents=True)
    binary.write_text("", encoding="utf-8")
    (home / "install").mkdir(parents=True)
    (home / "install" / "facilities.json").write_text(
        json.dumps(
            {
                "base": {"token": "bas_x"},
                "folders": {"source": "fld_src", "push": "fld_push"},
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def runner(argv, **kwargs):
        calls.append([str(item) for item in argv])
        joined = " ".join(str(item) for item in argv)
        if "auth" in argv:
            return _Proc(stdout=json.dumps(_auth_payload()))
        if "+table-list" in argv:
            return _Proc(stdout=json.dumps({"ok": True, "data": {"tables": []}}))
        if "files" in argv and "list" in argv:
            return _Proc(stdout=json.dumps({"ok": True, "data": {"files": []}}))
        return _Proc(stdout="{}")

    result = install.check(
        home, repo=Path(__file__).resolve().parents[1], host=_host(), runner=runner
    )

    assert result["steps"]["permissions"] == "ok"
    entry = install.load_state(home)["steps"]["permissions"]
    assert entry["evidence"]["base"]["status"] == "ok"
    assert entry["evidence"]["drive"]["status"] == "ok"
    assert entry["evidence"]["messages"]["status"] == "untested"
    drive_calls = [call for call in calls if "files" in call and "list" in call]
    assert drive_calls
    assert any("fld_src" in " ".join(call) for call in drive_calls)
    assert any("fld_push" in " ".join(call) for call in drive_calls)


def test_check_without_a_cli_records_permissions_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    home = tmp_path / "home"
    home.mkdir()

    result = install.check(
        home, repo=Path(__file__).resolve().parents[1], host=_host()
    )

    assert result["steps"]["lark_cli"] == "blocked"
    assert result["steps"]["permissions"] == "blocked"
    entry = install.load_state(home)["steps"]["permissions"]
    assert "CLI" in entry["note"]


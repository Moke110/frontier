"""Installation workspace: safe reuse, private uv/Python, pointer skill."""

import io
import json
import zipfile
from pathlib import Path

import pytest

from hostrun import workspace
from hostrun.base import HostRunError

ROOT = Path(__file__).resolve().parents[1]


def _seed_repo(repo: Path) -> Path:
    """A checkout with the files installation must read, plus a .git marker."""
    (repo / ".git").mkdir(parents=True)
    for rel in (
        "common.py",
        "requirements.txt",
        "contracts/README.md",
        "skills/frontier-run/SKILL.md",
        "skills/frontier-run/references/installation.md",
        "skills/frontier-run/references/workflow.md",
    ):
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# {rel}\n", encoding="utf-8")
    return repo


class Runner:
    """Records argv and answers the git/uv calls the module makes."""

    def __init__(self, *, status="", origin=workspace.DEFAULT_REPO_URL, commit="abc123"):
        self.calls = []
        self.status = status
        self.origin = origin
        self.commit = commit

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        joined = " ".join(argv)

        class Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        proc = Proc()
        if argv[:2] == ["git", "-C"] and "status" in argv:
            proc.stdout = self.status
        elif argv[:2] == ["git", "-C"] and "get-url" in argv:
            proc.stdout = self.origin
        elif argv[:2] == ["git", "-C"] and "rev-parse" in argv:
            proc.stdout = self.commit
        elif "clone" in joined:
            target = Path(argv[-1])
            _seed_repo(target)
            proc.stdout = "cloned"
        elif "--version" in joined:
            proc.stdout = "uv 0.11.19"
        return proc


def test_fresh_workspace_clones_code_and_creates_separate_data_root(tmp_path):
    root = tmp_path / "研究 项目"
    root.mkdir()
    runner = Runner()

    result = workspace.acquire(root, runner=runner)

    assert result["ok"] is True
    assert result["action"] == "clone"
    repo, home = Path(result["repo"]), Path(result["home"])
    assert repo.name == "frontier"
    assert home.name == "frontier-archive"
    assert (repo / ".git").is_dir()
    assert home.is_dir()
    assert not home.is_relative_to(repo)
    record = workspace.load_record(root)
    assert record["repo"] == str(repo)
    assert record["commit"] == "abc123"


def test_existing_checkout_with_changes_is_not_pulled_or_overwritten(tmp_path):
    root = tmp_path / "ws"
    (root / "frontier").mkdir(parents=True)
    _seed_repo(root / "frontier")
    runner = Runner(status=" M writer/tasks.py\n")

    result = workspace.acquire(root, runner=runner)

    assert result["ok"] is False
    assert "未提交改动" in result["blocked"]
    assert not any("clone" in " ".join(call) for call in runner.calls)


def test_existing_checkout_with_another_origin_is_blocked(tmp_path):
    root = tmp_path / "ws"
    (root / "frontier").mkdir(parents=True)
    _seed_repo(root / "frontier")
    runner = Runner(origin="https://example.com/other.git")

    result = workspace.acquire(root, runner=runner)

    assert result["ok"] is False
    assert result["existing"]["state"] == "other_origin"
    assert "origin" in result["blocked"]


def test_data_root_inside_the_code_checkout_is_rejected(tmp_path):
    with pytest.raises(HostRunError):
        workspace.resolve_layout(tmp_path, data_dirname="frontier/frontier-archive")
    with pytest.raises(HostRunError):
        workspace.resolve_layout(tmp_path, code_dirname="same", data_dirname="same")


def test_reusable_checkout_is_not_cloned_again(tmp_path):
    root = tmp_path / "ws"
    repo = root / "frontier"
    repo.mkdir(parents=True)
    _seed_repo(repo)
    runner = Runner()

    result = workspace.acquire(root, runner=runner)

    assert result["ok"] is True
    assert result["action"] == "reuse"
    assert not any("clone" in " ".join(call) for call in runner.calls)


def test_interrupted_clone_is_moved_aside_and_retried(tmp_path):
    root = tmp_path / "ws"
    repo = root / "frontier"
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / "partial.txt").write_text("leftover", encoding="utf-8")
    (root / ".frontier").mkdir()
    (root / ".frontier" / "clone-in-progress.json").write_text(
        json.dumps({"repo": str(repo), "started_at": "2026-10-27T10:00:00+08:00"}),
        encoding="utf-8",
    )

    def runner(argv, **kwargs):
        if argv[:2] == ["git", "-C"] and "status" in argv:
            if not (repo / "common.py").exists():
                return type("P", (), {"returncode": 128, "stdout": "", "stderr": "not a git repository"})()
            return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        if argv[:2] == ["git", "-C"] and "get-url" in argv:
            return type("P", (), {"returncode": 0, "stdout": workspace.DEFAULT_REPO_URL, "stderr": ""})()
        if argv[:2] == ["git", "-C"] and "rev-parse" in argv:
            return type("P", (), {"returncode": 0, "stdout": "abc123", "stderr": ""})()
        if "clone" in " ".join(argv):
            _seed_repo(repo)
            return type("P", (), {"returncode": 0, "stdout": "cloned", "stderr": ""})()
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    result = workspace.acquire(root, runner=runner)

    assert result["ok"] is True
    assert result["recovered_partial_clone"]["archived"]
    assert Path(result["recovered_partial_clone"]["archived"]).exists()
    assert (repo / "common.py").exists()
    assert not (root / ".frontier" / "clone-in-progress.json").exists()


def _zip_with_uv(binary="uv.exe") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"uv-x86_64-pc-windows-msvc/{binary}", b"fake-uv")
    return buffer.getvalue()


def test_missing_uv_is_installed_privately_without_path_changes(tmp_path):
    blob = _zip_with_uv()
    result = workspace.install_uv(
        tmp_path,
        asset="uv-x86_64-pc-windows-msvc.zip",
        fetch=lambda url: blob,
    )

    assert result["ok"] is True
    installed = Path(result["path"])
    assert installed.parent == tmp_path / ".frontier" / "bin"
    assert installed.read_bytes() == b"fake-uv"


def test_missing_uv_reports_blocked_when_download_fails(tmp_path):
    def broken(url):
        raise OSError("no network")

    result = workspace.install_uv(
        tmp_path, asset="uv-x86_64-pc-windows-msvc.zip", fetch=broken
    )

    assert result["ok"] is False
    assert result["reason"] == "uv_install_failed"


def test_uv_is_reused_when_already_present(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    binary = tmp_path / ".frontier" / "bin" / "uv.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"fake")
    runner = Runner()

    result = workspace.ensure_uv(tmp_path, runner=runner)

    assert result["ok"] is True
    assert Path(result["path"]) == binary
    assert result["source"] == "private"


def test_fresh_environment_is_created_by_uv(tmp_path):
    repo = _seed_repo(tmp_path / "repo")
    calls = []

    def runner(argv, **kwargs):
        calls.append(list(argv))

        class Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        if argv[1:2] == ["venv"]:
            python = repo / ".venv" / ("Scripts/python.exe" if __import__("os").name == "nt" else "bin/python")
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("", encoding="utf-8")
        return Proc()

    result = workspace.ensure_environment(
        repo, uv="uv", python_version="3.13", runner=runner, verify=lambda path: {"ok": path.exists()}
    )

    assert result["ok"] is True
    assert result["created"] is True
    assert result["repaired"] is False
    assert any(call[1:2] == ["venv"] for call in calls)
    assert not any("--clear" in call for call in calls)
    assert any(call[1:2] == ["pip"] for call in calls)


def test_broken_environment_is_repaired_with_clear(tmp_path):
    repo = _seed_repo(tmp_path / "repo")
    (repo / ".venv").mkdir()
    (repo / ".venv" / "pyvenv.cfg").write_text("home = retired\n", encoding="utf-8")
    calls = []

    def runner(argv, **kwargs):
        calls.append(list(argv))

        class Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        return Proc()

    result = workspace.ensure_environment(
        repo, uv="uv", runner=runner, verify=lambda path: {"ok": True}
    )

    assert result["ok"] is True
    assert result["repaired"] is True
    assert any("--clear" in call for call in calls)


def test_failed_uv_venv_reports_blocked(tmp_path):
    repo = _seed_repo(tmp_path / "repo")

    def runner(argv, **kwargs):
        class Proc:
            returncode = 2
            stdout = ""
            stderr = "download failed"

        return Proc()

    result = workspace.ensure_environment(repo, uv="uv", runner=runner, verify=lambda path: {"ok": True})

    assert result["ok"] is False
    assert "创建私有环境失败" in result["note"]


def _record(root: Path, repo: Path, home: Path) -> dict:
    record = {
        "schema_version": 1,
        "root": str(root),
        "repo": str(repo),
        "home": str(home),
        "repo_url": workspace.DEFAULT_REPO_URL,
        "commit": "abc123",
    }
    workspace.save_record(root, record)
    return record


def test_skill_launcher_points_at_repo_and_verifies_references(tmp_path):
    root = tmp_path / "ws"
    repo = _seed_repo(root / "frontier")
    home = root / "frontier-archive"
    home.mkdir()
    _record(root, repo, home)

    result = workspace.register_skill(root, root / ".host-skills" / "frontier-run")

    assert result["ok"] is True
    launcher = Path(result["skill"])
    text = launcher.read_text(encoding="utf-8")
    assert "name: frontier-run" in text
    assert str(repo) in text
    assert str(home) in text
    assert workspace.verify_skill(workspace.load_record(root))["ok"] is True


def test_moved_skill_still_locates_the_repo(tmp_path):
    root = tmp_path / "ws"
    repo = _seed_repo(root / "frontier")
    home = root / "frontier-archive"
    home.mkdir()
    _record(root, repo, home)
    first = workspace.register_skill(root, root / "skills-a" / "frontier-run")

    moved_dir = tmp_path / "another-host" / "frontier-run"
    moved_dir.mkdir(parents=True)
    Path(first["skill"]).rename(moved_dir / "SKILL.md")
    record = workspace.load_record(root)
    record["skill"] = str(moved_dir / "SKILL.md")
    workspace.save_record(root, record)

    status = workspace.verify_skill(workspace.load_record(root))
    assert status["ok"] is True
    assert str(repo) in (moved_dir / "SKILL.md").read_text(encoding="utf-8")


def test_skill_target_cannot_overwrite_the_source_entry(tmp_path):
    root = tmp_path / "ws"
    repo = _seed_repo(root / "frontier")
    home = root / "frontier-archive"
    home.mkdir()
    _record(root, repo, home)

    with pytest.raises(HostRunError):
        workspace.register_skill(root, repo / "skills" / "frontier-run")


def test_status_reports_missing_interpreter(tmp_path):
    root = tmp_path / "ws"
    repo = _seed_repo(root / "frontier")
    home = root / "frontier-archive"
    home.mkdir()
    _record(root, repo, home)
    workspace.register_skill(root, root / "host-skills" / "frontier-run")
    workspace.save_record(
        root,
        {
            **workspace.load_record(root),
            "python": str(repo / ".venv" / "missing-python"),
            "uv": str(tmp_path / "missing-uv"),
        },
    )

    status = workspace.status(root)

    assert status["ok"] is False
    assert any("解释器" in problem for problem in status["problems"])
    assert any("uv" in problem for problem in status["problems"])

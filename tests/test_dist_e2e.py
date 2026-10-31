"""Offline end-to-end proof of the documented distribution-package flow (#100).

The real acceptance run installs a package from a GitHub Release on a machine
without a system Python, generates the skill pointer and console launcher, then
upgrades, rolls back and runs ``/frontier-init`` against independent Feishu
facilities.  That live run needs the Lead, a real release and external side
effects, so it stays ``untested`` in ``docs/acceptance/README.md``.

This module drives the same *mechanics* through the public CLI seams with a
small fixture package (including a synthetic bundled runtime), no network and no
process execution: package -> console launcher -> skill pointer -> verify,
upgrade, rollback and report, with a run-state sentinel proving ``.frontier``
survives every swap.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

from hostrun import cli, dist, distribution, workspace


PACKAGE_FILES = {
    "common.py": "RUNTIME = True\n",
    "requirements.txt": "PyYAML>=6.0\n",
    "README.md": "# fixture frontier\n",
    "LICENSE": "MIT\n",
    "hostrun/__init__.py": "",
    "hostrun/cli.py": "CLI = 1\n",
    "hostrun/base.py": "VALUE = 1\n",
    "skills/frontier-run/SKILL.md": "---\nname: frontier-run\n---\n",
    "skills/frontier-run/references/installation.md": "# installation\n",
    "skills/frontier-run/references/workflow.md": "# workflow\n",
    "contracts/README.md": "contracts\n",
    "docs/adr/0010-distribution.md": "# decision\n",
}

#: A synthetic version of the CI-produced runtime layout.  The builder copies it
#: verbatim and generates ``bin/frontier.cmd``; nothing here is executed.
RUNTIME_FILES = {
    "python.exe": b"MZ fake bundled interpreter",
    "python313.dll": b"fake core dll",
    "python313._pth": b"python313.zip\n.\nLib\\site-packages\n",
    "Lib/site-packages/keep.txt": b"site-packages placeholder\n",
}

#: The user-facing order the README install section documents.  The test below
#: reads the section and proves these commands appear in exactly this order.
DOCUMENTED_INSTALL_STEPS = (
    "install package",
    "console install",
    "install skill",
    "install verify",
    "install report",
    "install rollback",
)

INSTALL_CHOICES = {
    "check",
    "status",
    "report",
    "migrate",
    "record",
    "package",
    "verify",
    "rollback",
    "workspace",
    "toolchain",
    "skill",
    "locate",
}
CONSOLE_CHOICES = {"control", "install"}


def _write_tree(root: Path, files: dict[str, str | bytes]) -> Path:
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data, encoding="utf-8")
    return root


def _host_compat() -> dict[str, str]:
    return {
        "os": distribution.normalize_os(sys.platform),
        "arch": distribution.normalize_arch(platform.machine()),
        "dsh": "*",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
    }


def _build_package(
    tmp_path: Path,
    *,
    version: str,
    commit: str,
    marker: str,
    channel: str = "prerelease",
) -> dict:
    """Build one real package artifact from a fixture source tree."""
    files = {
        **PACKAGE_FILES,
        "hostrun/cli.py": f"CLI = {marker!r}\n",
    }
    source = _write_tree(tmp_path / f"source-{version}", files)
    runtime = _write_tree(tmp_path / f"runtime-{version}", RUNTIME_FILES)
    return distribution.build(
        source=source,
        out=tmp_path / f"out-{version}",
        version=version,
        channel=channel,
        commit=commit,
        compat=_host_compat(),
        runtime_dir=runtime,
    )


def _manifest(result: dict) -> dict:
    return json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))


def _cli(capsys, code: Path, archive: Path, *args: str):
    """Run the hostrun CLI exactly as an installation wrapper would."""
    exit_code = cli.main(
        ["--code", str(code), "--archive", str(archive), *args]
    )
    captured = capsys.readouterr()
    raw = captured.out.strip() or captured.err.strip()
    assert "Traceback" not in captured.err
    return exit_code, json.loads(raw), captured


def _walk_subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:  # argparse has no public walker
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _readme_install_section() -> str:
    text = (Path(__file__).resolve().parents[1] / "README.md").read_text(
        encoding="utf-8"
    )
    start = text.index("## 安装")
    end = text.index("## 开发者")
    return text[start:end]


def test_readme_documented_install_steps_exist_and_are_in_order() -> None:
    section = _readme_install_section()
    positions = [section.index(step) for step in DOCUMENTED_INSTALL_STEPS]

    assert positions == sorted(positions), "README install steps are out of order"

    parser = cli.build_parser()
    install = _walk_subparsers(parser)["install"]
    for step in DOCUMENTED_INSTALL_STEPS:
        if step.startswith("install "):
            name = step.split(" ", 1)[1]
            assert name in INSTALL_CHOICES
            assert name in _walk_subparsers(install)
    console = _walk_subparsers(parser)["console"]
    assert "install" in CONSOLE_CHOICES
    assert "install" in _walk_subparsers(console)


def test_distribution_package_install_skill_upgrade_rollback_end_to_end(tmp_path, capsys):
    v1 = _build_package(tmp_path, version="1.0.0", commit="1111111", marker="V1")
    v2 = _build_package(tmp_path, version="2.0.0", commit="2222222", marker="V2")
    v1_manifest = _manifest(v1)

    workspace_root = tmp_path / "workspace"
    code = workspace_root / "code"
    archive = workspace_root / "archive"
    code.mkdir(parents=True)
    archive.mkdir(parents=True)
    host_skills = workspace_root / "host-skills" / "frontier-run"
    fake_dsh = tmp_path / "dsh.cmd"
    fake_dsh.write_text("@echo off\n", encoding="utf-8")

    # 1. install package -> lock, current pointer and bundled wrapper.
    exit_code, payload, _ = _cli(
        capsys,
        code,
        archive,
        "install",
        "package",
        "--from",
        str(v1["artifact"]["path"]),
        "--digest",
        v1["digest"],
    )
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["distribution"] == "package"
    assert payload["version"] == "1.0.0"
    assert (code / ".frontier" / "dist.lock.json").is_file()
    assert (code / ".frontier" / "current").read_text(encoding="utf-8").strip() == "1.0.0"
    assert (code / "bin" / "frontier.cmd").is_file()

    # 2. console install -> the package-mode launcher delegates to the wrapper.
    exit_code, payload, _ = _cli(
        capsys, code, archive, "console", "install", "--dsh", str(fake_dsh)
    )
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["processes_started"] is False
    console_path = code / "bin" / "frontier-console.cmd"
    console_text = console_path.read_text(encoding="utf-8")
    assert console_text == (
        "title frontier-console\n"
        f'call "%~dp0frontier.cmd" --code "{code}" '
        f'--archive "{archive}" console %*\n'
    )
    assert "python.exe" not in console_text

    # 3. install skill -> pointer derived from the package lock, not a fake
    #    source record; the workspace record is persisted only after this write.
    exit_code, payload, _ = _cli(
        capsys,
        code,
        archive,
        "install",
        "skill",
        "--root",
        str(code),
        "--target",
        str(host_skills),
    )
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["distribution"] == "package"

    pointer_path = host_skills / "SKILL.md"
    pointer = pointer_path.read_text(encoding="utf-8")
    lock = dist.read_lock(code)
    digest = workspace.entry_digest(code)
    assert "发行来源：package" in pointer
    assert "发行版本：1.0.0" in pointer
    assert "发行渠道：prerelease" in pointer
    assert f"制品摘要：{v1['artifact']['sha256']}" in pointer
    assert f"发行包来源：{lock['source_url']}" in pointer
    assert f"技能摘要：{digest}" in pointer
    assert f"安装锁：{code / '.frontier' / 'dist.lock.json'}" in pointer
    assert f"- 解释器：{code / 'bin' / 'frontier.cmd'}" in pointer

    record = workspace.load_record(code)
    assert record["repo"] == str(code.resolve())
    assert record["home"] == str((code / ".frontier").resolve())
    assert record["root"] == str(code.resolve())
    assert record["repo_url"] == lock["source_url"]
    assert record["commit"] == v1_manifest["built_from_commit"]
    assert record["python"] == str(code / "bin" / "frontier.cmd")
    assert record["dirty"] is False
    assert lock["distribution"] == "package"
    assert lock["version"] == "1.0.0"
    assert lock["artifact_sha256"] == v1["artifact"]["sha256"]
    assert lock["skill_digest"] == digest

    status = workspace.verify_skill(record)
    assert status["ok"] is True
    assert status["distribution"] == "package"
    assert status["version"] == "1.0.0"
    assert status["reasons"] == []

    # 4. a tampered lock version or pointer/lock digest blocks verification.
    lock_bytes = (code / ".frontier" / "dist.lock.json").read_bytes()
    tampered = json.loads(lock_bytes)
    tampered["version"] = "9.9.9"
    (code / ".frontier" / "dist.lock.json").write_text(
        json.dumps(tampered), encoding="utf-8"
    )
    status = workspace.verify_skill(workspace.load_record(code))
    assert status["ok"] is False
    assert "lock_version_mismatch" in status["reasons"]
    (code / ".frontier" / "dist.lock.json").write_bytes(lock_bytes)

    pointer_bytes = pointer_path.read_bytes()
    pointer_path.write_text(
        pointer.replace(
            f"制品摘要：{lock['artifact_sha256']}",
            f"制品摘要：{'0' * 64}",
        ),
        encoding="utf-8",
    )
    status = workspace.verify_skill(workspace.load_record(code))
    assert status["ok"] is False
    assert "lock_artifact_mismatch" in status["reasons"]
    pointer_path.write_bytes(pointer_bytes)

    pointer_path.write_text(
        pointer.replace(f"技能摘要：{digest}", f"技能摘要：{'0' * 64}"),
        encoding="utf-8",
    )
    status = workspace.verify_skill(workspace.load_record(code))
    assert status["ok"] is False
    assert "skill_digest_mismatch" in status["reasons"]
    pointer_path.write_bytes(pointer_bytes)
    assert workspace.verify_skill(workspace.load_record(code))["ok"] is True

    # 5. run state survives every package swap byte for byte.
    state_path = code / ".frontier" / "install" / "state.json"
    sentinel = b'{"schema_version": 1, "steps": {}, "sentinel": "e2e-run-state"}\n'
    state_path.write_bytes(sentinel)
    console_before = console_path.read_bytes()
    wrapper_before = (code / "bin" / "frontier.cmd").read_bytes()

    # 6. upgrade -> v1 retained, current/lock v2, verify passes.
    exit_code, payload, _ = _cli(
        capsys,
        code,
        archive,
        "install",
        "package",
        "--from",
        str(v2["artifact"]["path"]),
        "--digest",
        v2["digest"],
    )
    assert exit_code == 0
    assert payload["version"] == "2.0.0"
    assert payload["previous_version"] == "1.0.0"
    assert (code / ".frontier" / "releases" / "1.0.0" / "manifest.json").is_file()
    assert (code / ".frontier" / "current").read_text(encoding="utf-8").strip() == "2.0.0"
    assert dist.read_lock(code)["version"] == "2.0.0"
    assert dist.read_lock(code)["artifact_sha256"] == v2["artifact"]["sha256"]
    exit_code, payload, _ = _cli(capsys, code, archive, "install", "verify")
    assert exit_code == 0
    assert payload["status"] == "verified"
    assert state_path.read_bytes() == sentinel
    assert console_path.read_bytes() == console_before
    assert (code / "bin" / "frontier.cmd").read_bytes() == wrapper_before

    # 7. rollback -> v1 again, same run state, launcher still valid, verify passes.
    exit_code, payload, _ = _cli(capsys, code, archive, "install", "rollback")
    assert exit_code == 0
    assert payload["version"] == "1.0.0"
    assert payload["previous_version"] == "2.0.0"
    assert dist.read_lock(code)["version"] == "1.0.0"
    assert dist.read_lock(code)["artifact_sha256"] == v1["artifact"]["sha256"]
    assert (code / ".frontier" / "current").read_text(encoding="utf-8").strip() == "1.0.0"
    assert state_path.read_bytes() == sentinel
    assert console_path.read_bytes() == console_before
    assert (code / "bin" / "frontier.cmd").read_bytes() == wrapper_before
    assert dist.verify_install(code)["status"] == "verified"

    # 8. report shows the active v1 and the retained v2.
    _, report, _ = _cli(capsys, code, archive, "install", "report")
    release = report["release"]
    assert release["distribution"] == "package"
    assert release["version"] == "1.0.0"
    assert release["previous_version"] == "2.0.0"
    assert release["retained"] == [
        {
            "version": "2.0.0",
            "channel": "prerelease",
            "artifact_sha256": v2["artifact"]["sha256"],
        }
    ]

    # 9. an unknown rollback target is blocked and changes nothing.
    before = {
        "lock": (code / ".frontier" / "dist.lock.json").read_bytes(),
        "current": (code / ".frontier" / "current").read_bytes(),
        "state": state_path.read_bytes(),
        "console": console_path.read_bytes(),
        "wrapper": (code / "bin" / "frontier.cmd").read_bytes(),
    }
    exit_code, payload, _ = _cli(
        capsys, code, archive, "install", "rollback", "--to", "9.9.9"
    )
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["reason"] == "release_not_found"
    assert {
        "lock": (code / ".frontier" / "dist.lock.json").read_bytes(),
        "current": (code / ".frontier" / "current").read_bytes(),
        "state": state_path.read_bytes(),
        "console": console_path.read_bytes(),
        "wrapper": (code / "bin" / "frontier.cmd").read_bytes(),
    } == before

"""Retention, rollback and the install report's release block.

Ticket #96 builds on the #94 install seam: the active tree stays in the code
root, one previous release is retained under ``<code>/.frontier/releases/<v>``
and ``<code>/.frontier/current`` names the active version.  Every test builds
real distribution packages and works only through the public install/rollback
report seams; nothing reaches the network.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path

import pytest

from conftest import cli_locations
from hostrun import cli, dist, distribution, install

PACKAGE_FILES = {
    "common.py": "RUNTIME = True\n",
    "requirements.txt": "PyYAML>=6.0\n",
    "README.md": "# fixture frontier\n",
    "LICENSE": "MIT\n",
    "hostrun/__init__.py": "",
    "hostrun/cli.py": "CLI = 1\n",
    "hostrun/base.py": "VALUE = 1\n",
    "skills/frontier-run/SKILL.md": "---\nname: frontier-run\n---\n",
    "contracts/README.md": "contracts\n",
    "docs/adr/0010-distribution.md": "# decision\n",
}


def _write_tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _host_compat() -> dict[str, str]:
    return {
        "os": distribution.normalize_os(sys.platform),
        "arch": distribution.normalize_arch(platform.machine()),
        "dsh": "*",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
    }


def _build(
    tmp_path: Path,
    *,
    name: str,
    version: str,
    channel: str = "stable",
    files: dict[str, str] | None = None,
) -> dict:
    source = _write_tree(tmp_path / f"{name}-src", files or PACKAGE_FILES)
    return distribution.build(
        source=source,
        out=tmp_path / f"{name}-out",
        version=version,
        channel=channel,
        commit="deadbeefcafe",
        compat=_host_compat(),
    )


def _install(code: Path, result: dict, **kwargs) -> dict:
    return dist.install_package(
        code,
        from_source=str(result["artifact"]["path"]),
        **kwargs,
    )


def _manifest(result: dict) -> dict:
    return json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))


def _lock(code: Path) -> dict:
    return json.loads((code / ".frontier" / "dist.lock.json").read_text(encoding="utf-8"))


def _current(code: Path) -> str:
    return (code / ".frontier" / "current").read_text(encoding="utf-8").strip()


def _release_record(code: Path, version: str) -> dict:
    return json.loads(
        (code / ".frontier" / "releases" / version / "release.json").read_text(
            encoding="utf-8"
        )
    )


def _tree_files(root: Path, manifest: dict) -> dict[str, bytes]:
    return {
        row["path"]: (root / row["path"]).read_bytes() for row in manifest["files"]
    }


def _cli(capsys, home: Path, *args: str):
    code = cli.main([*cli_locations(home), *args])
    captured = capsys.readouterr()
    raw = captured.out.strip() or captured.err.strip()
    return code, json.loads(raw), captured


# --------------------------------------------------------------- retention
def test_upgrade_retains_the_outgoing_version_and_points_at_the_new_one(tmp_path):
    v1 = _build(tmp_path, name="v1", version="1.0.0")
    v2 = _build(tmp_path, name="v2", version="2.0.0")
    code = tmp_path / "code"
    assert _install(code, v1)["ok"] is True

    payload = _install(code, v2)

    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["version"] == "2.0.0"
    assert payload["extracted"] is True

    assert _current(code) == "2.0.0"
    lock = _lock(code)
    assert lock["version"] == "2.0.0"
    assert lock["previous_version"] == "1.0.0"
    assert lock["artifact_sha256"] == v2["artifact"]["sha256"]
    assert not (code / ".frontier" / "releases" / "2.0.0").exists()

    retained = code / ".frontier" / "releases" / "1.0.0"
    v1_manifest = _manifest(v1)
    for row in v1_manifest["files"]:
        assert (retained / row["path"]).read_bytes() == (
            Path(v1["package"]) / row["path"]
        ).read_bytes(), row["path"]
    assert (retained / "manifest.json").read_bytes() == Path(v1["manifest"]).read_bytes()

    record = _release_record(code, "1.0.0")
    assert record["schema_version"] == 1
    assert record["version"] == "1.0.0"
    assert record["channel"] == "stable"
    assert record["artifact_sha256"] == v1["artifact"]["sha256"]
    assert record["manifest_sha256"] == hashlib.sha256(
        (retained / "manifest.json").read_bytes()
    ).hexdigest()
    assert record["package_file_count"] == len(v1_manifest["files"])
    assert record["source_url"] == Path(v1["artifact"]["path"]).resolve().as_uri()
    assert record["installed_at"]


def test_upgrading_removes_files_only_the_previous_manifest_listed(tmp_path):
    v1_files = {**PACKAGE_FILES, "hostrun/legacy_only.py": "OLD = True\n"}
    v1 = _build(tmp_path, name="v1", version="1.0.0", files=v1_files)
    v2 = _build(tmp_path, name="v2", version="2.0.0")
    code = tmp_path / "code"
    assert _install(code, v1)["ok"] is True
    assert (code / "hostrun" / "legacy_only.py").is_file()

    payload = _install(code, v2)

    assert payload["ok"] is True
    assert not (code / "hostrun" / "legacy_only.py").exists()
    assert dist.verify_install(code)["status"] == "verified"


def test_runtime_state_and_knowledge_survive_an_upgrade(tmp_path):
    v1 = _build(tmp_path, name="v1", version="1.0.0")
    v2 = _build(tmp_path, name="v2", version="2.0.0")
    code = tmp_path / "code"
    assert _install(code, v1)["ok"] is True

    runtime = code / ".frontier"
    (runtime / "install").mkdir(parents=True, exist_ok=True)
    (runtime / "knowledge").mkdir(parents=True, exist_ok=True)
    state_bytes = b'{"schema_version": 1, "steps": {}}\n'
    knowledge_bytes = b'{"schema_version": 1, "cards": ["k1"]}\n'
    (runtime / "install" / "state.json").write_bytes(state_bytes)
    (runtime / "knowledge" / "base.json").write_bytes(knowledge_bytes)

    assert _install(code, v2)["ok"] is True

    assert (runtime / "install" / "state.json").read_bytes() == state_bytes
    assert (runtime / "knowledge" / "base.json").read_bytes() == knowledge_bytes


def test_installing_a_third_version_prunes_the_oldest_retained_release(tmp_path):
    v1 = _build(tmp_path, name="v1", version="1.0.0")
    v2 = _build(tmp_path, name="v2", version="2.0.0")
    v3 = _build(tmp_path, name="v3", version="3.0.0")
    code = tmp_path / "code"
    for result in (v1, v2, v3):
        assert _install(code, result)["ok"] is True

    releases = code / ".frontier" / "releases"
    assert sorted(path.name for path in releases.iterdir()) == ["2.0.0"]
    assert not (releases / "1.0.0").exists()
    record = _release_record(code, "2.0.0")
    assert record["version"] == "2.0.0"
    assert _current(code) == "3.0.0"
    assert _lock(code)["previous_version"] == "2.0.0"
    assert dist.verify_install(code)["status"] == "verified"


def test_idempotent_reinstall_does_not_rewrite_lock_current_or_retention(tmp_path):
    v1 = _build(tmp_path, name="v1", version="1.0.0")
    v2 = _build(tmp_path, name="v2", version="2.0.0")
    code = tmp_path / "code"
    for result in (v1, v2):
        assert _install(code, result)["ok"] is True

    lock_path = code / ".frontier" / "dist.lock.json"
    current_path = code / ".frontier" / "current"
    release_path = code / ".frontier" / "releases" / "1.0.0" / "release.json"
    lock_bytes = lock_path.read_bytes()
    current_bytes = current_path.read_bytes()
    release_bytes = release_path.read_bytes()
    installed_at = json.loads(lock_bytes)["installed_at"]

    payload = _install(code, v2)

    assert payload["ok"] is True
    assert payload["extracted"] is False
    assert payload["installed_at"] == installed_at
    assert lock_path.read_bytes() == lock_bytes
    assert current_path.read_bytes() == current_bytes
    assert release_path.read_bytes() == release_bytes


def test_release_record_schema_declares_the_contract():
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "contracts"
            / "release-record.schema.json"
        ).read_text(encoding="utf-8")
    )

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is True
    assert set(schema["required"]) == {
        "schema_version",
        "version",
        "channel",
        "artifact_sha256",
        "manifest_sha256",
        "package_file_count",
        "source_url",
        "installed_at",
    }
    assert schema["properties"]["schema_version"]["const"] == 1
    assert schema["properties"]["channel"]["enum"] == ["stable", "prerelease"]

    lock_schema = json.loads(
        (
            Path(__file__).resolve().parents[1] / "contracts" / "install-lock.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert "previous_version" in lock_schema["properties"]
    assert "rolled_back_at" in lock_schema["properties"]

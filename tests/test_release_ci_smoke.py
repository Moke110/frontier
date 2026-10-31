"""CI install smoke: a built artifact installs and reports as a package install.

Spec #92 testing seam 5 is a CI smoke test, not a pytest, but the logic lives in
``scripts/ci_install_smoke.py`` so it can be exercised offline here.  Every test
builds a real package with :mod:`hostrun.distribution` (synthetic source tree and
synthetic runtime) and runs the smoke script in a subprocess against temporary
code/archive/skills directories.  Nothing reaches the network and the workflow's
real-run step is only parsed elsewhere.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path

import pytest

from hostrun import distribution

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_install_smoke.py"

PACKAGE_FILES = {
    "common.py": "RUNTIME = True\n",
    "requirements.txt": "PyYAML>=6.0\n",
    "README.md": "# fixture frontier\n",
    "LICENSE": "MIT\n",
    "hostrun/__init__.py": "",
    "hostrun/cli.py": "CLI = 1\n",
    "hostrun/base.py": "VALUE = 1\n",
    "skills/frontier-run/SKILL.md": "---\nname: frontier-run\n---\n",
    "skills/frontier-run/references/installation.md": "# install\n",
    "skills/frontier-run/references/workflow.md": "# workflow\n",
    "contracts/README.md": "contracts\n",
    "docs/adr/0010-distribution.md": "# decision\n",
}


def _host_compat() -> dict[str, str]:
    return {
        "os": distribution.normalize_os(sys.platform),
        "arch": distribution.normalize_arch(platform.machine()),
        "dsh": "*",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
    }


def _write_tree(root: Path, files: dict[str, str]) -> Path:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _write_runtime(root: Path) -> Path:
    """The CPython embeddable layout the builder copies verbatim."""
    (root / "DLLs").mkdir(parents=True)
    (root / "Lib" / "site-packages").mkdir(parents=True)
    (root / "python.exe").write_bytes(b"MZ fake interpreter")
    (root / "python313.dll").write_bytes(b"dll")
    (root / "python313._pth").write_text("python313.zip\r\n.\r\n", encoding="utf-8")
    (root / "python313.zip").write_bytes(b"PK fake stdlib")
    (root / "DLLs" / "select.pyd").write_bytes(b"pyd")
    (root / "Lib" / "site-packages" / "yaml").mkdir()
    (root / "Lib" / "site-packages" / "yaml" / "__init__.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    return root


def _build(tmp_path: Path) -> dict:
    source = _write_tree(tmp_path / "src", PACKAGE_FILES)
    runtime = _write_runtime(tmp_path / "runtime")
    return distribution.build(
        source=source,
        out=tmp_path / "dist",
        version="0.1.0",
        channel="stable",
        commit="cafebabe",
        compat=_host_compat(),
        runtime_dir=runtime,
    )


def _smoke_args(built: dict, smoke: Path, **overrides: str) -> list[str]:
    values = {
        "--zip": str(built["artifact"]["path"]),
        "--code": str(smoke / "code"),
        "--archive": str(smoke / "archive"),
        "--dsh": str(smoke / "host" / "dsh.cmd"),
        "--skills-target": str(smoke / "host-skills" / "frontier-run"),
        "--bootstrap": str(smoke / "bootstrap"),
    }
    values.update(overrides)
    return [item for pair in values.items() for item in pair]


def _run_smoke(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPT), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )


def _payload(result: subprocess.CompletedProcess) -> dict:
    assert result.stdout.strip(), result.stderr
    return json.loads(result.stdout)


def test_ci_install_smoke_installs_verifies_and_reports_a_package(tmp_path):
    built = _build(tmp_path)
    smoke = tmp_path / "smoke"

    result = _run_smoke(*_smoke_args(built, smoke))

    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    payload = _payload(result)
    assert payload["ok"] is True
    assert payload["sha256"] == built["artifact"]["sha256"]
    assert payload["version"] == "0.1.0"
    assert payload["channel"] == "stable"

    code = smoke / "code"
    lock = json.loads(
        (code / ".frontier" / "dist.lock.json").read_text(encoding="utf-8")
    )
    assert lock["distribution"] == "package"
    assert lock["version"] == "0.1.0"
    assert lock["channel"] == "stable"
    assert lock["artifact_sha256"] == built["artifact"]["sha256"]
    assert (code / "manifest.json").is_file()
    assert (smoke / "bootstrap" / "runtime" / "python.exe").is_file()
    # `install skill` writes the host pointer; `console install` writes its script.
    assert (
        smoke / "host-skills" / "frontier-run" / "SKILL.md"
    ).is_file()
    assert (code / "bin" / "frontier-console.cmd").is_file()

    commands = {row["name"]: row for row in payload["commands"]}
    assert commands["install"]["status"] == "ok"
    assert commands["verify"]["status"] == "verified"
    assert commands["console"]["status"] == "ok"
    assert commands["console"]["processes_started"] is False
    assert commands["skill"]["ok"] is True
    assert commands["report"]["release"]["distribution"] == "package"
    assert commands["report"]["release"]["version"] == "0.1.0"
    assert commands["report"]["steps"]["skill"]["status"] == "ok"


def test_ci_install_smoke_fails_on_a_digest_mismatch_before_installing(tmp_path):
    built = _build(tmp_path)
    smoke = tmp_path / "smoke"

    result = _run_smoke(
        *_smoke_args(built, smoke, **{"--sha256": "0" * 64}),
    )

    assert result.returncode == 1
    payload = _payload(result)
    assert payload["ok"] is False
    assert "sha256" in payload["error"].lower()
    assert not (smoke / "code" / ".frontier" / "dist.lock.json").exists()


def test_ci_install_smoke_refuses_a_non_empty_code_directory(tmp_path):
    built = _build(tmp_path)
    smoke = tmp_path / "smoke"
    code = smoke / "code"
    code.mkdir(parents=True)
    (code / "keep.txt").write_text("user data\n", encoding="utf-8")

    result = _run_smoke(*_smoke_args(built, smoke))

    assert result.returncode == 1
    payload = _payload(result)
    assert payload["ok"] is False
    assert "empty" in payload["error"].lower()
    assert (code / "keep.txt").read_text(encoding="utf-8") == "user data\n"
    assert not (code / ".frontier" / "dist.lock.json").exists()

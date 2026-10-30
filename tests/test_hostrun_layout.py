"""Directory model step 1: ``--code`` / ``--archive`` with ``--home`` compatibility.

These tests describe the two top-level locations and the unified runtime area
under the code directory.  Everything runs against temporary directories; no
command touches a live installation.
"""

import json
import subprocess
from pathlib import Path

import pytest

from hostrun import cli, layout
from hostrun.base import HostRunError

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ defaults
def test_defaults_are_the_repo_root_and_a_sibling_archive():
    resolved = layout.resolve()

    assert resolved["mode"] == "code"
    assert Path(resolved["code"]) == ROOT
    assert Path(resolved["archive"]) == ROOT.parent / layout.ARCHIVE_DIRNAME
    assert Path(resolved["runtime"]) == ROOT / layout.RUNTIME_DIRNAME


def test_explicit_code_and_archive_are_used_verbatim(tmp_path):
    code = tmp_path / "checkout"
    archive = tmp_path / "papers"

    resolved = layout.resolve(code=str(code), archive=str(archive))

    assert Path(resolved["code"]) == code.resolve()
    assert Path(resolved["archive"]) == archive.resolve()
    assert Path(resolved["runtime"]) == code.resolve() / layout.RUNTIME_DIRNAME


def test_archive_defaults_to_the_code_sibling_when_only_code_is_given(tmp_path):
    code = tmp_path / "checkout"

    resolved = layout.resolve(code=str(code))

    assert Path(resolved["archive"]) == code.resolve().parent / layout.ARCHIVE_DIRNAME


# ------------------------------------------------------------- --home mapping
def test_home_maps_to_the_old_data_root_and_its_archive(tmp_path):
    home = tmp_path / "home"

    resolved = layout.resolve(home=str(home))

    assert resolved["mode"] == "home"
    assert Path(resolved["runtime"]) == home.resolve()
    assert Path(resolved["archive"]) == home.resolve() / "archive"
    # The old layout is the same relative category table as the new one.
    assert resolved["paths"] == {
        key: str(home.resolve() / rel) for key, rel in layout.CATEGORY_RELS.items()
    }
    assert resolved["archive_paths"] == {
        key: str(home.resolve() / "archive" / rel)
        for key, rel in layout.ARCHIVE_RELS.items()
    }


def test_home_and_the_new_flags_cannot_be_combined(tmp_path):
    with pytest.raises(HostRunError):
        layout.resolve(home=str(tmp_path / "home"), code=str(tmp_path / "code"))
    with pytest.raises(HostRunError):
        layout.resolve(home=str(tmp_path / "home"), archive=str(tmp_path / "papers"))


# ------------------------------------------------------- out-of-bounds layout
def test_archive_inside_the_code_directory_is_rejected(tmp_path):
    code = tmp_path / "checkout"

    with pytest.raises(HostRunError):
        layout.resolve(code=str(code), archive=str(code / "frontier-archive"))


def test_code_inside_the_archive_is_rejected(tmp_path):
    archive = tmp_path / "papers"

    with pytest.raises(HostRunError):
        layout.resolve(code=str(archive / "checkout"), archive=str(archive))


def test_archive_equal_to_code_is_rejected(tmp_path):
    same = tmp_path / "same"

    with pytest.raises(HostRunError):
        layout.resolve(code=str(same), archive=str(same))


# ------------------------------------------------------------- category table
def test_runtime_categories_cover_the_required_kinds():
    assert set(layout.CATEGORY_RELS) == {
        "config",
        "state",
        "queue",
        "proposals",
        "logs",
        "lease",
        "console",
        "install",
        "init",
        "lark_cli",
    }
    assert set(layout.ARCHIVE_RELS) == {"originals", "pushes"}


# ------------------------------------------------------ establishing the area
def test_ensure_creates_the_runtime_area_and_the_archive_skeleton(tmp_path):
    code = tmp_path / "checkout"
    archive = tmp_path / "papers"
    resolved = layout.resolve(code=str(code), archive=str(archive))

    layout.ensure(resolved)

    for key, rel in layout.CATEGORY_RELS.items():
        parent = Path(resolved["paths"][key]).parent
        assert parent.is_dir(), key
    for key in layout.ARCHIVE_RELS:
        assert Path(resolved["archive_paths"][key]).is_dir()
    assert sorted(p.name for p in archive.iterdir()) == ["originals", "pushes"]


def test_ensure_writes_no_file_into_the_archive(tmp_path):
    resolved = layout.resolve(
        code=str(tmp_path / "checkout"), archive=str(tmp_path / "papers")
    )

    layout.ensure(resolved)

    files = [p for p in Path(resolved["archive"]).rglob("*") if p.is_file()]
    assert files == []


def test_ensure_is_idempotent_and_keeps_existing_files(tmp_path):
    resolved = layout.resolve(
        code=str(tmp_path / "checkout"), archive=str(tmp_path / "papers")
    )
    layout.ensure(resolved)
    kept = Path(resolved["paths"]["logs"]) / "run.log"
    kept.write_text("kept", encoding="utf-8")

    layout.ensure(resolved)

    assert kept.read_text(encoding="utf-8") == "kept"


def test_ensure_leaves_a_legacy_home_untouched(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    resolved = layout.resolve(home=str(home))

    layout.ensure(resolved)

    assert list(home.iterdir()) == []


# ------------------------------------------------------ bounded write helpers
def test_entry_joins_only_inside_its_area(tmp_path):
    resolved = layout.resolve(
        code=str(tmp_path / "checkout"), archive=str(tmp_path / "papers")
    )

    allowed = layout.entry(resolved, "archive", "pushes", "push_1.html")
    assert allowed == Path(resolved["archive_paths"]["pushes"]) / "push_1.html"

    with pytest.raises(HostRunError):
        layout.entry(resolved, "archive", "..", "escape.html")
    with pytest.raises(HostRunError):
        layout.entry(resolved, "runtime", "..", "outside.json")
    with pytest.raises(HostRunError):
        layout.entry(resolved, "elsewhere", "x")


# ----------------------------------------------------------- git hygiene
def test_the_runtime_area_is_gitignored():
    probe = ".frontier/logs/run.log"
    result = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "--quiet", probe],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{probe} is not gitignored: {result.stderr}"


# --------------------------------------------------------------- CLI surface
def test_normalize_accepts_the_new_flags_after_the_subcommand():
    parser = cli.build_parser()

    args = parser.parse_args(
        cli._normalize(["install", "status", "--code", "C", "--archive", "A"])
    )

    assert args.code == "C"
    assert args.archive == "A"
    assert parser.parse_args(
        cli._normalize(["--code", "C", "--archive", "A", "install", "status"])
    ).code == "C"


def test_normalize_keeps_the_last_location_flag():
    parser = cli.build_parser()

    args = parser.parse_args(
        cli._normalize(["status", "--code", "first", "--code", "second"])
    )

    assert args.code == "second"


def test_cli_with_code_and_archive_lands_in_the_runtime_area(tmp_path, capsys):
    code = tmp_path / "checkout"
    archive = tmp_path / "papers"
    code.mkdir()

    rc = cli.main(
        [
            "--code",
            str(code),
            "--archive",
            str(archive),
            "install",
            "record",
            "--step",
            "workspace",
            "--status",
            "ok",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["steps"]["workspace"] == "ok"
    runtime = code / layout.RUNTIME_DIRNAME
    assert (runtime / "install" / "state.json").is_file()
    for rel in layout.RUNTIME_DIRS:
        assert (runtime / rel).is_dir(), rel
    assert sorted(p.name for p in archive.iterdir()) == ["originals", "pushes"]
    assert [p for p in archive.rglob("*") if p.is_file()] == []
    # No run state leaks next to the checkout either.
    assert not (code / "install").exists()


def test_cli_with_home_keeps_the_legacy_layout(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()

    rc = cli.main(
        [
            "--home",
            str(home),
            "install",
            "record",
            "--step",
            "workspace",
            "--status",
            "ok",
        ]
    )

    assert rc == 0
    assert json.loads(capsys.readouterr().out)["steps"]["workspace"] == "ok"
    assert (home / "install" / "state.json").is_file()
    # The mapped legacy layout adds nothing the old contract did not create.
    assert not (home / layout.RUNTIME_DIRNAME).exists()
    assert not (home / "archive").exists()


def test_cli_home_and_code_place_the_same_runtime_files(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    code = tmp_path / "checkout"
    code.mkdir()
    archive = tmp_path / "papers"

    assert (
        cli.main(
            ["--home", str(home), "install", "record", "--step", "workspace", "--status", "ok"]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        cli.main(
            [
                "--code",
                str(code),
                "--archive",
                str(archive),
                "install",
                "record",
                "--step",
                "workspace",
                "--status",
                "ok",
            ]
        )
        == 0
    )
    capsys.readouterr()

    legacy = {p.relative_to(home) for p in home.rglob("*") if p.is_file()}
    new = {
        p.relative_to(code / layout.RUNTIME_DIRNAME)
        for p in (code / layout.RUNTIME_DIRNAME).rglob("*")
        if p.is_file()
    }
    assert legacy == new == {Path("install") / "state.json"}


def test_cli_archive_defaults_next_to_the_code_directory(tmp_path, capsys):
    code = tmp_path / "checkout"
    code.mkdir()

    rc = cli.main(
        [
            "--code",
            str(code),
            "install",
            "record",
            "--step",
            "workspace",
            "--status",
            "ok",
        ]
    )

    assert rc == 0
    capsys.readouterr()
    default_archive = tmp_path / layout.ARCHIVE_DIRNAME
    assert sorted(p.name for p in default_archive.iterdir()) == ["originals", "pushes"]


def test_cli_reports_an_unusable_archive_path_as_json(tmp_path, capsys):
    blocker = tmp_path / "papers"
    blocker.write_text("not a directory", encoding="utf-8")

    rc = cli.main(
        ["--code", str(tmp_path / "checkout"), "--archive", str(blocker), "status"]
    )

    assert rc == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["ok"] is False
    assert "资料目录" in payload["error"]


def test_cli_rejects_home_together_with_code(tmp_path, capsys):
    rc = cli.main(
        [
            "--home",
            str(tmp_path / "home"),
            "--code",
            str(tmp_path / "checkout"),
            "status",
        ]
    )

    assert rc == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["ok"] is False
    assert "--home" in payload["error"]


def test_cli_rejects_an_archive_inside_the_code_directory(tmp_path, capsys):
    rc = cli.main(
        [
            "--code",
            str(tmp_path / "checkout"),
            "--archive",
            str(tmp_path / "checkout" / "papers"),
            "status",
        ]
    )

    assert rc == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["ok"] is False


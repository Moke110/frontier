"""Host-run config base: recorded ``dsh`` path, listener defaults, redaction.

The listener (ADR 0008) is the only resident component; everything it needs is
recorded configuration, so these tests stay offline: no real ``dsh``, no PATH
fallback, no network or credentials.
"""

import json
import os
from pathlib import Path

import pytest

from hostrun import base


def _write_config(home: Path, config: dict) -> Path:
    path = Path(home) / "install" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return path


def _dsh_file(directory: Path, name: str | None = None) -> Path:
    binary = Path(directory) / (name or ("dsh.cmd" if os.name == "nt" else "dsh"))
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text("", encoding="utf-8")
    return binary


def _repair_hint(home: Path) -> str:
    return str(Path(home) / "install" / "config.json")


# ---------------------------------------------------------------- defaults
def test_default_config_records_dsh_and_listener_defaults(tmp_path):
    config = base.default_config(tmp_path / "home")

    assert config["paths"]["dsh"] == ""
    assert config["listener"] == {
        "window_title": "frontier-listener",
        "heartbeat_seconds": 60,
        "feedback_poll_seconds": 300,
        "derived_timeout_seconds": 1200,
        "heartbeat_stale_seconds": 600,
        "recovery_recheck_seconds": 30,
        "start_command": "",
        "stop_command": "",
    }


def test_listener_dir_points_at_home_listener(tmp_path):
    home = tmp_path / "home"

    assert base.listener_dir(home) == Path(home) / "listener"


def test_load_config_fills_listener_defaults_without_overwriting(tmp_path):
    home = tmp_path / "home"
    _write_config(
        home,
        {
            "schema_version": 1,
            "paths": {"dsh": "D:/tools/dsh.cmd"},
            "listener": {"window_title": "custom-title", "heartbeat_seconds": 30},
        },
    )

    config = base.load_config(home)

    # recorded values win ...
    assert config["paths"]["dsh"] == "D:/tools/dsh.cmd"
    assert config["listener"]["window_title"] == "custom-title"
    assert config["listener"]["heartbeat_seconds"] == 30
    # ... and the rest of the section is filled from the defaults.
    assert config["listener"]["feedback_poll_seconds"] == 300
    assert config["listener"]["derived_timeout_seconds"] == 1200
    assert config["listener"]["heartbeat_stale_seconds"] == 600
    assert config["listener"]["recovery_recheck_seconds"] == 30
    assert config["listener"]["start_command"] == ""
    assert config["listener"]["stop_command"] == ""
    # unrelated sections keep their defaults too.
    assert config["paths"]["python"]
    assert config["schedules"]["tasks"] == []


def test_listener_section_and_dsh_round_trip(tmp_path):
    home = tmp_path / "home"
    start = str(Path(home) / "bin" / "frontier-listener.cmd")
    stop = str(Path(home) / "bin" / "frontier-listener-stop.cmd")

    base.update_config(
        home,
        paths={"dsh": "C:/tools/dsh.cmd"},
        listener={"start_command": start, "stop_command": stop},
    )
    loaded = base.load_config(home)

    assert loaded["paths"]["dsh"] == "C:/tools/dsh.cmd"
    assert loaded["listener"]["start_command"] == start
    assert loaded["listener"]["stop_command"] == stop
    assert loaded["listener"]["window_title"] == "frontier-listener"


def test_redaction_masks_credentials_but_keeps_paths_and_listener(tmp_path):
    home = tmp_path / "home"
    config = base.default_config(home)
    config["paths"]["dsh"] = "C:/tools/dsh.cmd"
    config["paths"]["lark_cli"] = "C:/tools/lark-cli.cmd"
    config["app_secret"] = "s3cret"
    config["listener"]["start_command"] = "C:/home/bin/frontier-listener.cmd"

    base.save_config(home, config)

    written = json.loads((home / "install" / "config.json").read_text(encoding="utf-8"))
    assert written["app_secret"] == "***"
    assert written["paths"]["dsh"] == "C:/tools/dsh.cmd"
    assert written["paths"]["lark_cli"] == "C:/tools/lark-cli.cmd"
    assert written["listener"]["start_command"] == "C:/home/bin/frontier-listener.cmd"


# -------------------------------------------------------------------- dsh
def test_dsh_bin_returns_empty_when_unrecorded_even_when_on_path(tmp_path, monkeypatch):
    home = tmp_path / "home"
    on_path = tmp_path / "path-bin"
    _dsh_file(on_path)
    monkeypatch.setenv("PATH", str(on_path))

    assert base.dsh_bin(home) == ""


def test_dsh_bin_rejects_relative_recorded_path(tmp_path):
    home = tmp_path / "home"
    _dsh_file(tmp_path / "tools")
    base.update_config(home, paths={"dsh": "tools/dsh.cmd"})

    assert base.dsh_bin(home) == ""


def test_dsh_bin_rejects_missing_recorded_file(tmp_path):
    home = tmp_path / "home"
    base.update_config(home, paths={"dsh": str(tmp_path / "tools" / "gone.cmd")})

    assert base.dsh_bin(home) == ""


def test_dsh_bin_returns_recorded_absolute_file(tmp_path):
    home = tmp_path / "home"
    binary = _dsh_file(tmp_path / "tools")
    base.update_config(home, paths={"dsh": str(binary)})

    assert base.dsh_bin(home) == str(binary)


def test_require_dsh_returns_recorded_absolute_file(tmp_path):
    home = tmp_path / "home"
    binary = _dsh_file(tmp_path / "tools")
    base.update_config(home, paths={"dsh": str(binary)})

    assert base.require_dsh(home) == str(binary)


def test_require_dsh_explains_repair_when_unrecorded(tmp_path):
    home = tmp_path / "home"

    with pytest.raises(base.HostRunError) as excinfo:
        base.require_dsh(home)

    message = str(excinfo.value)
    assert "paths.dsh" in message
    assert _repair_hint(home) in message


def test_require_dsh_explains_repair_when_relative(tmp_path):
    home = tmp_path / "home"
    _dsh_file(tmp_path / "tools")
    base.update_config(home, paths={"dsh": "tools/dsh.cmd"})

    with pytest.raises(base.HostRunError) as excinfo:
        base.require_dsh(home)

    message = str(excinfo.value)
    assert "paths.dsh" in message
    assert "不是绝对路径" in message
    assert _repair_hint(home) in message


def test_require_dsh_explains_repair_when_missing(tmp_path):
    home = tmp_path / "home"
    gone = tmp_path / "tools" / "gone.cmd"
    base.update_config(home, paths={"dsh": str(gone)})

    with pytest.raises(base.HostRunError) as excinfo:
        base.require_dsh(home)

    message = str(excinfo.value)
    assert "paths.dsh" in message
    assert str(gone) in message
    assert _repair_hint(home) in message

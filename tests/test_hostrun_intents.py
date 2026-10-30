"""Intents: the retired listener check is gone; owner verification stays strict."""

import json
from pathlib import Path

import pytest

from hostrun import intents
from hostrun.base import HostRunError, update_config


def _home(tmp_path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


def test_only_console_intents_remain():
    assert intents.INTENTS == ("daily", "feedback", "maintenance")
    assert not hasattr(intents, "INTENT_LISTENER_CHECK")
    assert not hasattr(intents, "run_listener_check")
    assert not hasattr(intents, "listener_health")


def test_the_listener_check_intent_is_rejected(tmp_path):
    with pytest.raises(HostRunError):
        intents.run(_home(tmp_path), "listener-check")


def test_status_no_longer_reports_host_schedules(tmp_path):
    payload = intents.status(_home(tmp_path))

    assert "schedules" not in payload
    assert "install" in payload


# ------------------------------------------------------------- verified owner
def _recipient(home, payload):
    path = Path(home) / "install" / "recipient.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_verified_owner_accepts_a_verified_recipient_record(tmp_path):
    home = _home(tmp_path)
    _recipient(
        home,
        {
            "schema_version": 1,
            "owner": "ou_ok",
            "verified_at": "2026-10-29T08:00:00+08:00",
            "source": "console.init.transport",
        },
    )

    assert intents.verified_owner(home) == "ou_ok"


def test_verified_owner_rejects_unverified_or_malformed_records(tmp_path):
    home = _home(tmp_path)
    for payload in (
        {"schema_version": 1, "owner": "ou_ok"},  # no verified_at
        {"owner": "ou_ok", "verified_at": "2026-10-29T08:00:00+08:00"},  # no schema
        {"schema_version": 0, "owner": "ou_ok", "verified_at": "2026-10-29T08:00:00+08:00"},
        {"schema_version": 1, "owner": "", "verified_at": "2026-10-29T08:00:00+08:00"},
        {"schema_version": 1, "owner": "ou_ok", "verified_at": ""},
    ):
        _recipient(home, payload)
        assert intents.verified_owner(home) == ""


def test_verified_owner_never_falls_back_to_the_unverified_config(tmp_path):
    """#72 item 5: the unverified config owner is not an acceptable recipient."""
    home = _home(tmp_path)
    update_config(home, permissions={"owner": "ou_unverified"})

    assert intents.verified_owner(home) == ""
    # The legacy helper keeps its old fallback for existing callers.
    assert intents._owner(home) == "ou_unverified"

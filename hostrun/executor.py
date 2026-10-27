"""Single-executor lease: one host drives one knowledge base at a time.

ADR 0005 keeps the first version single-user / single-executor. Overlapping runs
on the same machine must not consume or deliver twice, and switching computers
must be an explicit act. The lease is time-based (not pid-based) because the
previous executor may be another host, whose pids mean nothing here.

States:
  free       no lease file
  held       valid lease owned by this host, or by another host we must wait for
  stale      lease expired — the next run may take over, and says so in the log
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from common import append_jsonl, ensure_dir, now, read_json, write_json
from hostrun.base import HostRunError

DEFAULT_MINUTES = 45
LEASE_REL = Path("executor") / "lease.json"
EVENTS_REL = Path("executor") / "events.jsonl"


def _at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


def _event(home: Path, kind: str, **fields) -> None:
    append_jsonl(Path(home) / EVENTS_REL, {"schema_version": 1, "at": now(), "kind": kind, **fields})


def read_lease(home: Path) -> dict | None:
    return read_json(Path(home) / LEASE_REL)


def status(home: Path, *, at: datetime | None = None) -> dict:
    lease = read_lease(home)
    if not lease:
        return {"schema_version": 1, "state": "free", "host": None, "lease_until": None}
    until = _at(lease.get("lease_until"))
    moment = at or datetime.now().astimezone()
    state = "held" if until and until > moment else "stale"
    return {
        "schema_version": 1,
        "state": state,
        "host": lease.get("host"),
        "run_id": lease.get("run_id"),
        "lease_until": lease.get("lease_until"),
        "heartbeat_at": lease.get("heartbeat_at"),
    }


def acquire(
    home: Path,
    *,
    host: str,
    minutes: int = DEFAULT_MINUTES,
    run_id: str | None = None,
    at: datetime | None = None,
) -> dict:
    """Take the lease, or report who holds it. Never waits, never forces."""
    host = str(host or "").strip()
    if not host:
        raise HostRunError("executor host id is required")
    home = Path(home)
    moment = at or datetime.now().astimezone()
    current = read_lease(home)
    if current:
        until = _at(current.get("lease_until"))
        other = str(current.get("host") or "")
        if until and until > moment and other != host:
            _event(home, "blocked", host=host, holder=other, lease_until=current.get("lease_until"))
            return {"ok": False, "reason": "executor_busy", "holder": other, "lease_until": current.get("lease_until")}
        if until and until <= moment:
            _event(home, "taken_over", host=host, previous=other, expired_at=current.get("lease_until"))
    lease = {
        "schema_version": 1,
        "host": host,
        "run_id": run_id or f"{host}-{moment.strftime('%Y%m%dT%H%M%S')}",
        "acquired_at": current.get("acquired_at") if current and current.get("host") == host else moment.isoformat(timespec="seconds"),
        "heartbeat_at": moment.isoformat(timespec="seconds"),
        "lease_until": (moment + timedelta(minutes=max(1, int(minutes)))).isoformat(timespec="seconds"),
    }
    ensure_dir((home / LEASE_REL).parent)
    write_json(home / LEASE_REL, lease)
    _event(home, "acquired", host=host, run_id=lease["run_id"], lease_until=lease["lease_until"])
    return {"ok": True, "lease": lease, "took_over": bool(current and current.get("host") != host)}


def heartbeat(home: Path, *, host: str, minutes: int = DEFAULT_MINUTES, at: datetime | None = None) -> dict:
    home = Path(home)
    moment = at or datetime.now().astimezone()
    lease = read_lease(home)
    if not lease or str(lease.get("host")) != str(host):
        return {"ok": False, "reason": "not_holder"}
    lease["heartbeat_at"] = moment.isoformat(timespec="seconds")
    lease["lease_until"] = (moment + timedelta(minutes=max(1, int(minutes)))).isoformat(timespec="seconds")
    write_json(home / LEASE_REL, lease)
    return {"ok": True, "lease": lease}


def release(home: Path, *, host: str, ok: bool = True, reason: str = "") -> dict:
    home = Path(home)
    lease = read_lease(home)
    if not lease:
        return {"ok": True, "released": False}
    if str(lease.get("host")) != str(host):
        return {"ok": False, "reason": "not_holder", "holder": lease.get("host")}
    (home / LEASE_REL).unlink(missing_ok=True)
    _event(home, "released", host=host, ok=ok, reason=reason)
    return {"ok": True, "released": True}


def handover(home: Path, *, to_host: str, from_host: str | None = None, force: bool = False) -> dict:
    """Explicit switch: the old executor must be stopped, not merely ignored."""
    home = Path(home)
    current = read_lease(home)
    if not current:
        _event(home, "handover", to_host=to_host, from_host=from_host, empty=True)
        return {"ok": True, "handover": True, "note": "没有正在执行的旧宿主"}
    holder = str(current.get("host") or "")
    live = status(home)["state"] == "held"
    if from_host and holder and holder != str(from_host):
        return {"ok": False, "reason": "unexpected_holder", "holder": holder}
    if live and not force:
        return {
            "ok": False,
            "reason": "old_executor_active",
            "holder": holder,
            "note": "先在旧宿主结束本次运行并停用其任务再切换；确认后可用 --force 记录强制接管",
        }
    (home / LEASE_REL).unlink(missing_ok=True)
    _event(home, "handover", to_host=to_host, from_host=from_host or holder, forced=bool(live))
    return {"ok": True, "handover": True, "from": from_host or holder, "to": to_host, "forced": bool(live)}

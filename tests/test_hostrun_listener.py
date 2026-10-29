"""Offline tests for the listener core (issue #67, ADR 0008).

No real lark-cli, dsh, network or sleeps: the event source, spawner, clock,
sleep, messenger, install report and status snapshot are injected. The live
argv/envelope/exit-code meanings stay ``untested`` against a real host.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from common import file_lock
from hostrun import executor, listener

OWNER = "ou_owner_1"
HOST = "workbuddy"


# ------------------------------------------------------------------ fixtures
def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / "install").mkdir(parents=True)
    (home / "listener").mkdir(parents=True)
    (home / "install" / "recipient.json").write_text(
        json.dumps({"schema_version": 1, "owner": OWNER}), encoding="utf-8"
    )
    return home


def _config(home: Path, *, listener_config=None, dsh: str | None = None, host: str = HOST) -> dict:
    config = {
        "schema_version": 1,
        "host": {"product": host},
        "paths": {"home": str(home), "repo": str(home)},
        "listener": listener_config or {},
    }
    if dsh:
        config["paths"]["dsh"] = dsh
    path = home / "install" / "config.json"
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return config


def _event(
    text: str = "状态",
    *,
    chat_type: str = "p2p",
    sender: str = OWNER,
    sender_type: str = "user",
    message_type: str = "text",
    content: object = None,
) -> dict:
    payload = content if content is not None else json.dumps({"text": text}, ensure_ascii=False)
    return {
        "sender": {"sender_id": {"open_id": sender}, "sender_type": sender_type},
        "message": {
            "chat_type": chat_type,
            "chat_id": "oc_chat_1" if chat_type == "p2p" else "oc_group_1",
            "message_id": "om_1",
            "message_type": message_type,
            "content": payload,
        },
    }


def _wrapped(event: dict) -> dict:
    return {"type": "im.message.receive_v1", "data": {"event": event}}


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.value = start
        self.sleeps: list[float] = []
        self.on_sleep = None

    def clock(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(float(seconds))
        self.value += float(seconds)
        if self.on_sleep is not None:
            self.on_sleep(self)


class FakeProc:
    """A child that exits (or ignores termination) after simulated time."""

    def __init__(self, clock: FakeClock, *, exit_after: float = 5.0, returncode: int = 0):
        self.clock = clock
        self.started = clock.value
        self.exit_after = exit_after
        self.final = returncode
        self.returncode: int | None = None
        self.killed = False

    def poll(self) -> int | None:
        if self.returncode is None and self.clock.value - self.started >= self.exit_after:
            self.returncode = self.final
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def _starter_consumer(script, *, lines_by_call=None, on_call=None):
    """Fake event source: returns scripted chunk results, feeds scripted lines."""
    calls = []

    def consume(**kwargs):
        calls.append(kwargs)
        index = len(calls) - 1
        feed = (lines_by_call or {}).get(index) or []
        on_line = kwargs.get("on_line")
        if on_line is not None:
            for line in feed:
                on_line(line)
        if on_call is not None:
            on_call(index, kwargs)
        return dict(script[min(index, len(script) - 1)])

    return consume, calls


def _ok_chunk(**extra) -> dict:
    return {"ok": True, "reason": "ok", "kind": "ok", "returncode": 0, **extra}


def _transient(code: int = 4) -> dict:
    return {
        "ok": False,
        "reason": "transient" if code == 4 else "token_storage_lock",
        "kind": "transient" if code == 4 else "token_storage_lock",
        "returncode": code,
        "fatal": False,
        "retryable": True,
    }


def _fatal_scope() -> dict:
    return {
        "ok": False,
        "reason": "app_scope_not_applied",
        "kind": "app_scope_not_applied",
        "returncode": 3,
        "fatal": True,
        "retryable": False,
    }


def _report(*, blocked=None):
    def report(home):
        return {"ok": not blocked, "blocked": blocked or [], "untested": [], "pending": []}

    return report


def _status_snapshot():
    return {
        "executor": {"state": "free"},
        "queue": {"items": 2, "unfinished": False, "active": None},
        "schedules": {"tasks": [], "verified": []},
        "install": {"steps": {"knowledge": "ok"}},
    }


# ------------------------------------------------------------------- parsing
def test_parse_message_event_accepts_the_lark_cli_wrapper():
    event = listener.parse_message_event(_wrapped(_event("状态")))

    assert event is not None
    assert event["event_type"] == "im.message.receive_v1"
    assert event["chat_type"] == "p2p"
    assert event["chat_id"] == "oc_chat_1"
    assert event["message_id"] == "om_1"
    assert event["sender_type"] == "user"
    assert event["sender_id"] == OWNER
    assert event["message_type"] == "text"
    assert event["text"] == "状态"


def test_parse_message_event_accepts_an_event_envelope_and_a_bare_event():
    wrapped = listener.parse_message_event({"event": _event("推一篇")})
    bare = listener.parse_message_event(_event("处理反馈", content={"text": "处理反馈"}))

    assert wrapped["text"] == "推一篇"
    assert bare["text"] == "处理反馈"
    assert bare["message_type"] == "text"


def test_parse_message_event_ignores_non_message_events():
    card = {"type": "card.action.trigger", "data": {"event": {}}}
    empty_message = {"event": {"message": {}}}
    assert listener.parse_message_event(card) is None
    assert listener.parse_message_event({"event": {"foo": "bar"}}) is None
    assert listener.parse_message_event(empty_message) is None
    assert listener.parse_message_event("not-a-dict") is None


def test_parse_message_event_tolerates_plain_text_content():
    event = listener.parse_message_event(_event(content="状态"))

    assert event["text"] == "状态"


# ---------------------------------------------------------------- classification
@pytest.mark.parametrize(
    "text,action",
    [("推一篇", "daily"), ("处理反馈", "feedback"), ("状态", "status")],
)
def test_owner_dm_commands_map_to_actions(tmp_path, text, action):
    home = _home(tmp_path)

    decision = listener.classify_message(
        home, listener.parse_message_event(_wrapped(_event(text)))
    )

    assert decision["action"] == action
    assert decision["target"] == OWNER
    assert decision["ok"] is True


def test_unknown_text_is_usage_and_group_or_other_sender_is_ignored(tmp_path):
    home = _home(tmp_path)

    unknown = listener.classify_message(home, listener.parse_message_event(_event("随便聊聊")))
    group = listener.classify_message(
        home, listener.parse_message_event(_event("状态", chat_type="group"))
    )
    other = listener.classify_message(
        home, listener.parse_message_event(_event("状态", sender="ou_someone"))
    )

    assert unknown["action"] == "usage"
    assert group["action"] == "ignored" and group["reason"] == "not_owner_dm"
    assert other["action"] == "ignored" and other["reason"] == "not_owner"
    assert group["target"] is None and other["target"] is None


# -------------------------------------------------------------------- dispatch
def test_dispatch_unknown_text_sends_the_fixed_usage_hint(tmp_path):
    home = _home(tmp_path)
    sent = []

    result = listener.dispatch_message(
        home,
        listener.parse_message_event(_event("随便聊聊")),
        send=lambda target, text: sent.append((target, text)),
    )

    assert result["replied"] is True
    assert sent == [(OWNER, listener.USAGE_HINT)]


def test_dispatch_group_or_other_sender_never_replies_or_acts(tmp_path):
    home = _home(tmp_path)
    sent = []
    runs = []

    for event in (
        listener.parse_message_event(_event("推一篇", chat_type="group")),
        listener.parse_message_event(_event("推一篇", sender="ou_someone")),
    ):
        result = listener.dispatch_message(
            home,
            event,
            send=lambda target, text: sent.append((target, text)),
            run=lambda *a, **k: runs.append((a, k)),
        )
        assert result["action"] == "ignored"
        assert result["replied"] is False

    assert sent == [] and runs == []


def test_dispatch_status_sends_a_summary_receipt(tmp_path):
    home = _home(tmp_path)
    sent = []

    result = listener.dispatch_message(
        home,
        listener.parse_message_event(_event("状态")),
        send=lambda target, text: sent.append((target, text)),
        status=lambda home: _status_snapshot(),
    )

    assert result["action"] == "status"
    target, text = sent[0]
    assert target == OWNER
    assert "监听" in text and "执行端" in text and "队列" in text and "知识" in text


def test_dispatch_feedback_runs_a_mechanical_poll_and_replies(tmp_path):
    home = _home(tmp_path)
    _config(home)
    sent = []
    runs = []

    def run(home, intent, *, host, minutes):
        runs.append((intent, host, minutes))
        return {"ok": True, "quiet": True, "actions": []}

    result = listener.dispatch_message(
        home,
        listener.parse_message_event(_event("处理反馈")),
        send=lambda target, text: sent.append((target, text)),
        run=run,
    )

    assert result["action"] == "feedback"
    assert result["replied"] is True
    assert runs == [("feedback", HOST, 5)]
    assert sent and sent[0][0] == OWNER


def test_dispatch_push_command_goes_through_the_derived_run(monkeypatch, tmp_path):
    home = _home(tmp_path)
    calls = []

    def fake_derived(home, intent, **kwargs):
        calls.append((intent, kwargs.get("target")))
        return {"ok": True, "reason": "ok", "reply_text": "ok"}

    monkeypatch.setattr(listener, "run_derived", fake_derived)

    result = listener.dispatch_message(
        home,
        listener.parse_message_event(_event("推一篇")),
        send=lambda target, text: None,
    )

    assert result["action"] == "daily"
    assert calls == [("daily", OWNER)]


# -------------------------------------------------------------- status receipt
def test_status_snapshot_and_text_cover_listener_and_host_subsystems(tmp_path):
    home = _home(tmp_path)
    listener.write_heartbeat(home, started_at="2026-10-29T08:00:00+08:00", pid=7)

    snapshot = listener.status_snapshot(home, status=lambda home: _status_snapshot())
    text = listener.status_text(snapshot)

    assert snapshot["listener"]["pid"] == 7
    assert snapshot["executor"]["state"] == "free"
    assert snapshot["knowledge"] == "ok"
    assert "执行端：free" in text
    assert "知识：ok" in text


# ------------------------------------------------------------------ heartbeat
def test_heartbeat_has_the_documented_schema(tmp_path):
    home = _home(tmp_path)

    listener.write_heartbeat(home, started_at="2026-10-29T08:00:00+08:00", pid=1234)
    beat = listener.read_heartbeat(home)

    assert beat["schema_version"] == 1
    assert beat["pid"] == 1234
    assert beat["started_at"] == "2026-10-29T08:00:00+08:00"
    assert beat["updated_at"]
    assert beat["state"] == "running"
    assert beat["last_event_at"] is None
    assert beat["last_success_at"] is None
    assert beat["consecutive_failures"] == 0
    assert beat["last_error"] == ""


def test_heartbeat_preserves_degraded_state_fields(tmp_path):
    home = _home(tmp_path)

    listener.write_heartbeat(
        home, state="degraded", consecutive_failures=5, last_error="app_scope_not_applied"
    )
    beat = listener.read_heartbeat(home)

    assert beat["state"] == "degraded"
    assert beat["consecutive_failures"] == 5
    assert beat["last_error"] == "app_scope_not_applied"


# ---------------------------------------------------------------- console title
def test_console_title_is_a_no_op_off_windows():
    assert listener.set_console_title("frontier-listener", platform="posix") is False


# ---------------------------------------------------------------------- logging
def test_log_rotates_when_it_exceeds_the_limit(tmp_path, monkeypatch):
    home = _home(tmp_path)
    monkeypatch.setattr(listener, "LOG_MAX_BYTES", 120)
    first = "x" * 200

    listener.log_line(home, first)
    listener.log_line(home, "second line")

    assert (home / "listener" / "listener.log").exists()
    backup = (home / "listener" / "listener.log.1").read_text(encoding="utf-8")
    assert first in backup
    assert "second line" not in backup


# ------------------------------------------------------------------ serve/lock
def test_second_instance_cannot_take_the_lock(tmp_path):
    home = _home(tmp_path)
    _config(home)

    with file_lock(listener.lock_path(home), blocking=False) as held:
        assert held is True
        result = listener.serve(home, set_title=lambda title: None)

    assert result["ok"] is False
    assert result["reason"] == "already_running"


def test_serve_stops_on_the_sentinel_and_releases_the_lock(tmp_path):
    home = _home(tmp_path)
    _config(home)
    clock = FakeClock()
    consume, calls = _starter_consumer([_ok_chunk()])
    titles = []

    def on_sleep(fake):
        if len(fake.sleeps) >= 3:
            listener.request_stop(home)

    clock.on_sleep = on_sleep
    result = listener.serve(
        home,
        consume=consume,
        clock=clock.clock,
        sleep=clock.sleep,
        set_title=titles.append,
    )

    assert result["ok"] is True
    assert result["reason"] == "stopped"
    assert result["ticks"] >= 3
    assert titles == ["frontier-listener"]
    assert calls and calls[0]["event_key"] == "im.message.receive_v1"
    assert calls[0]["identity"] == "bot"
    with file_lock(listener.lock_path(home), blocking=False) as again:
        assert again is True


def test_a_second_instance_does_not_clear_a_pending_stop(tmp_path):
    home = _home(tmp_path)
    _config(home)
    listener.request_stop(home)

    with file_lock(listener.lock_path(home), blocking=False) as held:
        assert held is True
        result = listener.serve(home, set_title=lambda title: None)

    assert result["reason"] == "already_running"
    assert listener.stop_path(home).exists() is True


def test_serve_clears_a_stale_stop_sentinel_before_running(tmp_path):
    home = _home(tmp_path)
    _config(home)
    listener.request_stop(home)
    clock = FakeClock()
    consume, _calls = _starter_consumer([_ok_chunk()])
    clock.on_sleep = lambda fake: listener.request_stop(home) if len(fake.sleeps) >= 1 else None

    result = listener.serve(home, consume=consume, clock=clock.clock, sleep=clock.sleep)

    assert result["ok"] is True
    assert result["ticks"] >= 1


def test_serve_rewrites_the_heartbeat_at_least_every_60_seconds(tmp_path, monkeypatch):
    home = _home(tmp_path)
    _config(home)
    clock = FakeClock()
    consume, _calls = _starter_consumer([_ok_chunk()])
    writes = []
    original = listener.write_heartbeat

    def recording(home_path, **beat):
        writes.append({"clock": clock.value, **beat})
        return original(home_path, **beat)

    monkeypatch.setattr(listener, "write_heartbeat", recording)
    clock.on_sleep = lambda fake: listener.request_stop(home) if len(fake.sleeps) >= 7 else None

    def sleep(seconds):
        clock.sleep(float(seconds) * 10)  # 10 s of fake time per tick

    result = listener.serve(home, consume=consume, clock=clock.clock, sleep=sleep)

    assert result["ok"] is True
    assert len(writes) >= 2
    assert writes[0]["clock"] == 1000.0
    assert writes[1]["clock"] - writes[0]["clock"] >= 60


def test_serve_routes_an_owner_command_and_updates_the_event_time(tmp_path):
    home = _home(tmp_path)
    _config(home)
    clock = FakeClock()
    sent = []
    line = json.dumps(_wrapped(_event("状态")), ensure_ascii=False)
    consume, _calls = _starter_consumer([_ok_chunk()], lines_by_call={0: [line, "not json"]})
    clock.on_sleep = lambda fake: listener.request_stop(home) if len(fake.sleeps) >= 2 else None

    result = listener.serve(
        home,
        consume=consume,
        send=lambda target, text: sent.append((target, text)),
        status=lambda home: _status_snapshot(),
        clock=clock.clock,
        sleep=clock.sleep,
    )

    assert result["events"] == 1
    assert sent and sent[0][0] == OWNER and "监听" in sent[0][1]
    assert result["heartbeat"]["last_event_at"]


# ------------------------------------------------------------------- backoff
def test_transient_failures_back_off_5_15_30_60_and_cap(tmp_path, monkeypatch):
    home = _home(tmp_path)
    _config(home)
    clock = FakeClock()
    consume, calls = _starter_consumer([_transient(4)] * 5 + [_ok_chunk()] * 5)
    writes = []
    original = listener.write_heartbeat

    def recording(home_path, **beat):
        writes.append(dict(beat))
        return original(home_path, **beat)

    monkeypatch.setattr(listener, "write_heartbeat", recording)
    clock.on_sleep = lambda fake: listener.request_stop(home) if len(fake.sleeps) >= 6 else None

    def sleep(seconds):
        clock.sleep(float(seconds))

    result = listener.serve(home, consume=consume, clock=clock.clock, sleep=sleep)

    assert result["ok"] is True
    assert clock.sleeps[:6] == [5.0, 15.0, 30.0, 60.0, 60.0, 1.0]
    assert any(row["state"] == "degraded" and row["consecutive_failures"] == 5 for row in writes)
    assert result["heartbeat"]["state"] == "running"
    assert result["heartbeat"]["consecutive_failures"] == 0
    assert len(calls) >= 6


def test_exit_code_3_is_fatal_and_stops_the_listener(tmp_path):
    home = _home(tmp_path)
    _config(home)
    clock = FakeClock()
    consume, calls = _starter_consumer([_fatal_scope()])

    result = listener.serve(
        home,
        consume=consume,
        clock=clock.clock,
        sleep=clock.sleep,
    )

    assert result["ok"] is False
    assert result["reason"] == "app_scope_not_applied"
    assert result["returncode"] == 3
    assert len(calls) == 1
    beat = listener.read_heartbeat(home)
    assert beat["state"] == "degraded"
    assert "app_scope_not_applied" in beat["last_error"]
    assert clock.sleeps == []
    log = (home / "listener" / "listener.log").read_text(encoding="utf-8")
    assert "app_scope_not_applied" in log


def test_feedback_poll_skips_when_the_lease_is_held(tmp_path):
    home = _home(tmp_path)
    _config(home)
    executor.acquire(home, host="other-host", minutes=30)
    calls = []

    result = listener.poll_feedback(
        home, host=HOST, run=lambda home, intent, **kwargs: calls.append((intent, kwargs))
    )

    assert result["ok"] is True
    assert result["skipped"] == "executor_busy"
    assert calls == []
    assert executor.read_lease(home)["host"] == "other-host"


def test_serve_polls_feedback_on_the_configured_interval_and_stays_quiet(tmp_path):
    home = _home(tmp_path)
    _config(home, listener_config={"feedback_poll_seconds": 10})
    clock = FakeClock()
    consume, _calls = _starter_consumer([_ok_chunk()])
    runs = []
    sent = []

    def run(home_path, intent, *, host, minutes):
        runs.append((intent, host, minutes))
        return {"ok": True, "quiet": True, "actions": []}

    clock.on_sleep = lambda fake: listener.request_stop(home) if len(fake.sleeps) >= 4 else None

    def sleep(seconds):
        clock.sleep(5.0)  # 5 s of fake time per tick

    result = listener.serve(
        home,
        consume=consume,
        run=run,
        send=lambda target, text: sent.append((target, text)),
        clock=clock.clock,
        sleep=sleep,
    )

    assert result["ok"] is True
    assert ("feedback", HOST, 5) in runs
    assert sent == []


# ------------------------------------------------------------- derived-run guards
def test_derived_argv_is_the_documented_dsh_contract():
    assert listener.derived_argv("C:/dsh/dsh.cmd", "do the push") == [
        "C:/dsh/dsh.cmd",
        "--profile",
        "headless",
        "--prompt",
        "do the push",
    ]


def test_record_derived_run_matches_the_runs_jsonl_schema(tmp_path):
    home = _home(tmp_path)

    listener.record_derived_run(home, {"intent": "daily", "ok": True, "quiet": False})

    rows = [
        json.loads(line)
        for line in (home / "hostrun" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["schema_version"] == 1
    assert rows[0]["at"]
    assert rows[0]["derived"] is True
    assert rows[0]["parent"] == "listener"
    assert rows[0]["intent"] == "daily"


def test_derived_run_is_single_flight(tmp_path):
    home = _home(tmp_path)
    _config(home)
    sent = []
    calls = []

    with file_lock(listener.derived_lock_path(home), blocking=False) as held:
        assert held is True
        result = listener.run_derived(
            home,
            "daily",
            send=lambda target, text: sent.append((target, text)),
            run=lambda *a, **k: calls.append("run"),
            report=_report(),
        )

    assert result["ok"] is False
    assert result["reason"] == "derived_busy"
    assert calls == []
    assert sent and "稍后" in sent[0][1]


def test_derived_run_refuses_when_install_has_blocked_steps(tmp_path):
    home = _home(tmp_path)
    _config(home)
    sent = []
    runs = []

    result = listener.run_derived(
        home,
        "daily",
        send=lambda target, text: sent.append((target, text)),
        run=lambda home, intent, **kwargs: runs.append(intent),
        report=_report(blocked=[{"step": "lark_cli", "note": "missing"}]),
    )

    assert result["ok"] is False
    assert result["reason"] == "install_blocked"
    assert runs == []
    assert sent and "lark_cli" in sent[0][1]


def test_derived_run_refuses_without_a_recorded_dsh(tmp_path):
    home = _home(tmp_path)
    _config(home)
    sent = []

    result = listener.run_derived(
        home,
        "daily",
        send=lambda target, text: sent.append((target, text)),
        run=lambda home, intent, **kwargs: pytest.fail("must not run"),
        report=_report(),
    )

    assert result["ok"] is False
    assert result["reason"] == "dsh_missing"
    assert sent and "dsh" in sent[0][1]


def test_derived_run_refuses_when_the_executor_lease_is_held(tmp_path):
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))
    executor.acquire(home, host="other-host", minutes=30)
    sent = []

    result = listener.run_derived(
        home,
        "daily",
        send=lambda target, text: sent.append((target, text)),
        run=lambda home, intent, **kwargs: pytest.fail("must not run"),
        report=_report(),
    )

    assert result["ok"] is False
    assert result["reason"] == "executor_busy"
    assert sent


def test_derived_daily_run_spawns_dsh_and_records_a_derived_row(tmp_path):
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))
    clock = FakeClock()
    spawns = []
    sent = []

    def spawn(argv, **kwargs):
        spawns.append((argv, kwargs))
        return FakeProc(clock, exit_after=5.0, returncode=0)

    def run(home_path, intent, **kwargs):
        return {"ok": True, "brief": "BRIEF-TEXT", "next": "finish", "actions": []}

    result = listener.run_derived(
        home,
        "daily",
        send=lambda target, text: sent.append((target, text)),
        run=run,
        spawn=spawn,
        report=_report(),
        clock=clock.clock,
        sleep=clock.sleep,
        timeout_seconds=30,
    )

    assert result["ok"] is True
    argv, kwargs = spawns[0]
    assert argv == list(listener.derived_argv(str(dsh), "BRIEF-TEXT"))
    assert kwargs["stdin"] is not None
    assert sent and "派生" in sent[0][1]
    rows = [
        json.loads(line)
        for line in (home / "hostrun" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[-1]["derived"] is True and rows[-1]["ok"] is True
    assert executor.status(home)["state"] == "free"


def test_derived_run_times_out_kills_the_child_and_never_retries(tmp_path):
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))
    clock = FakeClock()
    procs = []
    sent = []

    def spawn(argv, **kwargs):
        proc = FakeProc(clock, exit_after=10_000.0)
        procs.append(proc)
        return proc

    result = listener.run_derived(
        home,
        "daily",
        send=lambda target, text: sent.append((target, text)),
        run=lambda home, intent, **kwargs: {"ok": True, "brief": "B", "next": "f"},
        spawn=spawn,
        report=_report(),
        clock=clock.clock,
        sleep=clock.sleep,
        timeout_seconds=20,
    )

    assert result["ok"] is False
    assert result["reason"] == "timeout"
    assert procs[0].killed is True
    assert len(procs) == 1
    assert sent and "超时" in sent[0][1]
    rows = [
        json.loads(line)
        for line in (home / "hostrun" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[-1]["timed_out"] is True and rows[-1]["ok"] is False
    assert executor.status(home)["state"] == "free"


def test_derived_run_reports_a_child_failure_without_retrying(tmp_path):
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))
    clock = FakeClock()
    procs = []
    sent = []

    def spawn(argv, **kwargs):
        proc = FakeProc(clock, exit_after=2.0, returncode=1)
        procs.append(proc)
        return proc

    result = listener.run_derived(
        home,
        "daily",
        send=lambda target, text: sent.append((target, text)),
        run=lambda home, intent, **kwargs: {"ok": True, "brief": "B", "next": "f"},
        spawn=spawn,
        report=_report(),
        clock=clock.clock,
        sleep=clock.sleep,
        timeout_seconds=30,
    )

    assert result["ok"] is False
    assert result["reason"] == "child_failed"
    assert result["returncode"] == 1
    assert len(procs) == 1
    assert sent and "1" in sent[0][1]


def test_derived_daily_run_without_a_brief_does_not_spawn(tmp_path):
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))
    sent = []
    spawns = []

    result = listener.run_derived(
        home,
        "daily",
        send=lambda target, text: sent.append((target, text)),
        run=lambda home, intent, **kwargs: {"ok": True, "brief": None, "next": "queue busy"},
        spawn=lambda *a, **k: spawns.append(a),
        report=_report(),
    )

    assert result["ok"] is False
    assert result["reason"] == "no_brief"
    assert spawns == []
    assert sent and "queue busy" in sent[0][1]


def test_derived_feedback_run_is_mechanical_and_replies(tmp_path):
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))
    sent = []

    result = listener.run_derived(
        home,
        "feedback",
        send=lambda target, text: sent.append((target, text)),
        run=lambda home, intent, **kwargs: {"ok": True, "quiet": False, "actions": ["feedback:1"]},
        spawn=lambda *a, **k: pytest.fail("feedback must not spawn a model run"),
        report=_report(),
    )

    assert result["ok"] is True
    assert result["reason"] == "no_derived_session"
    assert sent and sent[0][0] == OWNER


def test_derived_run_stops_when_the_listener_stops(tmp_path):
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))
    clock = FakeClock()
    procs = []
    sent = []
    stop = {"now": False}

    def spawn(argv, **kwargs):
        proc = FakeProc(clock, exit_after=10_000.0)
        procs.append(proc)
        return proc

    def sleep(seconds):
        clock.sleep(float(seconds))
        stop["now"] = True  # a stop arrives while the child is running

    result = listener.run_derived(
        home,
        "daily",
        send=lambda target, text: sent.append((target, text)),
        run=lambda home, intent, **kwargs: {"ok": True, "brief": "B", "next": "f"},
        spawn=spawn,
        report=_report(),
        clock=clock.clock,
        sleep=sleep,
        timeout_seconds=120,
        should_stop=lambda: stop["now"],
    )

    assert result["ok"] is False
    assert result["reason"] == "stopped"
    assert procs[0].killed is True
    assert sent and "停止" in sent[0][1]


def test_derived_run_reports_a_spawn_error_without_retrying(tmp_path):
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))
    sent = []

    def spawn(argv, **kwargs):
        raise OSError("cannot start dsh")

    result = listener.run_derived(
        home,
        "daily",
        send=lambda target, text: sent.append((target, text)),
        run=lambda home, intent, **kwargs: {"ok": True, "brief": "B", "next": "f"},
        spawn=spawn,
        report=_report(),
        clock=FakeClock().clock,
        sleep=lambda seconds: None,
        timeout_seconds=30,
    )

    assert result["ok"] is False
    assert result["reason"] == "spawn_failed"
    assert sent and "启动失败" in sent[0][1]
    assert executor.status(home)["state"] == "free"

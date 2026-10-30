"""Offline tests for the listener core (issue #67, ADR 0008).

No real lark-cli, dsh, network or sleeps: the event source, spawner, clock,
sleep, messenger, install report and status snapshot are injected. The live
argv/envelope/exit-code meanings stay ``untested`` against a real host.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
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
        json.dumps(
            {"schema_version": 1, "owner": OWNER, "verified_at": "2026-10-29T08:00:00+08:00"}
        ),
        encoding="utf-8",
    )
    return home


def _unverified_home(tmp_path: Path) -> Path:
    """A home whose recipient record exists but was never verified (#72 item 5)."""
    home = _home(tmp_path)
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


def test_a_dm_from_an_unverified_recipient_is_ignored_without_reply_or_action(tmp_path):
    """#72 item 5: only a recipient recorded with verified_at may command."""
    home = _unverified_home(tmp_path)
    sent = []
    runs = []

    for event in (
        listener.parse_message_event(_wrapped(_event("状态"))),
        listener.parse_message_event(_wrapped(_event("推一篇"))),
    ):
        decision = listener.classify_message(home, event)
        result = listener.dispatch_message(
            home,
            event,
            send=lambda target, text: sent.append((target, text)),
            run=lambda *a, **k: runs.append("run"),
        )
        assert decision["action"] == "ignored"
        assert decision["reason"] == "not_owner"
        assert result["action"] == "ignored"
        assert result["replied"] is False

    assert sent == [] and runs == []


def test_a_missing_recipient_record_ignores_every_dm(tmp_path):
    home = _home(tmp_path)
    (home / "install" / "recipient.json").unlink()
    sent = []

    result = listener.dispatch_message(
        home,
        listener.parse_message_event(_wrapped(_event("推一篇"))),
        send=lambda target, text: sent.append((target, text)),
    )

    assert result["action"] == "ignored"
    assert sent == []


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


def test_dispatch_feedback_starts_a_background_poll_and_replies_immediately(monkeypatch, tmp_path):
    """#73: explicit 处理反馈 replies at once, then runs off the event loop."""
    home = _home(tmp_path)
    _config(home)
    sent = []
    pending = []
    polled = []

    def fake_poll(home_path, *, host=None, run=None):
        polled.append("poll")
        return {
            "ok": True,
            "skipped": None,
            "quiet": False,
            "run": {"ok": True, "quiet": False, "actions": ["feedback:2 processed"]},
        }

    monkeypatch.setattr(listener, "poll_feedback", fake_poll)

    result = listener.dispatch_message(
        home,
        listener.parse_message_event(_event("处理反馈")),
        send=lambda target, text: sent.append((target, text)),
        start_worker=pending.append,
    )

    assert result["action"] == "feedback"
    assert result["status"] == "started"
    assert result["replied"] is True
    assert sent and sent[0][0] == OWNER and "已开始处理反馈" in sent[0][1]
    assert polled == [] and len(pending) == 1  # not executed on the loop thread

    pending[0]()
    assert polled == ["poll"]
    assert len(sent) == 2 and "反馈已处理" in sent[1][1]


def test_dispatch_feedback_stays_silent_after_a_no_change_poll(monkeypatch, tmp_path):
    home = _home(tmp_path)
    _config(home)
    sent = []

    monkeypatch.setattr(
        listener,
        "poll_feedback",
        lambda home_path, *, host=None, run=None: {
            "ok": True,
            "skipped": None,
            "quiet": True,
            "run": {"ok": True, "quiet": True, "actions": []},
        },
    )

    listener.dispatch_message(
        home,
        listener.parse_message_event(_event("处理反馈")),
        send=lambda target, text: sent.append((target, text)),
        start_worker=lambda target: target(),
    )

    assert len(sent) == 1 and "已开始处理反馈" in sent[0][1]


def test_a_second_feedback_command_while_poll_in_flight_replies_busy(tmp_path):
    home = _home(tmp_path)
    _config(home)
    inflight = {"feedback": True}
    sent = []
    pending = []

    result = listener.dispatch_message(
        home,
        listener.parse_message_event(_event("处理反馈")),
        send=lambda target, text: sent.append((target, text)),
        start_worker=pending.append,
        inflight=inflight,
    )

    assert result["status"] == "busy"
    assert "正在处理反馈" in sent[0][1]
    assert pending == []
    assert inflight == {"feedback": True}


def test_a_feedback_worker_exception_is_reported_not_raised(monkeypatch, tmp_path):
    home = _home(tmp_path)
    _config(home)
    sent = []

    def exploding_poll(home_path, *, host=None, run=None):
        raise RuntimeError("poll exploded")

    monkeypatch.setattr(listener, "poll_feedback", exploding_poll)

    result = listener.dispatch_message(
        home,
        listener.parse_message_event(_event("处理反馈")),
        send=lambda target, text: sent.append((target, text)),
        start_worker=lambda target: target(),
        inflight={},
    )

    assert result["status"] == "started"
    assert "反馈处理失败" in sent[-1][1]
    log = (home / "listener" / "listener.log").read_text(encoding="utf-8")
    assert "poll exploded" in log


def test_dispatch_push_command_starts_the_derived_run_in_the_background(monkeypatch, tmp_path):
    """#72 item 2: the event loop replies immediately and never waits."""
    home = _home(tmp_path)
    calls = []
    sent = []
    pending = []

    def fake_derived(home_path, intent, **kwargs):
        calls.append((intent, kwargs.get("target")))
        return {"ok": True, "reason": "ok", "reply_text": "完成回执"}

    monkeypatch.setattr(listener, "run_derived", fake_derived)

    result = listener.dispatch_message(
        home,
        listener.parse_message_event(_event("推一篇")),
        send=lambda target, text: sent.append((target, text)),
        start_worker=pending.append,
    )

    assert result["action"] == "daily"
    assert result["status"] == "started"
    assert result["replied"] is True
    assert sent and "已开始" in sent[0][1]
    assert calls == []  # the derived run did not execute on the event-loop thread
    assert len(pending) == 1

    pending[0]()  # the daemon worker finishes the run
    assert calls == [("daily", OWNER)]


def test_a_second_push_while_in_flight_gets_an_immediate_busy_reply(monkeypatch, tmp_path):
    home = _home(tmp_path)
    inflight = {}
    pending = []
    sent = []
    calls = []

    def fake_derived(*args, **kwargs):
        calls.append("run")
        return {"ok": True, "reply_text": "完成回执"}

    monkeypatch.setattr(listener, "run_derived", fake_derived)

    def dispatch():
        return listener.dispatch_message(
            home,
            listener.parse_message_event(_event("推一篇")),
            send=lambda target, text: sent.append((target, text)),
            start_worker=pending.append,
            inflight=inflight,
        )

    first = dispatch()
    second = dispatch()

    assert first["status"] == "started"
    assert second["status"] == "busy"
    assert "正在运行" in sent[-1][1]
    assert len(pending) == 1 and calls == []

    pending[0]()  # completion clears the in-flight flag
    assert inflight == {}

    third = dispatch()
    assert third["status"] == "started"
    assert len(pending) == 2


def test_a_status_command_answers_immediately_while_a_derived_run_is_in_flight(tmp_path):
    home = _home(tmp_path)
    inflight = {"derived": True}
    sent = []

    result = listener.dispatch_message(
        home,
        listener.parse_message_event(_event("状态")),
        send=lambda target, text: sent.append((target, text)),
        status=lambda home_path: _status_snapshot(),
        inflight=inflight,
    )

    assert result["action"] == "status"
    assert result["replied"] is True
    assert "监听" in sent[0][1]
    assert inflight == {"derived": True}  # answering status does not disturb the run


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


def test_log_line_is_safe_when_workers_write_concurrently(tmp_path):
    """#73: worker log appends and the main loop's appends never interleave."""
    home = _home(tmp_path)
    writers = [
        threading.Thread(
            target=lambda tag=tag: [listener.log_line(home, f"{tag}-{index}") for index in range(25)]
        )
        for tag in ("t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7")
    ]

    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join()

    lines = (home / "listener" / "listener.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 200
    bodies = [line.split(" ", 1)[1] for line in lines]
    assert all(re.fullmatch(r"t[0-7]-\d+", body) for body in bodies)
    assert len(set(bodies)) == 200


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


def test_serve_answers_status_and_heartbeats_while_a_derived_run_blocks(tmp_path, monkeypatch):
    """#72 item 2: an in-flight derived run must not stall the loop."""
    home = _home(tmp_path)
    _config(home, listener_config={"heartbeat_seconds": 1, "feedback_poll_seconds": 1})
    clock = FakeClock()
    sent = []
    feedback_runs = []
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocking_derived(home_path, intent, **kwargs):
        started.set()
        release.wait(timeout=5)
        kwargs["send"](kwargs.get("target") or OWNER, "完成回执")
        finished.set()
        return {"ok": True, "reply_text": "完成回执"}

    def feedback_run(home_path, intent, *, host, minutes):
        feedback_runs.append((intent, minutes))
        return {"ok": True, "quiet": True, "actions": []}

    monkeypatch.setattr(listener, "run_derived", blocking_derived)
    writes = []
    original = listener.write_heartbeat

    def recording(home_path, **beat):
        writes.append(dict(beat))
        return original(home_path, **beat)

    monkeypatch.setattr(listener, "write_heartbeat", recording)

    lines = {
        0: [json.dumps(_wrapped(_event("推一篇")), ensure_ascii=False)],
        1: [json.dumps(_wrapped(_event("状态")), ensure_ascii=False)],
        2: [json.dumps(_wrapped(_event("推一篇")), ensure_ascii=False)],
    }
    consume, _calls = _starter_consumer(
        [_ok_chunk()],
        lines_by_call=lines,
        on_call=lambda index, kwargs: listener.request_stop(home) if index >= 2 else None,
    )

    result = listener.serve(
        home,
        consume=consume,
        run=feedback_run,
        send=lambda target, text: sent.append((target, text)),
        status=lambda home_path: _status_snapshot(),
        clock=clock.clock,
        sleep=clock.sleep,
    )

    try:
        assert result["ok"] is True
        assert started.wait(timeout=5) is True
        assert finished.is_set() is False  # still in flight while status replied
        assert len(writes) >= 2  # heartbeat kept flowing during the run
        assert any(intent == "feedback" for intent, _minutes in feedback_runs)
        texts = [text for _target, text in sent]
        assert any("已开始" in text for text in texts)
        assert any("监听" in text for text in texts)  # 状态 answered immediately
        assert any("正在运行" in text for text in texts)  # second push got the busy reply
    finally:
        release.set()
        assert finished.wait(timeout=5) is True

    assert sent[-1][1] == "完成回执"


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


def test_feedback_poll_leases_the_whole_run_not_just_the_poll_interval(tmp_path):
    """#72 item 1: ``minutes`` is the lease duration, not the poll interval."""
    home = _home(tmp_path)
    _config(home)
    seen = []

    def run(home_path, intent, *, host, minutes):
        seen.append(minutes)
        return {"ok": True, "quiet": True, "actions": []}

    listener.poll_feedback(home, host=HOST, run=run)

    assert seen and seen[0] >= 45


def test_feedback_poll_lease_is_configurable(tmp_path):
    home = _home(tmp_path)
    _config(home, listener_config={"feedback_lease_minutes": 90})
    seen = []

    listener.poll_feedback(
        home,
        host=HOST,
        run=lambda home_path, intent, *, host, minutes: seen.append(minutes)
        or {"ok": True, "quiet": True},
    )

    assert seen == [90]


def test_a_run_older_than_the_poll_interval_still_holds_the_lease(tmp_path):
    """A 13-minute feedback run must not let the next 5-minute tick overlap it."""
    home = _home(tmp_path)
    _config(home)
    calls = []
    started = datetime.now().astimezone() - timedelta(minutes=5)

    def run(home_path, intent, *, host, minutes):
        calls.append(minutes)
        # A real run keeps its lease for the whole duration; this run started
        # five minutes ago (one full poll interval) and is still going.
        executor.acquire(home_path, host=host, minutes=minutes, at=started)
        return {"ok": True, "quiet": True, "actions": []}

    first = listener.poll_feedback(home, host=HOST, run=run)
    second = listener.poll_feedback(home, host=HOST, run=run)

    assert first["skipped"] is None
    assert second["skipped"] == "executor_busy"
    assert len(calls) == 1


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
        # Run workers inline so the test observes the poll deterministically;
        # the non-blocking behaviour has its own test below.
        start_worker=lambda target: target(),
    )

    assert result["ok"] is True
    assert ("feedback", HOST, executor.DEFAULT_MINUTES) in runs
    assert sent == []


def test_serve_answers_status_while_the_automatic_feedback_poll_blocks(tmp_path, monkeypatch):
    """#73: the 5-min poll runs on a worker; the loop keeps serving 状态."""
    home = _home(tmp_path)
    _config(home, listener_config={"heartbeat_seconds": 1, "feedback_poll_seconds": 1})
    clock = FakeClock()
    sent = []
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    poll_calls = []

    def blocking_poll(home_path, *, host=None, run=None):
        poll_calls.append(home_path)
        started.set()
        release.wait(timeout=5)
        finished.set()
        return {"ok": True, "skipped": None, "quiet": True, "run": {}}

    monkeypatch.setattr(listener, "poll_feedback", blocking_poll)
    writes = []
    original = listener.write_heartbeat

    def recording(home_path, **beat):
        writes.append(dict(beat))
        return original(home_path, **beat)

    monkeypatch.setattr(listener, "write_heartbeat", recording)

    lines = {
        0: [json.dumps(_wrapped(_event("状态")), ensure_ascii=False)],
        2: [json.dumps(_wrapped(_event("处理反馈")), ensure_ascii=False)],
    }
    consume, _calls = _starter_consumer(
        [_ok_chunk()],
        lines_by_call=lines,
        on_call=lambda index, kwargs: listener.request_stop(home) if index >= 3 else None,
    )

    result = listener.serve(
        home,
        consume=consume,
        send=lambda target, text: sent.append((target, text)),
        status=lambda home_path: _status_snapshot(),
        clock=clock.clock,
        sleep=clock.sleep,
    )

    try:
        assert result["ok"] is True
        assert started.wait(timeout=5) is True
        assert finished.is_set() is False  # the poll is still in flight
        assert len(poll_calls) == 1  # further intervals skip while in flight
        assert len(writes) >= 2  # heartbeat kept flowing
        texts = [text for _target, text in sent]
        assert any("监听" in text for text in texts)  # 状态 answered immediately
        assert any("正在处理反馈" in text for text in texts)  # busy reply for 处理反馈
    finally:
        release.set()
        assert finished.wait(timeout=5) is True


def test_automatic_feedback_worker_exception_does_not_kill_serve(tmp_path, monkeypatch):
    """#73: an automatic-poll crash is logged and the loop keeps running."""
    home = _home(tmp_path)
    _config(home, listener_config={"feedback_poll_seconds": 1})
    clock = FakeClock()

    def exploding_poll(home_path, *, host=None, run=None):
        raise RuntimeError("auto poll exploded")

    monkeypatch.setattr(listener, "poll_feedback", exploding_poll)
    consume, _calls = _starter_consumer([_ok_chunk()])
    clock.on_sleep = lambda fake: listener.request_stop(home) if len(fake.sleeps) >= 3 else None

    def sleep(seconds):
        clock.sleep(5.0)

    result = listener.serve(
        home,
        consume=consume,
        clock=clock.clock,
        sleep=sleep,
        start_worker=lambda target: target(),
    )

    assert result["ok"] is True
    assert result["reason"] == "stopped"
    log = (home / "listener" / "listener.log").read_text(encoding="utf-8")
    assert "auto poll exploded" in log


# ------------------------------------------------------------- derived-run guards
def test_derived_argv_is_the_documented_dsh_contract():
    # Verified against DeepSeek Harness 0.2.1-rc.3 on 2026-10-30: the headless
    # profile takes the task positionally and has no --prompt flag.
    assert listener.derived_argv("C:/dsh/dsh.cmd", "do the push") == [
        "C:/dsh/dsh.cmd",
        "--profile",
        "headless",
        "do the push",
    ]


def test_derived_brief_names_the_repo_home_interpreter_and_skill():
    """#72 item 4: ADR 0008 §5's environment/skill contract is in the prompt."""
    text = listener.derived_brief(
        Path("D:/frontier-archive"),
        "ORIGINAL BRIEF",
        repo="D:/frontier",
        python="D:/frontier-archive/.venv/Scripts/python.exe",
    )

    assert "frontier-run" in text
    assert "D:/frontier" in text
    assert "D:/frontier-archive" in text
    assert "D:/frontier-archive/.venv/Scripts/python.exe" in text
    assert "KL_HOME" in text
    assert text.rstrip().endswith("ORIGINAL BRIEF")


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


def test_derived_run_acquires_the_lease_before_preparing_and_spawning(tmp_path):
    """#72 item 3: prepare + spawn happen under one continuous lease."""
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))
    clock = FakeClock()
    seen = {}

    def run(home_path, intent, *, host, minutes, lease=True):
        seen["run_lease"] = lease
        seen["run_state"] = executor.status(home_path)["state"]
        return {"ok": True, "brief": "BRIEF-TEXT", "next": "finish", "actions": []}

    def spawn(argv, **kwargs):
        seen["spawn_state"] = executor.status(home)["state"]
        return FakeProc(clock, exit_after=5.0, returncode=0)

    result = listener.run_derived(
        home,
        "daily",
        send=lambda target, text: None,
        run=run,
        spawn=spawn,
        report=_report(),
        clock=clock.clock,
        sleep=clock.sleep,
        timeout_seconds=30,
    )

    assert result["ok"] is True
    # The inner bounded run must not take/release the listener's lease itself.
    assert seen["run_lease"] is False
    assert seen["run_state"] == "held"
    assert seen["spawn_state"] == "held"
    assert executor.status(home)["state"] == "free"


def test_a_failed_lease_acquire_never_prepares_or_spawns(tmp_path, monkeypatch):
    """#72 item 3: no request_push/try_start side effect without a lease."""
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))
    prepared = []
    monkeypatch.setattr(
        listener.executor,
        "acquire",
        lambda home_path, **kwargs: {"ok": False, "reason": "executor_busy"},
    )

    result = listener.run_derived(
        home,
        "daily",
        send=lambda target, text: None,
        run=lambda home_path, intent, **kwargs: prepared.append(intent),
        spawn=lambda *a, **k: pytest.fail("must not spawn without a lease"),
        report=_report(),
    )

    assert result["ok"] is False
    assert result["reason"] == "executor_busy"
    assert prepared == []


def test_derived_child_wait_renews_the_lease_beyond_the_initial_window(tmp_path, monkeypatch):
    """#73 follow-up: a child wait longer than the 20-min lease keeps it held."""
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))
    clock = FakeClock()
    base = datetime(2026, 10, 29, 8, 0, tzinfo=timezone.utc)

    def fake_now():
        return base + timedelta(seconds=clock.value - 1000.0)

    real_acquire = executor.acquire
    real_heartbeat = executor.heartbeat
    monkeypatch.setattr(
        listener.executor,
        "acquire",
        lambda home_path, *, host, minutes=45, run_id=None, at=None: real_acquire(
            home_path, host=host, minutes=minutes, run_id=run_id, at=fake_now()
        ),
    )
    monkeypatch.setattr(
        listener.executor,
        "heartbeat",
        lambda home_path, *, host, minutes=45, at=None: real_heartbeat(
            home_path, host=host, minutes=minutes, at=fake_now()
        ),
    )
    # One wait tick = 60 fake seconds, so 30 ticks cover a 30-minute child run.
    monkeypatch.setattr(listener, "POLL_INTERVAL_SECONDS", 60.0)
    observed = []

    def on_wait():
        observed.append(executor.status(home, at=fake_now())["state"])

    def spawn(argv, **kwargs):
        return FakeProc(clock, exit_after=30 * 60.0, returncode=0)

    result = listener.run_derived(
        home,
        "daily",
        send=lambda target, text: None,
        run=lambda home_path, intent, **kwargs: {
            "ok": True,
            "brief": "BRIEF-TEXT",
            "next": "finish",
            "actions": [],
        },
        spawn=spawn,
        report=_report(),
        clock=clock.clock,
        sleep=clock.sleep,
        timeout_seconds=40 * 60,
        on_wait=on_wait,
    )

    assert result["ok"] is True
    assert len(observed) >= 30  # the wait crossed the initial 20-minute window
    assert all(state == "held" for state in observed)
    assert executor.status(home)["state"] == "free"


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
    assert argv[:3] == [str(dsh), "--profile", "headless"]
    assert len(argv) == 4
    assert "BRIEF-TEXT" in argv[-1] and "frontier-run" in argv[-1]
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


def test_derived_spawn_uses_the_repo_cwd_and_the_kl_home_environment(tmp_path, monkeypatch):
    """#72 item 4: same repo/data-root/interpreter as the scheduled task."""
    home = _home(tmp_path)
    dsh = tmp_path / "dsh.cmd"
    dsh.write_text("", encoding="utf-8")
    _config(home, dsh=str(dsh))
    monkeypatch.setenv("FRONTIER_TEST_MARKER", "kept")
    clock = FakeClock()
    spawns = []

    def spawn(argv, **kwargs):
        spawns.append((argv, kwargs))
        return FakeProc(clock, exit_after=5.0, returncode=0)

    result = listener.run_derived(
        home,
        "daily",
        send=lambda target, text: None,
        run=lambda home_path, intent, **kwargs: {
            "ok": True,
            "brief": "BRIEF-TEXT",
            "next": "finish",
            "actions": [],
        },
        spawn=spawn,
        report=_report(),
        clock=clock.clock,
        sleep=clock.sleep,
        timeout_seconds=30,
    )

    assert result["ok"] is True
    argv, kwargs = spawns[0]
    prompt = argv[-1]
    assert "frontier-run" in prompt
    assert str(home) in prompt
    assert str(sys.executable) in prompt
    assert kwargs["cwd"] == str(home)  # _config records repo == home
    assert kwargs["env"]["KL_HOME"] == str(home)
    assert kwargs["env"]["FRONTIER_TEST_MARKER"] == "kept"  # the rest of the env is kept


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

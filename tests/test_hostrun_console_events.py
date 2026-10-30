"""Offline tests for the Console's Feishu event surface (issue #80, ADR 0009 §1/§4).

The Console consumes two independent event keys (``im.message.receive_v1`` and
``card.action.trigger``), gates messages to the verified owner's direct chat,
and runs the 5-minute feedback poll and 10-minute knowledge pull beside the
prompt loop without blocking it.  Every test injects the event source,
messenger, card handler, clock and worker, so no ``lark-cli`` process, network,
credential or real thread timing is involved.

Live lark-cli argv/envelopes, the real two-subscription reconnect and the real
10-minute pull stay ``untested`` and are recorded in the ticket report.
"""

from __future__ import annotations

import io
import json
import threading
import time
from pathlib import Path

import pytest

from hostrun import console, console_events, executor


# ------------------------------------------------------------------ fixtures
OWNER = "ou_owner"


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "runtime"
    (home / "install").mkdir(parents=True)
    return home


def _recipient(home: Path, owner: str = OWNER) -> None:
    (home / "install" / "recipient.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "owner": owner,
                "verified_at": "2026-10-30T10:00:00+08:00",
            }
        ),
        encoding="utf-8",
    )


def _event(
    text: str = "状态",
    *,
    chat_type: str = "p2p",
    sender: str = OWNER,
    sender_type: str = "user",
    message_id: str = "om_1",
) -> dict:
    return {
        "message": {
            "chat_type": chat_type,
            "chat_id": "oc_chat_1",
            "message_id": message_id,
            "message_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        },
        "sender": {
            "sender_type": sender_type,
            "sender_id": {"open_id": sender},
        },
    }


def _wrapped(event: dict) -> dict:
    return {"type": "im.message.receive_v1", "data": {"event": event}}


def _card(
    *,
    message_id: str = "om_card_1",
    action_name: str = "score_high",
    operator: str = OWNER,
) -> dict:
    return {
        "type": "card.action.trigger",
        "data": {
            "event": {
                "message_id": message_id,
                "action_name": action_name,
                "operator_id": operator,
                "token": "tok_1",
                "action_value": json.dumps({"queue_item_id": "q_1"}),
            }
        },
    }


def _surface(
    home: Path,
    *,
    consume=None,
    send=None,
    card=None,
    owner=None,
    paused=None,
    clock=None,
    sleep=None,
    start_worker=None,
    poll_feedback=None,
    pull=None,
    execute=None,
    judge=None,
    out=None,
):
    events: list[tuple[str, str, str]] = []

    def emit(home, level, source, message, *, at=None, out=None):
        events.append((level, source, message))

    surface = console_events.EventSurface(
        home,
        consume=consume,
        send=send,
        handle_card=card,
        owner=owner,
        paused=paused,
        execute=execute,
        judge=judge,
        emit=emit,
        out=out,
        clock=clock or (lambda: 0.0),
        sleep=sleep or (lambda seconds: None),
        start_worker=start_worker,
        poll_feedback=poll_feedback,
        pull=pull,
    )
    return surface, events


def _ok(**overrides) -> dict:
    result = {"ok": True, "reason": "ok", "kind": "ok", "retryable": False, "fatal": False}
    result.update(overrides)
    return result


def _lost() -> dict:
    return {
        "ok": False,
        "reason": "consume_lost",
        "kind": "consume_lost",
        "retryable": True,
        "fatal": False,
    }


# -------------------------------------------------------- message event surface
def test_an_owner_instruction_executes_and_gets_the_operation_receipt(tmp_path):
    home = _home(tmp_path)
    _recipient(home)
    sent: list[tuple[str, str]] = []
    executed: list[tuple[str, dict]] = []

    def fake_execute(home, operation, params, **kwargs):
        executed.append((operation, params))
        return {"ok": True, "reason": "", "text": "状态快照：运行中"}

    surface, events = _surface(
        home,
        send=lambda target, text: sent.append((target, text)),
        execute=fake_execute,
    )

    result = surface.handle_line(console_events.MESSAGE_EVENT_KEY, json.dumps(_wrapped(_event("状态"))))

    assert result["action"] == "received"
    assert result["route_action"] == "execute"
    assert result["operation"] == "status"
    assert result["replied"] is True
    assert executed == [("status", {})]
    assert sent == [(OWNER, "状态快照：运行中")]
    assert ("INFO", "feishu") in [(level, source) for level, source, _ in events]
    assert any("收到" in message and "状态" in message for _, _, message in events)


def test_an_unmatched_message_is_handed_to_intent_judgement_without_executing(tmp_path):
    home = _home(tmp_path)
    _recipient(home)
    sent: list[tuple[str, str]] = []
    executed: list[str] = []
    judged: list[str] = []

    def fake_execute(home, operation, params, **kwargs):
        executed.append(operation)
        return {"ok": True, "text": "不该执行"}

    def fake_judge(home, text, **kwargs):
        judged.append(text)
        return {"ok": True, "reason": "judged", "text": "意图判定中，稍后发送确认卡片。"}

    surface, _ = _surface(
        home,
        send=lambda target, text: sent.append((target, text)),
        execute=fake_execute,
        judge=fake_judge,
    )

    result = surface.handle_line(
        console_events.MESSAGE_EVENT_KEY, json.dumps(_wrapped(_event("请帮我推一下")))
    )

    assert result["route_action"] == "intent_judgement"
    assert result["operation"] is None
    assert executed == []
    assert judged == ["请帮我推一下"]
    assert sent == [(OWNER, "意图判定中，稍后发送确认卡片。")]


def test_an_unmatched_message_without_a_judge_seam_only_acknowledges(tmp_path):
    home = _home(tmp_path)
    _recipient(home)
    sent: list[tuple[str, str]] = []
    surface, _ = _surface(home, send=lambda target, text: sent.append((target, text)))

    result = surface.handle_line(
        console_events.MESSAGE_EVENT_KEY, json.dumps(_wrapped(_event("请帮我推一下")))
    )

    assert result["route_action"] == "intent_judgement"
    assert result["replied"] is True
    assert sent == [(OWNER, console_events.INTENT_PENDING_TEXT)]


def test_an_excluded_instruction_is_refused_without_executing(tmp_path):
    home = _home(tmp_path)
    _recipient(home)
    sent: list[tuple[str, str]] = []
    executed: list[str] = []
    surface, _ = _surface(
        home,
        send=lambda target, text: sent.append((target, text)),
        execute=lambda home, op, params, **kw: executed.append(op) or {"ok": True, "text": "x"},
    )

    result = surface.handle_line(
        console_events.MESSAGE_EVENT_KEY, json.dumps(_wrapped(_event("初始化")))
    )

    assert result["route_action"] == "refused"
    assert executed == []
    assert sent == [(OWNER, console_events.operations.CONSOLE_ONLY_TEXT)]


def test_a_failed_operation_still_receipts_the_reason(tmp_path):
    home = _home(tmp_path)
    _recipient(home)
    sent: list[tuple[str, str]] = []
    surface, _ = _surface(
        home,
        send=lambda target, text: sent.append((target, text)),
        execute=lambda home, op, params, **kw: {
            "ok": False,
            "reason": "invalid_parameters",
            "text": "参数不合法：缺少参数 time",
        },
    )

    result = surface.handle_line(
        console_events.MESSAGE_EVENT_KEY, json.dumps(_wrapped(_event("推一篇")))
    )

    assert result["replied"] is True
    assert sent == [(OWNER, "参数不合法：缺少参数 time")]


def test_an_empty_owner_message_executes_nothing(tmp_path):
    home = _home(tmp_path)
    _recipient(home)
    sent: list[tuple[str, str]] = []
    executed: list[str] = []
    surface, _ = _surface(
        home,
        send=lambda target, text: sent.append((target, text)),
        execute=lambda home, op, params, **kw: executed.append(op) or {"ok": True, "text": "x"},
    )

    result = surface.handle_line(
        console_events.MESSAGE_EVENT_KEY, json.dumps(_wrapped(_event("   ")))
    )

    assert result["route_action"] == "empty"
    assert executed == []
    assert sent == [(OWNER, console_events.EMPTY_MESSAGE_TEXT)]


@pytest.mark.parametrize(
    "event,reason",
    [
        (_event(chat_type="group"), "not_owner_dm"),
        (_event(sender="ou_someone_else"), "not_owner"),
        (_event(sender_type="bot"), "not_owner"),
    ],
)
def test_group_other_sender_and_bot_messages_are_logged_without_a_receipt(
    tmp_path, event, reason
):
    home = _home(tmp_path)
    _recipient(home)
    sent: list[tuple[str, str]] = []
    surface, events = _surface(home, send=lambda target, text: sent.append((target, text)))

    result = surface.handle_line(console_events.MESSAGE_EVENT_KEY, json.dumps(_wrapped(event)))

    assert result["action"] == "ignored"
    assert result["reason"] == reason
    assert result["replied"] is False
    assert sent == []
    assert any(reason in message for _, _, message in events)


def test_an_unverified_recipient_cannot_command_the_console(tmp_path):
    home = _home(tmp_path)
    sent: list[tuple[str, str]] = []
    surface, _ = _surface(home, send=lambda target, text: sent.append((target, text)))

    result = surface.handle_line(console_events.MESSAGE_EVENT_KEY, json.dumps(_wrapped(_event("状态"))))

    assert result["action"] == "ignored"
    assert result["reason"] == "not_owner"
    assert sent == []


def test_a_card_payload_on_the_message_key_is_only_logged(tmp_path):
    home = _home(tmp_path)
    _recipient(home)
    sent: list[tuple[str, str]] = []
    surface, events = _surface(home, send=lambda target, text: sent.append((target, text)))

    result = surface.handle_line(console_events.MESSAGE_EVENT_KEY, json.dumps(_card()))

    assert result["action"] == "ignored"
    assert result["reason"] == "not_a_message"
    assert sent == []
    assert any("忽略" in message for _, _, message in events)


def test_a_bad_event_line_is_logged_and_never_raises(tmp_path):
    home = _home(tmp_path)
    surface, events = _surface(home)

    result = surface.handle_line(console_events.MESSAGE_EVENT_KEY, "{not json")

    assert result["ok"] is False
    assert result["reason"] == "bad_event_line"
    assert any("坏事件行" in message for _, _, message in events)


# ----------------------------------------------------------- card callbacks
def test_a_card_callback_reaches_the_existing_publisher_handler(tmp_path):
    home = _home(tmp_path)
    seen: list[dict] = []
    surface, events = _surface(home, card=lambda repo, event: seen.append(event) or {"ok": True, "kind": "rating"})

    result = surface.handle_line(console_events.CARD_EVENT_KEY, json.dumps(_card()))

    assert seen == [
        {
            "event_type": "card.action.trigger",
            "message_id": "om_card_1",
            "action_name": "score_high",
            "operator_id": OWNER,
            "token": "tok_1",
            "action_value": json.dumps({"queue_item_id": "q_1"}),
            "form_value": "",
            "chat_id": "",
        }
    ]
    assert result["ok"] is True
    assert any(source == "feishu" for _, source, _ in events)


def test_a_card_payload_on_the_card_key_is_ignored_when_it_is_not_a_callback(tmp_path):
    home = _home(tmp_path)
    seen: list[dict] = []
    surface, events = _surface(home, card=lambda repo, event: seen.append(event))

    result = surface.handle_line(console_events.CARD_EVENT_KEY, json.dumps(_wrapped(_event("状态"))))

    assert result["action"] == "ignored"
    assert seen == []
    assert any("忽略" in message for _, _, message in events)


def test_a_failing_card_handler_is_reported_and_does_not_kill_the_surface(tmp_path):
    home = _home(tmp_path)

    def card(repo, event):
        raise RuntimeError("publisher offline")

    surface, events = _surface(home, card=card)

    result = surface.handle_line(console_events.CARD_EVENT_KEY, json.dumps(_card()))

    assert result["ok"] is False
    assert result["reason"] == "card_failed"
    assert any(level == "WARN" and "publisher offline" in message for level, _, message in events)


def test_card_2_0_nested_callbacks_are_normalised(tmp_path):
    home = _home(tmp_path)
    seen: list[dict] = []
    surface, _ = _surface(home, card=lambda repo, event: seen.append(event) or {"ok": True})
    raw = {
        "schema": "2.0",
        "header": {"event_type": "card.action.trigger"},
        "event": {
            "operator": {"open_id": OWNER},
            "action": {"name": "approve", "value": {"queue_item_id": "q_2"}},
            "context": {"open_message_id": "om_nested", "open_chat_id": "oc_1"},
            "token": "tok_2",
        },
    }

    result = surface.handle_line(console_events.CARD_EVENT_KEY, json.dumps(raw))

    assert result["ok"] is True
    assert seen[0]["message_id"] == "om_nested"
    assert seen[0]["action_name"] == "approve"
    assert seen[0]["operator_id"] == OWNER
    assert seen[0]["action_value"] == {"queue_item_id": "q_2"}


# ------------------------------------------------------- subscriptions / backoff
def test_the_two_event_keys_are_consumed_by_independent_subscriptions(tmp_path):
    home = _home(tmp_path)
    calls: list[str] = []
    stops = [threading.Event(), threading.Event()]

    def consume(**kwargs):
        calls.append(kwargs["event_key"])
        stops[len(calls) - 1].set()
        return _ok()

    surface, _ = _surface(home, consume=consume)
    surface.run_subscription(console_events.MESSAGE_EVENT_KEY, stop=stops[0])
    surface.run_subscription(console_events.CARD_EVENT_KEY, stop=stops[1])

    assert calls == [
        console_events.MESSAGE_EVENT_KEY,
        console_events.CARD_EVENT_KEY,
    ]


def test_a_disconnected_subscription_backs_off_and_recovers_without_exiting(tmp_path):
    home = _home(tmp_path)
    sleeps: list[float] = []
    results = [_lost(), _lost(), _ok(), _ok()]
    stop = threading.Event()

    def consume(**kwargs):
        result = results.pop(0)
        if not results:
            stop.set()
        return result

    surface, events = _surface(home, consume=consume, sleep=sleeps.append)

    surface.run_subscription(console_events.MESSAGE_EVENT_KEY, stop=stop)

    assert sleeps == [5, 15]
    messages = [message for _, _, message in events]
    assert any("消息订阅断开" in message and "5 秒" in message for message in messages)
    assert any("消息订阅断开" in message and "15 秒" in message for message in messages)
    assert any("消息订阅已恢复" in message for message in messages)


def test_each_event_key_keeps_its_own_backoff_and_state(tmp_path):
    home = _home(tmp_path)
    sleeps: list[float] = []
    calls: list[str] = []

    def consume(**kwargs):
        calls.append(kwargs["event_key"])
        if calls.count(kwargs["event_key"]) == 2:
            kwargs["stop_event"].set()
        return _lost()

    surface, events = _surface(home, consume=consume, sleep=sleeps.append)
    surface.run_subscription(console_events.MESSAGE_EVENT_KEY, stop=threading.Event())
    surface.run_subscription(console_events.CARD_EVENT_KEY, stop=threading.Event())

    assert sleeps == [5, 5]
    assert any("消息订阅断开" in message for _, _, message in events)
    assert any("卡片订阅断开" in message for _, _, message in events)


def test_start_and_stop_end_both_subscriptions_cleanly(tmp_path):
    home = _home(tmp_path)
    consuming = threading.Event()
    terminated: list[str] = []

    def consume(**kwargs):
        consuming.set()
        kwargs["stop_event"].wait(timeout=5)
        terminated.append(kwargs["event_key"])
        return _ok(reason="stopped", kind="stopped", stopped=True)

    surface, _ = _surface(home, consume=consume)
    surface.start()
    assert consuming.wait(timeout=5)

    result = surface.stop(timeout=5)

    assert result["ok"] is True
    assert sorted(terminated) == sorted(
        [console_events.MESSAGE_EVENT_KEY, console_events.CARD_EVENT_KEY]
    )
    assert surface.threads_alive() == []


def test_console_serve_starts_and_stops_the_event_surface(tmp_path):
    home = _home(tmp_path)
    started: list[bool] = []
    stopped: list[bool] = []

    class FakeSurface:
        def start(self):
            started.append(True)

        def stop(self, timeout=5):
            stopped.append(True)
            return {"ok": True}

    surface = FakeSurface()
    result = console.serve(
        home,
        isatty=lambda: True,
        reader=lambda prompt: (_ for _ in ()).throw(EOFError),
        out=io.StringIO(),
        status=lambda repo: {"executor": {}, "queue": {}, "install": {"steps": {}}},
        set_title=lambda title: True,
        start_worker=lambda function: None,
        events=surface,
    )

    assert result["ok"] is True
    assert started == [True]
    assert stopped == [True]
    log = console.log_path(home).read_text(encoding="utf-8")
    assert "飞书事件面" in log


# --------------------------------------------------------------------- ticks
def test_feedback_runs_every_five_minutes_and_pull_every_ten(tmp_path):
    home = _home(tmp_path)
    polls: list[int] = []
    pulls: list[int] = []
    surface, _ = _surface(
        home,
        start_worker=lambda function: function(),
        poll_feedback=lambda home, host=None, run=None: polls.append(1) or {"ok": True, "skipped": None},
        pull=lambda home: pulls.append(1) or {"ok": True},
    )

    assert surface.tick(now=0)["started"] == []
    assert surface.tick(now=299)["started"] == []
    assert surface.tick(now=300)["started"] == ["feedback"]
    assert surface.tick(now=599)["started"] == []
    assert surface.tick(now=600)["started"] == ["feedback", "pull"]

    assert len(polls) == 2
    assert len(pulls) == 1


def test_a_feedback_tick_skipped_by_the_executor_lease_is_logged_and_not_retried(tmp_path):
    home = _home(tmp_path)
    polls: list[int] = []
    surface, events = _surface(
        home,
        start_worker=lambda function: function(),
        poll_feedback=lambda home, host=None, run=None: polls.append(1)
        or {"ok": True, "skipped": "executor_busy"},
        pull=lambda home: {"ok": True},
    )

    result = surface.tick(now=300)

    assert result["started"] == ["feedback"]
    assert len(polls) == 1
    assert any("反馈轮询已跳过" in message and "executor_busy" in message for _, _, message in events)
    # The next second is not a new interval; the skipped round is not retried.
    assert surface.tick(now=301)["started"] == []
    assert len(polls) == 1


def test_a_tick_does_not_start_a_second_run_while_one_is_still_in_flight(tmp_path):
    home = _home(tmp_path)
    started_functions: list = []
    polls: list[int] = []
    surface, events = _surface(
        home,
        start_worker=lambda function: started_functions.append(function),
        poll_feedback=lambda home, host=None, run=None: polls.append(1) or {"ok": True, "skipped": None},
        pull=lambda home: {"ok": True},
    )

    assert surface.tick(now=300)["started"] == ["feedback"]
    assert polls == []
    assert surface.tick(now=600)["started"] == ["pull"]
    assert any("反馈轮询已跳过" in message and "in_flight" in message for _, _, message in events)

    started_functions[0]()
    assert polls == [1]
    assert "feedback" not in surface.inflight


def test_ticks_are_skipped_while_the_service_is_paused(tmp_path):
    home = _home(tmp_path)
    polls: list[int] = []
    pulls: list[int] = []
    surface, events = _surface(
        home,
        paused=lambda: True,
        start_worker=lambda function: function(),
        poll_feedback=lambda home, host=None, run=None: polls.append(1) or {"ok": True},
        pull=lambda home: pulls.append(1) or {"ok": True},
    )

    result = surface.tick(now=600)

    assert result["started"] == []
    assert polls == []
    assert pulls == []
    assert any("服务已暂停" in message for _, _, message in events)


def test_the_feedback_poll_skips_a_held_executor_lease_without_calling_the_run(tmp_path):
    home = _home(tmp_path)
    executor.acquire(home, host="someone-else", minutes=30)
    calls: list[tuple] = []

    result = console_events.poll_feedback(
        home, run=lambda *args, **kwargs: calls.append((args, kwargs))
    )

    assert result == {"ok": True, "skipped": "executor_busy"}
    assert calls == []


def test_the_feedback_poll_does_not_retry_when_the_run_reports_busy(tmp_path):
    home = _home(tmp_path)
    calls: list[tuple] = []

    def run(home, intent, **kwargs):
        calls.append((intent, kwargs))
        return {"ok": False, "reason": "executor_busy"}

    result = console_events.poll_feedback(home, run=run)

    assert result["ok"] is True
    assert result["skipped"] == "executor_busy"
    assert len(calls) == 1


def test_a_failed_pull_is_logged_without_killing_the_tick_loop(tmp_path):
    home = _home(tmp_path)
    surface, events = _surface(
        home,
        start_worker=lambda function: function(),
        poll_feedback=lambda home, host=None, run=None: {"ok": True},
        pull=lambda home: (_ for _ in ()).throw(RuntimeError("lark offline")),
    )

    result = surface.tick(now=600)

    assert result["started"] == ["feedback", "pull"]
    assert any(
        level == "WARN" and "知识库拉取失败" in message and "lark offline" in message
        for level, _, message in events
    )
    assert "pull" not in surface.inflight

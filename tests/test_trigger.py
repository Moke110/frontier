import subprocess

from question_queue.store import QueueStore
from trigger.keywords import parse, resolve_checkpoint
from trigger.service import Config, handle_event, run_pending, scheduled_pull


def test_parse_keywords_with_optional_checkpoint():
    assert parse("再推一篇").checkpoint is None
    assert parse("下一篇 hmbs").checkpoint == "hmbs"
    assert parse("NEXT virtual-cell").keyword == "NEXT"
    assert parse("more：HMBS").checkpoint == "HMBS"
    assert parse("今天天气不错") is None


def test_resolve_checkpoint_matches_id_or_label():
    cards = [{"id": "card_hmbs", "label": "HMBS / 羟甲基胆素合酶"}]
    assert resolve_checkpoint("card_hmbs", cards) == "card_hmbs"
    assert resolve_checkpoint("HMBS / 羟甲基胆素合酶", cards) == "card_hmbs"
    assert resolve_checkpoint("nope", cards) == ""
    assert resolve_checkpoint(None, cards) is None


def _config(kl_home):
    return Config(repo=kl_home, home=kl_home, owner="ou_owner", dry_run=True)


def _event(content, sender="ou_owner", chat_type="p2p"):
    return {
        "chat_type": chat_type,
        "sender_type": "user",
        "sender_id": sender,
        "chat_id": "oc_chat",
        "content": content,
        "message_type": "text",
    }


def test_handle_event_ignores_non_owner(kl_home):
    result = handle_event(_event("再推一篇", sender="ou_other"), _config(kl_home))
    assert result == {"ok": False, "reason": "not_owner"}


def test_handle_event_ignores_non_keyword(kl_home):
    result = handle_event(_event("随便聊聊"), _config(kl_home))
    assert result == {"ok": False, "reason": "no_keyword"}


def test_handle_event_runs_one_job_and_replies(kl_home):
    replies = []

    def replier(event, text, config, identity="bot"):
        replies.append(text)
        return {"ok": True}

    def runner(config, prompt):
        assert "KL_HOME=" + str(kl_home) in prompt
        return subprocess.CompletedProcess([], 0, "已推送 2026-10-20_hmbs_01", "")

    result = handle_event(
        _event("再推一篇 card_hmbs"), _config(kl_home), runner=runner, replier=replier
    )
    assert result["ok"] is True
    assert result["checkpoint"] == "card_hmbs"
    assert replies[0] == "收到，开始检索。"
    assert replies[-1] == "补推完成。"
    assert (kl_home / "publisher" / "trigger.log").exists()


def test_handle_event_unknown_checkpoint(kl_home):
    replies = []

    def replier(event, text, config, identity="bot"):
        replies.append(text)
        return {"ok": True}

    result = handle_event(
        _event("下一篇 nope"), _config(kl_home), replier=replier
    )
    assert result == {"ok": False, "reason": "unknown_checkpoint"}
    assert "未知 checkpoint" in replies[0]


def _busy_queue(kl_home):
    queue = QueueStore(kl_home)
    queue.init()
    queue.enqueue_push({"push_id": "push_busy", "proposals": []})
    return queue


def test_manual_request_is_queued_when_queue_busy(kl_home):
    _busy_queue(kl_home)
    called = []
    replies = []

    def runner(config, prompt):
        called.append(prompt)
        return subprocess.CompletedProcess([], 0, "已推送 x", "")

    def replier(event, text, config, identity="bot"):
        replies.append(text)
        return {"ok": True}

    result = handle_event(
        _event("再推一篇 card_hmbs"), _config(kl_home), runner=runner, replier=replier
    )
    assert result["queued"] is True
    assert result["reason"] == "queue_busy"
    assert called == []
    assert "已记下" in replies[-1]
    request = QueueStore(kl_home).status()["request"]
    assert request["sources"] == ["manual"]
    assert request["card_id"] == "card_hmbs"


def test_scheduled_records_only_when_queue_busy(kl_home):
    _busy_queue(kl_home)
    called = []

    def runner(config, prompt):
        called.append(prompt)
        return subprocess.CompletedProcess([], 0, "已推送 x", "")

    result = scheduled_pull(_config(kl_home), runner=runner)
    assert result["queued"] is True
    assert result["reason"] == "queue_busy"
    assert called == []
    request = QueueStore(kl_home).status()["request"]
    assert request["sources"] == ["scheduled"]


def test_scheduled_starts_and_clears_request_when_queue_empty(kl_home):
    called = []

    def runner(config, prompt):
        called.append(prompt)
        return subprocess.CompletedProcess([], 0, "已推送 2026-10-21_card_hmbs_01", "")

    result = scheduled_pull(_config(kl_home), runner=runner)
    assert result["ok"] is True
    assert len(called) == 1
    assert QueueStore(kl_home).status()["request"] is None


def test_manual_and_scheduled_coalesce_into_one_start(kl_home):
    queue = QueueStore(kl_home)
    queue.init()
    queue.request_push("manual", "card_hmbs")
    queue.request_push("scheduled")
    first = queue.try_start()
    second = queue.try_start()
    assert first["start"] is True
    assert second["reason"] == "starting"
    request = queue.status()["request"]
    assert request["sources"] == ["manual", "scheduled"]
    assert request["count"] == 2


def test_run_pending_executes_the_merged_request(kl_home):
    queue = QueueStore(kl_home)
    queue.init()
    queue.request_push("manual", "card_hmbs")
    called = []

    def runner(config, prompt):
        called.append(prompt)
        assert "本次只处理知识卡片：card_hmbs" in prompt
        return subprocess.CompletedProcess([], 0, "已推送 x", "")

    result = run_pending(_config(kl_home), runner=runner)
    assert result["ok"] is True
    assert len(called) == 1
    assert queue.status()["request"] is None

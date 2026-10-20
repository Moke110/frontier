import subprocess

from trigger.keywords import parse, resolve_checkpoint
from trigger.service import Config, handle_event


def test_parse_keywords_with_optional_checkpoint():
    assert parse("再推一篇").checkpoint is None
    assert parse("下一篇 hmbs").checkpoint == "hmbs"
    assert parse("NEXT virtual-cell").keyword == "NEXT"
    assert parse("more：HMBS").checkpoint == "HMBS"
    assert parse("今天天气不错") is None


def test_resolve_checkpoint_matches_id_or_label():
    vocab = {"checkpoints": [{"id": "hmbs", "label": "HMBS / 羟甲基胆素合酶"}]}
    assert resolve_checkpoint("hmbs", vocab) == "hmbs"
    assert resolve_checkpoint("HMBS / 羟甲基胆素合酶", vocab) == "hmbs"
    assert resolve_checkpoint("nope", vocab) == ""
    assert resolve_checkpoint(None, vocab) is None


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
        _event("再推一篇 hmbs"), _config(kl_home), runner=runner, replier=replier
    )
    assert result["ok"] is True
    assert result["checkpoint"] == "hmbs"
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

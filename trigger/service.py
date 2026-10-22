"""Manual-push listener: Lark message -> one forward pipeline run.

The listener only recognizes keywords, enforces the owner, serializes jobs and
invokes a headless agent. It does not rank, write, or touch the knowledge base.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import signal
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from common import append_jsonl, now, read_json, read_jsonl
from publisher import feishu
from question_queue.store import LEASE_MINUTES, QueueStore
from trigger.keywords import parse, resolve_checkpoint

PROMPT = """使用 frontier skill（{repo}/SKILL.md）执行一次检索推送，只处理一篇论文。

硬约束：
- 工作目录 {repo}；数据根 KL_HOME={home}；
- 只允许执行「检索 → 排序 → 写作 → 渲染 → 推送」这一条正向链路；
- 评分题与更新题由统一队列发送，不要手写审批卡；不要运行 frontier record / editor fit；
- 收件人固定为 $FRONTIER_OWNER_ID，推送前不用再次询问；
- 论文必须来自本次检索候选，不得编造；没有新候选就直接结束并输出「今天没有新的」。

步骤：
1. python -m frontier.cli validate
2. python -m frontier.cli plan --date "$(date +%%F)" --days 7 --out /tmp/frontier-plan.json
3. python -m retriever.cli fetch --plan /tmp/frontier-plan.json --out /tmp/frontier-candidates.jsonl --source live
4. 逐条 python -m archive.cli add-paper --file <临时 json>（自动去重）
5. python -m editor.cli task --candidates /tmp/frontier-candidates.jsonl --date "$(date +%%F)" --out /tmp/editor-task.json
6. 你亲自读 task、写 /tmp/selection.json，并 python -m editor.cli check ...
7. 从 selection 里只选 1 篇；python -m writer.cli task ...；python -m writer.cli figures ...
8. 你亲自写 push（七段 HTML + assets）；python -m writer.cli check ...
9. python -m writer.cli render --push ... --out /tmp/<push_id>.pdf
10. python -m archive.cli add-push --file ...
11. python -m publisher.cli send --push ... --pdf ... --to "$FRONTIER_OWNER_ID"

如果 publisher send 返回非零（尤其 reason=duplicate_paper），立即停止，不要换论文重试、不要重复 add-push；输出「推送发送失败：<reason>」并结束。
{checkpoint_line}
完成后输出一句：已推送 <push_id>，或 今天没有新的。"""

CHECKPOINT_LINE = "- 本次只处理知识卡片：{checkpoint}"


@dataclass
class Config:
    repo: Path
    home: Path
    owner: str
    timeout: int = 1800
    dry_run: bool = False


def _env_file_owner(home: Path) -> str:
    path = Path.home() / ".config" / "frontier" / "env"
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("FRONTIER_OWNER_ID="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def load_owner(explicit: str | None = None) -> str:
    return explicit or os.environ.get("FRONTIER_OWNER_ID") or _env_file_owner(Path.home())


@contextmanager
def job_lock(home: Path):
    path = Path(home) / "publisher" / "trigger.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    acquired = False
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            acquired = False
        yield acquired
    finally:
        if acquired:
            fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def lease_minutes(config: Config) -> int:
    """A start lease must outlive the agent run, or the retry timer would
    start a second pipeline while the first one is still working."""
    return max(LEASE_MINUTES, int(math.ceil(config.timeout / 60)) + 5)


def _push_ids(home: Path) -> set[str]:
    return {path.stem for path in (Path(home) / "archive" / "pushes").glob("*.json")}


def _sent_push_ids(home: Path) -> set[str]:
    rows = read_jsonl(Path(home) / "publisher" / "messages.jsonl")
    return {row.get("push_id") for row in rows if row.get("kind") == "push_file"}


def _output_tail(exc: subprocess.TimeoutExpired, limit: int = 1500) -> str:
    def _text(value) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", "replace")
        return value or ""

    merged = (_text(exc.stdout) + "\n" + _text(exc.stderr)).strip()
    return merged[-limit:]


def build_prompt(config: Config, checkpoint: str | None) -> str:
    line = CHECKPOINT_LINE.format(checkpoint=checkpoint) if checkpoint else ""
    return PROMPT.format(
        repo=config.repo,
        home=config.home,
        checkpoint_line=line,
    ).strip()


def run_agent(config: Config, prompt: str) -> subprocess.CompletedProcess:
    if config.dry_run:
        return subprocess.CompletedProcess([], 0, "dry-run 已推送", "")
    env = os.environ.copy()
    env["KL_HOME"] = str(config.home)
    env["FRONTIER_OWNER_ID"] = config.owner
    proc = subprocess.Popen(
        ["opencode", "run", "--auto", prompt],
        cwd=str(config.repo),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=config.timeout)
    except subprocess.TimeoutExpired:
        # Kill the whole process group, not just the direct child: a timed-out
        # opencode run can leave grandchildren that keep writing pushes.
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        stdout, stderr = proc.communicate()
        raise subprocess.TimeoutExpired(
            proc.args, config.timeout, output=stdout, stderr=stderr
        ) from None
    return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)


def _reply(event: dict, text: str, config: Config, identity: str = "bot") -> dict:
    target = event.get("chat_id") or event.get("sender_id") or config.owner
    if config.dry_run:
        return {"ok": True, "dry_run": True, "text": text, "target": target}
    return feishu.send_text(target, text, identity=identity, to_chat=bool(event.get("chat_id")))


def _log(config: Config, row: dict) -> None:
    append_jsonl(
        Path(config.home) / "publisher" / "trigger.log",
        {"schema_version": 1, "at": now(), **row},
    )


def _queue(config: Config) -> QueueStore:
    queue = QueueStore(config.home)
    queue.init()
    return queue


def _notify(config: Config, text: str) -> None:
    if config.dry_run or not config.owner:
        return
    try:
        feishu.send_text(config.owner, text)
    except feishu.FeishuError as exc:
        _log(config, {"kind": "notify_failed", "error": str(exc)})


def _run_job(config: Config, queue: QueueStore, checkpoint: str | None, runner) -> dict:
    """Run one forward pipeline while holding the process job lock."""
    with job_lock(config.home) as acquired:
        if not acquired:
            # Another job is already running. Do not touch the request or its
            # lease: the running job owns them and will clear them on finish.
            _log(config, {"kind": "blocked", "reason": "job_lock"})
            return {"ok": False, "reason": "busy", "text": None}
        before = _push_ids(config.home)
        try:
            proc = runner(config, build_prompt(config, checkpoint))
            output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
            ok = proc.returncode == 0
            no_new = "今天没有新的" in output
            failure = None
            if ok and not no_new:
                new_pushes = _push_ids(config.home) - before
                unsent = sorted(new_pushes - _sent_push_ids(config.home))
                if not new_pushes:
                    ok, failure = False, "no_push_output"
                elif unsent:
                    ok, failure = False, "push_not_sent:" + ",".join(unsent)
            if ok and no_new:
                text = "今天没有新的。"
            elif ok:
                text = "补推完成。"
            elif failure == "no_push_output":
                text = "补推没有产出新推送，请查看日志。"
            elif failure and failure.startswith("push_not_sent:"):
                text = "推送已生成但没有发出（可能命中已推送论文），请查看日志。"
            else:
                text = f"补推失败（exit {proc.returncode}），请查看日志。"
            queue.finish_start(ok, failure or (None if ok else f"exit {proc.returncode}"))
            _log(
                config,
                {
                    "kind": "finish",
                    "checkpoint": checkpoint,
                    "ok": ok,
                    "reason": failure,
                    "text": text,
                    "stdout_tail": output[-1500:],
                },
            )
            return {
                "ok": ok,
                "checkpoint": checkpoint,
                "text": text,
                "exit": proc.returncode,
                "reason": failure,
                "queued_request": queue.status().get("request"),
            }
        except subprocess.TimeoutExpired as exc:
            queue.finish_start(False, "timeout")
            _log(
                config,
                {
                    "kind": "timeout",
                    "checkpoint": checkpoint,
                    "timeout": config.timeout,
                    "stdout_tail": _output_tail(exc),
                },
            )
            return {
                "ok": False,
                "reason": "timeout",
                "text": f"补推超时（{config.timeout}s），已终止进程组，请查看日志。",
            }
        except Exception as exc:  # noqa: BLE001 - keep listener alive
            queue.finish_start(False, str(exc))
            _log(config, {"kind": "error", "checkpoint": checkpoint, "error": str(exc)})
            return {"ok": False, "reason": "error", "error": str(exc), "text": "补推失败，请查看日志。"}


def _job_free(home: Path) -> bool:
    """True when no other process is running the forward pipeline."""
    with job_lock(home) as acquired:
        return acquired


def scheduled_pull(config: Config, runner=run_agent) -> dict:
    """08:00 timer entry: request one push, or merge into the pending request."""
    queue = _queue(config)
    queue.request_push("scheduled")
    if not _job_free(config.home):
        _log(config, {"kind": "blocked", "reason": "job_lock", "source": "scheduled"})
        return {"ok": False, "reason": "busy", "text": None}
    start = queue.try_start(lease_minutes(config))
    if not start or not start.get("ok"):
        reason = (start or {}).get("reason", "no_request")
        _log(config, {"kind": "queued", "source": "scheduled", "reason": reason})
        return {"ok": True, "queued": True, "reason": reason}
    _log(config, {"kind": "start", "source": "scheduled", "checkpoint": start.get("card_id")})
    result = _run_job(config, queue, start.get("card_id"), runner)
    _notify(config, result.get("text") or "定时推送完成。")
    return result


def run_pending(config: Config, runner=run_agent, quiet: bool = False) -> dict:
    """Started after a queue drains: execute the merged pending request once.

    `quiet` is used by the periodic retry timer: it runs every couple of
    minutes, so normal "nothing to do" outcomes must not spam the log or Lark.
    """
    queue = _queue(config)
    if not _job_free(config.home):
        if not quiet:
            _log(config, {"kind": "blocked", "reason": "job_lock", "source": "pending"})
        return {"ok": False, "reason": "busy", "text": None}
    start = queue.try_start(lease_minutes(config))
    if not start or not start.get("ok"):
        reason = (start or {}).get("reason", "no_request")
        if not quiet:
            _log(config, {"kind": "queued", "source": "pending", "reason": reason})
        return {"ok": True, "queued": True, "reason": reason}
    _log(config, {"kind": "start", "source": "pending", "checkpoint": start.get("card_id")})
    result = _run_job(config, queue, start.get("card_id"), runner)
    if result.get("text"):
        _notify(config, result["text"])
    return result


def handle_event(
    event: dict,
    config: Config,
    runner=run_agent,
    replier=_reply,
) -> dict:
    if event.get("chat_type") != "p2p":
        return {"ok": False, "reason": "not_p2p"}
    if event.get("sender_type") not in (None, "user"):
        return {"ok": False, "reason": "not_user"}
    sender = event.get("sender_id") or ""
    if not config.owner or sender != config.owner:
        _log(config, {"kind": "ignored", "reason": "not_owner", "sender_id": sender})
        return {"ok": False, "reason": "not_owner"}

    request = parse(event.get("content") or "")
    if not request:
        return {"ok": False, "reason": "no_keyword"}

    card_dir = Path(config.home) / "archive" / "cards"
    cards = [
        read_json(path) or {}
        for path in sorted(card_dir.glob("*.json"))
    ] if card_dir.exists() else []
    checkpoint = resolve_checkpoint(request.checkpoint, cards)
    if checkpoint == "":
        replier(event, f"未知 checkpoint：{request.checkpoint}", config)
        return {"ok": False, "reason": "unknown_checkpoint"}

    queue = _queue(config)
    queue.request_push("manual", checkpoint)
    start = queue.try_start(lease_minutes(config))
    if not start or not start.get("ok"):
        reason = (start or {}).get("reason", "no_request")
        _log(config, {"kind": "queued", "source": "manual", "reason": reason})
        replier(event, "队列还有题没答完，已记下；答完最后一题会自动开始下一次推送。", config)
        return {"ok": True, "queued": True, "reason": reason, "checkpoint": checkpoint}

    replier(event, "收到，开始检索。", config)
    _log(config, {"kind": "start", "source": "manual", "checkpoint": checkpoint})
    result = _run_job(config, queue, checkpoint, runner)
    replier(event, result.get("text") or "补推失败，请查看日志。", config)
    return result


def listen(config: Config, max_events: int = 0, timeout: str = "0", identity: str = "bot") -> int:
    try:
        events = feishu.consume_events(
            identity=identity,
            max_events=max_events,
            timeout=timeout,
            event_key="im.message.receive_v1",
        )
        for line in events:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                result = handle_event(event, config)
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "reason": "handle_failed", "error": str(exc)}
            print(json.dumps(result, ensure_ascii=False), flush=True)
    except feishu.FeishuError as exc:
        print(json.dumps({"ok": False, "reason": "consume_failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    return 0

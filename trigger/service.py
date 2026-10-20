"""Manual-push listener: Lark message -> one forward pipeline run.

The listener only recognizes keywords, enforces the owner, serializes jobs and
invokes a headless agent. It does not rank, write, or touch the knowledge base.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from common import append_jsonl, now, read_yaml
from publisher import feishu
from trigger.keywords import parse, resolve_checkpoint

PROMPT = """使用 frontier skill（{repo}/SKILL.md）执行一次手动补推，只处理一篇论文。

硬约束：
- 工作目录 {repo}；数据根 KL_HOME={home}；
- 只允许执行「检索 → 排序 → 写作 → 渲染 → 推送 → 评分卡」这一条正向链路；
- 不要运行 frontier record / editor fit，不要修改知识图或命题，不要发审批卡；
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
{checkpoint_line}
完成后输出一句：已推送 <push_id>，或 今天没有新的。"""

CHECKPOINT_LINE = "- 本次只处理 checkpoint：{checkpoint}"


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
    return subprocess.run(
        ["opencode", "run", "--auto", prompt],
        cwd=str(config.repo),
        env=env,
        capture_output=True,
        text=True,
        timeout=config.timeout,
    )


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

    vocab = read_yaml(Path(config.home) / "frontier.yaml") or {}
    checkpoint = resolve_checkpoint(request.checkpoint, vocab)
    if checkpoint == "":
        replier(event, f"未知 checkpoint：{request.checkpoint}", config)
        return {"ok": False, "reason": "unknown_checkpoint"}

    with job_lock(config.home) as acquired:
        if not acquired:
            replier(event, "正在推送，请等这一篇完成。", config)
            return {"ok": False, "reason": "busy"}
        replier(event, "收到，开始检索。", config)
        _log(config, {"kind": "start", "checkpoint": checkpoint})
        try:
            proc = runner(config, build_prompt(config, checkpoint))
            output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
            ok = proc.returncode == 0
            no_new = "今天没有新的" in output
            if ok and no_new:
                text = "今天没有新的。"
            elif ok:
                text = "补推完成。" if "已推送" in output else "补推完成。"
            else:
                text = f"补推失败（exit {proc.returncode}），请查看日志。"
            _log(
                config,
                {
                    "kind": "finish",
                    "checkpoint": checkpoint,
                    "ok": ok,
                    "text": text,
                    "stdout_tail": output[-1500:],
                },
            )
            replier(event, text, config)
            return {"ok": ok, "checkpoint": checkpoint, "text": text, "exit": proc.returncode}
        except subprocess.TimeoutExpired:
            _log(config, {"kind": "timeout", "checkpoint": checkpoint})
            replier(event, "补推超时，请查看日志。", config)
            return {"ok": False, "reason": "timeout"}
        except Exception as exc:  # noqa: BLE001 - keep listener alive
            _log(config, {"kind": "error", "checkpoint": checkpoint, "error": str(exc)})
            replier(event, "补推失败，请查看日志。", config)
            return {"ok": False, "reason": "error", "error": str(exc)}


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

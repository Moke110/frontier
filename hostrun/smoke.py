"""Temporary end-to-end acceptance, driven by one keyword or query.

The installation test must exercise the *real* chain without touching formal
knowledge:

    keyword → temporary knowledge card → retrieval plan → paper → push →
    Feishu display → rating → adoption → knowledge write → verification

The host agent performs retrieval, ranking and writing (ADR 0005); this module
owns what must not be improvised:

- a test identity and a recognizable temporary card (``card_smoke_*``), written
  both to the local archive and the authoritative Base;
- a resumable step record, so an interrupted run continues instead of sending
  twice or applying a decision twice;
- artifact ownership (push ids, message ids, file tokens, question ids) for the
  later exact cleanup;
- an ordered state machine: success is only declared after every step and a
  real read-back verification; a failure can never open formal initialization.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from common import now, read_json, write_json
from hostrun import facilities as facilities_mod
from hostrun import install as install_mod
from hostrun.base import HostRunError, base_client, base_config
from question_queue.store import QueueStore

SMOKE_REL = Path("install") / "smoke.json"
PLAN_REL = Path("install") / "smoke-plan.json"
STEPS = ("retrieved", "written", "rendered", "sent", "rated", "decided", "applied")
TERMINAL_FAILED = ("failed", "aborted")


# ------------------------------------------------------------------ helpers
def load(home: Path) -> dict:
    return read_json(Path(home) / SMOKE_REL) or {}


def save(home: Path, state: dict) -> Path:
    path = Path(home) / SMOKE_REL
    write_json(path, {**state, "updated_at": now()})
    return path


def _fail(home: Path, state: dict, reason: str, **evidence) -> dict:
    state = {
        **state,
        "status": "failed",
        "failures": [
            *(state.get("failures") or []),
            {"reason": reason, "at": now(), "evidence": evidence},
        ],
    }
    save(home, state)
    install_mod.record(
        home,
        "test_loop",
        "blocked",
        note=f"临时闭环失败：{reason}",
        evidence={"test_id": state.get("test_id"), "reason": reason},
        recheck=True,
    )
    return {**state, "ok": False, "reason": reason}


def _test_id() -> str:
    stamp = now().replace("-", "").replace(":", "").replace("+", "").replace("T", "")
    digest = hashlib.sha1(stamp.encode("utf-8")).hexdigest()[:6]
    return f"smoke_{stamp[:14]}_{digest}"


def _queue(home: Path) -> QueueStore:
    queue = QueueStore(home)
    queue.init()
    return queue


def _card_path(home: Path, card_id: str) -> Path:
    return Path(home) / "archive" / "cards" / f"{card_id}.json"


def _temp_card(test_id: str, keyword: str) -> dict:
    card_id = f"card_{test_id}"
    return {
        "id": card_id,
        "label": f"[临时验收] {keyword}",
        "ontology": [keyword],
        "annotation": (
            f"⛔ 仅用于 {test_id} 安装验收，不属于研究范围；"
            f"⚠️ 清理时必须连同本卡片一起删除。"
        ),
        "created_at": now(),
        "updated_at": now(),
    }


# -------------------------------------------------------------------- start
def start(
    home: Path,
    keyword: str,
    *,
    owner: str = "",
    repo: str | Path | None = None,
    client=None,
    confirmed: bool = False,
) -> dict:
    """Create the temporary card and the resumable test record."""
    home = Path(home).expanduser().resolve()
    keyword = " ".join(str(keyword or "").split())
    if not confirmed:
        return {
            "ok": False,
            "reason": "needs_user_confirmation",
            "keyword": keyword,
            "note": "确认用该关键词做一次真实临时推送；测试内容会在成功后清理",
        }
    if not keyword:
        raise HostRunError("需要用户提供关键词或检索式")
    if len(keyword) > 120:
        raise HostRunError("关键词过长，请提供一个可用于检索的短语")

    previous = load(home)
    if previous:
        if previous.get("status") not in TERMINAL_FAILED and previous.get("status") != "complete":
            return {
                "ok": False,
                "reason": "test_in_progress",
                "test_id": previous.get("test_id"),
                "status": previous.get("status"),
                "next": previous.get("next"),
            }
        if not previous.get("cleaned_at"):
            return {
                "ok": False,
                "reason": "unfinished_previous_test",
                "test_id": previous.get("test_id"),
                "note": "上一次临时测试尚未清理；先完成清理再开始新的测试",
            }

    queue = _queue(home)
    if queue.has_unfinished():
        return {
            "ok": False,
            "reason": "queue_busy",
            "note": "正式队列仍有未完成问题；临时测试不能插入或清理正式工作",
            "resume": queue.status(),
        }

    try:
        base_config(home)
    except HostRunError as exc:
        state = {
            "schema_version": 1,
            "test_id": _test_id(),
            "keyword": keyword,
            "owner": owner,
            "repo": str(repo) if repo else "",
            "status": "failed",
            "created_at": now(),
            "card": {},
            "artifacts": {},
            "steps": {},
        }
        return _fail(home, state, "facilities_missing", note=str(exc))

    test_id = _test_id()
    card = _temp_card(test_id, keyword)
    path = _card_path(home, card["id"])
    if path.exists():
        raise HostRunError(f"临时卡片已存在：{card['id']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, card)

    state = {
        "schema_version": 1,
        "test_id": test_id,
        "keyword": keyword,
        "owner": owner,
        "repo": str(repo) if repo else "",
        "status": "running",
        "created_at": now(),
        "card": {"id": card["id"], "label": card["label"], "local_path": str(path)},
        "artifacts": {
            "push_ids": [],
            "message_ids": [],
            "file_ids": [],
            "source_ids": [],
            "question_ids": [],
            "record_ids": [],
        },
        "steps": {},
        "failures": [],
        "next": "plan",
    }

    try:
        client = client or base_client(home)
        config = read_json(home / "knowledge" / "base.json") or {}
        cards_table = (config.get("tables") or {}).get("cards")
        if not cards_table:
            raise HostRunError("知识卡片表尚未创建")
        record_ids = client.create(
            cards_table,
            [
                {
                    "卡片 ID": card["id"],
                    "label": card["label"],
                    "ontology": [keyword],
                    "annotation": card["annotation"],
                    "created_at": card["created_at"],
                    "updated_at": card["updated_at"],
                }
            ],
        )
        state["card"]["remote_record_id"] = (record_ids or [""])[0]
        state["artifacts"]["record_ids"].append(state["card"]["remote_record_id"])
    except Exception as exc:  # noqa: BLE001 - permission/network failures are results
        path.unlink(missing_ok=True)
        return _fail(home, state, "temp_card_write_failed", error=str(exc))

    save(home, state)
    install_mod.record(
        home,
        "test_loop",
        "untested",
        note=f"临时闭环进行中：关键词「{keyword}」",
        evidence={"test_id": test_id, "keyword": keyword, "card_id": card["id"]},
        recheck=True,
    )
    return {"ok": True, **state, "path": str(home / SMOKE_REL)}


# --------------------------------------------------------------------- plan
def plan(home: Path, *, days: int = 7, out: Path | None = None) -> dict:
    """Only the temporary card's queries: formal research is not re-scoped."""
    home = Path(home).expanduser().resolve()
    state = load(home)
    if not state or state.get("status") in TERMINAL_FAILED:
        raise HostRunError("没有进行中的临时测试")
    from frontier.model import plan as build_plan

    full = build_plan(home, days=days)
    card_id = (state.get("card") or {}).get("id")
    queries = [row for row in full.get("queries") or [] if row.get("card_id") == card_id]
    result = {**full, "queries": queries, "smoke": state.get("test_id")}
    target = Path(out) if out else home / PLAN_REL
    write_json(target, result)
    if not queries:
        raise HostRunError("临时卡片没有生成检索式；检查关键词和卡片内容")
    return {**result, "out": str(target)}


def brief(home: Path) -> dict:
    """The exact next actions, using the same pipeline as a normal push."""
    home = Path(home).expanduser().resolve()
    state = load(home)
    if not state:
        raise HostRunError("先运行 smoke start")
    card_id = (state.get("card") or {}).get("id")
    test_id = state.get("test_id")
    command = (
        f'python -m hostrun.cli --home "{home}" smoke record --step {{step}} '
        f"--evidence '{{...}}'"
    )
    steps = [
        "python -m frontier.cli validate",
        f'python -m hostrun.cli --home "{home}" smoke plan --out "{home / PLAN_REL}"',
        f'python -m retriever.cli fetch --plan "{home / PLAN_REL}" --out '
        f'"<临时目录>/{test_id}-candidates.jsonl" --source live',
        "python -m archive.cli add-paper --file <候选 json>（逐条，自动去重）",
        f'python -m editor.cli task --candidates <候选> --date <today> --out "<临时目录>/{test_id}-editor.json"',
        "你亲自写 selection.json，并 python -m editor.cli check ...",
        f'python -m writer.cli task ... --card {card_id} ...',
        "python -m writer.cli figures ...；你亲自写七段 HTML 与 assets",
        "python -m writer.cli check ...",
        f'python -m writer.cli render --push <push> --out "<临时目录>/{test_id}.html"',
        "python -m archive.cli add-push --file <push json>",
        "python -m library.cli ensure-source --paper <paper_id>",
        f'python -m publisher.cli send --push <push> --html <html> --to {state.get("owner") or "<owner>"}',
        "python -m hostrun.cli feedback sync",
        f'python -m hostrun.cli --home "{home}" smoke record --step sent '
        "--push <push_id> --message <file_message_id> --question <item_id> "
        "--source <source_id> --file <source_file_token> --file <push_file_token>",
        "请用户在飞书检查展示并评分；用户提交后运行 feedback submit --item <id> --verdict ...",
        f'python -m hostrun.cli --home "{home}" smoke record --step rated --item <id> --verdict <verdict>',
        "用户明确采纳更新：feedback submit --item <id> --decision agree_all（或 adopt）",
        f'python -m hostrun.cli --home "{home}" smoke record --step decided --item <id> --decision <decision>',
        "python -m hostrun.cli feedback process",
        f'python -m hostrun.cli --home "{home}" smoke verify --target-key cards '
        f"--target-id {card_id} --field <字段> --expected <值>",
    ]
    return {
        "ok": True,
        "test_id": test_id,
        "keyword": state.get("keyword"),
        "card_id": card_id,
        "steps": steps,
        "record_command": command,
        "rules": [
            "只推一篇，只处理当前活动题；评分先行，采纳后才写入",
            "论文必须来自本次临时检索，不得编造",
            "更新只落到本次临时卡片；若必须新建命题/证据，其 ID 必须包含本次 test_id",
            "任何一步失败先核对再重试；发送不确定时暂停，不能重发",
            "不得改动已有正式知识、正式待答问题与唯一离线备份",
        ],
    }


# ------------------------------------------------------------------- record
def record(
    home: Path,
    step: str,
    *,
    evidence: dict | None = None,
    item: str | None = None,
    push: str | None = None,
    message: str | None = None,
    question: str | None = None,
    verdict: str | None = None,
    decision: str | None = None,
    file_id: str | list[str] | None = None,
    source_id: str | None = None,
) -> dict:
    """Record one ordered step; rerunning the same step is a no-op."""
    home = Path(home).expanduser().resolve()
    if step not in STEPS:
        raise HostRunError(f"未知步骤：{step}")
    state = load(home)
    if not state:
        raise HostRunError("没有临时测试记录")
    if state.get("status") in TERMINAL_FAILED:
        raise HostRunError("临时测试已失败；先完成清理再继续")
    if step in state.get("steps", {}):
        return {"ok": True, "duplicate": True, "step": step, "status": state["status"]}

    expected = next(
        (name for name in STEPS if name not in state.get("steps", {})),
        None,
    )
    if expected != step:
        raise HostRunError(f"步骤顺序错误：下一步是 {expected or '已完成'}，不能先记录 {step}")
    if step == "sent" and not (push and message and question):
        raise HostRunError("sent 步骤需要 --push、--message 与 --question，记录本次副作用归属")
    if step == "rated" and (not item or verdict not in ("irrelevant", "ok", "great")):
        raise HostRunError("rated 步骤需要 --item 和 --verdict")
    if step == "decided" and (not item or decision not in ("agree_all", "adopt", "keep_previous", "reject_all")):
        raise HostRunError("decided 步骤需要 --item 和 --decision")

    artifacts = state.setdefault("artifacts", {})
    file_ids = file_id if isinstance(file_id, list) else ([file_id] if file_id else [])
    for key, values in (
        ("push_ids", [push]),
        ("message_ids", [message]),
        ("question_ids", [question]),
        ("file_ids", file_ids),
        ("source_ids", [source_id]),
    ):
        for value in values:
            if value and value not in artifacts.setdefault(key, []):
                artifacts[key].append(value)
    if item and item not in artifacts.setdefault("question_ids", []):
        artifacts["question_ids"].append(item)

    state.setdefault("steps", {})[step] = {
        "ok": True,
        "at": now(),
        "evidence": {
            **(evidence or {}),
            **({"item": item} if item else {}),
            **({"push": push} if push else {}),
            **({"message": message} if message else {}),
            **({"verdict": verdict} if verdict else {}),
            **({"decision": decision} if decision else {}),
            **({"source": source_id} if source_id else {}),
            **({"files": file_ids} if file_ids else {}),
        },
    }
    if step == "sent":
        state["status"] = "awaiting_rating"
        state["next"] = "用户检查飞书展示、评分并提交"
    elif step == "rated":
        state["status"] = "awaiting_decision"
        state["next"] = "用户逐题确认更新；只有采纳才写入"
    elif step == "decided":
        state["status"] = "awaiting_apply"
        state["next"] = "运行 feedback process 应用已提交的答案"
    elif step == "applied":
        state["status"] = "awaiting_verification"
        state["next"] = "运行 smoke verify 读取并核对写入结果"
    elif step in ("retrieved", "written", "rendered"):
        state["next"] = step
    save(home, state)
    return {"ok": True, "step": step, "status": state["status"], "artifacts": artifacts}


# --------------------------------------------------------------------- verify
def _find_row(client, table: str, key: str, value: str) -> dict | None:
    for row in client.list(table):
        if str((row.get("fields") or {}).get(key) or "") == str(value):
            return row
    return None


def verify(
    home: Path,
    *,
    target_key: str,
    target_id: str,
    field: str,
    expected: str,
    client=None,
) -> dict:
    """Read the authoritative Base and require the accepted change to be there."""
    home = Path(home).expanduser().resolve()
    state = load(home)
    if not state:
        raise HostRunError("没有临时测试记录")
    if any(name not in (state.get("steps") or {}) for name in STEPS):
        raise HostRunError("还有步骤未记录，不能先做写入核对")
    test_id = state.get("test_id") or ""
    card_id = (state.get("card") or {}).get("id") or ""
    if target_id not in {card_id} and not target_id.startswith(f"card_{test_id}") and not target_id.startswith(
        f"prop_{test_id}"
    ):
        return _fail(
            home,
            state,
            "verification_target_outside_test",
            target_id=target_id,
            note="验收只允许核对本次测试创建的知识卡片或命题",
        )

    config = read_json(home / "knowledge" / "base.json") or {}
    table_id = (config.get("tables") or {}).get(target_key)
    if not table_id:
        return _fail(home, state, "verification_table_missing", target_key=target_key)
    client = client or base_client(home)
    key_field = "卡片 ID" if target_key == "cards" else (
        "命题 ID" if target_key == "propositions" else "证据 ID"
    )
    row = _find_row(client, table_id, key_field, target_id)
    if not row:
        return _fail(home, state, "verification_target_missing", target_id=target_id)
    actual = (row.get("fields") or {}).get(field)
    if isinstance(actual, list):
        actual = actual[0] if len(actual) == 1 else actual
    same = str(actual) == str(expected)
    if not same:
        return _fail(
            home,
            state,
            "verification_mismatch",
            target_id=target_id,
            field=field,
            expected=expected,
            actual=actual,
        )

    state.setdefault("steps", {})["verified"] = {
        "ok": True,
        "at": now(),
        "evidence": {
            "target_key": target_key,
            "target_id": target_id,
            "field": field,
            "expected": expected,
        },
    }
    complete = all(name in state["steps"] for name in STEPS)
    state["status"] = "complete" if complete else state.get("status")
    state["next"] = None if complete else "还有未完成步骤"
    save(home, state)
    install_mod.record(
        home,
        "test_loop",
        "ok" if complete else "untested",
        note=(
            "关键词临时闭环通过：推送、评分、采纳、写入与读回均已验证"
            if complete
            else "已核对该项写入；仍有步骤未完成"
        ),
        evidence={
            "test_id": test_id,
            "card_id": card_id,
            "steps": sorted(state["steps"]),
        },
        recheck=True,
    )
    return {
        "ok": complete,
        "test_id": test_id,
        "status": state["status"],
        "steps": sorted(state["steps"]),
        "verified": True,
        "next": state["next"],
    }


# --------------------------------------------------------------------- status
def status(home: Path) -> dict:
    home = Path(home).expanduser().resolve()
    state = load(home)
    if not state:
        return {"ok": False, "status": "none", "note": "尚未开始临时闭环"}
    done = [name for name in STEPS if name in (state.get("steps") or {})]
    verified = (
        "verified" in (state.get("steps") or {})
        or state.get("test_status") == "complete"
    )
    complete = state.get("status") == "complete" or state.get("test_status") == "complete"
    return {
        "ok": complete,
        "test_id": state.get("test_id"),
        "keyword": state.get("keyword"),
        "status": state.get("status"),
        "done": done,
        "verified": verified,
        "complete": complete,
        "cleaned": bool(state.get("cleaned_at")),
        "next": state.get("next"),
        "failures": state.get("failures") or [],
        "artifacts": state.get("artifacts") or {},
        "card": state.get("card") or {},
    }


def fail(home: Path, reason: str, *, evidence: dict | None = None) -> dict:
    home = Path(home).expanduser().resolve()
    state = load(home)
    if not state:
        raise HostRunError("没有临时测试记录")
    state = _fail(home, state, reason, **(evidence or {}))
    return {"ok": False, "status": state["status"], "reason": reason, "test_id": state["test_id"]}


def require_success(home: Path) -> dict:
    """Formal initialization may only start after a complete, verified test."""
    result = status(home)
    if not result["ok"]:
        raise HostRunError(
            "临时闭环尚未通过（" + ("、".join(result.get("done") or []) or "未开始") + "）"
        )
    return result

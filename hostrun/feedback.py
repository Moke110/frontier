"""Persistent feedback in Feishu: questions, submissions, results, corrections.

ADR 0005 makes the issued question, its proposal snapshot, the submitted answer
and the processing outcome durable in the Bitable — the local queue is only a
rebuildable view. That is what lets a researcher answer while the agent is
stopped (or on another computer) and still be processed exactly once.

Three tables, all in the same Base as the knowledge tables:

  「问题」   one row per issued question, keyed by the queue item id
  「反馈」   append-only submissions; only 待处理 rows are acted on
  「更正」   a recorded correction request, never an automatic undo

Rules enforced here:
  - only a submitted answer for the *active* question is processed;
  - a stale (already terminal) submission is marked 过期, not applied twice;
  - editing a row after processing does not revert knowledge — that needs 更正;
  - nothing is applied without an explicit submission.
"""

from __future__ import annotations

import json
from pathlib import Path

from common import now, stable_id
from hostrun.base import (
    HostRunError,
    base_client,
    base_config,
    save_base_config,
)
from question_queue.store import QueueError, QueueStore

QUESTIONS = "questions"
SUBMISSIONS = "submissions"
CORRECTIONS = "corrections"
TABLE_NAMES = {QUESTIONS: "问题", SUBMISSIONS: "反馈", CORRECTIONS: "更正"}

QUESTION_FIELDS = [
    {"name": "问题 ID", "type": "text"},
    {"name": "推送 ID", "type": "text"},
    {"name": "类型", "type": "text"},
    {"name": "目标", "type": "text"},
    {"name": "状态", "type": "text"},
    {"name": "提议快照", "type": "text"},
    {"name": "当前答案", "type": "text"},
    {"name": "提交时间", "type": "text"},
    {"name": "处理结果", "type": "text"},
    {"name": "处理时间", "type": "text"},
    {"name": "创建时间", "type": "text"},
]
SUBMISSION_FIELDS = [
    {"name": "反馈 ID", "type": "text"},
    {"name": "问题 ID", "type": "text"},
    {"name": "答案", "type": "text"},
    {"name": "提交时间", "type": "text"},
    {"name": "处理状态", "type": "text"},
    {"name": "处理时间", "type": "text"},
    {"name": "结果", "type": "text"},
]
CORRECTION_FIELDS = [
    {"name": "更正 ID", "type": "text"},
    {"name": "问题 ID", "type": "text"},
    {"name": "目标", "type": "text"},
    {"name": "原因", "type": "text"},
    {"name": "状态", "type": "text"},
    {"name": "提交时间", "type": "text"},
    {"name": "处理时间", "type": "text"},
    {"name": "结果", "type": "text"},
]
FIELDS = {QUESTIONS: QUESTION_FIELDS, SUBMISSIONS: SUBMISSION_FIELDS, CORRECTIONS: CORRECTION_FIELDS}

OPEN = "待回答"
ACTIVE = "当前"
SUBMITTED = "已提交"
PROCESSED = "已处理"
DROPPED = "已丢弃"
FAILED = "失败"

PENDING = "待处理"
STALE = "过期"
IGNORED = "忽略"

LOCAL_TO_REMOTE = {
    "pending": OPEN,
    "active": ACTIVE,
    "answered": PROCESSED,
    "dropped": DROPPED,
    "failed": FAILED,
}


# ------------------------------------------------------------------ helpers
def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _loads(value) -> dict:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _rows(client, table: str) -> list[dict]:
    return client.list(table) or []


def _find(rows: list[dict], key: str, value: str) -> dict | None:
    for row in rows:
        if str(row.get("fields", {}).get(key) or "") == str(value):
            return row
    return None


def load_tables(home: Path, client=None) -> dict:
    cfg = base_config(home)
    tables = cfg.get("tables") or {}
    missing = [name for name in TABLE_NAMES if not tables.get(name)]
    if missing:
        raise HostRunError(
            "缺少反馈表：" + "、".join(TABLE_NAMES[name] for name in missing)
            + "；先运行 hostrun feedback setup"
        )
    return {name: tables[name] for name in TABLE_NAMES}


def setup(home: Path, *, client=None, dry_run: bool = False, names: dict | None = None) -> dict:
    """Create the three feedback tables when they are missing (idempotent)."""
    home = Path(home)
    cfg = base_config(home)
    client = base_client(home, client=client)
    listing = client.list_tables()
    existing = {row["name"]: row["id"] for row in listing}
    tables = dict(cfg.get("tables") or {})
    actions = []
    names = names or {}
    for key, default in TABLE_NAMES.items():
        name = str(names.get(key) or default)
        if name in existing:
            tables[key] = existing[name]
            continue
        actions.append(f"create table {name}")
        if dry_run:
            tables[key] = tables.get(key) or f"tbl_dry_{name}"
            continue
        tables[key] = client.create_table(name, FIELDS[key])
    if not dry_run:
        save_base_config(home, {**cfg, "tables": tables})
    return {"ok": True, "dry_run": dry_run, "tables": tables, "actions": actions}


def _queue(home: Path) -> QueueStore:
    queue = QueueStore(home)
    queue.init()
    return queue


# --------------------------------------------------------------------- sync
def _question_fields(item: dict) -> dict:
    payload = item.get("payload") or {}
    status = LOCAL_TO_REMOTE.get(item.get("status"), OPEN)
    answer = item.get("answer") or {}
    processed = item.get("status") in ("answered", "dropped") or item.get("status") == "failed"
    return {
        "问题 ID": item["id"],
        "推送 ID": item.get("push_id") or "",
        "类型": item.get("kind") or "",
        "目标": payload.get("target_label") or payload.get("target_id") or item.get("card_id") or "",
        "状态": status,
        "提议快照": json.dumps(payload.get("proposals") or [], ensure_ascii=False),
        "创建时间": item.get("created_at") or "",
        "处理结果": _result_text(answer) if processed else "",
        "处理时间": (item.get("answered_at") or "") if processed else "",
    }


def _result_text(answer: dict) -> str:
    if not answer:
        return ""
    if answer.get("verdict"):
        return f"评分 {answer['verdict']}" + (f"（{answer['comment']}）" if answer.get("comment") else "")
    if answer.get("decision"):
        return {"agree_all": "采纳更新", "reject_all": "拒绝更新", "adopt": "采纳综述", "keep_previous": "保留上一版"}.get(
            answer["decision"], str(answer["decision"])
        )
    if answer.get("error"):
        return f"处理失败：{answer['error']}"
    return ""


def sync(home: Path, *, client=None, at: str | None = None) -> dict:
    """Mirror the local queue into 「问题」 without ever losing a submission."""
    home = Path(home)
    tables = load_tables(home)
    client = base_client(home, client=client)
    queue = _queue(home)
    rows = _rows(client, tables[QUESTIONS])
    by_id = {str(row["fields"].get("问题 ID") or ""): row for row in rows}
    created = updated = kept = 0
    creates: list[dict] = []
    updates: dict[str, dict] = {}
    for item in queue.status()["items"]:
        fields = _question_fields(item)
        current = by_id.get(item["id"])
        if not current:
            creates.append(fields)
            created += 1
            continue
        remote = current["fields"]
        # A submission made in Feishu must survive a sync from a machine that
        # has not processed it yet.
        if remote.get("状态") == SUBMITTED and not fields["处理结果"]:
            kept += 1
            continue
        diff = {
            key: value
            for key, value in fields.items()
            if key != "当前答案" and _text(remote.get(key)) != _text(value)
        }
        if diff:
            updates[current["record_id"]] = diff
            updated += 1
    if creates:
        client.create(tables[QUESTIONS], creates)
    if updates:
        client.update(tables[QUESTIONS], updates)
    return {"ok": True, "created": created, "updated": updated, "kept_submitted": kept, "at": at or now()}


# ------------------------------------------------------------------- submit
def _answer_key(answer: dict) -> str:
    return "|".join(
        [
            str(answer.get("verdict") or ""),
            str(answer.get("decision") or ""),
            str(answer.get("comment") or ""),
        ]
    )


def validate_answer(answer: dict) -> list[str]:
    problems = []
    if answer.get("verdict") and answer["verdict"] not in {"irrelevant", "ok", "great"}:
        problems.append(f"未知评分：{answer['verdict']}")
    if answer.get("decision") and answer["decision"] not in {"agree_all", "reject_all", "adopt", "keep_previous"}:
        problems.append(f"未知决定：{answer['decision']}")
    if not answer.get("verdict") and not answer.get("decision"):
        problems.append("需要评分或决定")
    if answer.get("verdict") and answer.get("decision"):
        problems.append("一次只提交评分或一个决定")
    return problems


def submit(
    home: Path,
    item_id: str,
    answer: dict,
    *,
    comment: str = "",
    client=None,
    at: str | None = None,
) -> dict:
    """Explicit submission boundary: nothing is processed before this call."""
    home = Path(home)
    answer = {**answer}
    if comment:
        answer["comment"] = comment
    problems = validate_answer(answer)
    if problems:
        return {"ok": False, "reason": "bad_answer", "problems": problems}
    tables = load_tables(home)
    client = base_client(home, client=client)
    queue = _queue(home)
    try:
        item = queue.get(item_id)
    except QueueError:
        return {"ok": False, "reason": "unknown_item", "item_id": item_id}

    rows = _rows(client, tables[QUESTIONS])
    row = _find(rows, "问题 ID", item_id)
    if row is None:
        sync(home, client=client)
        rows = _rows(client, tables[QUESTIONS])
        row = _find(rows, "问题 ID", item_id)
    if row is None:
        return {"ok": False, "reason": "not_synced", "item_id": item_id}

    state = str(row["fields"].get("状态") or "")
    if state in (PROCESSED, DROPPED):
        return {"ok": False, "reason": "closed", "item_id": item_id, "state": state}

    stamp = at or now()
    submissions = _rows(client, tables[SUBMISSIONS])
    mine = [r for r in submissions if str(r["fields"].get("问题 ID") or "") == item_id]
    for existing in mine:
        if (
            str(existing["fields"].get("处理状态") or "") == PENDING
            and _loads(existing["fields"].get("答案")) == answer
        ):
            return {"ok": True, "deduped": True, "submission_id": existing["fields"].get("反馈 ID")}
    if any(_loads(r["fields"].get("答案")) == answer and str(r["fields"].get("处理状态")) in (PROCESSED, STALE) for r in mine):
        latest = next(
            r for r in mine
            if _loads(r["fields"].get("答案")) == answer and str(r["fields"].get("处理状态")) in (PROCESSED, STALE)
        )
        return {"ok": True, "deduped": True, "submission_id": latest["fields"].get("反馈 ID")}

    submission_id = f"fb_{len(mine) + 1:02d}_{stable_id('s', item_id, _answer_key(answer))}"
    client.create(
        tables[SUBMISSIONS],
        [{
            "反馈 ID": submission_id,
            "问题 ID": item_id,
            "答案": json.dumps(answer, ensure_ascii=False),
            "提交时间": stamp,
            "处理状态": PENDING,
            "处理时间": "",
            "结果": "",
        }],
    )
    client.update(
        tables[QUESTIONS],
        {
            row["record_id"]: {
                "当前答案": json.dumps(answer, ensure_ascii=False),
                "提交时间": stamp,
                "状态": SUBMITTED,
            }
        },
    )
    return {"ok": True, "submission_id": submission_id, "item_id": item_id, "submitted_at": stamp}


def pending_submissions(home: Path, *, client=None) -> list[dict]:
    tables = load_tables(home)
    client = base_client(home, client=client)
    rows = [r for r in _rows(client, tables[SUBMISSIONS]) if str(r["fields"].get("处理状态") or "") == PENDING]
    rows.sort(key=lambda r: str(r["fields"].get("提交时间") or ""))
    return rows


# ------------------------------------------------------------------ process
def process(home: Path, *, client=None, at: str | None = None) -> dict:
    """Apply submitted answers for the active question, in submission order."""
    home = Path(home)
    tables = load_tables(home)
    client = base_client(home, client=client)
    queue = _queue(home)
    submissions = pending_submissions(home, client=client)
    questions = _rows(client, tables[QUESTIONS])
    stamp = at or now()
    results = []
    processed = skipped = stale = 0

    for row in submissions:
        fields = row["fields"]
        item_id = str(fields.get("问题 ID") or "")
        answer = _loads(fields.get("答案"))
        outcome = _process_one(queue, item_id, answer)
        if outcome["state"] == "processed":
            processed += 1
        elif outcome["state"] == "stale":
            stale += 1
        else:
            skipped += 1
        record_state = {
            "processed": PROCESSED,
            "stale": STALE,
            "skipped": PENDING,
        }[outcome["state"]]
        client.update(
            tables[SUBMISSIONS],
            {
                row["record_id"]: {
                    "处理状态": record_state,
                    "处理时间": "" if record_state == PENDING else stamp,
                    "结果": outcome["note"],
                }
            },
        )
        question = _find(questions, "问题 ID", item_id)
        if question and outcome["state"] != "skipped":
            patch = {"处理结果": outcome["note"], "处理时间": stamp}
            if outcome["state"] == "processed":
                patch["状态"] = PROCESSED
            client.update(tables[QUESTIONS], {question["record_id"]: patch})
        results.append({"item_id": item_id, **outcome})

    if processed:
        sync(home, client=client)
    return {
        "ok": True,
        "processed": processed,
        "skipped": skipped,
        "stale": stale,
        "results": results,
        "quiet": processed == 0 and stale == 0 and skipped == 0,
    }


def _process_one(queue: QueueStore, item_id: str, answer: dict) -> dict:
    try:
        item = queue.get(item_id)
    except QueueError:
        return {"state": "stale", "note": "本地队列没有这条问题（可能已被清理）；未应用"}
    if item.get("status") in ("answered", "dropped"):
        return {"state": "stale", "note": f"该问题已是 {item.get('status')}；重复提交未再次应用"}
    if item.get("status") == "failed":
        return {"state": "skipped", "note": "该问题处理失败，先重试或放弃后再处理新提交"}
    if item.get("status") != "active":
        return {"state": "skipped", "note": "不是当前活动问题；等它成为活动题再处理"}
    result = queue.answer(item_id, answer)
    if not result.get("ok"):
        return {"state": "stale", "note": f"未应用：{result.get('reason')}"}
    if result.get("deduped"):
        return {"state": "stale", "note": "重复提交，未再次应用"}
    summary = _result_text(answer)
    nxt = (result.get("next") or {}).get("id")
    return {"state": "processed", "note": summary + (f"；下一题 {nxt}" if nxt else "；队列已清空")}


# ------------------------------------------------------------------- rebuild
def rebuild(home: Path, *, client=None) -> dict:
    """Reconstruct the local queue from Feishu (fresh machine / after cleanup)."""
    home = Path(home)
    tables = load_tables(home)
    client = base_client(home, client=client)
    rows = _rows(client, tables[QUESTIONS])
    if not rows:
        return {"ok": True, "rebuilt": 0, "items": 0, "note": "飞书没有问题记录"}
    queue = _queue(home)
    incoming = []
    for row in rows:
        fields = row["fields"]
        item_id = str(fields.get("问题 ID") or "")
        if not item_id:
            continue
        remote_state = str(fields.get("状态") or "")
        snapshot = fields.get("提议快照") or ""
        proposals = []
        if str(snapshot).strip().startswith("["):
            try:
                proposals = json.loads(snapshot)
            except json.JSONDecodeError:
                proposals = []
        incoming.append(
            {
                "id": item_id,
                "kind": str(fields.get("类型") or ""),
                "push_id": str(fields.get("推送 ID") or "") or None,
                "card_id": None,
                "status": {
                    ACTIVE: "active",
                    SUBMITTED: "active",
                    PROCESSED: "answered",
                    DROPPED: "dropped",
                    FAILED: "failed",
                }.get(remote_state, "pending"),
                "created_at": str(fields.get("创建时间") or "") or now(),
                "sent_at": None,
                "answered_at": str(fields.get("处理时间") or "") or None,
                "message_id": None,
                "attempts": 0,
                "answer": _loads(fields.get("当前答案")) if remote_state in (SUBMITTED, PROCESSED) else None,
                "payload": {
                    "proposals": proposals,
                    "proposal_ids": [p.get("proposal_id") for p in proposals if p.get("proposal_id")],
                    "target_type": "",
                    "target_id": None,
                    "target_label": str(fields.get("目标") or ""),
                    "ready": True,
                },
            }
        )
    adopted = queue.adopt(incoming)
    return {"ok": True, "items": len(incoming), **adopted}


# --------------------------------------------------------------- corrections
def correct(home: Path, item_id: str, reason: str, *, client=None, at: str | None = None) -> dict:
    """Record a correction request; it is queued as a new question, not applied."""
    home = Path(home)
    if not str(reason or "").strip():
        return {"ok": False, "reason": "reason_required"}
    tables = load_tables(home)
    client = base_client(home, client=client)
    queue = _queue(home)
    try:
        item = queue.get(item_id)
    except QueueError:
        return {"ok": False, "reason": "unknown_item", "item_id": item_id}
    row = _find(_rows(client, tables[QUESTIONS]), "问题 ID", item_id)
    target = str(((row or {}).get("fields") or {}).get("目标") or "")
    stamp = at or now()
    correction_id = stable_id("fix", item_id, stamp)
    client.create(
        tables[CORRECTIONS],
        [{
            "更正 ID": correction_id,
            "问题 ID": item_id,
            "目标": target,
            "原因": reason,
            "状态": "待处理",
            "提交时间": stamp,
            "处理时间": "",
            "结果": "",
        }],
    )
    payload = item.get("payload") or {}
    enqueued = queue.enqueue_correction(
        correction_id=correction_id,
        target_type=str(payload.get("target_type") or ""),
        target_id=payload.get("target_id"),
        target_label=target or str(payload.get("target_label") or ""),
        reason=reason,
        card_id=item.get("card_id"),
    )
    sync(home, client=client)
    return {
        "ok": True,
        "correction_id": correction_id,
        "item_id": enqueued["item"]["id"],
        "note": "更正已记录并进入串行队列；需要新的可采用更新，仍按确认规则处理",
    }


def pending_corrections(home: Path, *, client=None) -> list[dict]:
    tables = load_tables(home)
    client = base_client(home, client=client)
    return [
        r for r in _rows(client, tables[CORRECTIONS])
        if str(r["fields"].get("状态") or "") == "待处理"
    ]


# --------------------------------------------------------------- read model
def delivered_push_ids(home: Path, *, client=None) -> set[str]:
    """Pushes recorded in the 推送日志 table — only delivered pushes enter it."""
    cfg = base_config(home)
    table = (cfg.get("tables") or {}).get("pushes")
    if not table:
        return set()
    client = base_client(home, client=client)
    return {
        str(row["fields"].get("推送 ID") or "")
        for row in _rows(client, table)
        if row["fields"].get("推送 ID")
    }


def status(home: Path, *, client=None) -> dict:
    tables = load_tables(home)
    client = base_client(home, client=client)
    questions = _rows(client, tables[QUESTIONS])
    counts: dict[str, int] = {}
    for row in questions:
        state = str(row["fields"].get("状态") or "")
        counts[state] = counts.get(state, 0) + 1
    pending = pending_submissions(home, client=client)
    corrections = pending_corrections(home, client=client)
    active = next((r for r in questions if str(r["fields"].get("状态")) in (ACTIVE, SUBMITTED)), None)
    return {
        "schema_version": 1,
        "questions": len(questions),
        "by_state": counts,
        "pending_submissions": len(pending),
        "pending_corrections": len(corrections),
        "active": (active or {}).get("fields", {}).get("问题 ID"),
        "quiet": not pending and not corrections,
    }

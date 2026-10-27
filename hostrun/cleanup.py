"""Remove the temporary acceptance's artifacts, exactly and verifiably.

Cleanup is scoped by the recorded test identity, never by a folder name, a
display-name match or "clear the table":

- Base rows are deleted by ``record_id`` selected through the test card id,
  push id, question id or test-created proposition/evidence id;
- Drive files only by the recorded file token; messages only by message id;
- local files only under the recorded test card / push / plan paths;
- the environment, configuration, empty facilities and the minimal acceptance
  record stay in place, so cleanup never forces a reinstall;
- every deletion is read back.  A permission failure or an unretractable
  message is reported as incomplete and keeps the formal-initialization gate
  closed.  Rerunning retries only what is still present, without extra effect.
"""

from __future__ import annotations

from pathlib import Path

from common import now, read_json, write_json
from hostrun import install as install_mod
from hostrun import smoke
from hostrun.base import HostRunError, base_client
from library.drive import LarkDrive
from question_queue.store import QueueStore

PREFIX_KEYS = {
    "propositions": ("命题 ID", "prop_"),
    "evidence": ("证据 ID", "ev_"),
}
ID_KEYS = {
    "cards": ("卡片 ID",),
    "papers": ("paper_id", "push_id"),
    "pushes": ("推送 ID",),
    "sources": ("原文 ID",),
    "decisions": ("问题 ID",),
    "questions": ("问题 ID", "推送 ID"),
    "submissions": ("问题 ID", "推送 ID"),
    "corrections": ("问题 ID",),
    "logs": ("source_id",),
}


def _config(home: Path) -> dict:
    return read_json(Path(home) / "knowledge" / "base.json") or {}


def inventory(
    home: Path,
    *,
    client,
) -> dict:
    """Every artifact owned by this test, with the exact selector used."""
    home = Path(home).expanduser().resolve()
    state = smoke.load(home)
    if not state:
        raise HostRunError("没有临时测试记录")
    test_id = state.get("test_id") or ""
    card_id = (state.get("card") or {}).get("id") or ""
    artifacts = state.get("artifacts") or {}
    push_ids = set(artifacts.get("push_ids") or [])
    question_ids = set(artifacts.get("question_ids") or [])
    source_ids = set(artifacts.get("source_ids") or [])
    paper_ids = {str(value) for value in (artifacts.get("paper_ids") or []) if value}
    # 报道 rows are selected by the recorded selected paper ids, plus ids that
    # are derivable from this test's identity; a row created by archive
    # add-paper may carry no push id at all.
    paper_scope = set(paper_ids)
    paper_scope.update({test_id, f"paper_{test_id}"})
    for push_id in push_ids:
        paper_scope.update({push_id, f"paper_{push_id}"})
    paper_scope = {value for value in paper_scope if value}
    config = _config(home)
    tables = config.get("tables") or {}
    records: dict[str, dict] = {}
    notes: list[str] = []

    for key, table_id in tables.items():
        if key not in ID_KEYS and key not in PREFIX_KEYS:
            continue
        try:
            rows = client.list(table_id)
        except Exception as exc:  # noqa: BLE001 - report, keep other scopes
            notes.append(f"{key}: 读取失败（{exc}）")
            continue
        selected = []
        if key in PREFIX_KEYS:
            field, prefix = PREFIX_KEYS[key]
            selected = [
                row["record_id"]
                for row in rows
                if str((row.get("fields") or {}).get(field) or "").startswith(prefix + test_id)
            ]
        else:
            fields = ID_KEYS[key]
            dynamic = {
                "cards": {card_id},
                "papers": paper_scope,
                "pushes": push_ids,
                "sources": source_ids,
                "decisions": question_ids,
                "questions": question_ids | push_ids,
                "submissions": question_ids | push_ids,
                "corrections": question_ids,
                "logs": {test_id, *push_ids, *question_ids, *source_ids},
            }[key]
            dynamic = {value for value in dynamic if value}
            if not dynamic:
                continue
            selected = [
                row["record_id"]
                for row in rows
                if any(
                    str((row.get("fields") or {}).get(field) or "") in dynamic
                    for field in fields
                )
            ]
        if key == "cards" and (state.get("card") or {}).get("remote_record_id"):
            # The recorded row is authoritative; the id lookup is the fallback.
            selected = list(dict.fromkeys([state["card"]["remote_record_id"], *selected]))
        if selected:
            records[key] = {"table_id": table_id, "record_ids": selected}

    local = {
        "card": (state.get("card") or {}).get("local_path") or "",
        "plan": str(home / smoke.PLAN_REL),
        "pushes": [
            str(home / "archive" / "pushes" / f"{push_id}.json")
            for push_id in sorted(push_ids)
        ],
    }
    return {
        "test_id": test_id,
        "test_ok": state.get("status") == "complete" or state.get("test_status") == "complete",
        "card_id": card_id,
        "records": records,
        "local": local,
        "push_ids": sorted(push_ids),
        "question_ids": sorted(question_ids),
        "file_ids": list(dict.fromkeys(artifacts.get("file_ids") or [])),
        "message_ids": list(dict.fromkeys(artifacts.get("message_ids") or [])),
        "source_ids": sorted(source_ids),
        "paper_ids": sorted(paper_ids),
        "paper_scope": sorted(paper_scope),
        "notes": notes,
    }


def _still_present(client, table_id: str, record_ids: list[str]) -> list[str]:
    try:
        rows = client.list(table_id)
    except Exception:  # noqa: BLE001 - unreadable means unverified, not clean
        return list(record_ids)
    present = {row.get("record_id") for row in rows}
    return [record_id for record_id in record_ids if record_id in present]


def _drive_folders(home: Path, drive) -> list[str]:
    from hostrun import facilities

    record = facilities.load_facilities(home)
    folders = record.get("folders") or {}
    values = [folders.get("source"), folders.get("push")]
    return [value for value in values if value]


def _strip(state: dict, cleanup: dict) -> dict:
    """Keep acceptance facts, not the content that was just deleted."""
    counts = {
        key: len(value["record_ids"]) for key, value in (cleanup.get("removed") or {}).items()
    }
    return {
        "schema_version": 1,
        "test_id": state.get("test_id"),
        "test_status": "complete" if cleanup.get("test_ok") else "failed",
        "created_at": state.get("created_at"),
        "cleaned_at": now(),
        "status": "cleaned" if cleanup.get("test_ok") else "failed_cleaned",
        "cleanup": {
            "status": cleanup.get("status"),
            "verified": cleanup.get("verified"),
            "removed_counts": counts,
            "unretractable": cleanup.get("unretractable") or [],
            "failed": cleanup.get("failed") or [],
        },
    }


def plan(home: Path, *, client=None) -> dict:
    home = Path(home).expanduser().resolve()
    client = client or base_client(home)
    found = inventory(home, client=client)
    return {
        "ok": True,
        "test_id": found["test_id"],
        "test_ok": found["test_ok"],
        "records": {
            key: len(value["record_ids"]) for key, value in found["records"].items()
        },
        "local_files": [path for path in [found["local"]["card"], found["local"]["plan"], *found["local"]["pushes"]] if path],
        "messages": len(found["message_ids"]),
        "files": len(found["file_ids"]),
        "notes": found["notes"],
        "needs_user_confirmation": True,
    }


def run(
    home: Path,
    *,
    confirmed: bool = False,
    allow_failed: bool = False,
    client=None,
    drive=None,
    messenger=None,
    lark_cli: str | None = None,
) -> dict:
    """Delete every recorded artifact, then verify nothing is left behind."""
    home = Path(home).expanduser().resolve()
    state = smoke.load(home)
    if not state:
        raise HostRunError("没有临时测试记录")
    if state.get("cleaned_at"):
        return {
            "ok": True,
            "already_cleaned": True,
            "test_id": state.get("test_id"),
            "test_status": state.get("test_status"),
            "status": "cleaned",
        }
    if not confirmed:
        return {
            "ok": False,
            "reason": "needs_user_confirmation",
            "plan": plan(home, client=client),
        }
    client = client or base_client(home)
    found = inventory(home, client=client)
    if not found["test_ok"] and not allow_failed:
        return {
            "ok": False,
            "reason": "test_not_successful",
            "note": (
                "临时测试未成功；不能用清理把失败伪装成通过。"
                "如需移除失败测试的产物，显式使用 --abort，清理后正式初始化闸门仍关闭"
            ),
            "test_id": found["test_id"],
        }

    removed: dict[str, dict] = {}
    failed: list[str] = []
    unretractable: list[str] = []

    for key, value in found["records"].items():
        try:
            client.delete(value["table_id"], value["record_ids"])
            removed[key] = {"table_id": value["table_id"], "record_ids": value["record_ids"]}
        except Exception as exc:  # noqa: BLE001 - keep going, report the residue
            failed.append(f"Base {key}: {exc}")

    for message_id in found["message_ids"]:
        try:
            if messenger is None:
                from hostrun.base import load_config
                from publisher import feishu

                executable = lark_cli or (load_config(home).get("paths") or {}).get(
                    "lark_cli"
                ) or "lark-cli"
                feishu.delete_message(message_id, executable=executable)
            else:
                messenger(message_id)
        except Exception as exc:  # noqa: BLE001 - recall can fail by age/authority
            unretractable.append({"message_id": message_id, "error": str(exc)})

    if drive is None:
        try:
            from hostrun.base import lark_bin

            drive = LarkDrive(bin=lark_bin(home))
        except Exception:  # noqa: BLE001
            drive = None
    for file_id in found["file_ids"]:
        if drive is None:
            failed.append(f"Drive {file_id}: 无云盘客户端，无法删除或验证")
            continue
        present = None
        for folder in _drive_folders(home, drive):
            try:
                tokens = {row["token"] for row in drive.list(folder)}
            except Exception:  # noqa: BLE001 - fall through to an explicit delete
                tokens = None
            if tokens is not None:
                present = bool(present) or file_id in tokens
        if present is False:
            continue  # already gone: idempotent rerun, not a failure
        try:
            drive.delete(file_id, kind="file")
        except Exception as exc:  # noqa: BLE001
            if "unknown token" in str(exc).lower() or "not found" in str(exc).lower():
                continue
            failed.append(f"Drive {file_id}: {exc}")

    for path in [found["local"]["card"], found["local"]["plan"], *found["local"]["pushes"]]:
        if not path:
            continue
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as exc:
            failed.append(f"本地文件 {path}: {exc}")

    try:
        queue = QueueStore(home)
        queue.init()
        queue.discard_push(found["push_ids"], reason="smoke_cleanup")
    except Exception as exc:  # noqa: BLE001
        failed.append(f"本地队列: {exc}")

    # ---- verification: deletion requests are not evidence of deletion
    residue = []
    for key, value in removed.items():
        left = _still_present(client, value["table_id"], value["record_ids"])
        if left:
            residue.append(f"Base {key} 仍有 {len(left)} 行")
    for path in [found["local"]["card"], found["local"]["plan"], *found["local"]["pushes"]]:
        if path and Path(path).exists():
            residue.append(f"本地文件仍存在：{path}")
    try:
        queue = QueueStore(home)
        left = [item for item in queue.items() if item.get("push_id") in set(found["push_ids"])]
        if left:
            residue.append(f"本地队列仍有 {len(left)} 题")
    except Exception as exc:  # noqa: BLE001
        residue.append(f"本地队列无法核对：{exc}")
    if drive is not None and found["file_ids"]:
        for folder in _drive_folders(home, drive):
            try:
                tokens = {row["token"] for row in drive.list(folder)}
            except Exception as exc:  # noqa: BLE001
                residue.append(f"云盘目录无法核对：{exc}")
                continue
            still = [file_id for file_id in found["file_ids"] if file_id in tokens]
            if still:
                residue.append(f"云盘仍有 {len(still)} 个测试文件")

    verified = not failed and not residue and not unretractable and not found["notes"]
    cleanup = {
        "started_at": now(),
        "status": "ok" if verified else "blocked",
        "test_ok": found["test_ok"],
        "verified": verified,
        "removed": removed,
        "failed": failed,
        "residue": residue,
        "unretractable": unretractable,
        "read_errors": found["notes"],
    }
    state["cleanup"] = cleanup
    if verified:
        state = _strip(state, cleanup)
        write_json(home / smoke.SMOKE_REL, {**state, "updated_at": now()})
    else:
        write_json(home / smoke.SMOKE_REL, {**state, "updated_at": now()})

    if verified and found["test_ok"]:
        install_mod.record(
            home,
            "cleanup",
            "ok",
            note="临时测试产物已删除并读回确认，正式初始化闸门可开启",
            evidence={
                "test_id": found["test_id"],
                "removed": {key: len(value["record_ids"]) for key, value in removed.items()},
                "unretractable": 0,
            },
            recheck=True,
        )
    elif verified:
        install_mod.record(
            home,
            "cleanup",
            "blocked",
            note="失败测试的产物已清理；测试未成功，正式初始化仍关闭",
            evidence={"test_id": found["test_id"], "test_ok": False},
            recheck=True,
        )
    else:
        parts = failed + residue
        if unretractable:
            parts = parts + [
                f"不可撤回消息 {row.get('message_id')}" for row in unretractable
            ]
        install_mod.record(
            home,
            "cleanup",
            "blocked",
            note="清理未完成：" + ("；".join(parts) or "存在不可撤回消息"),
            evidence={
                "test_id": found["test_id"],
                "failed": failed,
                "residue": residue,
                "unretractable": [row["message_id"] for row in unretractable],
            },
            recheck=True,
        )
    return {
        "ok": verified and found["test_ok"],
        "cleanup": cleanup,
        "test_id": found["test_id"],
        "test_ok": found["test_ok"],
        "status": "cleaned" if verified else "blocked",
        "next": None if verified else "修复失败项后重跑 cleanup；仍不允许开始正式初始化",
    }


def require_cleaned(home: Path) -> dict:
    """Formal knowledge initialization needs a passed *and* cleaned test."""
    state = smoke.load(home)
    if not state:
        raise HostRunError("没有临时验收记录；先完成关键词闭环")
    if state.get("test_status") != "complete":
        raise HostRunError("临时验收未通过，不能开始正式知识初始化")
    if not state.get("cleaned_at"):
        raise HostRunError("临时验收产物尚未清理干净，不能开始正式知识初始化")
    return {"ok": True, "test_id": state.get("test_id"), "cleaned_at": state.get("cleaned_at")}

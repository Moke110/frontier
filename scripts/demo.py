#!/usr/bin/env python3
"""Offline end-to-end demo: six modules, file contracts only.

  checkpoint -> frontier.plan -> retriever(fixture) -> editor.fit/rank
  -> writer.write -> archive.add-push -> publisher.send(dry-run)
  -> rating event -> approval card -> approval event -> archive.apply-decisions

Runs in a throwaway $KL_HOME; never touches the real data root.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def step(title: str) -> None:
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")


def run(args: list[str], env: dict, quiet: bool = False) -> dict:
    print(f"$ {' '.join(args)}")
    proc = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"command failed ({proc.returncode}): {' '.join(args)}")
    out = proc.stdout.strip()
    if out and not quiet:
        text = out if len(out) < 1600 else out[:1600] + "\n…"
        print(text)
    try:
        return json.loads(out) if out else {}
    except json.JSONDecodeError:
        return {}


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix="kl-demo-"))
    shutil.copytree(ROOT / "fixtures" / "home", home, dirs_exist_ok=True)
    env = {**os.environ, "KL_HOME": str(home)}
    print(f"KL_HOME = {home}")

    step("1. archive: 四层存储（fixtures 已预置知识卡片 + 命题）")
    run([PY, "-m", "archive.cli", "reindex"], env)
    run([PY, "-m", "archive.cli", "stats"], env)

    step("2. frontier: 知识卡片 -> 检索式")
    run([PY, "-m", "frontier.cli", "validate"], env)
    run(
        [
            PY, "-m", "frontier.cli", "plan", "--date", "2026-10-20",
            "--days", "7", "--out", str(home / "plan.json"),
        ],
        env,
    )

    step("3. retriever: 离线取原文（fixture 源）")
    run(
        [
            PY, "-m", "retriever.cli", "fetch", "--plan", str(home / "plan.json"),
            "--out", str(home / "candidates.jsonl"), "--source", "fixture",
            "--fixtures", "fixtures/papers",
        ],
        env,
    )

    step("4. archive: 候选入原文层（去重）")
    ingest_dir = home / "_ingest"
    ingest_dir.mkdir(exist_ok=True)
    for index, line in enumerate((home / "candidates.jsonl").read_text().splitlines(), start=1):
        if not line.strip():
            continue
        path = ingest_dir / f"{index}.json"
        path.write_text(line, encoding="utf-8")
        run([PY, "-m", "archive.cli", "add-paper", "--file", str(path)], env, quiet=True)
    run([PY, "-m", "archive.cli", "stats"], env)

    step("5. editor: 冷启动排序（无评分）+ fit")
    run([PY, "-m", "editor.cli", "fit"], env)
    run(
        [
            PY, "-m", "editor.cli", "rank", "--candidates", str(home / "candidates.jsonl"),
            "--date", "2026-10-20", "--limit", "4", "--per-checkpoint", "2",
            "--out", str(home / "selection.json"),
        ],
        env,
    )
    run(
        [
            PY, "-m", "editor.cli", "task", "--candidates", str(home / "candidates.jsonl"),
            "--date", "2026-10-20", "--limit", "4", "--per-checkpoint", "2",
            "--out", str(home / "editor-task.json"),
        ],
        env,
    )
    run(
        [
            PY, "-m", "editor.cli", "check", "--task", str(home / "editor-task.json"),
            "--selection", str(home / "selection.json"),
        ],
        env,
    )

    step("6. writer: 四段式推送 + 知识更新提议")
    run(
        [
            PY, "-m", "writer.cli", "write", "--selection", str(home / "selection.json"),
            "--out", str(home / "outbox"),
        ],
        env,
    )
    run(
        [
            PY, "-m", "writer.cli", "task", "--selection", str(home / "selection.json"),
            "--out", str(home / "writer-task.json"),
        ],
        env,
    )
    run(
        [
            PY, "-m", "writer.cli", "check", "--task", str(home / "writer-task.json"),
            "--outbox", str(home / "outbox"),
        ],
        env,
    )

    step("7. archive: 推送入库")
    push_files = sorted((home / "outbox" / "pushes").glob("*.json"))
    pushes = []
    for path in push_files:
        pushes.append(json.loads(path.read_text()))
        run([PY, "-m", "archive.cli", "add-push", "--file", str(path)], env, quiet=True)
    chosen = max(pushes, key=lambda p: len(p.get("proposals", [])))
    print(f"\n选用推送：{chosen['push_id']}（{len(chosen.get('proposals', []))} 条提议）")
    print(chosen["body_md"])

    step("8. publisher: 发评分卡（dry-run，不发网络请求）")
    push_path = home / "outbox" / "pushes" / f"{chosen['push_id']}.json"
    html_path = home / "outbox" / f"{chosen['push_id']}.html"
    run(
        [PY, "-m", "writer.cli", "render", "--push", str(push_path),
         "--format", "html", "--out", str(html_path)],
        env,
    )
    send = run(
        [
            PY, "-m", "publisher.cli", "send", "--push", str(push_path),
            "--html", str(html_path),
            "--to", "ou_demo", "--dry-run",
        ],
        env,
    )

    step("9. publisher: 模拟点击「质量优秀」+ 评语")
    rating_event = {
        "message_id": send["message_id"],
        "action_name": "score_high",
        "form_value": json.dumps({"comment": "接上了之前的 HMBS 线索，PDF 预览也清楚"}, ensure_ascii=False),
        "operator_id": "ou_demo",
        "token": "",
    }
    events = home / "events.ndjson"
    events.write_text(json.dumps(rating_event, ensure_ascii=False) + "\n", encoding="utf-8")
    run([PY, "-m", "publisher.cli", "ingest", "--events", str(events), "--offline"], env)

    step("10. publisher: 生成审批卡，模拟点击「同意」")
    messages = [
        json.loads(line)
        for line in (home / "publisher" / "messages.jsonl").read_text().splitlines()
        if line.strip()
    ]
    approval_id = [m for m in messages if m["kind"] == "approval"][-1]["message_id"]
    approval_event = {
        "message_id": approval_id,
        "action_name": "approve",
        "form_value": "{}",
        "operator_id": "ou_demo",
        "token": "",
    }
    approval_path = home / "approval.ndjson"
    approval_path.write_text(json.dumps(approval_event, ensure_ascii=False) + "\n", encoding="utf-8")
    run([PY, "-m", "publisher.cli", "ingest", "--events", str(approval_path), "--offline"], env)

    step("11. archive: 应用已同意的更新")
    run(
        [
            PY, "-m", "archive.cli", "apply-decisions",
            "--pending-dir", str(home / "publisher" / "pending"),
            "--decisions", str(home / "publisher" / "decisions.jsonl"),
        ],
        env,
    )

    step("12. 反哺：评分 -> frontier 权重 -> editor 偏好")
    run(
        [PY, "-m", "frontier.cli", "record", "--checkpoint", chosen["checkpoint_id"], "--verdict", "great", "--pushed"],
        env,
    )
    run([PY, "-m", "editor.cli", "fit"], env)
    rerank = run(
        [
            PY, "-m", "editor.cli", "rank", "--candidates", str(home / "candidates.jsonl"),
            "--date", "2026-10-20", "--limit", "4", "--per-checkpoint", "2",
            "--out", str(home / "selection_after.json"),
        ],
        env,
    )

    step("13. 结果")
    prop = json.loads(
        subprocess.run(
            [PY, "-m", "archive.cli", "prop-get", "prop_hmbs_aip"],
            cwd=ROOT, env=env, capture_output=True, text=True,
        ).stdout
    )
    node = json.loads(
        subprocess.run(
            [PY, "-m", "archive.cli", "card-get", "card_hmbs"],
            cwd=ROOT, env=env, capture_output=True, text=True,
        ).stdout
    )
    print(f"命题 prop_hmbs_aip 历史条数：{len(prop['history'])} -> {[e.get('paper_id') for h in prop['history'] for e in h.get('evidence', [])]}")
    print(f"知识卡 card_hmbs ontology：{node['ontology']}")
    print(f"知识卡片数：{len(list((home / 'archive' / 'cards').glob('*.json')))}")
    print(f"命题数：{len(list((home / 'archive' / 'propositions').glob('*.json')))}")
    print(f"评分：{(home / 'ratings.jsonl').read_text().strip()}")
    print(f"排序前 3：{[s['paper_id'] for s in rerank.get('scores', [])]}")
    print(f"\n全部产物在 {home}")
    print("可单独重跑任一模块，例如：")
    print(f"  KL_HOME={home} python -m frontier.cli show")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

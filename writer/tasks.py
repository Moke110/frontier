"""Agent-facing writer tasks: build a writing packet, validate the pushes.

The agent writes the card and the proposals. This module never calls a model.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from common import now, read_json, read_yaml
from writer.model import _context
from writer.render import inspect as inspect_pdf

INSTRUCTIONS = """你是知识循环的写作者。对每个 item 写一篇长文推送（push JSON，format=pdf）：
1) 先运行 figures 命令取图：python -m writer.cli figures --selection <selection.json> --out <outbox>；
   它会把原文图或生成图落到 outbox/assets/<push_id>/，并返回 assets 列表；
2) 七个 sections 都必填：takeaway / background / methods / results / why / limits / sources；
   中文 1500–2500 字，克制、具体；「why」必须引用 context 里的知识卡摘要、命题、或归档篇数；
3) body_html 是文章正文片段（HTML），不是整页，也不要写 <style>/<script>/CSS；
   用 <h2>、<h3>、<p>、<ul>、<table>、<blockquote> 组织内容；
4) 图片用占位符 <figure data-asset="fig-1"></figure>，渲染器会替换成本地图片与图注；
   每个占位必须在 assets 里有对应项，至少 1 张图；
5) assets 直接使用 figures 命令的输出；source=paper|generated，caption 必须写清来源；
   generated 图不能伪装成原文图；
6) sections.sources 必须包含原文 URL；paper 元数据（authors / journal / published / url）要保留；
7) 如果原文足以更新知识卡或命题，在 proposals 里提出（add_evidence / add_alias /
   add_proposition / update_summary），每条都要有 rationale 与 confidence；
8) proposals 一律 status=draft，绝不直接改 archive。
输出目录 outbox/pushes，一个 push 一个文件，文件名 = push_id。
渲染：python -m writer.cli render --push outbox/pushes/<push_id>.json --out <pdf>。"""

PROPOSAL_KINDS = {
    "add_evidence": "给现有命题补一条证据，target_type=proposition",
    "add_alias": "给知识卡补别名，target_type=kg_node",
    "add_proposition": "新建命题，target_type=none，value 含 text + node_ids",
    "update_summary": "改写知识卡摘要或命题文本，target_type=kg_node|proposition",
}


def build_task(home: Path, selection: dict, date: str) -> dict:
    home = Path(home)
    vocab = read_yaml(home / "frontier.yaml") or {}
    checkpoints = {cp["id"]: cp for cp in vocab.get("checkpoints", [])}
    items = []
    for index, row in enumerate(selection.get("selected", []), start=1):
        paper = row.get("paper") or {}
        cp_id = row.get("checkpoint_id")
        cp = checkpoints.get(cp_id, {})
        ctx = _context(home, cp.get("kg_node_id"), cp_id)
        items.append(
            {
                "checkpoint_id": cp_id,
                "suggested_push_id": f"{date}_{cp_id}_{index:02d}",
                "checkpoint": {
                    "label": cp.get("label"),
                    "annotation": cp.get("annotation", ""),
                    "ontology": cp.get("ontology", []),
                },
                "paper": paper,
                "context": {
                    "node": ctx["node"],
                    "propositions": ctx["props"],
                    "archived_count": ctx["archived"],
                    "recent_papers": [
                        (read_json(p) or {}).get("paper_id")
                        for p in sorted(
                            (home / "archive" / "raw").glob("*.json")
                        )
                        if (read_json(p) or {}).get("checkpoint_id") == cp_id
                    ][:5],
                    "nodes": ctx["nodes"],
                },
            }
        )
    return {
        "schema_version": 1,
        "kind": "writer-task",
        "format": "pdf",
        "date": date,
        "generated_at": now(),
        "instructions": INSTRUCTIONS,
        "archive_cli": "python -m archive.cli",
        "figure_command": "python -m writer.cli figures --selection <selection.json> --out <outbox>",
        "render_command": "python -m writer.cli render --push outbox/pushes/<push_id>.json --out <pdf>",
        "proposal_kinds": PROPOSAL_KINDS,
        "items": items,
        "output": {
            "dir": "outbox/pushes",
            "filename": "<push_id>.json",
            "schema": "contracts/README.md §5.1",
        },
    }


def _target_sets(task: dict) -> tuple[set[str], set[str]]:
    props, nodes = set(), set()
    for item in task.get("items", []):
        ctx = item.get("context", {})
        node = ctx.get("node") or {}
        if node.get("node_id"):
            nodes.add(node["node_id"])
        for prop in ctx.get("propositions", []):
            if prop.get("prop_id"):
                props.add(prop["prop_id"])
        for n in ctx.get("nodes", []):
            if n.get("node_id"):
                nodes.add(n["node_id"])
    return props, nodes


def validate(task: dict, outbox: Path) -> dict:
    errors: list[str] = []
    pushes_dir = Path(outbox) / "pushes"
    files = sorted(pushes_dir.glob("*.json")) if pushes_dir.exists() else []
    if not files:
        return {"ok": False, "errors": [f"no push files under {pushes_dir}"]}

    expected = {
        item["paper"]["paper_id"]: item for item in task.get("items", []) if item.get("paper")
    }
    props, nodes = _target_sets(task)
    seen_papers: dict[str, str] = {}
    proposal_ids: set[str] = set()
    date = task.get("date")

    for path in files:
        push = read_json(path) or {}
        name = f"{path.name}"
        where = f"push[{name}]"
        for key in ("push_id", "date", "checkpoint_id", "paper_ids", "sections", "proposals"):
            if key not in push:
                errors.append(f"{where}: missing {key}")
        if "push_id" in push and path.stem != push["push_id"]:
            errors.append(f"{where}: filename must equal push_id")
        if push.get("date") != date:
            errors.append(f"{where}: date {push.get('date')} != task date {date}")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}_[a-z0-9-]+_\d{2}", str(push.get("push_id", ""))):
            errors.append(f"{where}: push_id must look like <date>_<checkpoint>_<NN>")

        paper_ids = push.get("paper_ids") or []
        if not paper_ids:
            errors.append(f"{where}: paper_ids is empty")
        for pid in paper_ids:
            if pid not in expected:
                errors.append(f"{where}: paper {pid} is not in the task")
            elif pid in seen_papers:
                errors.append(f"{where}: paper {pid} already used by {seen_papers[pid]}")
            else:
                seen_papers[pid] = name

        if push.get("format") == "pdf":
            errors.extend(f"{where}: {error}" for error in inspect_pdf(push, path.parent))
        else:
            sections = push.get("sections") or {}
            for key in ("did", "found", "why", "keep"):
                value = sections.get(key)
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"{where}: sections.{key} must be non-empty")
            if not isinstance(push.get("body_md"), str) or not push["body_md"].strip():
                errors.append(f"{where}: body_md must be non-empty")

        for proposal in push.get("proposals") or []:
            pid = proposal.get("proposal_id")
            kind = proposal.get("kind")
            if not pid:
                errors.append(f"{where}: proposal without proposal_id")
            elif pid in proposal_ids:
                errors.append(f"{where}: duplicate proposal_id {pid}")
            proposal_ids.add(pid)
            if kind not in PROPOSAL_KINDS:
                errors.append(f"{where}: unknown proposal kind {kind}")
            if proposal.get("status") != "draft":
                errors.append(f"{where}: proposal {pid} status must be draft")
            if proposal.get("push_id") != push.get("push_id"):
                errors.append(f"{where}: proposal {pid} push_id mismatch")
            target = proposal.get("target_id")
            if kind in ("add_evidence", "update_summary") and proposal.get("target_type") == "proposition":
                if target not in props:
                    errors.append(f"{where}: proposal {pid} targets unknown proposition {target}")
            if kind in ("add_alias", "update_summary") and proposal.get("target_type") == "kg_node":
                if target not in nodes:
                    errors.append(f"{where}: proposal {pid} targets unknown kg node {target}")
            if kind == "add_evidence" and proposal.get("target_type") != "proposition":
                errors.append(f"{where}: proposal {pid} add_evidence needs target_type=proposition")
            if kind == "add_alias" and proposal.get("target_type") != "kg_node":
                errors.append(f"{where}: proposal {pid} add_alias needs target_type=kg_node")
            if kind == "add_proposition":
                value = (proposal.get("diff") or {}).get("value") or {}
                if not value.get("text"):
                    errors.append(f"{where}: proposal {pid} add_proposition needs diff.value.text")
                for node_id in value.get("node_ids") or []:
                    if node_id not in nodes:
                        errors.append(f"{where}: proposal {pid} references unknown node {node_id}")

    missing = set(expected) - set(seen_papers)
    for pid in sorted(missing):
        errors.append(f"missing push for paper {pid}")

    return {
        "ok": not errors,
        "errors": errors,
        "pushes": len(files),
        "expected": len(expected),
        "proposals": len(proposal_ids),
    }

"""writer: selection -> push (four sections) + knowledge-update proposals.

Deterministic extractive prototype. The only "intelligence" is sentence
selection + simple keyword matching against the archive's knowledge graph.
Replace `_summarise` / `_propose` with an LLM later; the output contract stays.
"""

from __future__ import annotations

import re
from pathlib import Path

from common import clip, now, read_json, read_yaml, write_json

SENTENCE_RE = re.compile(r"(?<=[.!?。！？])\s+")

METHOD_CUES = (
    "we ",
    "here ",
    "using ",
    "developed",
    "performed",
    "generated",
    "profiled",
    "screened",
    "knockdown",
    "knockout",
    "crispr",
)
RESULT_CUES = (
    "show",
    "find",
    "found",
    "demonstrate",
    "reveal",
    "observe",
    "suggest",
    "increase",
    "decrease",
    "improve",
    "predict",
    "associated",
)
KEEP_CUES = ("conclusion", "implication", "provide", "enable", "future", "suggest")


def _sentences(text: str) -> list[str]:
    parts = [s.strip() for s in SENTENCE_RE.split(text or "") if s.strip()]
    return parts or [clip(text or "", 200)]


def _pick(sentences: list[str], cues: tuple[str, ...], fallback: int) -> str:
    for sentence in sentences:
        low = sentence.lower()
        if any(cue in low for cue in cues):
            return sentence
    return sentences[min(fallback, len(sentences) - 1)]


def _summarise(abstract: str) -> dict:
    sentences = _sentences(abstract)
    did = _pick(sentences, METHOD_CUES, 0)
    found = _pick([s for s in sentences if s != did] or sentences, RESULT_CUES, 0)
    keep = _pick(list(reversed(sentences)), KEEP_CUES, 0)
    return {
        "did": clip(did, 400),
        "found": clip(found, 400),
        "keep": clip(keep, 300),
    }


def _context(home: Path, node_id: str | None, checkpoint_id: str) -> dict:
    root = Path(home) / "archive"
    node = read_json(root / "kg" / "nodes" / f"{node_id}.json") if node_id else None
    prop_dir = root / "propositions"
    props = []
    for path in sorted(prop_dir.glob("*.json")) if prop_dir.exists() else []:
        prop = read_json(path) or {}
        if node_id and node_id in prop.get("node_ids", []):
            props.append(prop)
    raw_dir = root / "raw"
    papers = list(raw_dir.glob("*.json")) if raw_dir.exists() else []
    archived = 0
    for path in papers:
        rec = read_json(path) or {}
        if rec.get("checkpoint_id") == checkpoint_id:
            archived += 1
    node_dir = root / "kg" / "nodes"
    nodes = []
    for path in sorted(node_dir.glob("*.json")) if node_dir.exists() else []:
        nodes.append(read_json(path) or {})
    return {"node": node, "props": props, "archived": archived, "nodes": nodes}


def _why(context: dict) -> str:
    node = context["node"]
    parts = []
    if node and node.get("summary"):
        parts.append(node["summary"].rstrip("。."))
    for prop in context["props"][:2]:
        parts.append(f"命题「{prop.get('text','').rstrip('。.')}」")
    if context["archived"]:
        parts.append(f"该 checkpoint 已归档 {context['archived']} 篇，本篇是其中之一")
    return clip("；".join(parts) or "暂无知识卡脉络，本篇作为该 checkpoint 的新线索。", 400)


def _propose(
    push: dict, paper: dict, context: dict, checkpoint_id: str, home: Path
) -> list[dict]:
    """Heuristic proposals. Every one is a *proposal*; the user approves later."""
    proposals: list[dict] = []
    node = context["node"] or {}
    node_id = node.get("node_id")
    abstract = paper.get("abstract", "")
    low = abstract.lower()
    counter = 0

    def add(kind: str, target_type: str, target_id: str, diff: dict, before, after, why: str, conf: float) -> None:
        nonlocal counter
        counter += 1
        proposals.append(
            {
                "schema_version": 1,
                "proposal_id": f"p_{push['push_id']}_{counter}",
                "push_id": push["push_id"],
                "kind": kind,
                "target_type": target_type,
                "target_id": target_id,
                "diff": diff,
                "before": before,
                "after": after,
                "rationale": why,
                "confidence": conf,
                "status": "draft",
            }
        )

    # 1) add evidence to the most relevant existing proposition
    best, best_hits = None, 0
    for prop in context["props"]:
        hits = 0
        for nid in prop.get("node_ids", []):
            other = next((n for n in context["nodes"] if n.get("node_id") == nid), None)
            if not other:
                continue
            labels = [other.get("label", "")] + list(other.get("aliases", []))
            hits += sum(1 for label in labels if label and label.lower() in low)
        if hits > best_hits:
            best, best_hits = prop, hits
    if best and best_hits:
        already = any(e.get("paper_id") == paper.get("paper_id") for e in best.get("evidence", []))
        if not already:
            add(
                "add_evidence",
                "proposition",
                best["prop_id"],
                {
                    "op": "add",
                    "path": "evidence",
                    "value": {"paper_id": paper.get("paper_id"), "note": clip(paper.get("title", ""), 160)},
                },
                len(best.get("evidence", [])),
                len(best.get("evidence", [])) + 1,
                f"摘要中出现 {best_hits} 个与该命题节点相关的术语，可作为新证据。",
                0.7,
            )

    # 2) propose an alias that exists in the checkpoint ontology but not on the node
    vocab = read_yaml(Path(home) / "frontier.yaml") or {}
    cp = next((c for c in vocab.get("checkpoints", []) if c.get("id") == checkpoint_id), {})
    aliases = {a.lower() for a in node.get("aliases", [])}
    for term in sorted(cp.get("ontology", []), key=len, reverse=True):
        if term.lower() == (node.get("label") or "").lower():
            continue
        if term.lower() not in aliases and term.lower() in low:
            add(
                "add_alias",
                "kg_node",
                node_id,
                {"op": "add", "path": "aliases", "value": term},
                list(node.get("aliases", [])),
                list(node.get("aliases", [])) + [term],
                "该词已在该 checkpoint 的 ontology 中，但知识卡未收录为别名。",
                0.4,
            )
            break

    # 3) propose a new proposition when two graph nodes co-occur in one sentence
    for sentence in _sentences(abstract):
        low_sentence = sentence.lower()
        hit_nodes = []
        for candidate in context["nodes"]:
            labels = [candidate.get("label", "")] + list(candidate.get("aliases", []))
            if any(label and label.lower() in low_sentence for label in labels):
                hit_nodes.append(candidate)
        if len(hit_nodes) < 2:
            continue
        ids = [n["node_id"] for n in hit_nodes[:2]]
        linked = any(set(ids).issubset(set(p.get("node_ids", []))) for p in context["props"])
        if linked or ids[0] == ids[1]:
            continue
        add(
            "add_proposition",
            "none",
            "",
            {
                "op": "add",
                "path": "proposition",
                "value": {
                    "text": clip(sentence, 300),
                    "node_ids": ids,
                    "paper_id": paper.get("paper_id"),
                    "note": "由摘要中的共现句抽取",
                },
            },
            None,
            clip(sentence, 300),
            "同一句话同时提到两个知识节点，且现有命题未连接它们。",
            0.5,
        )
        break
    return proposals


def write(selection: dict, home: Path, out_dir: Path, day: str | None = None) -> dict:
    home = Path(home)
    day = day or selection.get("date")
    pushes = []
    for index, row in enumerate(selection.get("selected", []), start=1):
        paper = row["paper"]
        cp_id = row["checkpoint_id"]
        context = _context(home, row.get("kg_node_id") or _node_for(home, cp_id), cp_id)
        node = context["node"] or {}
        label = node.get("label") or cp_id
        title = f"{label}：{clip(paper.get('title', ''), 60)}"
        sections = _summarise(paper.get("abstract", ""))
        sections["why"] = _why(context)
        push = {
            "schema_version": 1,
            "push_id": f"{day}_{cp_id}_{index:02d}",
            "date": day,
            "checkpoint_id": cp_id,
            "kg_node_id": node.get("node_id"),
            "paper_ids": [paper.get("paper_id")],
            "title": title,
            "sections": sections,
            "context": {
                "kg_node_id": node.get("node_id"),
                "propositions": [p["prop_id"] for p in context["props"]],
                "archived_count": context["archived"],
            },
            "source": paper.get("source"),
            "is_preprint": bool(paper.get("is_preprint")),
            "url": paper.get("url"),
            "status": "written",
            "created_at": now(),
        }
        push["proposals"] = _propose(push, paper, context, cp_id, home)
        push["body_md"] = _render(push, paper)
        pushes.append(push)

    out_dir = Path(out_dir)
    (out_dir / "pushes").mkdir(parents=True, exist_ok=True)
    for push in pushes:
        write_json(out_dir / "pushes" / f"{push['push_id']}.json", push)
    return {"ok": True, "count": len(pushes), "out_dir": str(out_dir), "pushes": pushes}


def _node_for(home: Path, checkpoint_id: str) -> str | None:
    vocab = read_yaml(Path(home) / "frontier.yaml") or {}
    for cp in vocab.get("checkpoints", []):
        if cp.get("id") == checkpoint_id:
            return cp.get("kg_node_id")
    return None


def _render(push: dict, paper: dict) -> str:
    badge = "预印本（未经同行评审）" if push.get("is_preprint") else "同行评审"
    return "\n".join(
        [
            f"### {push['title']}",
            f"<font color='grey'>{badge} · {paper.get('source','')} · {paper.get('published') or '日期未知'}</font>",
            "",
            f"**做了什么** {push['sections']['did']}",
            "",
            f"**发现** {push['sections']['found']}",
            "",
            f"**为什么重要** {push['sections']['why']}",
            "",
            f"**保留** {push['sections']['keep']}",
        ]
    )

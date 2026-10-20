"""archive: four-layer file store.

Layers (all under $KL_HOME/archive):
  1. raw/          original papers (metadata + text)
  2. pushes/       generated cards
  3. kg/           knowledge graph (nodes are knowledge cards)
  4. propositions/ claims with evidence

Only this module writes archive/. Everything else reads the documented files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from common import (
    append_jsonl,
    ensure_dir,
    now,
    paper_id as make_paper_id,
    read_json,
    read_jsonl,
    stable_id,
    write_json,
)


class ArchiveError(RuntimeError):
    pass


class Archive:
    def __init__(self, home: Path):
        self.home = Path(home)
        self.root = self.home / "archive"
        self.raw = self.root / "raw"
        self.raw_text = self.raw / "text"
        self.pushes = self.root / "pushes"
        self.kg_nodes = self.root / "kg" / "nodes"
        self.kg_edges = self.root / "kg" / "edges.jsonl"
        self.props = self.root / "propositions"
        self.index = self.root / "index"
        self.applied = self.root / "applied"

    # ---------------------------------------------------------------- setup
    def init(self) -> dict:
        for path in (
            self.raw,
            self.raw_text,
            self.pushes,
            self.kg_nodes,
            self.props,
            self.index,
            self.applied,
        ):
            ensure_dir(path)
        for name in ("papers", "pushes", "kg", "propositions"):
            (self.index / f"{name}.jsonl").touch()
        self.kg_edges.touch()
        return {"ok": True, "root": str(self.root)}

    def reindex(self) -> dict:
        ensure_dir(self.index)
        papers = [read_json(p) for p in sorted(self.raw.glob("*.json"))]
        pushes = [read_json(p) for p in sorted(self.pushes.glob("*.json"))]
        nodes = [read_json(p) for p in sorted(self.kg_nodes.glob("*.json"))]
        props = [read_json(p) for p in sorted(self.props.glob("*.json"))]
        for name, rows in (
            ("papers", papers),
            ("pushes", pushes),
            ("kg", nodes),
            ("propositions", props),
        ):
            target = self.index / f"{name}.jsonl"
            with target.open("w", encoding="utf-8") as fh:
                for row in rows:
                    if row:
                        import json

                        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {
            "ok": True,
            "papers": len(papers),
            "pushes": len(pushes),
            "kg_nodes": len(nodes),
            "propositions": len(props),
        }

    # ------------------------------------------------------------ layer 1
    def add_paper(self, rec: dict) -> dict:
        source = rec.get("source")
        source_id = rec.get("source_id")
        if not source or not source_id:
            raise ArchiveError("paper needs source and source_id")
        pid = rec.get("paper_id") or make_paper_id(source, source_id)
        target = self.raw / f"{pid}.json"
        if target.exists():
            return {"paper_id": pid, "deduped": True, "path": str(target)}

        text = rec.pop("text", None) or rec.get("abstract", "")
        record = {
            "schema_version": 1,
            "paper_id": pid,
            "fetched_at": now(),
            **{k: v for k, v in rec.items() if k != "paper_id"},
        }
        record["text_path"] = f"raw/text/{pid}.txt"
        write_json(target, record)
        ensure_dir(self.raw_text)
        (self.raw_text / f"{pid}.txt").write_text(text or "", encoding="utf-8")
        append_jsonl(self.index / "papers.jsonl", record)
        return {"paper_id": pid, "deduped": False, "path": str(target)}

    def get_paper(self, pid: str) -> dict:
        rec = read_json(self.raw / f"{pid}.json")
        if not rec:
            raise ArchiveError(f"unknown paper: {pid}")
        return rec

    def list_papers(self, checkpoint_id: str | None = None) -> list[dict]:
        rows = [read_json(p) for p in sorted(self.raw.glob("*.json"))]
        rows = [r for r in rows if r]
        if checkpoint_id:
            rows = [r for r in rows if r.get("checkpoint_id") == checkpoint_id]
        return sorted(rows, key=lambda r: r.get("published") or "", reverse=True)

    # ------------------------------------------------------------ layer 2
    def add_push(self, push: dict) -> dict:
        pid = push.get("push_id")
        if not pid:
            raise ArchiveError("push needs push_id")
        push.setdefault("schema_version", 1)
        push.setdefault("created_at", now())
        push.setdefault("status", "written")
        write_json(self.pushes / f"{pid}.json", push)
        append_jsonl(self.index / "pushes.jsonl", push)
        return {"push_id": pid, "path": str(self.pushes / f"{pid}.json")}

    def get_push(self, push_id: str) -> dict:
        rec = read_json(self.pushes / f"{push_id}.json")
        if not rec:
            raise ArchiveError(f"unknown push: {push_id}")
        return rec

    def list_pushes(self, checkpoint_id: str | None = None) -> list[dict]:
        rows = [read_json(p) for p in sorted(self.pushes.glob("*.json"))]
        rows = [r for r in rows if r]
        if checkpoint_id:
            rows = [r for r in rows if r.get("checkpoint_id") == checkpoint_id]
        return sorted(rows, key=lambda r: r.get("created_at") or "", reverse=True)

    # ------------------------------------------------------------ layer 3
    def put_node(self, node: dict) -> dict:
        nid = node.get("node_id")
        if not nid:
            raise ArchiveError("node needs node_id")
        node.setdefault("schema_version", 1)
        node.setdefault("type", "concept")
        node.setdefault("aliases", [])
        node["updated_at"] = now()
        write_json(self.kg_nodes / f"{nid}.json", node)
        return {"node_id": nid, "path": str(self.kg_nodes / f"{nid}.json")}

    def get_node(self, node_id: str) -> dict:
        rec = read_json(self.kg_nodes / f"{node_id}.json")
        if not rec:
            raise ArchiveError(f"unknown kg node: {node_id}")
        return rec

    def link(self, src: str, dst: str, kind: str = "related_to", note: str = "") -> dict:
        self.get_node(src)
        self.get_node(dst)
        edge = {
            "schema_version": 1,
            "from": src,
            "to": dst,
            "type": kind,
            "note": note,
            "created_at": now(),
        }
        append_jsonl(self.kg_edges, edge)
        return edge

    def edges(self) -> list[dict]:
        return read_jsonl(self.kg_edges)

    def subgraph(self, node_id: str, depth: int = 1) -> dict:
        self.get_node(node_id)
        seen = {node_id}
        frontier = {node_id}
        edges: list[dict] = []
        for _ in range(max(depth, 0)):
            nxt = set()
            for edge in self.edges():
                if edge["from"] in frontier or edge["to"] in frontier:
                    edges.append(edge)
                    nxt.update((edge["from"], edge["to"]))
            frontier = nxt - seen
            seen |= nxt
        return {
            "root": node_id,
            "nodes": [self.get_node(n) for n in sorted(seen)],
            "edges": edges,
        }

    # ------------------------------------------------------------ layer 4
    def put_prop(self, prop: dict) -> dict:
        prid = prop.get("prop_id")
        if not prid:
            raise ArchiveError("proposition needs prop_id")
        prop.setdefault("schema_version", 1)
        prop.setdefault("node_ids", [])
        prop.setdefault("evidence", [])
        prop.setdefault("status", "active")
        prop["updated_at"] = now()
        for node_id in prop["node_ids"]:
            self.get_node(node_id)
        write_json(self.props / f"{prid}.json", prop)
        return {"prop_id": prid, "path": str(self.props / f"{prid}.json")}

    def get_prop(self, prop_id: str) -> dict:
        rec = read_json(self.props / f"{prop_id}.json")
        if not rec:
            raise ArchiveError(f"unknown proposition: {prop_id}")
        return rec

    def list_props(self, node_id: str | None = None) -> list[dict]:
        rows = [read_json(p) for p in sorted(self.props.glob("*.json"))]
        rows = [r for r in rows if r]
        if node_id:
            rows = [r for r in rows if node_id in r.get("node_ids", [])]
        return rows

    # ------------------------------------------------------------ context
    def context(self, node_id: str, checkpoint_id: str, limit: int = 5) -> dict:
        node = self.get_node(node_id)
        props = self.list_props(node_id)
        papers = self.list_papers(checkpoint_id)
        pushes = self.list_pushes(checkpoint_id)
        related = [
            e for e in self.edges() if node_id in (e["from"], e["to"])
        ]
        return {
            "node": node,
            "propositions": props,
            "archived_count": len(papers),
            "recent_papers": [
                {
                    "paper_id": p["paper_id"],
                    "title": p.get("title", ""),
                    "published": p.get("published"),
                }
                for p in papers[:limit]
            ],
            "recent_pushes": [
                {"push_id": p["push_id"], "title": p.get("title", "")}
                for p in pushes[:limit]
            ],
            "related_edges": related,
        }

    # ------------------------------------------------------------ apply
    def apply_proposal(self, push_id: str, proposal_id: str) -> dict:
        push = self.get_push(push_id)
        proposal = next(
            (p for p in push.get("proposals", []) if p.get("proposal_id") == proposal_id),
            None,
        )
        if not proposal:
            raise ArchiveError(f"proposal {proposal_id} not found in push {push_id}")
        return self._apply(proposal)

    def _apply(self, proposal: dict) -> dict:
        kind = proposal.get("kind")
        target_id = proposal.get("target_id")
        value = proposal.get("diff", {}).get("value", {})

        if kind == "add_evidence":
            prop = self.get_prop(target_id)
            entry = {
                "paper_id": value.get("paper_id"),
                "push_id": proposal.get("push_id"),
                "note": value.get("note", ""),
            }
            if not any(e.get("paper_id") == entry["paper_id"] for e in prop["evidence"]):
                prop["evidence"].append(entry)
                write_json(self.props / f"{target_id}.json", {**prop, "updated_at": now()})
        elif kind == "add_alias":
            node = self.get_node(target_id)
            alias = value if isinstance(value, str) else value.get("alias")
            if alias and alias not in node["aliases"]:
                node["aliases"].append(alias)
                write_json(
                    self.kg_nodes / f"{target_id}.json",
                    {**node, "updated_at": now()},
                )
        elif kind == "add_proposition":
            prop_id = value.get("prop_id") or stable_id(
                "prop", proposal.get("push_id", ""), value.get("text", "")
            )
            self.put_prop(
                {
                    "prop_id": prop_id,
                    "text": value.get("text", ""),
                    "node_ids": value.get("node_ids", []),
                    "evidence": [
                        {
                            "paper_id": value.get("paper_id"),
                            "push_id": proposal.get("push_id"),
                            "note": value.get("note", ""),
                        }
                    ],
                }
            )
            target_id = prop_id
        elif kind == "update_summary":
            text = value if isinstance(value, str) else value.get("text", "")
            if proposal.get("target_type") == "proposition":
                prop = self.get_prop(target_id)
                write_json(
                    self.props / f"{target_id}.json",
                    {**prop, "text": text, "updated_at": now()},
                )
            else:
                node = self.get_node(target_id)
                write_json(
                    self.kg_nodes / f"{target_id}.json",
                    {**node, "summary": text, "updated_at": now()},
                )
        else:
            raise ArchiveError(f"unknown proposal kind: {kind}")

        record = {
            "schema_version": 1,
            "proposal_id": proposal.get("proposal_id"),
            "push_id": proposal.get("push_id"),
            "kind": kind,
            "target_id": target_id,
            "applied_at": now(),
            "status": "applied",
        }
        write_json(self.applied / f"{proposal.get('proposal_id')}.json", record)
        return record

    def apply_decisions(self, pending_dir: Path, decisions_path: Path) -> dict:
        pending_dir = Path(pending_dir)
        decisions = read_jsonl(Path(decisions_path))
        applied, rejected, skipped = [], [], []
        done = {
            r["proposal_id"]
            for r in read_jsonl(self.index / "decisions_applied.jsonl")
            if r.get("proposal_id")
        }
        for decision in decisions:
            proposal_id = decision.get("proposal_id")
            if not proposal_id:
                continue
            if proposal_id in done:
                skipped.append(proposal_id)
                continue
            if decision.get("decision") == "reject":
                record = {
                    "schema_version": 1,
                    "proposal_id": proposal_id,
                    "status": "rejected",
                    "at": now(),
                }
                write_json(self.applied / f"{proposal_id}.json", record)
                append_jsonl(self.index / "decisions_applied.jsonl", record)
                rejected.append(proposal_id)
                continue
            proposal = read_json(pending_dir / f"{proposal_id}.json")
            if not proposal:
                skipped.append(proposal_id)
                continue
            try:
                record = self._apply(proposal)
            except ArchiveError:
                skipped.append(proposal_id)
                continue
            append_jsonl(self.index / "decisions_applied.jsonl", record)
            applied.append(proposal_id)
        return {"applied": applied, "rejected": rejected, "skipped": skipped}

    # ------------------------------------------------------------ stats
    def stats(self) -> dict:
        return {
            "papers": len(list(self.raw.glob("*.json"))),
            "pushes": len(list(self.pushes.glob("*.json"))),
            "kg_nodes": len(list(self.kg_nodes.glob("*.json"))),
            "kg_edges": len(read_jsonl(self.kg_edges)),
            "propositions": len(list(self.props.glob("*.json"))),
            "applied": len(list(self.applied.glob("*.json"))),
        }

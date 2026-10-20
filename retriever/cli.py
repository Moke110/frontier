"""retriever CLI: plan -> candidates.jsonl."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import emit, paper_id, read_json, write_jsonl
from retriever.adapters import RetrieverError, fetch


def run(
    plan: dict,
    mode: str,
    fixtures: Path,
    checkpoint: str | None = None,
    check_window: bool = True,
) -> list[dict]:
    start = (plan.get("window") or {}).get("start")
    end = (plan.get("window") or {}).get("end")
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for query in plan.get("queries", []):
        if checkpoint and query.get("checkpoint_id") != checkpoint:
            continue
        for rank, paper in enumerate(fetch(query, mode, fixtures), start=1):
            key = (paper.get("source", ""), paper.get("source_id", ""))
            if key in seen:
                continue
            published = paper.get("published") or ""
            if check_window and start and end and published and not (start <= published <= end):
                continue
            seen.add(key)
            out.append(
                {
                    **paper,
                    "paper_id": paper_id(paper.get("source", "unknown"), paper.get("source_id", "")),
                    "checkpoint_id": query["checkpoint_id"],
                    "retrieval": {
                        "query_id": query["query_id"],
                        "checkpoint_id": query["checkpoint_id"],
                        "source": query["source"],
                        "rank_hint": rank,
                    },
                }
            )
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="retriever", description=__doc__)
    parser.add_argument("--home", help="data root (default: $KL_HOME or ~/knowledge-loop)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fetch")
    p.add_argument("--plan", required=True)
    p.add_argument("--out", required=True, help="candidates.jsonl path")
    p.add_argument("--source", choices=["fixture", "live"], default="fixture")
    p.add_argument("--fixtures", default="fixtures/papers")
    p.add_argument("--checkpoint")
    p.add_argument("--no-window", action="store_true", help="do not filter by publication window")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plan = read_json(Path(args.plan))
    if not plan:
        print(json.dumps({"ok": False, "error": f"no plan at {args.plan}"}), file=sys.stderr)
        return 1
    try:
        rows = run(
            plan,
            args.source,
            Path(args.fixtures),
            args.checkpoint,
            check_window=not args.no_window,
        )
    except RetrieverError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 3
    if not rows:
        print(json.dumps({"ok": False, "reason": "no candidates"}), file=sys.stderr)
        return 2
    write_jsonl(Path(args.out), rows)
    emit(
        {
            "ok": True,
            "out": args.out,
            "count": len(rows),
            "by_checkpoint": {
                cp: sum(1 for r in rows if r["checkpoint_id"] == cp)
                for cp in sorted({r["checkpoint_id"] for r in rows})
            },
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

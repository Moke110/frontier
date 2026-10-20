"""archive CLI — the only writer of $KL_HOME/archive."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from archive.store import Archive, ArchiveError
from common import emit, home, read_json


def _payload(args) -> dict:
    if getattr(args, "json", None):
        if args.json == "-":
            return json.load(sys.stdin)
        if args.json.startswith("@"):
            return read_json(Path(args.json[1:]))
        return json.loads(args.json)
    if getattr(args, "file", None):
        if args.file == "-":
            return json.load(sys.stdin)
        return read_json(Path(args.file))
    raise SystemExit("provide --json <json|@file|-> or --file <path>")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="archive", description=__doc__)
    parser.add_argument("--home", help="data root (default: $KL_HOME or ~/knowledge-loop)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create layer directories")
    sub.add_parser("reindex", help="rebuild indexes from files")

    p = sub.add_parser("add-paper", help="store a paper (dedupe by source:source_id)")
    p.add_argument("--json")
    p.add_argument("--file")

    p = sub.add_parser("get-paper")
    p.add_argument("paper_id")

    p = sub.add_parser("list-papers")
    p.add_argument("--checkpoint")

    p = sub.add_parser("add-push", help="store a generated push")
    p.add_argument("--json")
    p.add_argument("--file")

    p = sub.add_parser("get-push")
    p.add_argument("push_id")

    p = sub.add_parser("list-pushes")
    p.add_argument("--checkpoint")

    p = sub.add_parser("kg-put-node")
    p.add_argument("--json")
    p.add_argument("--file")

    p = sub.add_parser("kg-get")
    p.add_argument("node_id")

    p = sub.add_parser("kg-link")
    p.add_argument("--from", dest="src", required=True)
    p.add_argument("--to", dest="dst", required=True)
    p.add_argument("--type", default="related_to")
    p.add_argument("--note", default="")

    p = sub.add_parser("kg-subgraph")
    p.add_argument("node_id")
    p.add_argument("--depth", type=int, default=1)

    p = sub.add_parser("prop-put")
    p.add_argument("--json")
    p.add_argument("--file")

    p = sub.add_parser("prop-get")
    p.add_argument("prop_id")

    p = sub.add_parser("prop-list")
    p.add_argument("--node")

    p = sub.add_parser("context", help="aggregate KG + propositions + history for writer")
    p.add_argument("--node", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--limit", type=int, default=5)

    p = sub.add_parser("apply-proposal")
    p.add_argument("--push-id", required=True)
    p.add_argument("--proposal-id", required=True)

    p = sub.add_parser("apply-decisions", help="apply approved publisher decisions")
    p.add_argument("--pending-dir", required=True)
    p.add_argument("--decisions", required=True)

    sub.add_parser("stats")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = Archive(home(args.home))
    try:
        if args.cmd == "init":
            emit(store.init())
        elif args.cmd == "reindex":
            emit(store.reindex())
        elif args.cmd == "add-paper":
            emit(store.add_paper(_payload(args)))
        elif args.cmd == "get-paper":
            emit(store.get_paper(args.paper_id))
        elif args.cmd == "list-papers":
            emit(store.list_papers(args.checkpoint))
        elif args.cmd == "add-push":
            emit(store.add_push(_payload(args)))
        elif args.cmd == "get-push":
            emit(store.get_push(args.push_id))
        elif args.cmd == "list-pushes":
            emit(store.list_pushes(args.checkpoint))
        elif args.cmd == "kg-put-node":
            emit(store.put_node(_payload(args)))
        elif args.cmd == "kg-get":
            emit(store.get_node(args.node_id))
        elif args.cmd == "kg-link":
            emit(store.link(args.src, args.dst, args.type, args.note))
        elif args.cmd == "kg-subgraph":
            emit(store.subgraph(args.node_id, args.depth))
        elif args.cmd == "prop-put":
            emit(store.put_prop(_payload(args)))
        elif args.cmd == "prop-get":
            emit(store.get_prop(args.prop_id))
        elif args.cmd == "prop-list":
            emit(store.list_props(args.node))
        elif args.cmd == "context":
            emit(store.context(args.node, args.checkpoint, args.limit))
        elif args.cmd == "apply-proposal":
            emit(store.apply_proposal(args.push_id, args.proposal_id))
        elif args.cmd == "apply-decisions":
            emit(store.apply_decisions(Path(args.pending_dir), Path(args.decisions)))
        elif args.cmd == "stats":
            emit(store.stats())
        else:  # pragma: no cover
            raise ArchiveError(f"unknown command {args.cmd}")
    except ArchiveError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

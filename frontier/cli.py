"""frontier CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import emit, home, write_json
from frontier.model import FrontierError, plan, record, show, validate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="frontier", description=__doc__)
    parser.add_argument("--home", help="data root (default: $KL_HOME or ~/knowledge-loop)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("validate", help="check every knowledge card has its four fields")
    sub.add_parser("show")

    p = sub.add_parser("plan", help="emit retrieval queries")
    p.add_argument("--date", help="end date, default today")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--source", action="append", choices=["arxiv", "europepmc"])
    p.add_argument("--out", help="write plan JSON here (also printed)")

    p = sub.add_parser("record", help="record one rating against a knowledge card")
    p.add_argument("--card", "--checkpoint", dest="checkpoint", required=True)
    p.add_argument("--verdict", required=True, choices=["irrelevant", "ok", "great"])
    p.add_argument("--pushed", action="store_true", help="count this as a pushed card")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = home(args.home)
    try:
        if args.cmd == "validate":
            emit(validate(root))
        elif args.cmd == "show":
            emit(show(root))
        elif args.cmd == "plan":
            sources = tuple(args.source) if args.source else ("arxiv", "europepmc")
            result = plan(root, args.date, args.days, args.limit, sources)
            if args.out:
                write_json(Path(args.out), result)
            emit(result)
        elif args.cmd == "record":
            emit(record(root, args.checkpoint, args.verdict, args.pushed))
        else:  # pragma: no cover
            raise FrontierError(f"unknown command {args.cmd}")
    except FrontierError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

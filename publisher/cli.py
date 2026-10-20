"""publisher CLI: Feishu push, ratings, approvals."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import emit, home, read_json
from publisher.cards import build_rating_card
from publisher.service import listen, replay, send_rating
from publisher.store import PublisherStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="publisher", description=__doc__)
    parser.add_argument("--home", help="data root (default: $KL_HOME or ~/knowledge-loop)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("send", help="send one push as a rating card")
    p.add_argument("--push", required=True)
    p.add_argument("--to", required=True, help="open_id (ou_...)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--as", dest="identity", default="bot", choices=["bot", "user"])

    p = sub.add_parser("preview", help="print the card JSON, send nothing")
    p.add_argument("--push", required=True)

    p = sub.add_parser("ingest", help="replay card.action.trigger NDJSON offline")
    p.add_argument("--events", required=True)
    p.add_argument("--offline", action="store_true", help="do not call Feishu (write outbox)")
    p.add_argument("--as", dest="identity", default="bot", choices=["bot", "user"])

    p = sub.add_parser("listen", help="consume real card callbacks")
    p.add_argument("--max-events", type=int, default=1)
    p.add_argument("--timeout", default="10m")
    p.add_argument("--as", dest="identity", default="bot", choices=["bot", "user"])

    sub.add_parser("pending")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = home(args.home)
    try:
        if args.cmd == "send":
            push = read_json(Path(args.push))
            if not push:
                raise ValueError(f"no push at {args.push}")
            emit(send_rating(root, push, args.to, args.dry_run, args.identity))
        elif args.cmd == "preview":
            push = read_json(Path(args.push))
            if not push:
                raise ValueError(f"no push at {args.push}")
            emit(build_rating_card(push))
        elif args.cmd == "ingest":
            for result in replay(root, Path(args.events), args.offline, args.identity):
                result.pop("approval_card", None)
                emit(result)
        elif args.cmd == "listen":
            return listen(root, args.identity, args.max_events, args.timeout)
        elif args.cmd == "pending":
            emit(PublisherStore(root).pending_proposals())
        else:  # pragma: no cover
            raise ValueError(args.cmd)
    except (ValueError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

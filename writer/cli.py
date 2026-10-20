"""writer CLI: agent task packets, validation, and a heuristic fallback.

Primary flow (agent-driven):
  writer task  -> agent writes push JSON -> writer check -> archive add-push
Fallback (offline / tests):
  writer write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import emit, home, read_json, today, write_json
from writer.model import write
from writer.tasks import build_task, validate as validate_outbox


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="writer", description=__doc__)
    parser.add_argument("--home", help="data root (default: $KL_HOME or ./data)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("write", help="heuristic writer (fallback, no agent)")
    p.add_argument("--selection", required=True)
    p.add_argument("--out", required=True, help="outbox directory (not archive)")
    p.add_argument("--date")

    p = sub.add_parser("task", help="build an agent writing packet")
    p.add_argument("--selection", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--date")

    p = sub.add_parser("check", help="validate agent-written pushes")
    p.add_argument("--task", required=True)
    p.add_argument("--outbox", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = home(args.home)
    try:
        if args.cmd == "write":
            selection = read_json(Path(args.selection))
            if not selection:
                raise ValueError(f"no selection at {args.selection}")
            result = write(selection, root, Path(args.out), args.date)
            emit(
                {
                    "ok": True,
                    "count": result["count"],
                    "out_dir": result["out_dir"],
                    "pushes": [
                        {
                            "push_id": p["push_id"],
                            "title": p["title"],
                            "proposals": len(p.get("proposals", [])),
                            "path": str(Path(result["out_dir"]) / "pushes" / f"{p['push_id']}.json"),
                        }
                        for p in result["pushes"]
                    ],
                }
            )
        elif args.cmd == "task":
            selection = read_json(Path(args.selection))
            if not selection:
                raise ValueError(f"no selection at {args.selection}")
            task = build_task(root, selection, args.date or selection.get("date") or today())
            write_json(Path(args.out), task)
            emit(
                {
                    "ok": True,
                    "out": args.out,
                    "items": len(task["items"]),
                    "proposal_kinds": list(task["proposal_kinds"]),
                }
            )
        elif args.cmd == "check":
            task = read_json(Path(args.task))
            if not task:
                raise ValueError(f"no task at {args.task}")
            result = validate_outbox(task, Path(args.outbox))
            emit(result)
            return 0 if result["ok"] else 1
        else:  # pragma: no cover
            raise ValueError(args.cmd)
    except (ValueError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

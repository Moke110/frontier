"""CLI: ``python -m initial_build.cli apply --draft drafts/initial-build/<theme>``."""

from __future__ import annotations

import argparse

from common import emit, home
from initial_build.build import apply, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="initial_build", description=__doc__)
    parser.add_argument("--home", help="data root (default: $KL_HOME or ~/knowledge-loop)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("apply", help="validate then write a draft into archive")
    p.add_argument("--draft", required=True, help="directory with cards/propositions/sources.jsonl")
    p.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    report = apply(home(args.home), args.draft, dry_run=args.dry_run)
    emit(summary(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

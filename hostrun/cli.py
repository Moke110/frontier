"""hostrun CLI: the entry points a host agent calls.

    python -m hostrun.cli install check|status|report|record
    python -m hostrun.cli kb attach|create|create-tables|verify|initial-confirm
    python -m hostrun.cli feedback setup|sync|status|submit|process|rebuild|correct
    python -m hostrun.cli run --intent daily|feedback|maintenance [--finish ok|error]
    python -m hostrun.cli schedules plan|confirm|status
    python -m hostrun.cli audit run|streak
    python -m hostrun.cli executor status|handover
    python -m hostrun.cli status

Every command is bounded and exits. Nothing installs a service, edits PATH or
starts a background listener; the host's own scheduler calls ``run``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import emit, home, read_json
from hostrun import audit as audit_mod
from hostrun import executor, feedback, install, intents, kb, schedules
from hostrun.base import HostRunError


def _host_declaration(args) -> dict | None:
    if not args.host_product:
        return None
    return {
        "product": args.host_product,
        "version": args.host_version or "",
        "mode": args.host_mode or "",
        "local_execution": bool(args.host_local_execution),
        "schedules": bool(args.host_schedules),
        "permissions": [p for p in (args.permissions or "").split(",") if p.strip()],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hostrun", description=__doc__)
    parser.add_argument("--home", help="data root (default: $KL_HOME or ~/knowledge-loop)")
    parser.add_argument("--offline", action="store_true", help="use JSON Base/Drive fixtures")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ------------------------------------------------------------------ install
    p = sub.add_parser("install", help="installation probes, progress and report")
    isub = p.add_subparsers(dest="action", required=True)
    c = isub.add_parser("check", help="run every offline-checkable probe")
    c.add_argument("--repo")
    c.add_argument("--lark-cli", dest="lark_cli")
    c.add_argument("--python", dest="python_path")
    c.add_argument("--timezone", dest="timezone_name")
    c.add_argument("--host-product")
    c.add_argument("--host-version")
    c.add_argument("--host-mode")
    c.add_argument("--host-local-execution", action="store_true")
    c.add_argument("--host-schedules", action="store_true")
    c.add_argument("--permissions", help="comma separated granted scopes")
    isub.add_parser("status")
    r = isub.add_parser("report")
    r.add_argument("--out")
    rec = isub.add_parser("record")
    rec.add_argument("--step", required=True, choices=install.STEPS)
    rec.add_argument("--status", required=True, choices=install.STATE_STATUSES)
    rec.add_argument("--note", default="")
    rec.add_argument("--evidence", help="JSON object")

    # ----------------------------------------------------------------------- kb
    p = sub.add_parser("kb", help="knowledge base create / attach / verify")
    ksub = p.add_subparsers(dest="action", required=True)
    a = ksub.add_parser("attach", help="connect an existing base by link")
    a.add_argument("--link", required=True)
    a.add_argument("--base-url")
    c = ksub.add_parser("create", help="create tables in an empty base")
    c.add_argument("--link", required=True)
    c.add_argument("--name", default="")
    c.add_argument("--dry-run", action="store_true")
    t = ksub.add_parser("create-tables", help="add missing tables to the configured base")
    t.add_argument("--dry-run", action="store_true")
    v = ksub.add_parser("verify", help="report structure and data counts")
    v.add_argument("--expect-empty", action="store_true")
    i = ksub.add_parser("initial-confirm", help="record the confirmed initial themes")
    i.add_argument("--themes", required=True, help="JSON file with the proposed themes")
    i.add_argument("--yes", action="store_true", help="the user confirmed these themes")
    i.add_argument("--note", default="")
    ksub.add_parser("initial-status")

    # ----------------------------------------------------------------- feedback
    p = sub.add_parser("feedback", help="persistent questions / submissions / results")
    fsub = p.add_subparsers(dest="action", required=True)
    s = fsub.add_parser("setup")
    s.add_argument("--dry-run", action="store_true")
    fsub.add_parser("sync")
    fsub.add_parser("status")
    fsub.add_parser("process")
    fsub.add_parser("rebuild")
    sub_p = fsub.add_parser("submit", help="submit a rating or decision (explicit act)")
    sub_p.add_argument("--item", required=True)
    sub_p.add_argument("--verdict", choices=["irrelevant", "ok", "great"])
    sub_p.add_argument("--decision", choices=["agree_all", "reject_all", "adopt", "keep_previous"])
    sub_p.add_argument("--comment", default="")
    corr = fsub.add_parser("correct", help="record a correction request for a processed question")
    corr.add_argument("--item", required=True)
    corr.add_argument("--reason", required=True)

    # ---------------------------------------------------------------------- run
    p = sub.add_parser("run", help="one bounded run for one intent")
    p.add_argument("--intent", required=True, choices=intents.INTENTS)
    p.add_argument("--repo")
    p.add_argument("--host", help="executor id (default: declared host product)")
    p.add_argument("--minutes", type=int, default=executor.DEFAULT_MINUTES)
    p.add_argument("--finish", help="ok|error — record the pipeline outcome")
    p.add_argument("--date", help="calendar date for maintenance/coalescing (default today)")

    # ---------------------------------------------------------------- schedules
    p = sub.add_parser("schedules", help="schedule spec for the host scheduler")
    ssub = p.add_subparsers(dest="action", required=True)
    pl = ssub.add_parser("plan")
    pl.add_argument("--timezone", dest="timezone_name")
    pl.add_argument("--daily", default=schedules.DEFAULT_DAILY)
    pl.add_argument("--maintenance", default=schedules.DEFAULT_MAINTENANCE)
    pl.add_argument("--feedback-minute", type=int, default=schedules.DEFAULT_FEEDBACK_MINUTE)
    cf = ssub.add_parser("confirm")
    cf.add_argument("--timezone", dest="timezone_name")
    cf.add_argument("--daily", default=schedules.DEFAULT_DAILY)
    cf.add_argument("--maintenance", default=schedules.DEFAULT_MAINTENANCE)
    cf.add_argument("--feedback-minute", type=int, default=schedules.DEFAULT_FEEDBACK_MINUTE)
    cf.add_argument("--yes", action="store_true", help="the user confirmed timezone and enablement")
    cf.add_argument("--host-created", action="store_true", help="the host actually created the tasks")
    ssub.add_parser("status")

    # -------------------------------------------------------------------- audit
    p = sub.add_parser("audit", help="existing data audit against the migration baseline")
    asub = p.add_subparsers(dest="action", required=True)
    ar = asub.add_parser("run")
    ar.add_argument("--baseline", help="baseline manifest (JSONL) of the 174 originals")
    ar.add_argument("--record", action="store_true", help="persist today's result for the streak")
    ar.add_argument("--date")
    asub.add_parser("streak")

    # ----------------------------------------------------------------- executor
    p = sub.add_parser("executor", help="single-executor lease")
    esub = p.add_subparsers(dest="action", required=True)
    esub.add_parser("status")
    h = esub.add_parser("handover")
    h.add_argument("--to", required=True)
    h.add_argument("--from", dest="from_host")
    h.add_argument("--force", action="store_true")

    sub.add_parser("status", help="one snapshot of executor, queue, feedback, schedules")
    return parser


def _normalize(argv: list[str]) -> list[str]:
    """Accept ``--home`` / ``--offline`` after the subcommand.

    argparse only knows them as global options, so ``run --home X --intent daily``
    used to die with "unrecognized arguments". Generated schedule commands and
    hand-typed ones both work now, and the last value wins.
    """
    home: list[str] = []
    offline = False
    rest: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--home" and index + 1 < len(argv):
            home.append(argv[index + 1])
            index += 2
            continue
        if arg.startswith("--home="):
            home.append(arg.split("=", 1)[1])
            index += 1
            continue
        if arg == "--offline":
            offline = True
            index += 1
            continue
        rest.append(arg)
        index += 1
    prefix: list[str] = []
    if home:
        prefix += ["--home", home[-1]]
    if offline:
        prefix.append("--offline")
    return [*prefix, *rest]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(_normalize(list(sys.argv[1:] if argv is None else argv)))
    root = home(args.home)
    offline = bool(args.offline)
    try:
        code, payload = _dispatch(args, root, offline)
    except HostRunError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    if payload is not None:
        emit(payload)
    return code


def _dispatch(args, root: Path, offline: bool) -> tuple[int, dict | None]:
    if args.cmd == "install":
        return _install(args, root)
    if args.cmd == "kb":
        return _kb(args, root, offline)
    if args.cmd == "feedback":
        return _feedback(args, root, offline)
    if args.cmd == "run":
        result = intents.run(
            root,
            args.intent,
            repo=args.repo,
            host=args.host,
            minutes=args.minutes,
            offline=offline,
            date=args.date,
            finish=args.finish,
        )
        return (0 if result.get("ok") else 1), result
    if args.cmd == "schedules":
        return _schedules(args, root)
    if args.cmd == "audit":
        return _audit(args, root, offline)
    if args.cmd == "executor":
        if args.action == "status":
            return 0, executor.status(root)
        result = executor.handover(
            root, to_host=args.to, from_host=args.from_host, force=args.force
        )
        return (0 if result.get("ok") else 1), result
    if args.cmd == "status":
        return 0, intents.status(root)
    raise HostRunError(f"unknown command {args.cmd}")


def _install(args, root: Path) -> tuple[int, dict]:
    if args.action == "check":
        result = install.check(
            root,
            repo=args.repo,
            host=_host_declaration(args),
            lark_cli=args.lark_cli,
            python=args.python_path,
            timezone_name=args.timezone_name,
        )
        return (0 if result["ok"] else 1), result
    if args.action == "status":
        return 0, install.summary(root)
    if args.action == "report":
        report = install.report(root)
        if getattr(args, "out", None):
            from common import write_json

            write_json(Path(args.out), report)
        return (0 if report["ok"] else 1), report
    evidence = json.loads(args.evidence) if args.evidence else {}
    install.record(root, args.step, args.status, note=args.note, evidence=evidence)
    return 0, install.summary(root)


def _kb(args, root: Path, offline: bool) -> tuple[int, dict]:
    from hostrun.base import base_client

    client = base_client(root, offline=offline) if offline else None
    if args.action == "attach":
        result = kb.attach(root, args.link, base_url=args.base_url, client=client)
        return (0 if result.get("ok") else 1), result
    if args.action == "create":
        result = kb.create_empty(
            root, args.link, client=client, dry_run=args.dry_run, name=args.name
        )
        return (0 if result.get("ok") else 1), result
    if args.action == "create-tables":
        result = kb.create_tables(root, client=client, dry_run=args.dry_run)
        return 0, result
    if args.action == "verify":
        result = kb.verify(root, client=client, expect_empty=args.expect_empty)
        return (0 if result.get("ok") else 1), result
    if args.action == "initial-confirm":
        themes = read_json(Path(args.themes)) or []
        if isinstance(themes, dict):
            themes = themes.get("themes") or []
        result = kb.record_initial_confirmation(
            root, themes, confirmed_by_user=args.yes, note=args.note
        )
        return (0 if result.get("ok") else 1), result
    return 0, kb.initial_confirmed(root)


def _feedback(args, root: Path, offline: bool) -> tuple[int, dict]:
    from hostrun.base import base_client

    client = base_client(root, offline=offline) if offline else None
    if args.action == "setup":
        return 0, feedback.setup(root, client=client, dry_run=args.dry_run)
    if args.action == "sync":
        return 0, feedback.sync(root, client=client)
    if args.action == "status":
        return 0, feedback.status(root, client=client)
    if args.action == "process":
        result = feedback.process(root, client=client)
        return (0 if result.get("ok") else 1), result
    if args.action == "rebuild":
        result = feedback.rebuild(root, client=client)
        return (0 if result.get("ok") else 1), result
    if args.action == "submit":
        answer = {}
        if args.verdict:
            answer["verdict"] = args.verdict
        if args.decision:
            answer["decision"] = args.decision
        result = feedback.submit(
            root, args.item, answer, comment=args.comment, client=client
        )
        return (0 if result.get("ok") else 1), result
    result = feedback.correct(root, args.item, args.reason, client=client)
    return (0 if result.get("ok") else 1), result


def _schedules(args, root: Path) -> tuple[int, dict]:
    if args.action == "plan":
        return 0, schedules.plan(
            root,
            timezone_name=args.timezone_name,
            daily=args.daily,
            maintenance=args.maintenance,
            feedback_minute=args.feedback_minute,
        )
    if args.action == "confirm":
        result = schedules.confirm(
            root,
            timezone_name=args.timezone_name,
            daily=args.daily,
            maintenance=args.maintenance,
            feedback_minute=args.feedback_minute,
            confirmed_by_user=args.yes,
            host_created=args.host_created,
        )
        return (0 if result.get("ok") else 1), result
    return 0, schedules.status(root)


def _audit(args, root: Path, offline: bool) -> tuple[int, dict]:
    if args.action == "streak":
        return 0, audit_mod.streak(root)
    report = audit_mod.audit(root, baseline=args.baseline, offline=offline, date=args.date)
    if args.record and report.get("counts"):
        reported = audit_mod.record(root, report, day=args.date)
        report["recorded"] = reported
    return (0 if report.get("ok") else 1), report


if __name__ == "__main__":
    raise SystemExit(main())

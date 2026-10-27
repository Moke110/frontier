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
from hostrun import cleanup as cleanup_mod
from hostrun import executor, facilities, feedback, initialize, install, intents, kb, lark, schedules, smoke
from hostrun import workspace as workspace_mod
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
    c.add_argument("--workspace-root", help="installation workspace recorded by install workspace")
    isub.add_parser("status")
    r = isub.add_parser("report")
    r.add_argument("--out")
    rec = isub.add_parser("record")
    rec.add_argument("--step", required=True, choices=install.STEPS)
    rec.add_argument("--status", required=True, choices=install.STATE_STATUSES)
    rec.add_argument("--note", default="")
    rec.add_argument("--evidence", help="JSON object")

    # ------------------------------------------------------- install workspace
    w = isub.add_parser("workspace", help="acquire code and create the data root")
    w.add_argument("--root", required=True, help="installation workspace (host project folder)")
    w.add_argument("--repo-url", default=workspace_mod.DEFAULT_REPO_URL)
    w.add_argument("--code-dir", default=workspace_mod.DEFAULT_CODE_DIRNAME)
    w.add_argument("--data-dir", default=workspace_mod.DEFAULT_DATA_DIRNAME)
    w.add_argument("--dry-run", action="store_true")
    t = isub.add_parser("toolchain", help="resolve uv outside the workspace, then build the data-root environment")
    t.add_argument("--root", required=True)
    t.add_argument("--uv", dest="uv_path")
    t.add_argument("--python-version", default=workspace_mod.DEFAULT_PYTHON)
    t.add_argument("--clear", action="store_true", help="rebuild a missing or broken data-root interpreter")
    sk = isub.add_parser("skill", help="register the frontier-run launcher for the host")
    sk.add_argument("--root", required=True)
    sk.add_argument("--target", required=True, help="host skill directory for frontier-run")
    sk.add_argument("--dry-run", action="store_true")
    loc = isub.add_parser("locate", help="print the nearest workspace record")
    loc.add_argument("--start")

    # ------------------------------------------------------------------ facilities
    p = sub.add_parser("facilities", help="create or attach the Feishu Base, tables and folders")
    fsub = p.add_subparsers(dest="action", required=True)
    fp = fsub.add_parser("plan", help="show the confirmed names and defaults")
    fp.add_argument("--base-name")
    fp.add_argument("--table", action="append", default=[], metavar="KEY=NAME")
    fp.add_argument("--folder", action="append", default=[], metavar="KEY=NAME")
    fc = fsub.add_parser("create", help="create the Base and all tables/folders")
    fc.add_argument("--yes", action="store_true", help="the user confirmed the names")
    fc.add_argument("--base-name")
    fc.add_argument("--table", action="append", default=[], metavar="KEY=NAME")
    fc.add_argument("--folder", action="append", default=[], metavar="KEY=NAME")
    fc.add_argument("--dry-run", action="store_true")
    fa = fsub.add_parser("attach", help="connect an existing Base by link")
    fa.add_argument("--link", required=True)
    fa.add_argument("--yes", action="store_true", help="the user confirmed the names")
    fa.add_argument("--base-name")
    fa.add_argument("--table", action="append", default=[], metavar="KEY=NAME")
    fa.add_argument("--folder", action="append", default=[], metavar="KEY=NAME")
    fa.add_argument("--create-missing", action="store_true")
    fsub.add_parser("status")
    fr = fsub.add_parser("rename", help="rename a table's display name (ID unchanged)")
    fr.add_argument("--key", required=True)
    fr.add_argument("--name", required=True)

    # ---------------------------------------------------------------------- smoke
    p = sub.add_parser("smoke", help="temporary keyword-driven acceptance test")
    ssub = p.add_subparsers(dest="action", required=True)
    st = ssub.add_parser("start", help="create the temporary card and test record")
    st.add_argument("--keyword", required=True)
    st.add_argument("--owner", default="")
    st.add_argument("--repo")
    st.add_argument("--yes", action="store_true", help="the user confirmed this test")
    sp = ssub.add_parser("plan", help="write a plan limited to the temporary card")
    sp.add_argument("--days", type=int, default=7)
    sp.add_argument("--out")
    ssub.add_parser("brief", help="the exact next actions for the host agent")
    ssub.add_parser("status")
    sr = ssub.add_parser("record", help="record one ordered step")
    sr.add_argument("--step", required=True, choices=smoke.STEPS)
    sr.add_argument("--evidence", help="JSON object")
    sr.add_argument("--item")
    sr.add_argument("--push")
    sr.add_argument("--message")
    sr.add_argument("--question")
    sr.add_argument("--verdict", choices=["irrelevant", "ok", "great"])
    sr.add_argument("--decision", choices=["agree_all", "adopt", "keep_previous", "reject_all"])
    sr.add_argument("--file", dest="file_ids", action="append", default=[],
                    help="uploaded file token; repeat for source and push files")
    sr.add_argument("--source", dest="source_id")
    sr.add_argument("--candidates", type=int,
                    help="retrieved: number of candidates returned by the real retrieval (>0)")
    sr.add_argument("--plan", dest="plan",
                    help="retrieved: path/reference of the temporary retrieval plan")
    sr.add_argument("--paper", dest="paper_ids", action="append", default=[],
                    help="written: selected paper id; repeat for each selected paper")
    sr.add_argument("--html", dest="html",
                    help="rendered: path of the rendered push html artifact")
    sv = ssub.add_parser("verify", help="read the Base and require the accepted change")
    sv.add_argument("--target-key", required=True, choices=["cards", "propositions", "evidence"])
    sv.add_argument("--target-id", required=True)
    sv.add_argument("--field", dest="fields", action="append", default=[],
                    help="read-back check as name=value; repeat for each adopted field "
                         "(legacy: --field <name> --expected <value>)")
    sv.add_argument("--expected", action="append", default=[],
                    help="legacy value paired with a bare --field <name>")
    sf = ssub.add_parser("fail", help="mark the test failed and keep it for cleanup")
    sf.add_argument("--reason", required=True)

    # -------------------------------------------------------------------- cleanup
    p = sub.add_parser("cleanup", help="delete the temporary test's artifacts and verify")
    csub = p.add_subparsers(dest="action", required=True)
    csub.add_parser("plan", help="list what would be deleted (read-only)")
    cr = csub.add_parser("run", help="delete recorded artifacts, then read back")
    cr.add_argument("--yes", action="store_true", help="the user confirmed this cleanup")
    cr.add_argument("--abort", action="store_true", help="clean a failed test; gate stays closed")
    csub.add_parser("status")

    # ----------------------------------------------------------------------- init
    p = sub.add_parser("init", help="formal knowledge-card initialization")
    isub = p.add_subparsers(dest="action", required=True)
    ii = isub.add_parser("intake", help="record PDFs, text, indexes and the user's requirements")
    ii.add_argument("--pdf", action="append", default=[])
    ii.add_argument("--text", action="append", default=[])
    ii.add_argument("--index", action="append", default=[])
    ii.add_argument("--requirements", required=True)
    ip = isub.add_parser("propose", help="validate the agent's candidate cards")
    ip.add_argument("--cards", required=True, help="JSON file with a card array")
    ip.add_argument("--rationale", default="")
    isub.add_parser("review")
    ic = isub.add_parser("confirm", help="record the user's confirmation")
    ic.add_argument("--yes", action="store_true")
    ic.add_argument("--note", default="")
    isub.add_parser("apply")
    ia = isub.add_parser("adopt-existing")
    ia.add_argument("--yes", action="store_true", help="the user confirmed keeping the existing library")
    isub.add_parser("retrieve")
    isub.add_parser("status")

    # ---------------------------------------------------------------------- lark
    p = sub.add_parser("lark", help="Lark CLI discovery, login guidance and access preflight")
    lsub = p.add_subparsers(dest="action", required=True)
    ld = lsub.add_parser("discover", help="report which lark-cli would be used")
    ld.add_argument("--root", required=True)
    ld.add_argument("--cli", dest="cli_path")
    li = lsub.add_parser("install", help="install @larksuite/cli privately under the workspace")
    li.add_argument("--root", required=True)
    li.add_argument("--registry")
    ll = lsub.add_parser("login", help="print the interactive login step (never faked)")
    ll.add_argument("--root", required=True)
    ll.add_argument("--as", dest="identity_name", default="user", choices=["user", "bot"])
    ll.add_argument("--cli", dest="cli_path")
    ll.add_argument("--device-code", help="finish a split-flow login after the user authorises")
    ls = lsub.add_parser("status", help="executable / identity / authorization / resources")
    ls.add_argument("--root", required=True)
    ls.add_argument("--cli", dest="cli_path")
    ls.add_argument("--required", default="base,drive,messages",
                    help="comma separated capabilities (base,drive,messages) or scope names")

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
    p.add_argument("--scheduled", action="store_true", help="set only by the host scheduler")
    p.add_argument("--task", help="host task id set by the host scheduler")
    p.add_argument("--proof", help="per-task proof embedded in the confirmed command")

    # ---------------------------------------------------------------- schedules
    p = sub.add_parser("schedules", help="two-task schedule spec for the host scheduler")
    ssub = p.add_subparsers(dest="action", required=True)
    pl = ssub.add_parser("plan")
    pl.add_argument("--timezone", dest="timezone_name")
    pl.add_argument("--daily", default=schedules.DEFAULT_DAILY)
    pl.add_argument("--feedback-minute", type=int, default=schedules.DEFAULT_FEEDBACK_MINUTE)
    cf = ssub.add_parser("confirm")
    cf.add_argument("--timezone", dest="timezone_name")
    cf.add_argument("--daily", default=schedules.DEFAULT_DAILY)
    cf.add_argument("--feedback-minute", type=int, default=schedules.DEFAULT_FEEDBACK_MINUTE)
    cf.add_argument("--yes", action="store_true", help="the user confirmed timezone and enablement")
    cf.add_argument("--host-created", action="store_true", help="the host actually created the tasks")
    cf.add_argument("--paused", action="store_true", help="confirm but keep the tasks disabled")
    cf.add_argument("--task-id", action="append", default=[], metavar="ID=HOST_TASK_ID")
    ssub.add_parser("status")
    pa = ssub.add_parser("pause")
    pa.add_argument("--yes", action="store_true")
    pa.add_argument("--reason", default="")
    re = ssub.add_parser("resume")
    re.add_argument("--yes", action="store_true")
    tr = ssub.add_parser("trigger", help="record one real scheduled run from the run log")
    tr.add_argument("--task", required=True)
    tr.add_argument("--at")
    tr.add_argument("--evidence")

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
            scheduled=args.scheduled,
            task=args.task,
            proof=args.proof,
        )
        return (0 if result.get("ok") else 1), result
    if args.cmd == "lark":
        return _lark(args, root)
    if args.cmd == "facilities":
        return _facilities(args, root, offline)
    if args.cmd == "smoke":
        return _smoke(args, root, offline)
    if args.cmd == "cleanup":
        return _cleanup(args, root, offline)
    if args.cmd == "init":
        return _init(args, root, offline)
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
    from common import ensure_dir
    from hostrun.base import update_config

    if args.action == "workspace":
        result = workspace_mod.acquire(
            args.root,
            repo_url=args.repo_url,
            code_dirname=args.code_dir,
            data_dirname=args.data_dir,
            dry_run=args.dry_run,
        )
        # A rejected layout has no safe data root to write into: report it and
        # leave the code checkout (and the data-root candidate inside it) alone.
        if not args.dry_run and result.get("layout_valid", True):
            data_root = Path(result["home"])
            ensure_dir(data_root / "install")
            install.record(
                data_root,
                "workspace",
                "ok" if result["ok"] else "blocked",
                note="代码与数据根已就绪" if result["ok"] else result.get("blocked", ""),
                evidence={
                    "root": result["root"],
                    "repo": result["repo"],
                    "home": result["home"],
                    "action": result["action"],
                    "commit": result.get("commit"),
                },
                recheck=True,
            )
            update_config(
                data_root,
                workspace={
                    "root": result["root"],
                    "repo": result["repo"],
                    "home": result["home"],
                    "repo_url": args.repo_url,
                },
                paths={"repo": result["repo"], "home": result["home"]},
            )
        return (0 if result["ok"] else 1), result

    if args.action == "toolchain":
        result = workspace_mod.toolchain(
            args.root,
            uv_path=args.uv_path,
            python_version=args.python_version,
            clear=args.clear,
        )
        record = workspace_mod.load_record(args.root)
        data_root = Path(record.get("home") or root)
        if not args.root or not record:
            return 1, result
        ensure_dir(data_root / "install")
        environment = result.get("environment") or {}
        install.record(
            data_root,
            "dependencies",
            "ok" if result["ok"] else "blocked",
            note=(
                "数据根私有 uv 与解释器可用，导入探针通过"
                if result["ok"]
                else (result.get("note") or "工具链未就绪")
            ),
            evidence={
                "uv": result.get("uv", {}).get("path"),
                "uv_source": result.get("uv", {}).get("source"),
                "python": environment.get("python"),
                "venv": environment.get("venv"),
                "repaired": environment.get("repaired"),
                "imports_ok": (environment.get("probe") or {}).get("ok"),
                "repair": result.get("repair"),
            },
            recheck=True,
        )
        if result["ok"]:
            update_config(
                data_root,
                paths={
                    "uv": result["uv"]["path"],
                    "python": environment["python"],
                    "venv": environment.get("venv", ""),
                },
            )
        return (0 if result["ok"] else 1), result

    if args.action == "skill":
        result = workspace_mod.register_skill(args.root, args.target, dry_run=args.dry_run)
        record = workspace_mod.load_record(args.root)
        data_root = Path(record.get("home") or root)
        if not args.dry_run:
            ensure_dir(data_root / "install")
            install.record(
                data_root,
                "skill",
                "ok" if result["ok"] else "blocked",
                note=(
                    f"入口 {result.get('skill')}"
                    if result["ok"]
                    else "；".join(result.get("problems") or [result.get("note", "")])
                ),
                evidence={
                    "skill": result.get("skill"),
                    "entry": result.get("entry"),
                    "references": result.get("references"),
                },
                recheck=True,
            )
            if result["ok"]:
                update_config(data_root, paths={"skill": result["skill"]})
        return (0 if result["ok"] else 1), result

    if args.action == "locate":
        record = workspace_mod.locate(args.start)
        if not record:
            return 1, {"ok": False, "reason": "workspace_not_found"}
        return 0, {**record, "status": workspace_mod.status(record["root"])}

    if args.action == "check":
        result = install.check(
            root,
            repo=args.repo,
            host=_host_declaration(args),
            lark_cli=args.lark_cli,
            python=args.python_path,
            timezone_name=args.timezone_name,
            workspace_root=args.workspace_root,
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


def _pairs(values: list[str]) -> dict:
    out = {}
    for item in values or []:
        if "=" not in item:
            raise HostRunError(f"参数需为 KEY=NAME：{item}")
        key, value = item.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def _name_overrides(args) -> dict:
    return {
        "base": args.base_name,
        "tables": _pairs(getattr(args, "table", [])),
        "folders": _pairs(getattr(args, "folder", [])),
    }


class _OfflineAdmin:
    """Local Base creator for ``--offline`` demos and tests; no tenant touched."""

    def __init__(self, home: Path, client):
        self.home = home
        self.client = client

    def resolve_title(self, title: str) -> dict:
        return {"matches": [], "count": 0}

    def create_base(self, name: str, *, table_name: str, fields: list[dict]) -> dict:
        table_id = self.client.create_table(table_name, fields)
        token = "basoffline"
        kb.register_base(
            self.home, token, base_url=f"https://example.feishu.cn/base/{token}", name=name
        )
        return {
            "base_token": token,
            "table_id": table_id,
            "url": f"https://example.feishu.cn/base/{token}",
            "name": name,
        }


def _offline_assets(home: Path):
    from library.offline import JsonBase, JsonDrive

    return JsonBase(home / "library" / "offline-base.json"), JsonDrive(
        home / "library" / "offline-drive.json"
    )


def _cli_bin(home: Path) -> str:
    from hostrun.base import load_config

    config = load_config(home)
    return str((config.get("paths") or {}).get("lark_cli") or "lark-cli")


def _facilities(args, root: Path, offline: bool) -> tuple[int, dict]:
    home = Path(root).expanduser().resolve()
    overrides = _name_overrides(args) if args.action in ("plan", "create", "attach") else {}
    if args.action == "plan":
        return 0, facilities.plan(home, overrides)

    client = None
    drive = None
    admin = None
    if offline:
        client, drive = _offline_assets(home)
        admin = _OfflineAdmin(home, client)

    if args.action == "create":
        if offline:
            # The offline Base has no pre-existing token; let the fake admin create it.
            result = facilities.create(
                home,
                names=overrides,
                confirmed=args.yes,
                admin=admin,
                client=client,
                drive=drive,
                dry_run=args.dry_run,
                cli_bin="lark-cli",
            )
        else:
            result = facilities.create(
                home,
                names=overrides,
                confirmed=args.yes,
                cli_bin=_cli_bin(home),
                dry_run=args.dry_run,
            )
        return (0 if result.get("ok") else 1), result

    if args.action == "attach":
        if not offline:
            from library.base import LarkBaseClient
            from library.drive import LarkDrive

            parsed = kb.parse_link(args.link)
            client = LarkBaseClient({"base_token": parsed["base_token"]}, bin=_cli_bin(home))
            drive = LarkDrive(bin=_cli_bin(home))
        result = facilities.attach(
            home,
            args.link,
            names=overrides,
            confirmed=args.yes,
            client=client,
            drive=drive,
            create_missing=args.create_missing,
            cli_bin=_cli_bin(home),
        )
        return (0 if result.get("ok") else 1), result

    if args.action == "rename":
        if client is None:
            from library.base import LarkBaseClient

            config = read_json(home / "knowledge" / "base.json") or {}
            client = LarkBaseClient(config, bin=_cli_bin(home))
        result = facilities.rename(home, args.key, args.name, client=client)
        return (0 if result.get("ok") else 1), result

    if client is None:
        from library.base import LarkBaseClient

        config = read_json(home / "knowledge" / "base.json") or {}
        client = LarkBaseClient(config, bin=_cli_bin(home)) if config.get("base_token") else None
    result = facilities.status(home, client=client)
    return (0 if result.get("ok") else 1), result


def _smoke(args, root: Path, offline: bool) -> tuple[int, dict]:
    from hostrun.base import base_client

    client = base_client(root, offline=True) if offline else None
    if args.action == "start":
        result = smoke.start(
            root,
            args.keyword,
            owner=args.owner,
            repo=args.repo,
            client=client,
            confirmed=args.yes,
        )
        return (0 if result.get("ok") else 1), result
    if args.action == "plan":
        result = smoke.plan(root, days=args.days, out=Path(args.out) if args.out else None)
        return 0, result
    if args.action == "brief":
        result = smoke.brief(root)
        return (0 if result.get("ok") else 1), result
    if args.action == "record":
        evidence = json.loads(args.evidence) if args.evidence else {}
        result = smoke.record(
            root,
            args.step,
            evidence=evidence,
            item=args.item,
            push=args.push,
            message=args.message,
            question=args.question,
            verdict=args.verdict,
            decision=args.decision,
            file_id=args.file_ids,
            source_id=args.source_id,
            candidates=args.candidates,
            plan=args.plan,
            papers=args.paper_ids,
            html=args.html,
        )
        return 0, result
    if args.action == "verify":
        fields = args.fields or []
        expecteds = args.expected or []
        if len(expecteds) > len(fields):
            raise HostRunError("--expected 数量多于 --field")
        checks: list[str] = []
        for index, raw in enumerate(fields):
            if "=" in raw:
                checks.append(raw)
            elif index < len(expecteds):
                checks.append(f"{raw}={expecteds[index]}")
            else:
                raise HostRunError(
                    f"--field {raw} 缺少对应 --expected；也可写成 --field name=value"
                )
        result = smoke.verify(
            root,
            target_key=args.target_key,
            target_id=args.target_id,
            checks=checks,
            client=client,
        )
        return (0 if result.get("ok") else 1), result
    if args.action == "fail":
        result = smoke.fail(root, args.reason)
        return 1, result
    return 0, smoke.status(root)


def _cleanup(args, root: Path, offline: bool) -> tuple[int, dict]:
    from hostrun.base import base_client

    client = base_client(root, offline=True) if offline else None
    if args.action == "plan":
        return 0, cleanup_mod.plan(root, client=client)
    if args.action == "status":
        state = smoke.load(root)
        return 0, {
            "ok": bool(state.get("cleaned_at")),
            "test_id": state.get("test_id"),
            "test_status": state.get("test_status") or state.get("status"),
            "cleaned_at": state.get("cleaned_at"),
            "cleanup": state.get("cleanup") or {},
        }
    drive = None
    if offline:
        from library.offline import JsonDrive

        drive = JsonDrive(root / "library" / "offline-drive.json")
    result = cleanup_mod.run(
        root,
        confirmed=args.yes,
        allow_failed=args.abort,
        client=client,
        drive=drive,
        lark_cli=_cli_bin(root),
    )
    return (0 if result.get("ok") else 1), result


def _init(args, root: Path, offline: bool) -> tuple[int, dict]:
    from hostrun.base import base_client

    client = base_client(root, offline=True) if offline else None
    if args.action == "intake":
        result = initialize.intake(
            root,
            pdfs=args.pdf,
            texts=args.text,
            indexes=args.index,
            requirements=args.requirements,
        )
        return 0, result
    if args.action == "propose":
        cards = read_json(Path(args.cards)) or []
        if isinstance(cards, dict):
            cards = cards.get("cards") or []
        return 0, initialize.propose(root, cards, rationale=args.rationale)
    if args.action == "review":
        return 0, initialize.review(root)
    if args.action == "confirm":
        result = initialize.confirm(root, confirmed_by_user=args.yes, note=args.note)
        return (0 if result.get("ok") else 1), result
    if args.action == "apply":
        result = initialize.apply_draft(root, client=client)
        return (0 if result.get("ok") else 1), result
    if args.action == "adopt-existing":
        result = initialize.adopt_existing(root, client=client, confirmed=args.yes)
        return (0 if result.get("ok") else 1), result
    if args.action == "retrieve":
        result = initialize.standard_retrieval(root)
        return (0 if result.get("ok") else 1), result
    return 0, initialize.status(root)


def _lark(args, root: Path) -> tuple[int, dict]:
    from common import ensure_dir
    from hostrun.base import load_config, update_config

    record = workspace_mod.load_record(args.root)
    data_root = Path(record.get("home") or root)
    if not args.root:
        return 1, {"ok": False, "note": "需要 --root 工作区"}
    config = load_config(data_root)
    recorded_cli = str((config.get("paths") or {}).get("lark_cli") or "")
    # The recorded absolute path is authoritative (ADR 0007); an explicit
    # --cli wins because the user is deliberately re-recording it.
    spec = getattr(args, "cli_path", None) or recorded_cli or None

    if args.action == "discover":
        found = lark.discover_cli(args.root, spec=spec, home=data_root)
        if found["ok"]:
            ensure_dir(data_root / "install")
            update_config(data_root, paths={"lark_cli": found["path"]})
        return (0 if found["ok"] else 1), found

    if args.action == "install":
        result = lark.install_cli(args.root, registry=args.registry)
        ensure_dir(data_root / "install")
        install.record(
            data_root,
            "lark_cli",
            "ok" if result["ok"] else "blocked",
            note=(
                f"已私有安装并解析 {result.get('path')}"
                if result["ok"]
                else result.get("note", "安装失败")
            ),
            evidence={
                "path": result.get("path"),
                "source": result.get("source"),
                "version": result.get("version"),
            },
            recheck=True,
        )
        if result["ok"]:
            update_config(data_root, paths={"lark_cli": result["path"]})
        return (0 if result["ok"] else 1), result

    if args.action == "login":
        found = lark.discover_cli(
            args.root, spec=spec, home=data_root
        )
        if args.device_code:
            result = lark.complete_login(
                found.get("path") if found["ok"] else "", args.device_code
            )
            return (0 if result.get("ok") else 1), result
        guidance = lark.login_command(
            found.get("path") if found["ok"] else None,
            identity_name=args.identity_name,
        )
        return (0 if guidance["ok"] else 1), guidance

    required: list[str] = []
    for item in str(args.required or "").split(","):
        name = item.strip()
        if not name:
            continue
        required.extend(lark.REQUIRED_SCOPES.get(name, [name]))
    result = lark.status(
        args.root,
        home=data_root,
        required=required,
        spec=spec,
    )
    ensure_dir(data_root / "install")
    install.record(
        data_root,
        "lark_cli",
        "ok" if result["cli"]["status"] == "ok" else "blocked",
        note=(
            f"可执行 {result['cli'].get('path')}"
            if result["cli"]["status"] == "ok"
            else result["cli"].get("note", "未找到 lark-cli")
        ),
        evidence={"path": result["cli"].get("path"), "source": result["cli"].get("source")},
        recheck=True,
    )
    install.record(
        data_root,
        "identity",
        result["identity"]["status"],
        note=result["identity"]["note"],
        evidence=result["identity"].get("evidence") or {},
        recheck=True,
    )
    authz = result["authorization"]
    resources = result["resources"]
    if authz["status"] == "blocked" or resources["status"] == "blocked":
        perm_status = "blocked"
    elif authz["status"] == "ok" and resources["status"] == "ok":
        perm_status = "ok"
    else:
        perm_status = "untested"
    install.record(
        data_root,
        "permissions",
        perm_status,
        note="授权范围与资源读取均已验证"
        if perm_status == "ok"
        else (authz.get("note") or resources.get("note", "")),
        evidence={
            "granted": authz.get("granted"),
            "missing": authz.get("missing"),
            "base": resources.get("base"),
            "drive": resources.get("drive"),
            "messages": resources.get("messages"),
        },
        recheck=True,
    )
    if result["cli"]["status"] == "ok":
        update_config(
            data_root,
            paths={"lark_cli": result["cli"]["path"]},
            permissions={
                "scope": authz.get("granted") or [],
                "missing": authz.get("missing") or [],
                "checked_at": result.get("checked_at"),
            },
        )
    return (0 if result["ok"] else 1), result


def _schedules(args, root: Path) -> tuple[int, dict]:
    if args.action == "plan":
        return 0, schedules.plan(
            root,
            timezone_name=args.timezone_name,
            daily=args.daily,
            feedback_minute=args.feedback_minute,
        )
    if args.action == "confirm":
        task_ids = _pairs(args.task_id)
        result = schedules.confirm(
            root,
            timezone_name=args.timezone_name,
            daily=args.daily,
            feedback_minute=args.feedback_minute,
            confirmed_by_user=args.yes,
            host_created=args.host_created,
            enabled=not args.paused,
            task_ids=task_ids,
        )
        return (0 if result.get("ok") else 1), result
    if args.action == "pause":
        result = schedules.pause(root, confirmed_by_user=args.yes, reason=args.reason)
        return (0 if result.get("ok") else 1), result
    if args.action == "resume":
        result = schedules.resume(root, confirmed_by_user=args.yes)
        return (0 if result.get("ok") else 1), result
    if args.action == "trigger":
        evidence = json.loads(args.evidence) if args.evidence else {}
        result = schedules.record_trigger(root, args.task, at=args.at, evidence=evidence)
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

"""SemLift command line.

    semlift run <bundle.zip|folder> [-w WORKSPACE] [-c CONFIG]   ingest -> design -> generate package
    semlift review <object-id> approve|reject|reset [--ack]      record a review decision
    semlift approve-all                                          approve every object >= confidence threshold
    semlift deploy [--branch B] [--remote URL --push]            write approved objects to a Git branch for CI
    semlift parity                                               run parity SQL (needs a Snowflake connection)
    semlift serve [--port 8000]                                  start the API + UI
    semlift summary                                              print the last run summary
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__


def _ws(args):
    from .service.workspace import Workspace
    return Workspace(args.workspace)


def cmd_run(args) -> int:
    ws = _ws(args)
    if args.config or not ws.config_path.exists():
        ws.set_config(args.config)
    extra = [args.catalog] if args.catalog else None
    st = ws.run(args.source, live_compile=args.live_compile, extra_sources=extra)
    _print_summary(st)
    print(f"\nOutput package: {ws.output}")
    return 0


def _print_summary(st: dict) -> None:
    c = st["ingest"]["counts"]
    rat = st["estate"]["rationalization"]
    print(f"SemLift {st['tool_version']}  run {st['run_id']}")
    print(f"  ingest   : {len(st['ingest']['files'])} files, {c['reports']} reports, {c['report_items']} data items, "
          f"{c['filters']} filters, {c['security_rules']} security rules")
    print(f"  estate   : {rat.get('clusters')} intent clusters ({rat.get('retired_clusters')} retired); dispositions {rat.get('dispositions')}")
    print(f"  model    : {len(st['model']['entities'])} logical entities, {len(st['model']['relationships'])} relationships, "
          f"{len(st['model']['join_issues'])} join-path issues")
    print(f"  design   : {len(st['objects'])} objects {st['review_summary']}; {len(st['aggregates']['plans'])} aggregates; "
          f"{len(st['products'])} data products")
    sev: dict[str, int] = {}
    for f in st["findings"]:
        sev[f["severity"]] = sev.get(f["severity"], 0) + 1
    print(f"  findings : {len(st['findings'])} {dict(sorted(sev.items()))}")
    for v in st["validation"]:
        res = "n/a " if v["passed"] is None else ("PASS" if v["passed"] else "FAIL")
        print(f"  {v['rule']} {res} {v['title']} - {v['detail']}")
    d = st["diff"]
    print(f"  diff     : {'baseline' if d['baseline'] else ''} +{len(d['added'])} ~{len(d['changed'])} -{len(d['removed'])}")
    print(f"  timings  : " + ", ".join(f"{k} {v:.2f}s" for k, v in st["timings"].items()))


def cmd_review(args) -> int:
    ws = _ws(args)
    o = ws.review(args.object_id, args.action, reviewer=args.reviewer, comment=args.comment or "",
                  acknowledge_low_confidence=args.ack)
    print(json.dumps({"id": o["id"], "status": o["status"]}))
    return 0


def cmd_approve_all(args) -> int:
    print(json.dumps(_ws(args).auto_approve(args.reviewer)))
    return 0


def cmd_deploy(args) -> int:
    res = _ws(args).deploy(branch=args.branch, remote=args.remote, push=args.push)
    print(json.dumps({k: res[k] for k in ("branch", "commit", "pushed", "repo")}, indent=2))
    print(f"{len(res['deployed'])} objects written; {len(res['skipped'])} skipped (unapproved dependencies)")
    return 0


def cmd_parity(args) -> int:
    res = _ws(args).run_parity()
    for r in res["results"]:
        print(f"{r['status']:8} {r['report']} -> {r['semantic_view']}")
    return 0


def cmd_summary(args) -> int:
    st = _ws(args).state()
    if not st:
        print("no run yet", file=sys.stderr)
        return 1
    _print_summary(st)
    return 0


def cmd_serve(args) -> int:
    import uvicorn
    import os
    os.environ["SEMLIFT_WORKSPACE"] = str(Path(args.workspace).resolve())
    uvicorn.run("semlift.api.app:app", host=args.host, port=args.port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="semlift", description="Cognos-to-Data-Platform Semantic Layer Migrator")
    p.add_argument("--version", action="version", version=f"SemLift {__version__}")
    p.add_argument("-w", "--workspace", default="workspace", help="workspace folder (default ./workspace)")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="ingest a Cognos bundle and generate the design package")
    r.add_argument("source")
    r.add_argument("-c", "--config", help="estate configuration YAML")
    r.add_argument("--catalog", help="landed source catalog CSV (SRC-CAT)")
    r.add_argument("--live-compile", action="store_true", help="EXPLAIN against Snowflake (needs SEMLIFT_SNOWFLAKE_*)")
    r.set_defaults(fn=cmd_run)
    rv = sub.add_parser("review", help="approve / reject / reset an object")
    rv.add_argument("object_id")
    rv.add_argument("action", choices=["approve", "reject", "reset"])
    rv.add_argument("--reviewer", default="steward")
    rv.add_argument("--comment")
    rv.add_argument("--ack", action="store_true", help="acknowledge low-confidence (inferred) object")
    rv.set_defaults(fn=cmd_review)
    aa = sub.add_parser("approve-all", help="approve objects meeting the confidence threshold")
    aa.add_argument("--reviewer", default="auto")
    aa.set_defaults(fn=cmd_approve_all)
    dp = sub.add_parser("deploy", help="commit approved objects to a Git branch for CI deployment")
    dp.add_argument("--branch")
    dp.add_argument("--remote")
    dp.add_argument("--push", action="store_true")
    dp.set_defaults(fn=cmd_deploy)
    sub.add_parser("parity", help="run parity tests").set_defaults(fn=cmd_parity)
    sub.add_parser("summary", help="print last run summary").set_defaults(fn=cmd_summary)
    sv = sub.add_parser("serve", help="start the API and web UI")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.set_defaults(fn=cmd_serve)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

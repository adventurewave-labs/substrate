"""Operator CLI. Stdlib argparse — no framework until ops demand one (Law 8).

Subcommands:
  migrate        apply pending SQL migrations
  import-csv     parse a CRM export, persist it, emit a reconciliation report
                 (--dry-run parses and reports without touching the database)
  er-v0          deterministic entity resolution over an imported tenant
                 (--dry-run scores candidates without writing decisions)
  golden-sample  write the stratified golden-set labeling worksheet for a tenant
  golden-eval    score labeled worksheet vs the ER rule set (precision + blocking recall)
  audit          Graph Audit v0 resolution report (JSON + HTML)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from substrate import db
from substrate.config import get_settings
from substrate.importers.csv_import import parse_contacts
from substrate.reconcile import build_contact_report
from substrate.store import ImportStats, ensure_tenant, persist_contacts


def cmd_migrate(args: argparse.Namespace) -> int:
    url = args.database_url or get_settings().database_url
    conn = db.connect(url)
    try:
        applied = db.run_migrations(conn)
    finally:
        conn.close()
    print(f"applied: {', '.join(applied) if applied else 'nothing pending'}")
    return 0


def cmd_import_csv(args: argparse.Namespace) -> int:
    text = Path(args.contacts_file).read_text(encoding="utf-8-sig")  # BOM-safe (Excel exports)
    rows, skipped = parse_contacts(text)
    report = build_contact_report("contact", rows, skipped)

    stats: ImportStats | None = None
    if not args.dry_run:
        url = args.database_url or get_settings().database_url
        conn = db.connect(url)
        try:
            with conn.transaction():
                tenant_id = ensure_tenant(conn, args.tenant, args.crm_type)
                stats = persist_contacts(conn, tenant_id, rows, system=args.system)
        finally:
            conn.close()

    out: dict[str, Any] = {"reconciliation": report.as_dict()}
    if stats is not None:
        out["persistence"] = stats.as_dict()
    Path(args.report).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(
        f"rows_read={report.rows_read} parsed={report.rows_parsed} skipped={report.rows_skipped} "
        f"-> {args.report}"
    )
    return 0


def _connect(args: argparse.Namespace):
    url = args.database_url or get_settings().database_url
    return db.connect(url)


def cmd_er_v0(args: argparse.Namespace) -> int:
    from substrate.er.engine import run_er_v0, stats_json, tenant_id_by_name

    conn = _connect(args)
    try:
        tenant_id = tenant_id_by_name(conn, args.tenant)
        stats = run_er_v0(conn, tenant_id, dry_run=args.dry_run, force=args.force)
    finally:
        conn.close()
    print(stats_json(stats))
    return 0


def cmd_golden_sample(args: argparse.Namespace) -> int:
    from substrate.er.engine import run_golden_sample, tenant_id_by_name

    conn = _connect(args)
    try:
        tenant_id = tenant_id_by_name(conn, args.tenant)
        worksheet = run_golden_sample(conn, tenant_id)
    finally:
        conn.close()
    Path(args.out).write_text(worksheet)
    print(f"worksheet -> {args.out}")
    return 0


def cmd_golden_eval(args: argparse.Namespace) -> int:
    from substrate.er.engine import run_golden_eval, tenant_id_by_name

    worksheet = Path(args.worksheet).read_text()
    conn = _connect(args)
    try:
        tenant_id = tenant_id_by_name(conn, args.tenant)
        result = run_golden_eval(conn, tenant_id, worksheet)
    finally:
        conn.close()
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"metrics -> {args.out}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    from substrate.er.engine import run_audit

    if not args.out.endswith(".json"):
        # The HTML lands alongside; a non-.json --out would silently overwrite the
        # JSON with it (gate finding). Fail loudly instead.
        raise SystemExit("--out must end with .json (the .html report is written alongside)")
    html_path = args.out[:-5] + ".html"

    conn = _connect(args)
    try:
        report, page = run_audit(conn, args.tenant)
    finally:
        conn.close()
    Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    Path(html_path).write_text(page)
    print(f"audit -> {args.out} (+ {html_path})")
    return 0


def cmd_watch_add(args: argparse.Namespace) -> int:
    conn = _connect(args)
    try:
        from substrate.store import ensure_tenant

        with conn.transaction():
            tenant_id = ensure_tenant(conn, args.tenant, "csv")
            conn.execute(
                "SELECT watch_upsert(%s, %s, %s, %s, %s, %s)",
                (tenant_id, args.domain.lower(), args.greenhouse, args.lever, args.ashby, args.cik),
            )
    finally:
        conn.close()
    print(f"watch: {args.domain} updated for tenant {args.tenant}")
    return 0


def cmd_crawl(args: argparse.Namespace) -> int:
    import json
    from datetime import date

    from substrate.er.engine import tenant_id_by_name
    from substrate.sources.crawl import (
        crawl_careers_for_tenant,
        crawl_edgar_for_tenant,
        crawl_press_for_tenant,
    )
    from substrate.sources.http import Fetcher
    from substrate.sources.llm import LlmGateway

    conn = _connect(args)
    try:
        tenant_id = tenant_id_by_name(conn, args.tenant)
        if args.source == "careers":
            report = crawl_careers_for_tenant(conn, tenant_id, Fetcher(), dry_run=args.dry_run)
        elif args.source == "edgar":
            from substrate.sources.edgar import sec_user_agent

            report = crawl_edgar_for_tenant(
                conn,
                tenant_id,
                Fetcher(user_agent=sec_user_agent()),  # SEC UA on robots fetch too
                start=date.fromisoformat(args.start) if args.start else None,
                end=date.fromisoformat(args.end) if args.end else None,
                dry_run=args.dry_run,
            )
        elif args.source == "press":
            if not args.feed_url:
                raise SystemExit("press crawl needs --feed-url")
            report = crawl_press_for_tenant(
                conn,
                tenant_id,
                Fetcher(),
                LlmGateway(database_url=args.database_url),
                args.feed_url,
                dry_run=args.dry_run,
            )
        else:
            raise SystemExit(f"unknown source {args.source!r}")
    finally:
        conn.close()
    Path(args.report).write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n")
    print(f"crawl {args.source}: {report.as_dict()} -> {args.report}")
    return 0


def cmd_detect(args: argparse.Namespace) -> int:
    import os

    if args.detect_only and args.deliver_only:
        raise SystemExit("--detect-only and --deliver-only are mutually exclusive")
    if args.first_run and args.deliver_only:
        raise SystemExit(
            "--first-run with --deliver-only would deliver the backlog it was "
            "supposed to suppress — run detect --first-run alone first"
        )

    from substrate.er.engine import tenant_id_by_name
    from substrate.signals.delivery import SlackWebhookSink, deliver_pending
    from substrate.signals.detector import detect_for_tenant

    report: dict[str, object] = {}
    conn = _connect(args)
    try:
        tenant_id = tenant_id_by_name(conn, args.tenant)
        if not args.deliver_only:
            # first_run=None → the detector's auto semantics (suppress the backlog
            # on a tenant's first run, alert every later run).
            first_run = True if args.first_run else None
            stats = detect_for_tenant(conn, tenant_id, first_run=first_run)
            report["detection"] = stats.as_dict()
        if not args.detect_only:
            sink = SlackWebhookSink(webhook_url=os.environ.get("SUBSTRATE_SLACK_WEBHOOK_URL"))
            delivery = deliver_pending(conn, tenant_id, sink)
            report["delivery"] = delivery.as_dict()
    finally:
        conn.close()
    Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"detect -> {args.report}")
    return 0


def cmd_canary(args: argparse.Namespace) -> int:
    from substrate.signals.canary import replay

    conn = _connect(args)  # canary replay owns its rolled-back tenant; --tenant unused
    try:
        result = replay(conn, Path(args.fixture))
    finally:
        conn.close()
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"canary replay -> {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="substrate", description="Substrate core CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_migrate = sub.add_parser("migrate", help="apply pending SQL migrations")
    p_migrate.add_argument("--database-url", default=None, help="overrides SUBSTRATE_DATABASE_URL")
    p_migrate.set_defaults(func=cmd_migrate)

    p_import = sub.add_parser("import-csv", help="import a CRM contact export")
    p_import.add_argument("--tenant", required=True, help="tenant name (created if missing)")
    p_import.add_argument("--crm-type", default="csv", choices=("salesforce", "hubspot", "csv"))
    p_import.add_argument("--system", default="csv", help="source system tag for ids/claims")
    p_import.add_argument("--contacts-file", required=True)
    p_import.add_argument("--report", required=True, help="path for the reconciliation report JSON")
    p_import.add_argument("--dry-run", action="store_true", help="parse + report only, no database")
    p_import.add_argument("--database-url", default=None, help="overrides SUBSTRATE_DATABASE_URL")
    p_import.set_defaults(func=cmd_import_csv)

    def with_db(p: argparse.ArgumentParser) -> None:
        p.add_argument("--tenant", required=True)
        p.add_argument("--database-url", default=None, help="overrides SUBSTRATE_DATABASE_URL")

    p_er = sub.add_parser("er-v0", help="deterministic entity resolution for a tenant")
    with_db(p_er)
    p_er.add_argument("--dry-run", action="store_true", help="score candidates, write nothing")
    p_er.add_argument(
        "--force",
        action="store_true",
        help="replace this featureset's auto_merge decisions (new imports get resolved)",
    )
    p_er.set_defaults(func=cmd_er_v0)

    p_sample = sub.add_parser("golden-sample", help="write golden-set labeling worksheet")
    with_db(p_sample)
    p_sample.add_argument("--out", required=True, help="worksheet CSV path")
    p_sample.set_defaults(func=cmd_golden_sample)

    p_eval = sub.add_parser("golden-eval", help="evaluate labeled worksheet vs ER rules")
    with_db(p_eval)
    p_eval.add_argument("--worksheet", required=True, help="labeled worksheet CSV")
    p_eval.add_argument("--out", required=True, help="metrics JSON path")
    p_eval.set_defaults(func=cmd_golden_eval)

    p_audit = sub.add_parser("audit", help="Graph Audit v0 resolution report")
    with_db(p_audit)
    p_audit.add_argument("--out", required=True, help="report JSON path (HTML alongside)")
    p_audit.set_defaults(func=cmd_audit)

    p_watch = sub.add_parser("watch", help="manage the source watch list")
    watch_sub = p_watch.add_subparsers(dest="watch_command", required=True)
    p_watch_add = watch_sub.add_parser("add", help="upsert one watch row")
    with_db(p_watch_add)
    p_watch_add.add_argument("--domain", required=True)
    p_watch_add.add_argument("--greenhouse", default=None, help="public board token")
    p_watch_add.add_argument("--lever", default=None, help="public board token")
    p_watch_add.add_argument("--ashby", default=None, help="public board token")
    p_watch_add.add_argument("--cik", default=None, help="SEC CIK for Form D watch")
    p_watch_add.set_defaults(func=cmd_watch_add)

    p_crawl = sub.add_parser("crawl", help="run a source crawler for a tenant")
    with_db(p_crawl)
    p_crawl.add_argument("--source", required=True, choices=("careers", "edgar", "press"))
    p_crawl.add_argument("--feed-url", default=None, help="press: RSS feed URL")
    p_crawl.add_argument("--start", default=None, help="edgar: window start YYYY-MM-DD")
    p_crawl.add_argument("--end", default=None, help="edgar: window end YYYY-MM-DD")
    p_crawl.add_argument("--report", required=True, help="crawl report JSON path")
    p_crawl.add_argument("--dry-run", action="store_true", help="fetch + parse, write nothing")
    p_crawl.set_defaults(func=cmd_crawl)

    p_detect = sub.add_parser("detect", help="detect job changes and deliver pending events")
    with_db(p_detect)
    p_detect.add_argument(
        "--detect-only", action="store_true", help="diff snapshots, skip delivery"
    )
    p_detect.add_argument(
        "--deliver-only", action="store_true", help="deliver pending, skip detection"
    )
    p_detect.add_argument(
        "--first-run",
        action="store_true",
        help="record historical moves as already delivered (no Slack flood on "
        "a tenant with re-import history)",
    )
    p_detect.add_argument("--report", required=True, help="detect/delivery report JSON path")
    p_detect.set_defaults(func=cmd_detect)

    p_canary = sub.add_parser("canary", help="replay known-move canaries (rolled back)")
    p_canary.add_argument("--database-url", default=None, help="overrides SUBSTRATE_DATABASE_URL")
    p_canary.add_argument(
        "--fixture", default="tests/fixtures/canary_moves.json", help="canary fixture path"
    )
    p_canary.add_argument("--out", required=True, help="replay report JSON path")
    p_canary.set_defaults(func=cmd_canary)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

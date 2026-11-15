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
        stats = run_er_v0(conn, tenant_id, dry_run=args.dry_run)
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

    conn = _connect(args)
    try:
        report, page = run_audit(conn, args.tenant)
    finally:
        conn.close()
    Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    Path(args.out.removesuffix(".json") + ".html").write_text(page)
    print(f"audit -> {args.out} (+ .html)")
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

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

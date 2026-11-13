"""Operator CLI. Stdlib argparse — no framework until ops demand one (Law 8).

Subcommands:
  migrate      apply pending SQL migrations
  import-csv   parse a CRM export, persist it, emit a reconciliation report
               (--dry-run parses and reports without touching the database)
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

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

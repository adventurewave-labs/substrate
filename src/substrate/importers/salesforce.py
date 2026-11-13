"""Read-only Salesforce import (PLAN §7 W1–2).

Credentials: integration service account with a read-only profile on the Salesforce
side; we additionally issue SELECT only. Incremental by SystemModstamp watermark in
import_checkpoints; replay-safety ultimately rests on the (tenant, system, external_id)
upsert contract, never on the watermark alone.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg
from simple_salesforce import Salesforce

from substrate.importers.csv_import import normalize_contact_row
from substrate.reconcile import ReconciliationReport, build_contact_report
from substrate.store import ImportStats, persist_contacts

_CONTACT_FIELDS = "Id, Email, FirstName, LastName, Title, AccountId, SystemModstamp"


def build_contact_soql(watermark: datetime | None) -> str:
    q = f"SELECT {_CONTACT_FIELDS} FROM Contact"
    if watermark:
        literal = watermark.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        q += f" WHERE SystemModstamp > {literal}"
    return q + " ORDER BY SystemModstamp ASC"


def to_contact_row(rec: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    return normalize_contact_row(
        {
            "Id": rec.get("Id"),
            "Email": rec.get("Email"),
            "FirstName": rec.get("FirstName"),
            "LastName": rec.get("LastName"),
            "Title": rec.get("Title"),
            "AccountId": rec.get("AccountId"),
        }
    )


def _parse_sf_timestamp(raw: str) -> datetime:
    # Salesforce format: 2024-01-01T12:00:00.000+0000
    return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S.%f%z").astimezone(UTC)


def import_contacts(
    sf: Salesforce,
    conn: psycopg.Connection,
    tenant_id: Any,
    *,
    max_records: int | None = None,
) -> tuple[ReconciliationReport, ImportStats]:
    """Import contacts incrementally; returns (reconciliation report, stats)."""
    row = conn.execute(
        "SELECT watermark FROM import_checkpoints WHERE tenant_id = %s AND object_name = 'contact'",
        (tenant_id,),
    ).fetchone()
    watermark: datetime | None = row[0] if row else None

    rows: list[dict[str, Any]] = []
    skipped: list[tuple[int, str]] = []
    max_modstamp: str | None = None
    for rec in sf.query_all_iter(build_contact_soql(watermark)):
        parsed, reason = to_contact_row(rec)
        if parsed is None:
            skipped.append((len(rows) + len(skipped) + 1, reason or "unparseable record"))
        else:
            rows.append(parsed)
        modstamp = rec.get("SystemModstamp")
        if modstamp and (max_modstamp is None or str(modstamp) > max_modstamp):
            max_modstamp = str(modstamp)  # fixed-width SF timestamps order lexicographically
        if max_records is not None and len(rows) + len(skipped) >= max_records:
            break

    stats = persist_contacts(conn, tenant_id, rows, system="sfdc")
    conn.execute(
        "INSERT INTO import_checkpoints "
        "(tenant_id, object_name, watermark, rows_imported, updated_at) "
        "VALUES (%s, 'contact', %s, %s, now()) "
        "ON CONFLICT (tenant_id, object_name) DO UPDATE SET "
        "watermark = EXCLUDED.watermark, "
        "rows_imported = import_checkpoints.rows_imported + EXCLUDED.rows_imported, "
        "updated_at = now()",
        (tenant_id, _parse_sf_timestamp(max_modstamp) if max_modstamp else None, len(rows)),
    )
    return build_contact_report("contact", rows, skipped), stats

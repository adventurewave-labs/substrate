"""Read-only HubSpot import (PLAN §7 W1–2).

v1 does a full paged scan — idempotent upserts make replay safe. The watermark is
recorded but not yet used to filter; filtered scans (search API on lastmodifieddate)
come with W3 crawlers once a second source proves the pattern.
"""

from __future__ import annotations

from typing import Any

import psycopg
from hubspot import HubSpot

from substrate.importers.csv_import import normalize_contact_row
from substrate.reconcile import ReconciliationReport, build_contact_report
from substrate.store import ImportStats, persist_contacts

_CONTACT_PROPS = ["email", "firstname", "lastname", "jobtitle", "company", "hs_object_id"]


def build_contact_request(limit: int = 100, after: str | None = None) -> dict[str, Any]:
    req: dict[str, Any] = {
        "properties": _CONTACT_PROPS,
        "limit": min(limit, 100),
        "associations": [],
    }
    if after:
        req["after"] = after
    return req


def to_contact_row(rec: Any) -> tuple[dict[str, Any] | None, str | None]:
    props = getattr(rec, "properties", None) or {}
    return normalize_contact_row(
        {
            "hs_object_id": props.get("hs_object_id"),
            "Email": props.get("email"),
            "FirstName": props.get("firstname"),
            "LastName": props.get("lastname"),
            "Title": props.get("jobtitle"),
            "Company": props.get("company"),
        }
    )


def import_contacts(
    client: HubSpot,
    conn: psycopg.Connection,
    tenant_id: Any,
    *,
    max_records: int | None = None,
) -> tuple[ReconciliationReport, ImportStats]:
    """Import contacts via full paged scan; returns (reconciliation report, stats)."""
    rows: list[dict[str, Any]] = []
    skipped: list[tuple[int, str]] = []
    after: str | None = None
    while True:
        page = client.crm.contacts.basic_api.get_page(**build_contact_request(after=after))
        for rec in getattr(page, "results", []) or []:
            parsed, reason = to_contact_row(rec)
            if parsed is None:
                skipped.append((len(rows) + len(skipped) + 1, reason or "unparseable record"))
            else:
                rows.append(parsed)
            if max_records is not None and len(rows) + len(skipped) >= max_records:
                break
        paging = getattr(page, "paging", None)
        nxt = getattr(getattr(paging, "next", None), "after", None) if paging else None
        if not nxt or (max_records is not None and len(rows) + len(skipped) >= max_records):
            break
        after = str(nxt)

    stats = persist_contacts(conn, tenant_id, rows, system="hubspot")
    return build_contact_report("contact", rows, skipped), stats

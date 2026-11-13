"""Canonical contact-row schema + normalization, shared by every importer.

CSV exports (Salesforce/HubSpot conventions) land here first; CRM importers reuse
``normalize_contact_row`` so all sources emit identical shapes. Unknown columns are
ignored, never fatal — exports differ cosmetically. Rows without a stable identity
key (contact_id or email) are skipped: replay-safety (repo invariant) beats volume.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any

CANONICAL_FIELDS = (
    "contact_id",
    "email",
    "name_given",
    "name_family",
    "title",
    "org_name",
    "account_id",
    "last_activity",
)

_ALIASES: dict[str, set[str]] = {
    "contact_id": {"contact id", "contactid", "record id", "id", "hs_object_id"},
    "email": {"email", "email address"},
    "name_given": {"first name", "firstname", "given name"},
    "name_family": {"last name", "lastname", "surname", "family name"},
    "title": {"title", "job title", "role"},
    "org_name": {
        "account name", "company", "company name", "associated company", "organization", "employer"
    },
    "account_id": {"account id", "accountid"},
    "last_activity": {"last activity", "last activity date", "recent activity date"},
}
_LOOKUP = {alias: canon for canon, aliases in _ALIASES.items() for alias in aliases}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def canonicalize_header(raw: str) -> str | None:
    key = raw.strip().lower()
    if key in CANONICAL_FIELDS:
        return key
    return _LOOKUP.get(key)


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def normalize_contact_row(raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Map one source record to canonical keys; returns (None, reason) to skip."""
    row: dict[str, Any] = {}
    for header, value in raw.items():
        if header is None:  # DictReader restkey artifacts
            continue
        canon = canonicalize_header(str(header))
        if canon is None:
            continue
        cleaned = _clean(value)
        if cleaned is not None:
            row[canon] = cleaned

    if not row.get("contact_id") and not row.get("email"):
        return None, "no stable identity key (need contact_id or email)"
    if row.get("email") and not _EMAIL_RE.match(row["email"]):
        return None, f"invalid email: {row['email']!r}"
    if row.get("email"):
        row["email"] = row["email"].strip().lower()
    return row, None


def parse_contacts(text: str) -> tuple[list[dict[str, Any]], list[tuple[int, str]]]:
    """Parse a CSV export into (canonical rows, [(data-row ordinal, skip reason)])."""
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, Any]] = []
    skipped: list[tuple[int, str]] = []
    for ordinal, raw in enumerate(reader, start=1):
        row, reason = normalize_contact_row(raw)
        if row is None:
            skipped.append((ordinal, reason or "unparseable row"))
        else:
            rows.append(row)
    return rows, skipped

"""Row-level reconciliation: the trust artifact shipped with every import.

PLAN §7 W1–2 acceptance requires a row-level reconciliation report per partner CRM.
Pure functions only — no I/O — so the report math is unit-testable without a database.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReconciliationReport:
    object_name: str
    rows_read: int = 0
    rows_parsed: int = 0
    rows_skipped: int = 0
    skip_reasons: Counter[str] = field(default_factory=Counter)
    distinct_emails: int = 0
    duplicate_email_rows: int = 0
    field_population: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "object_name": self.object_name,
            "rows_read": self.rows_read,
            "rows_parsed": self.rows_parsed,
            "rows_skipped": self.rows_skipped,
            "skip_reasons": dict(self.skip_reasons),
            "distinct_emails": self.distinct_emails,
            "duplicate_email_rows": self.duplicate_email_rows,
            "field_population": dict(self.field_population),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True)


# Fields whose population share we report. Empty = the field was absent or blank.
CONTACT_KEY_FIELDS = ("email", "title", "org_name", "account_id", "name_given", "name_family")


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def build_contact_report(
    object_name: str,
    rows: list[dict[str, Any]],
    skipped: list[tuple[int, str]],
) -> ReconciliationReport:
    """Aggregate source-side stats for one contact import batch.

    ``rows`` are parsed (canonical-keyed) contact dicts; ``skipped`` carries
    ``(row_number, reason)`` pairs for every source row rejected at parse time.
    """
    report = ReconciliationReport(object_name=object_name)
    report.rows_read = len(rows) + len(skipped)
    report.rows_parsed = len(rows)
    report.rows_skipped = len(skipped)
    for _, reason in skipped:
        report.skip_reasons[reason] += 1

    emails = [str(r["email"]).strip().lower() for r in rows if not _is_blank(r.get("email"))]
    report.distinct_emails = len(set(emails))
    counts = Counter(emails)
    report.duplicate_email_rows = sum(c - 1 for c in counts.values() if c > 1)

    if rows:
        for field_name in CONTACT_KEY_FIELDS:
            populated = sum(1 for r in rows if not _is_blank(r.get(field_name)))
            report.field_population[field_name] = round(populated / len(rows), 4)
    return report

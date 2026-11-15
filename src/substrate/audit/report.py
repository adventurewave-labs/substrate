"""Graph Audit resolution report — v0, report-only (PLAN §6).

Honesty contract (PRD F5): uncovered things say "not yet measurable", never a guess.
Stale-title % needs external comparison sources (W5+ crawlers); movement counts need
graph mass (W8 canaries). Both appear as explicit placeholders until then.
"""

from __future__ import annotations

import html
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from substrate.er.blocking import PersonRecord, normalize_email


@dataclass
class AuditReport:
    tenant: str
    contacts_total: int
    clusters: int
    duplicates_collapsed: int
    contactable_rate: float  # share with ≥1 email
    org_anchored_rate: float  # share with ≥1 current position
    title_population: float
    shared_email_collisions: int  # same email across ≥2 distinct persons (pre-ER)
    generated_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant": self.tenant,
            "contacts_total": self.contacts_total,
            "clusters": self.clusters,
            "duplicates_collapsed": self.duplicates_collapsed,
            "contactable_rate": self.contactable_rate,
            "org_anchored_rate": self.org_anchored_rate,
            "title_population": self.title_population,
            "shared_email_collisions": self.shared_email_collisions,
            "generated_at": self.generated_at,
            "not_yet_measurable": {
                "stale_title_pct": "requires external comparison sources (W5+ crawlers)",
                "champions_moved_90d": "requires graph mass + canaries (W8)",
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True)


def build_report(
    tenant: str,
    persons: list[PersonRecord],
    cluster_map: dict[str, str],
    now: datetime | None = None,
) -> AuditReport:
    """Pure report math over imported persons + the ER cluster view."""
    total = len(persons)
    if total == 0:
        raise ValueError("audit on an empty tenant — import first")

    distinct_emails: Counter[str] = Counter()
    contactable = 0
    anchored = 0
    titled = 0
    for person in persons:
        emails = {
            normalize_email(e)
            for e in person.emails
            if isinstance(e, str) and e.strip()  # blanks are not contactable
        }
        if emails:
            contactable += 1
            distinct_emails.update(emails)
        if person.employer_slug is not None:
            anchored += 1
        if person.has_title:  # actual job title on the current position, not name presence
            titled += 1

    return AuditReport(
        tenant=tenant,
        contacts_total=total,
        clusters=len(set(cluster_map.values())) if cluster_map else total,
        duplicates_collapsed=max(total - len(set(cluster_map.values())), 0) if cluster_map else 0,
        contactable_rate=round(contactable / total, 4),
        org_anchored_rate=round(anchored / total, 4),
        title_population=round(titled / total, 4),
        shared_email_collisions=sum(1 for c in distinct_emails.values() if c > 1),
        generated_at=(now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Substrate Graph Audit — {tenant}</title>
<style>
body{{font-family:-apple-system,Helvetica,sans-serif;max-width:680px;
     margin:3rem auto;color:#1a1a2e}}
h1{{font-size:1.4rem}}
.kpi{{display:flex;gap:1rem;flex-wrap:wrap;margin:2rem 0}}
.card{{border:1px solid #ddd;border-radius:10px;padding:1rem 1.25rem;min-width:130px}}
.card b{{display:block;font-size:1.6rem}}
.muted{{color:#777;font-size:.85rem}}
.pending{{background:#fff7e6;border-color:#e6c78a}}
</style></head><body>
<h1>Graph Audit — {tenant}</h1>
<p class="muted">Generated {generated_at} · read-only scan of imported CRM data
· every number below is measured, not modeled.</p>
<div class="kpi">
<div class="card"><b>{contacts_total}</b>contacts imported</div>
<div class="card"><b>{clusters}</b>resolved identities</div>
<div class="card"><b>{duplicates_collapsed}</b>duplicates collapsed</div>
<div class="card"><b>{contactable_pct}</b>contactable (has email)</div>
<div class="card"><b>{org_pct}</b>org-anchored</div>
<div class="card"><b>{shared_email_collisions}</b>shared-email collisions</div>
</div>
<div class="card pending"><b>—</b>stale titles
<span class="muted">measured from W6 (external comparison sources)</span></div>
<div class="card pending" style="margin-top:.5rem"><b>—</b>champions moved (90d)
<span class="muted">measured from W8 (graph mass + canaries)</span></div>
<p class="muted">B2B professional contacts only · read-only access
· erasure honored cascade-wide.</p>
</body></html>
"""


def render_html(report: AuditReport) -> str:
    return _HTML.format(
        tenant=html.escape(report.tenant),
        generated_at=report.generated_at,
        contacts_total=report.contacts_total,
        clusters=report.clusters,
        duplicates_collapsed=report.duplicates_collapsed,
        contactable_pct=f"{report.contactable_rate:.0%}",
        org_pct=f"{report.org_anchored_rate:.0%}",
        shared_email_collisions=report.shared_email_collisions,
    )

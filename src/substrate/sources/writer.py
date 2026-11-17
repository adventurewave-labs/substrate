"""Source-to-graph persistence: ClaimDrafts in, provenance-complete rows out.

Anchoring is DETERMINISTIC ONLY (repo invariant): orgs anchor by domain, persons by
exact email match. No fuzzy, no LLM — an unanchored draft is counted and skipped,
never guessed. The writer is the single chokepoint where provenance is enforced:
a draft without both a source_type and (source_id or url) refuses to persist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg

from substrate.store import org_external_key, slugify, supersede_claim

VALID_ENTITY_TYPES = ("person", "organization")


class AmbiguousAnchorError(Exception):
    """Two entities share the anchor key (domain/email). Attaching observations to
    'whichever row comes back' is arbitrary identity — refuse and let ER decide."""


@dataclass(frozen=True)
class ClaimDraft:
    """One source observation destined for the graph. Entity ids are anchors —
    resolved deterministically BEFORE persistence, never inside the LLM."""

    entity_type: str          # 'person' | 'organization'
    field: str
    value_norm: str
    source_type: str          # 'greenhouse' | 'edgar' | 'press' | 'coresignal' | 'pdl' | ...
    source_id: str | None
    url: str | None
    retrieved_at: datetime
    entity_id: UUID | None = None
    confidence: float = 1.0

    def validate_provenance(self) -> None:
        if self.entity_type not in VALID_ENTITY_TYPES:
            raise ValueError(f"invalid entity_type {self.entity_type!r}")
        if not self.source_type:
            raise ValueError("claim without source_type — provenance incomplete")
        if not self.source_id and not self.url:
            raise ValueError(
                f"claim without source_id or url — provenance incomplete ({self.field!r})"
            )
        if self.entity_id is None:
            raise ValueError(f"unanchored claim must be skipped, not persisted ({self.field!r})")


@dataclass
class WriteStats:
    orgs_created: int = 0
    claims_written: int = 0
    postings_written: int = 0
    funding_events_written: int = 0
    skipped_unanchored: int = 0
    skipped_unchanged: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "orgs_created": self.orgs_created,
            "claims_written": self.claims_written,
            "postings_written": self.postings_written,
            "funding_events_written": self.funding_events_written,
            "skipped_unanchored": self.skipped_unanchored,
            "skipped_unchanged": self.skipped_unchanged,
        }


def resolve_org_by_domain(
    conn: psycopg.Connection, tenant_id: Any, domain: str, *, display_name: str | None = None
) -> tuple[UUID, bool]:
    """Anchor an org by exact domain match; create+bind when new (deterministic —
    domain is a stable natural key, merging into existing orgs is ER's job)."""
    domain = domain.strip().lower()
    rows = conn.execute(
        "SELECT id FROM organizations WHERE tenant_id = %s AND %s = ANY(domains)",
        (tenant_id, domain),
    ).fetchall()
    if len(rows) > 1:
        raise AmbiguousAnchorError(
            f"two or more orgs claim domain {domain!r} — anchoring is ER's decision"
        )
    if rows:
        return rows[0][0], False
    org_row = conn.execute(
        "INSERT INTO organizations (tenant_id, name_canonical, domains) VALUES (%s, %s, %s) "
        "RETURNING id",
        (tenant_id, display_name or domain, [domain]),
    ).fetchone()
    assert org_row is not None
    org_id: UUID = org_row[0]
    conn.execute(
        "INSERT INTO external_ids (tenant_id, system, external_id, entity_type, entity_id) "
        "VALUES (%s, 'domain', %s, 'organization', %s)",
        (tenant_id, org_external_key(domain), org_id),
    )
    return org_id, True


def resolve_person_by_email(
    conn: psycopg.Connection, tenant_id: Any, email: str
) -> UUID | None:
    """Exact email match only — feed people data never creates or merges persons."""
    email = email.strip().lower()
    if not email:
        return None
    rows = conn.execute(
        "SELECT id FROM persons WHERE tenant_id = %s AND %s = ANY(emails)",
        (tenant_id, email),
    ).fetchall()
    if len(rows) > 1:
        raise AmbiguousAnchorError(
            f"two or more persons claim email {email!r} — anchoring is ER's decision"
        )
    return rows[0][0] if rows else None


def persist_claim_drafts(
    conn: psycopg.Connection, tenant_id: Any, drafts: list[ClaimDraft], stats: WriteStats
) -> None:
    """Attribute claims with provenance enforced; supersede semantics from store."""
    for draft in drafts:
        draft.validate_provenance()
        assert draft.entity_id is not None  # validated above
        written = supersede_claim(
            conn,
            tenant_id,
            draft.entity_type,
            draft.entity_id,
            draft.field,
            draft.value_norm,
            source_type=draft.source_type,
            source_id=draft.source_id or draft.url or "",
            confidence=draft.confidence,
            url=draft.url,
            retrieved_at=draft.retrieved_at,
        )
        if written:
            stats.claims_written += 1
        else:
            stats.skipped_unchanged += 1


def persist_postings(
    conn: psycopg.Connection,
    tenant_id: Any,
    org_id: UUID,
    postings: list[dict[str, Any]],
    *,
    source_type: str,
    retrieved_at: datetime,
    stats: WriteStats,
    reconcile: bool = True,
) -> None:
    """Job postings: idempotent upsert keyed on (tenant, org, source, url).

    One posting = one URL: a retitled posting updates in place, a posting that
    returns after a delisting is resurrected (closed_at cleared), and postings
    absent from the batch are closed — the hiring_activity snapshot is CURRENT,
    never a monotone maximum. The aggregate hiring claim is written separately
    (write_hiring_activity_claim) once per org per crawl, across all platforms.

    ``reconcile=False`` (scheduler: a contributing board failed this cycle) skips
    the close-pass — an absent URL from an un-fetched board must never close a
    live posting (W9 gate review: incomplete batches are additive-only).
    """
    incoming_urls = [posting["url"] for posting in postings]
    for posting in postings:
        title_norm = slugify(posting["title_norm"])
        row = conn.execute(
            "INSERT INTO job_postings "
            "(tenant_id, org_id, title_norm, function, location, source_type, url, "
            "posted_at, retrieved_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (tenant_id, org_id, source_type, url) DO UPDATE SET "
            "title_norm = EXCLUDED.title_norm, "
            "function = EXCLUDED.function, "
            "location = EXCLUDED.location, "
            "posted_at = EXCLUDED.posted_at, "
            "closed_at = NULL, "
            "retrieved_at = EXCLUDED.retrieved_at "
            "RETURNING (xmax = 0) AS inserted",
            (
                tenant_id,
                org_id,
                title_norm,
                posting.get("function"),
                posting.get("location"),
                source_type,
                posting["url"],
                posting.get("posted_at"),
                retrieved_at,
            ),
        ).fetchone()
        if row is not None and row[0]:
            stats.postings_written += 1

    if reconcile:
        # Reconciliation: postings from this source no longer listed are closed.
        conn.execute(
            "UPDATE job_postings SET closed_at = %s "
            "WHERE tenant_id = %s AND org_id = %s AND source_type = %s "
            "AND closed_at IS NULL AND NOT (url = ANY(%s))",
            (retrieved_at, tenant_id, org_id, source_type, incoming_urls),
        )


def write_hiring_activity_claim(
    conn: psycopg.Connection, tenant_id: Any, org_id: UUID, *, stats: WriteStats
) -> None:
    """Aggregate open-posting snapshot across ALL career platforms — written once
    per org per crawl, after every platform's postings are reconciled."""
    count = conn.execute(
        "SELECT count(*) FROM job_postings "
        "WHERE tenant_id = %s AND org_id = %s AND closed_at IS NULL",
        (tenant_id, org_id),
    ).fetchone()
    open_count = int(count[0]) if count else 0
    written = supersede_claim(
        conn, tenant_id, "organization", org_id, "hiring_activity",
        f"open_postings:{open_count}",
        source_type="careers", source_id=f"careers:{org_id}",
    )
    if written:
        stats.claims_written += 1
    else:
        stats.skipped_unchanged += 1


def count_orgs_by_domain(conn: psycopg.Connection, tenant_id: Any, domain: str) -> int:
    """Read-only ambiguity probe: how many orgs claim this domain. Dry-run paths
    use it to make the SAME anchoring decisions the write path makes (which raises
    on >1) — dry-run and real runs must never diverge."""
    domain = domain.strip().lower()
    row = conn.execute(
        "SELECT count(*) FROM organizations WHERE tenant_id = %s AND %s = ANY(domains)",
        (tenant_id, domain),
    ).fetchone()
    return int(row[0]) if row else 0


def find_org_by_domain(
    conn: psycopg.Connection, tenant_id: Any, domain: str
) -> UUID | None:
    """Read-only domain lookup — the dry-run anchoring path (never creates).
    Ambiguous matches return None: the caller counts the item skipped, never
    guesses (write paths raise AmbiguousAnchorError instead)."""
    domain = domain.strip().lower()
    rows = conn.execute(
        "SELECT id FROM organizations WHERE tenant_id = %s AND %s = ANY(domains)",
        (tenant_id, domain),
    ).fetchall()
    if len(rows) != 1:
        return None  # zero or ambiguous → not anchorable without a human/ER decision
    return rows[0][0]


def persist_funding_events(
    conn: psycopg.Connection,
    tenant_id: Any,
    org_id: UUID,
    events: list[dict[str, Any]],
    *,
    stats: WriteStats,
) -> None:
    """Funding events: idempotent on (org, announced_on, source, url); the org's
    last_funding_event claim supersedes for cheap downstream reads."""
    inserted_any = False
    for event in events:
        row = conn.execute(
            "INSERT INTO funding_events "
            "(tenant_id, org_id, round_type, amount_usd, announced_on, source_type, "
            "url, retrieved_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (org_id, announced_on, source_type, url) DO NOTHING "
            "RETURNING id",
            (
                tenant_id,
                org_id,
                event.get("round_type"),
                event.get("amount_usd"),
                event["announced_on"],
                event["source_type"],
                event["url"],
                event.get("retrieved_at") or datetime.now(UTC),
            ),
        ).fetchone()
        if row is not None:
            stats.funding_events_written += 1
            inserted_any = True

    if inserted_any:
        # Latest-wins: the claim reflects the org's newest event by announced date —
        # never whatever event was inserted last (an older EDGAR window run after a
        # newer one must not roll the claim backwards).
        latest = conn.execute(
            "SELECT announced_on, COALESCE(round_type, 'unknown'), source_type, url "
            "FROM funding_events WHERE tenant_id = %s AND org_id = %s "
            "AND closed_at IS NULL "
            "ORDER BY announced_on DESC, id LIMIT 1",
            (tenant_id, org_id),
        ).fetchone()
        assert latest is not None
        written = supersede_claim(
            conn, tenant_id, "organization", org_id, "last_funding_event",
            f"{latest[0].isoformat()}:{latest[1]}",
            source_type=latest[2], source_id=latest[3], url=latest[3],
            # observation time: the claim says "this is the newest event we know
            # NOW, from that source" — the cited event may predate this run
        )
        if written:
            stats.claims_written += 1


def persist_drafts_with_anchoring(
    conn: psycopg.Connection,
    tenant_id: Any,
    drafts: list[ClaimDraft],
    *,
    stats: WriteStats | None = None,
) -> WriteStats:
    """Anchor then persist. Unanchored drafts are counted and skipped — never guessed,
    never created from a fuzzy match."""
    stats = stats or WriteStats()
    for draft in drafts:
        if draft.entity_id is None:
            stats.skipped_unanchored += 1
            continue
        persist_claim_drafts(conn, tenant_id, [draft], stats)
    return stats

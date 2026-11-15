"""Idempotent persistence: normalized contact rows -> entities, claims, positions.

Contracts (repo invariants):
  * identity = (tenant_id, system, external_id) — one entity, always the same one
  * import never merges identities; duplicate humans across sources stay separate
    until the ER engine merges them (merge_decisions / review_queue)
  * attribute corrections supersede claims (append-only store; the DB trigger admits
    superseded_by-only updates)
  * positions are bitemporal versions; import closes the current version when the
    world changed and appends a new one
  * employment without an organization anchor is not written — a title with no
    org has nothing to hang on
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg

EXTRACTOR_VERSION = "import-0.1.0"


@dataclass
class ImportStats:
    persons_created: int = 0
    persons_updated: int = 0
    organizations_created: int = 0
    positions_created: int = 0
    positions_closed: int = 0
    claims_inserted: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "unknown"


def org_external_key(name: str) -> str:
    """Deterministic stand-in external id when the source carries no account id."""
    return f"org-slug:{slugify(name)}"


def ensure_tenant(conn: psycopg.Connection, name: str, crm_type: str) -> UUID:
    row = conn.execute("SELECT id FROM tenants WHERE name = %s", (name,)).fetchone()
    if row is None:
        row = conn.execute(
            "INSERT INTO tenants (name, crm_type) VALUES (%s, %s) RETURNING id", (name, crm_type)
        ).fetchone()
    if row is None:  # INSERT ... RETURNING always yields a row; narrow for the typechecker
        raise RuntimeError(f"tenant upsert for {name!r} returned no id")
    return row[0]


def _lookup_external(
    conn: psycopg.Connection, tenant_id: UUID, system: str, external_id: str, entity_type: str
) -> UUID | None:
    row = conn.execute(
        "SELECT entity_id FROM external_ids WHERE tenant_id = %s AND system = %s "
        "AND external_id = %s AND entity_type = %s",
        (tenant_id, system, external_id, entity_type),
    ).fetchone()
    return row[0] if row else None


def _bind_external(
    conn: psycopg.Connection,
    tenant_id: UUID,
    system: str,
    external_id: str,
    entity_type: str,
    entity_id: UUID,
) -> None:
    conn.execute(
        "INSERT INTO external_ids (tenant_id, system, external_id, entity_type, entity_id) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (tenant_id, system, external_id) DO UPDATE SET entity_id = EXCLUDED.entity_id",
        (tenant_id, system, external_id, entity_type, entity_id),
    )


def supersede_claim(
    conn: psycopg.Connection,
    tenant_id: UUID,
    entity_type: str,
    entity_id: UUID,
    field_name: str,
    value: str,
    *,
    source_type: str,
    source_id: str,
    confidence: float = 1.0,
    url: str | None = None,
    retrieved_at: datetime | None = None,
) -> bool:
    """Insert the current claim for a field, superseding the prior one iff changed.

    Returns True when a claim row was written; False means the store already holds
    this exact value (idempotent replay).
    """
    current = conn.execute(
        "SELECT id, value_norm FROM claims WHERE tenant_id = %s AND entity_type = %s "
        "AND entity_id = %s AND field = %s AND superseded_by IS NULL "
        "ORDER BY retrieved_at DESC, created_at DESC LIMIT 1",
        (tenant_id, entity_type, entity_id, field_name),
    ).fetchone()
    if current and current[1] == value:
        return False
    now = retrieved_at or datetime.now(UTC)
    new_id = conn.execute(
        "INSERT INTO claims (tenant_id, entity_type, entity_id, field, value_norm, "
        "source_type, source_id, url, retrieved_at, extractor_version, confidence) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            tenant_id,
            entity_type,
            entity_id,
            field_name,
            value,
            source_type,
            source_id,
            url,
            now,
            EXTRACTOR_VERSION,
            confidence,
        ),
    ).fetchone()
    assert new_id is not None
    if current:
        conn.execute("UPDATE claims SET superseded_by = %s WHERE id = %s", (new_id[0], current[0]))
    return True


def upsert_organization(
    conn: psycopg.Connection,
    tenant_id: UUID,
    system: str,
    external_id: str | None,
    name: str | None,
) -> tuple[UUID, bool]:
    ext = external_id or org_external_key(name or "unknown")
    found = _lookup_external(conn, tenant_id, system, ext, "organization")
    if found is not None:
        return found, False
    row = conn.execute(
        "INSERT INTO organizations (tenant_id, name_canonical) VALUES (%s, %s) RETURNING id",
        (tenant_id, name),
    ).fetchone()
    assert row is not None
    org_id: UUID = row[0]
    _bind_external(conn, tenant_id, system, ext, "organization", org_id)
    return org_id, True


def upsert_person(
    conn: psycopg.Connection, tenant_id: UUID, system: str, external_id: str, row: dict[str, Any]
) -> tuple[UUID, bool]:
    found = _lookup_external(conn, tenant_id, system, external_id, "person")
    if found is None:
        given, family = row.get("name_given"), row.get("name_family")
        full = " ".join(p for p in (given, family) if p) or None
        emails = [row["email"]] if row.get("email") else []
        new_row = conn.execute(
            "INSERT INTO persons (tenant_id, name_full, name_given, name_family, emails) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (tenant_id, full, given, family, emails),
        ).fetchone()
        assert new_row is not None
        person_id: UUID = new_row[0]
        _bind_external(conn, tenant_id, system, external_id, "person", person_id)
        return person_id, True
    person_id = found
    if row.get("email"):
        conn.execute(
            "UPDATE persons SET emails = array_append(emails, %s), updated_at = now() "
            "WHERE id = %s AND NOT (%s = ANY(emails))",
            (row["email"], person_id, row["email"]),
        )
    return person_id, False


def upsert_position(
    conn: psycopg.Connection,
    tenant_id: UUID,
    person_id: UUID,
    org_id: UUID,
    title: str | None,
    *,
    source_type: str,
    source_id: str,
    stats: ImportStats,
) -> None:
    current = conn.execute(
        "SELECT id, org_id, title_norm FROM positions "
        "WHERE tenant_id = %s AND person_id = %s AND txn_to IS NULL",
        (tenant_id, person_id),
    ).fetchone()
    if current and current[1] == org_id and current[2] == title:
        return
    if current:
        conn.execute("UPDATE positions SET txn_to = now() WHERE id = %s", (current[0],))
        stats.positions_closed += 1
    new_pos = conn.execute(
        "INSERT INTO positions (tenant_id, person_id, org_id, title_norm) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (tenant_id, person_id, org_id, title),
    ).fetchone()
    assert new_pos is not None
    position_id: UUID = new_pos[0]
    stats.positions_created += 1
    if title and supersede_claim(
        conn, tenant_id, "position", position_id, "title_norm", title,
        source_type=source_type, source_id=source_id,
    ):
        stats.claims_inserted += 1


def persist_contacts(
    conn: psycopg.Connection, tenant_id: UUID, rows: list[dict[str, Any]], *, system: str = "csv"
) -> ImportStats:
    """Upsert a parsed batch. Caller wraps in a transaction (all-or-nothing per batch)."""
    stats = ImportStats()
    for row in rows:
        external_id = row.get("contact_id") or row["email"]  # parse layer guarantees one
        person_id, created = upsert_person(conn, tenant_id, system, external_id, row)
        stats.persons_created += int(created)
        stats.persons_updated += int(not created)

        org_name = row.get("org_name")
        account_id = row.get("account_id")
        if org_name or account_id:
            org_id, org_created = upsert_organization(conn, tenant_id, system, account_id, org_name)
            stats.organizations_created += int(org_created)
            if org_name and supersede_claim(
                conn, tenant_id, "organization", org_id, "name_canonical", org_name,
                source_type=system, source_id=external_id,
            ):
                stats.claims_inserted += 1
            if row.get("title"):
                upsert_position(
                    conn, tenant_id, person_id, org_id, row["title"],
                    source_type=system, source_id=external_id, stats=stats,
                )

        for field_name in ("name_given", "name_family", "email"):
            value = row.get(field_name)
            if value and supersede_claim(
                conn, tenant_id, "person", person_id, field_name, value,
                source_type=system, source_id=external_id,
            ):
                stats.claims_inserted += 1
    return stats

"""Canary replay: a known-moves fixture run through the detector inside a rolled-
back transaction — correctness measurement with zero tenant pollution.

This measures DETECTION RECALL (did the detector fire on every known move?).
TTR (time-to-report) is a live-ops metric — it needs continuous crawls and lands
with the W9 scheduler; the report carries the plumbing (expected vs detected)
that measurement will read.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg

from substrate.signals.detector import detect_for_tenant


def load_canaries(path: Path) -> list[dict[str, Any]]:
    canaries = json.loads(path.read_text())
    if not isinstance(canaries, list):
        raise ValueError("canary fixture must be a JSON list")
    required = {
        "marker", "name_given", "name_family",
        "org_name", "new_org_name", "new_title", "move_date",
    }
    for entry in canaries:
        missing = required - set(entry)
        if missing:
            raise ValueError(f"canary entry missing keys: {sorted(missing)}")
    return canaries


def replay(conn: psycopg.Connection, fixture_path: Path) -> dict[str, Any]:
    """Seed canary persons in a DEDICATED rolled-back tenant → detect → report
    recall. Detection is scoped to the canary tenant only: no real-tenant
    collisions, no real pairs in the stats, and the rollback leaves nothing.

    The fixture entries' persons are matched by seeded person_id, never by name
    (a real same-name person's event must not count as a canary hit)."""
    canaries = load_canaries(fixture_path)
    tenant_row = conn.execute(
        "INSERT INTO tenants (name, crm_type) "
        "VALUES ('canary-replay-' || md5(random()::text), 'csv') "
        "RETURNING id"
    ).fetchone()
    assert tenant_row is not None
    tenant_id = tenant_row[0]
    seeded_person_ids: list[Any] = []
    try:
        for entry in canaries:
            person = conn.execute(
                "INSERT INTO persons (tenant_id, name_given, name_family) "
                "VALUES (%s, %s, %s) RETURNING id",
                (tenant_id, entry["name_given"], entry["name_family"]),
            ).fetchone()
            assert person is not None
            person_id = person[0]
            seeded_person_ids.append(person_id)

            org_ids: list[Any] = []
            for org_name in (entry["org_name"], entry["new_org_name"]):
                row = conn.execute(
                    "SELECT id FROM organizations WHERE tenant_id = %s "
                    "AND name_canonical = %s LIMIT 1",
                    (tenant_id, org_name),
                ).fetchone()
                if row is None:
                    row = conn.execute(
                        "INSERT INTO organizations (tenant_id, name_canonical) "
                        "VALUES (%s, %s) RETURNING id",
                        (tenant_id, org_name),
                    ).fetchone()
                assert row is not None
                org_ids.append(row[0])

            move = date.fromisoformat(str(entry["move_date"]))
            old_start = move - timedelta(days=400)
            open_at = datetime.combine(move, datetime.min.time(), tzinfo=UTC)
            close_at = datetime.combine(move - timedelta(days=1), datetime.min.time(), tzinfo=UTC)

            conn.execute(
                "INSERT INTO positions (tenant_id, person_id, org_id, title_norm, "
                "seniority, valid_start, valid_end, txn_from, txn_to) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (tenant_id, person_id, org_ids[0], "former title", "ic",
                 old_start, move - timedelta(days=1), close_at, open_at),
            )
            conn.execute(
                "INSERT INTO positions (tenant_id, person_id, org_id, title_norm, "
                "seniority, valid_start, valid_end, txn_from, txn_to) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (tenant_id, person_id, org_ids[1], entry["new_title"], None,
                 move, None, open_at, None),
            )

        stats = detect_for_tenant(conn, tenant_id, commit=False)  # events write inside
        # this transaction; the finally-rollback discards everything

        detected: list[str] = []
        missed: list[str] = []
        for entry, person_id in zip(canaries, seeded_person_ids, strict=True):
            hit = conn.execute(
                "SELECT 1 FROM events WHERE tenant_id = %s "
                "AND event_type = 'job_change' AND entity_id = %s LIMIT 1",
                (tenant_id, person_id),
            ).fetchone()
            (detected if hit else missed).append(str(entry["marker"]))

        recall = round(len(detected) / len(canaries), 4) if canaries else None
        return {
            "canaries": len(canaries),
            "detected": detected,
            "missed": missed,
            "detection_recall": recall,
            "pairs_diffed": stats.pairs_diffed,  # canary-tenant scoped: canary pairs only
            "ttr": "live-ops metric — continuous crawls land with the W9 scheduler",
        }
    finally:
        conn.rollback()  # the dedicated canary tenant and all seeds are discarded

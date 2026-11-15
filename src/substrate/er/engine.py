"""ER v0 driver: pull a tenant's persons, run blocking + rules, persist decisions.

Thin DB adapter — all decision logic is pure (rules.py / cluster.py / blocking.py).
Every decision row carries its featureset_version; identity stays auditable end to
end (repo invariant). No merge mutates person rows — clusters are computed views.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg

from substrate.er import rules as er_rules
from substrate.er.blocking import PersonRecord, candidate_pairs, email_domain, slugify
from substrate.er.cluster import MergeEdge, clusters
from substrate.er.rules import FEATURESET_VERSION, Decision, Outcome


@dataclass
class ErRunStats:
    persons_scanned: int
    candidates: int
    auto_merge: int
    review: int
    clusters: int


def tenant_id_by_name(conn: psycopg.Connection, name: str) -> Any:
    row = conn.execute("SELECT id FROM tenants WHERE name = %s", (name,)).fetchone()
    if row is None:
        raise SystemExit(f"tenant {name!r} not found — import first")
    return row[0]


def load_person_records(
    conn: psycopg.Connection, tenant_id: Any
) -> tuple[list[PersonRecord], dict[str, str]]:
    """Persons + current employer, keyed by person uuid-string."""
    rows = conn.execute(
        """
        SELECT p.id::text, p.emails, p.name_given, p.name_family,
               o.name_canonical, ext.system
        FROM persons p
        LEFT JOIN external_ids ext
               ON ext.entity_id = p.id AND ext.entity_type = 'person'
        LEFT JOIN LATERAL (
            SELECT o2.name_canonical
            FROM positions pos
            JOIN organizations o2 ON o2.id = pos.org_id
            WHERE pos.person_id = p.id AND pos.txn_to IS NULL
            LIMIT 1
        ) cur ON true
        WHERE p.tenant_id = %s AND p.erased_at IS NULL
        """,
        (tenant_id,),
    ).fetchall()

    persons: list[PersonRecord] = []
    for pid, emails, given, family, org_name, _system in rows:
        persons.append(
            PersonRecord(
                person_id=pid,
                emails=list(emails or []),
                name_given=given,
                name_family=family,
                employer_slug=slugify(org_name) if org_name else None,
                email_domain=email_domain(emails[0]) if emails else None,
            )
        )
    return persons, {p.person_id: p.person_id for p in persons}


def _auto_merge_edges(conn: psycopg.Connection, tenant_id: Any) -> list[MergeEdge]:
    rows = conn.execute(
        "SELECT cluster_a::text, cluster_b::text FROM merge_decisions "
        "WHERE tenant_id = %s AND decision = 'auto_merge'",
        (tenant_id,),
    ).fetchall()
    return [MergeEdge(left_id=a, right_id=b) for a, b in rows]


def run_er_v0(
    conn: psycopg.Connection,
    tenant_id: Any,
    *,
    dry_run: bool = False,
    decide_fn: Callable[[PersonRecord, PersonRecord], Outcome | None] = er_rules.decide,
) -> ErRunStats:
    persons, _ = load_person_records(conn, tenant_id)
    by_id = {p.person_id: p for p in persons}
    pairs = candidate_pairs(persons)

    auto = review = 0
    if not dry_run:
        existing = conn.execute(
            "SELECT 1 FROM merge_decisions "
            "WHERE tenant_id = %s AND featureset_version = %s LIMIT 1",
            (tenant_id, FEATURESET_VERSION),
        ).fetchone()
        if existing is not None:
            raise SystemExit(
                f"merge_decisions already carry {FEATURESET_VERSION} for this tenant — "
                "ER v0 is deterministic; a rerun would duplicate decisions"
            )

    for left_id, right_id in sorted(pairs):
        outcome = decide_fn(by_id[left_id], by_id[right_id])
        if outcome is None:
            continue
        if outcome.decision == Decision.AUTO_MERGE:
            auto += 1
        elif outcome.decision == Decision.REVIEW:
            review += 1
        if dry_run:
            continue
        conn.execute(
            "INSERT INTO merge_decisions "
            "(tenant_id, cluster_a, cluster_b, score, decision, featureset_version) "
            "VALUES (%s, %s::uuid, %s::uuid, %s, %s, %s)",
            (
                tenant_id,
                left_id,
                right_id,
                float(outcome.score),
                outcome.decision.value,
                FEATURESET_VERSION,
            ),
        )
        if outcome.decision == Decision.REVIEW:
            conn.execute(
                "INSERT INTO review_queue "
                "(tenant_id, left_person_id, right_person_id, score, featureset_version) "
                "VALUES (%s, %s::uuid, %s::uuid, %s, %s)",
                (tenant_id, left_id, right_id, float(outcome.score), FEATURESET_VERSION),
            )

    if dry_run:
        conn.commit()
        edges: list[MergeEdge] = []
    else:
        conn.commit()
        edges = _auto_merge_edges(conn, tenant_id)

    cluster_map = clusters([p.person_id for p in persons], edges)
    return ErRunStats(
        persons_scanned=len(persons),
        candidates=len(pairs),
        auto_merge=auto,
        review=review,
        clusters=len(set(cluster_map.values())),
    )


def cluster_map_for(conn: psycopg.Connection, tenant_id: Any) -> dict[str, str]:
    persons, _ = load_person_records(conn, tenant_id)
    edges = _auto_merge_edges(conn, tenant_id)
    return clusters([p.person_id for p in persons], edges)


def run_golden_sample(conn: psycopg.Connection, tenant_id: Any) -> str:
    from substrate.eval.golden import sample_pairs, write_worksheet

    persons, _ = load_person_records(conn, tenant_id)
    return write_worksheet(sample_pairs(persons))


def run_golden_eval(
    conn: psycopg.Connection, tenant_id: Any, worksheet_csv: str
) -> dict[str, Any]:
    from substrate.eval.golden import evaluate, read_worksheet

    persons, _ = load_person_records(conn, tenant_id)
    by_id = {p.person_id: p for p in persons}
    for pair in read_worksheet(worksheet_csv):
        if pair.left_id not in by_id or pair.right_id not in by_id:
            raise SystemExit(
                f"worksheet pair {pair.left_id}/{pair.right_id} not in tenant {tenant_id}"
            )
    report = evaluate(read_worksheet(worksheet_csv), persons, er_rules.decide)
    return report.as_dict()


def run_audit(conn: psycopg.Connection, tenant_name: str) -> tuple[dict[str, Any], str]:
    """Returns (report dict, rendered HTML)."""
    from substrate.audit.report import build_report, render_html

    tenant_id = tenant_id_by_name(conn, tenant_name)
    persons, _ = load_person_records(conn, tenant_id)
    report = build_report(tenant_name, persons, cluster_map_for(conn, tenant_id))
    return report.as_dict(), render_html(report)


def stats_json(stats: ErRunStats) -> str:
    return json.dumps(
        {
            "featureset_version": FEATURESET_VERSION,
            "persons_scanned": stats.persons_scanned,
            "candidates": stats.candidates,
            "auto_merge": stats.auto_merge,
            "review": stats.review,
            "clusters": stats.clusters,
        },
        indent=2,
    )


def main(argv: list[str] | None = None) -> int:  # pragma: no cover — CLI smoke only
    parser = argparse.ArgumentParser(prog="substrate-er")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    conn = psycopg.connect(args.database_url)
    try:
        tenant_id = tenant_id_by_name(conn, args.tenant)
        print(stats_json(run_er_v0(conn, tenant_id, dry_run=args.dry_run)))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

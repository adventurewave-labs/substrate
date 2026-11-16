"""Job-change detection: position snapshots → typed SignalEvents.

The store already versions positions bitemporally (``store.upsert_position``
closes the old version and opens the new one on every re-import). Detection is a
pure diff across those versions: an org change is a ``job_change``, a seniority
increase at the same org is a ``promotion``, anything else is silence — noise is
the enemy of trust (PRD: one false alert mutes the channel forever).

No LLM, no learned model in this path. The ER scorer (PLAN §4) ranks *identity*
candidates; it has no bearing on whether a known person changed jobs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import psycopg

from substrate.seniority import SENIORITY_RANK


@dataclass(frozen=True)
class PositionSnapshot:
    person_id: str
    position_id: str
    org_id: str
    org_name: str | None
    title_norm: str | None
    seniority: str | None


@dataclass(frozen=True)
class Signal:
    event_type: str          # 'job_change' | 'promotion'
    person_id: str
    old_state: dict[str, Any]
    new_state: dict[str, Any]
    confidence: float
    idempotency_key: str
    provenance_refs: list[str] = field(default_factory=list)  # backing position ids

    @property
    def key(self) -> str:
        return self.idempotency_key


def diff_positions(old: PositionSnapshot, new: PositionSnapshot) -> Signal | None:
    """Diff two snapshots of one person. None = no signal (silence is correct)."""
    old_state = {
        "position_id": old.position_id, "org_id": old.org_id,
        "org_name": old.org_name, "title": old.title_norm, "seniority": old.seniority,
    }
    new_state = {
        "position_id": new.position_id, "org_id": new.org_id,
        "org_name": new.org_name, "title": new.title_norm, "seniority": new.seniority,
    }

    if old.org_id != new.org_id:
        key_source = f"job_change:{new.person_id}:{new.position_id}"
        return Signal(
            event_type="job_change",
            person_id=new.person_id,
            old_state=old_state,
            new_state=new_state,
            confidence=1.0,  # first-party CRM diff; feed-derived lowers this later
            idempotency_key=hashlib.sha256(key_source.encode()).hexdigest(),
            provenance_refs=[old.position_id, new.position_id],
        )

    old_rank = SENIORITY_RANK.get(old.seniority or "", None)
    new_rank = SENIORITY_RANK.get(new.seniority or "", None)
    if (
        old_rank is not None
        and new_rank is not None
        and new_rank > old_rank
        and (old.title_norm or "") != (new.title_norm or "")
    ):
        key_source = f"promotion:{new.person_id}:{new.position_id}"
        return Signal(
            event_type="promotion",
            person_id=new.person_id,
            old_state=old_state,
            new_state=new_state,
            confidence=1.0,
            idempotency_key=hashlib.sha256(key_source.encode()).hexdigest(),
            provenance_refs=[old.position_id, new.position_id],
        )

    return None  # lateral retitle, unknown bands, no-op: silence


@dataclass
class DetectStats:
    persons_scanned: int = 0  # distinct persons with a diffed pair (final count)
    persons_scanned_ids: set[str] = field(default_factory=set)
    pairs_diffed: int = 0
    job_changes: int = 0
    promotions: int = 0
    events_written: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "persons_scanned": self.persons_scanned,
            "pairs_diffed": self.pairs_diffed,
            "job_changes": self.job_changes,
            "promotions": self.promotions,
            "events_written": self.events_written,
        }


# Consecutive-version diffing (gate review, W7–8 round 2): EVERY adjacent pair
# in a person's version chain is diffed, keyed by the NEWER position id. This is
# what preserves recall when a move AND a retitle land between two detection
# runs — the move's pair was never reported, and it still fires — while the
# events table's unique key suppresses anything already reported. Pairing only
# the latest closed version (the round-1 fix) silently dropped such moves.
_PAIR_SQL = """
SELECT cur.person_id::text,
       cur.prev_id::text,       cur.prev_org_id::text, o1.name_canonical,
       cur.prev_title,          cur.prev_seniority,
       cur.id::text,            cur.org_id::text,      o2.name_canonical,
       cur.title_norm,          cur.seniority
FROM (
    SELECT p.id, p.person_id, p.org_id, p.title_norm, p.seniority, p.txn_from,
           p.valid_start,
           LAG(p.id) OVER w AS prev_id,
           LAG(p.org_id) OVER w AS prev_org_id,
           LAG(p.title_norm) OVER w AS prev_title,
           LAG(p.seniority) OVER w AS prev_seniority
    FROM positions p
    WHERE p.tenant_id = %s
    WINDOW w AS (PARTITION BY p.person_id
                 ORDER BY p.txn_from, p.valid_start, p.id)
) cur
JOIN organizations o1 ON o1.id = cur.prev_org_id
JOIN organizations o2 ON o2.id = cur.org_id
WHERE cur.prev_id IS NOT NULL
ORDER BY cur.person_id, cur.txn_from, cur.valid_start, cur.id
"""


def detect_for_tenant(
    conn: psycopg.Connection,
    tenant_id: Any,
    *,
    dry_run: bool = False,
    commit: bool = True,
    first_run: bool | None = None,
) -> DetectStats:
    """Diff each person's immediately-preceding closed position against the open
    one; write typed events.

    Idempotent by construction: the idempotency key is a function of (signal type,
    person, new position id), and the events table enforces uniqueness per
    (tenant, key). Re-running detects the same pairs and writes nothing new.

    ``commit=False`` (canary replay) writes inside the caller's transaction so the
    rollback discards everything — canaries never touch the tenant graph.

    Auto-first-run (``first_run=None``, the default): a tenant with NO prior row
    in detect_runs is on its FIRST run — its whole backlog records as already
    delivered (the moves predate our watching), while every LATER run alerts on
    genuinely new moves. ``first_run=True`` forces suppression; ``False`` forces
    alerting. The decision lives HERE so every caller and every test exercises
    identical semantics (gate r15: CLI-only logic was untestable).
    """
    stats = DetectStats()
    prior_run = conn.execute(
        "SELECT 1 FROM detect_runs WHERE tenant_id = %s LIMIT 1", (tenant_id,)
    ).fetchone() is not None
    # Contract (documented in the docstring): first_run=None → AUTO (suppress on
    # a true first run); True → FORCE suppression regardless of history;
    # False → force alerting. The explicit modes always win.
    if first_run is None:
        suppress_backlog = not prior_run
    else:
        suppress_backlog = first_run
    rows = conn.execute(_PAIR_SQL, (tenant_id,)).fetchall()

    for row in rows:
        (
            person_id,
            old_pos, old_org, old_org_name, old_title, old_seniority,
            new_pos, new_org, new_org_name, new_title, new_seniority,
        ) = row
        stats.persons_scanned_ids.add(person_id)
        stats.pairs_diffed += 1  # every pair IS diffed, not just the firing ones
        old_snap = PositionSnapshot(
            person_id, old_pos, old_org, old_org_name, old_title, old_seniority
        )
        new_snap = PositionSnapshot(
            person_id, new_pos, new_org, new_org_name, new_title, new_seniority
        )
        signal = diff_positions(old_snap, new_snap)
        if signal is None:
            continue
        if signal.event_type == "job_change":
            stats.job_changes += 1
        else:
            stats.promotions += 1
        if dry_run:
            continue
        # Auto-first-run: on the tenant's first detection run the backlog is
        # RECORDED but not alerted — the moves predate our watching (gate r4
        # finding 2 + r14/r15 semantics fix).
        delivered_expr = "now()" if suppress_backlog else "NULL"
        written = conn.execute(
            "INSERT INTO events "
            "(tenant_id, event_type, entity_id, old_state, new_state, confidence, "
            " provenance_refs, idempotency_key, delivered_at) "
            f"VALUES (%s, %s, %s::uuid, %s, %s, %s, %s::uuid[], %s, {delivered_expr}) "
            "ON CONFLICT (tenant_id, idempotency_key) DO NOTHING "
            "RETURNING id",
            (
                tenant_id,
                signal.event_type,
                signal.person_id,
                json.dumps(signal.old_state),
                json.dumps(signal.new_state),
                signal.confidence,
                [old_pos, new_pos],  # provenance: the positions backing the event
                signal.key,
            ),
        ).fetchone()
        if written is not None:
            stats.events_written += 1

    stats.persons_scanned = len(stats.persons_scanned_ids)
    if not dry_run:
        conn.execute(
            "INSERT INTO detect_runs (tenant_id) VALUES (%s) "
            "ON CONFLICT (tenant_id) DO NOTHING",
            (tenant_id,),
        )
    if commit:
        conn.commit()
    return stats

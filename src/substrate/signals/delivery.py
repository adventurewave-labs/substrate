"""Event delivery: pending SignalEvents → sinks (Slack webhook today).

At-least-once semantics: the event row is the truth; `delivered_at` marks sink
success. The Slack sink is env-configured (SUBSTRATE_SLACK_WEBHOOK_URL) and a
no-op when unset — the dispatcher reports honestly what was skipped and why.
Rendering uses ONLY the event's stored states: no enrichment, no invention.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import psycopg

Transport = Callable[[urllib.request.Request], tuple[int, bytes]]

# Retired events (attempts exhausted) stay pending in the audit trail but
# the batch skips them so they can never pin the oldest-first queue head.
MAX_DELIVERY_ATTEMPTS = 5


def _stdlib_transport(request: urllib.request.Request) -> tuple[int, bytes]:
    with urllib.request.urlopen(request, timeout=15) as resp:  # noqa: S310 — env-configured webhook
        return resp.status, resp.read()


@dataclass
class PendingEvent:
    event_id: str
    event_type: str
    person_name: str | None
    old_state: dict[str, Any]
    new_state: dict[str, Any]
    detected_at: str


@dataclass
class DeliveryStats:
    delivered: int = 0
    failed: int = 0
    skipped_not_configured: int = 0
    skipped_orphan: int = 0  # events whose person row is gone (erasure cascade)
    retired_exhausted: int = 0  # delivery_attempts exhausted; audit-visible, not sent
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "delivered": self.delivered,
            "failed": self.failed,
            "skipped_not_configured": self.skipped_not_configured,
            "skipped_orphan": self.skipped_orphan,
            "retired_exhausted": self.retired_exhausted,
            "max_delivery_attempts": MAX_DELIVERY_ATTEMPTS,
            "errors": self.errors,
        }


def _slack_escape(text: str) -> str:
    """Escape untrusted text for Slack mrkdwn: & < > carry control meaning
    (<!channel> pings and disguised links die here). Slack mrkdwn has NO
    backslash escapes — formatting characters are left alone rather than
    rendering as visible backslashes (gate review, W7–8 round 10)."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def render_slack_message(event: PendingEvent) -> dict[str, Any]:
    """Slack payload from the event's OWN states — nothing invented, everything
    escaped: title/org/name text is untrusted input (gate review, W7–8 r6)."""
    old_org = _slack_escape(event.old_state.get("org_name") or "unknown")
    new_org = _slack_escape(event.new_state.get("org_name") or "unknown")
    old_title = _slack_escape(event.old_state.get("title") or "unknown title")
    new_title = _slack_escape(event.new_state.get("title") or "unknown title")
    who = _slack_escape(event.person_name or "a tracked champion")
    if event.event_type == "job_change":
        headline = f":rotating_light: {who} changed jobs"
        detail = f"{old_title} @ {old_org} → {new_title} @ {new_org}"
    else:
        headline = f":arrow_up: {who} was promoted"
        detail = f"{old_title} → {new_title} @ {new_org}"
    return {
        "text": f"{headline}\n{detail}\nDetected: {event.detected_at} · "
        "Substrate: provenance-backed signal, react 👍/👎 to grade it",
    }


class SlackWebhookSink:
    """Slack incoming-webhook sink. Transport-injected for tests."""

    def __init__(
        self,
        webhook_url: str | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.url = webhook_url or os.environ.get("SUBSTRATE_SLACK_WEBHOOK_URL", "")
        self.transport = transport or _stdlib_transport
        self.configured = bool(self.url)

    def deliver(self, payload: dict[str, Any]) -> bool:
        if not self.configured:
            return False
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        status, _ = self.transport(request)
        return 200 <= status < 300


def deliver_pending(
    conn: psycopg.Connection,
    tenant_id: Any,
    sink: SlackWebhookSink | None,
    *,
    limit: int = 100,
    now: datetime | None = None,
) -> DeliveryStats:
    """Deliver pending events (oldest first); mark delivered_at on sink success.

    At-least-once: a sink failure leaves the event pending for the next run —
    the DB row is the truth, never the webhook.

    Connection contract: call on a connection whose own work is already committed
    (detector commits before returning). Delivery commits per delivered event —
    savepoint-nesting here would silently drop `delivered_at` and re-send every
    alert on every run (gate review, W7–8 r3+r4).
    """
    stats = DeliveryStats()
    if sink is None or not sink.configured:
        row = conn.execute(
            "SELECT count(*) FROM events WHERE tenant_id = %s AND delivered_at IS NULL",
            (tenant_id,),
        ).fetchone()
        stats.skipped_not_configured = int(row[0]) if row else 0
        return stats

    rows = conn.execute(
        """
        SELECT e.id::text, e.event_type, p.name_full,
               e.old_state, e.new_state, e.detected_at
        FROM events e
        LEFT JOIN persons p
               ON p.id = e.entity_id AND p.tenant_id = e.tenant_id
        WHERE e.tenant_id = %s
          AND e.delivered_at IS NULL
          -- Undeliverables are excluded here so the oldest-first LIMIT can
          -- never be pinned: orphans (person erased) retire via SQL, exhausted
          -- events via the attempts counter. Both counted in the report.
          AND p.id IS NOT NULL
          AND e.delivery_attempts < %s
        ORDER BY e.detected_at ASC
        LIMIT %s
        """,
        (tenant_id, MAX_DELIVERY_ATTEMPTS, limit),
    ).fetchall()

    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
    orphan_count = conn.execute(
        "SELECT count(*) FROM events e LEFT JOIN persons p "
        "ON p.id = e.entity_id AND p.tenant_id = e.tenant_id "
        "WHERE e.tenant_id = %s AND e.delivered_at IS NULL AND p.id IS NULL",
        (tenant_id,),
    ).fetchone()
    stats.skipped_orphan = int(orphan_count[0]) if orphan_count else 0
    retired_count = conn.execute(
        "SELECT count(*) FROM events e WHERE e.tenant_id = %s "
        "AND e.delivered_at IS NULL AND e.delivery_attempts >= %s",
        (tenant_id, MAX_DELIVERY_ATTEMPTS),
    ).fetchone()
    stats.retired_exhausted = int(retired_count[0]) if retired_count else 0

    for row in rows:
        event_id, event_type, person_name, old_state, new_state, detected_at = row
        pending = PendingEvent(
            event_id=event_id,
            event_type=event_type,
            person_name=person_name,
            old_state=old_state if isinstance(old_state, dict) else {},
            new_state=new_state if isinstance(new_state, dict) else {},
            detected_at=(
                detected_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
                if detected_at
                else stamp
            ),
        )
        try:
            ok = sink.deliver(render_slack_message(pending))
        except Exception as exc:  # noqa: BLE001 — delivery failures must not abort the batch
            ok = False
            stats.failed += 1
            # Type only: urllib errors can embed the webhook URL (a secret in the
            # report file would leak it).
            stats.errors.append(f"{event_id}: {type(exc).__name__}")
            conn.execute(
                "UPDATE events SET delivery_attempts = delivery_attempts + 1 "
                "WHERE id = %s::uuid AND tenant_id = %s",
                (event_id, tenant_id),
            )
            conn.commit()
            continue
        if ok:
            conn.execute(
                "UPDATE events SET delivered_at = now() "
                "WHERE id = %s::uuid AND tenant_id = %s",
                (event_id, tenant_id),
            )
            # EXPLICIT commit per event: a transaction()-block here would be
            # savepoint-only on a normal connection (the initial SELECT already
            # opened one), so delivered_at would never persist and every run
            # would re-send every alert (gate review, W7–8 r3+r4).
            conn.commit()
            stats.delivered += 1
        else:
            stats.failed += 1
            conn.execute(
                "UPDATE events SET delivery_attempts = delivery_attempts + 1 "
                "WHERE id = %s::uuid AND tenant_id = %s",
                (event_id, tenant_id),
            )
            conn.commit()
            stats.errors.append(f"{event_id}: sink returned failure")
    return stats

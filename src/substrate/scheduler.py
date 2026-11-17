"""Scheduler (W9 housekeeping): one bounded cycle per tenant, on a loop.

Replaces the Railway placeholder's `sleep infinity` (PLAN §1 deviation follow-up).
v1 cycle per tenant: careers crawl → detect → deliver. EDGAR/press stay
operator-triggered (`substrate crawl`) — they need date windows and feed URLs,
not a timer.

Error isolation is the contract: one tenant's failure never stops the others,
and every failure lands in the cycle report. The loop is stoppable (graceful
shutdown on SIGTERM via `stop()`), and `run_once` exists for tests and manual
cycles.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import psycopg

from substrate.signals.delivery import SlackWebhookSink, deliver_pending
from substrate.signals.detector import detect_for_tenant
from substrate.sources.careers import crawl_careers
from substrate.sources.http import Fetcher, FetchFailed, RobotsDisallowed
from substrate.sources.writer import WriteStats


@dataclass
class TenantCycleReport:
    tenant: str
    careers_boards_ok: int = 0
    careers_boards_failed: int = 0
    postings_written: int = 0
    job_changes_detected: int = 0
    events_delivered: int = 0
    delivery_unconfigured: int = 0  # pending events, tenant webhook not set
    stats: WriteStats = field(default_factory=WriteStats)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant": self.tenant,
            "careers_boards_ok": self.careers_boards_ok,
            "careers_boards_failed": self.careers_boards_failed,
            "postings_written": self.postings_written,
            "job_changes_detected": self.job_changes_detected,
            "events_delivered": self.events_delivered,
            "delivery_unconfigured": self.delivery_unconfigured,
            "error": self.error,
        }


@dataclass
class CycleReport:
    tenants: int = 0
    errors: int = 0
    per_tenant: dict[str, dict[str, Any]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenants": self.tenants,
            "errors": self.errors,
            "per_tenant": self.per_tenant,
        }


def _tenant_cycles(conn: psycopg.Connection) -> list[tuple[Any, str]]:
    rows = conn.execute("SELECT id, name FROM tenants ORDER BY name").fetchall()
    return [(r[0], r[1]) for r in rows]


def _careers_cycle_isolated(
    conn: psycopg.Connection,
    tenant_id: Any,
    fetcher: Fetcher,
    report: TenantCycleReport,
) -> None:
    """Careers crawl per WATCH DOMAIN — postings are never merged across
    domains: two watched companies sharing a platform must each keep their own
    postings and their own hiring snapshot (gate review, W9 r1). Boards fail in
    isolation; a failed board's (domain, platform) pair skips reconciliation
    only."""
    from datetime import UTC, datetime

    from substrate.sources.writer import (
        WriteStats,
        persist_postings,
        write_hiring_activity_claim,
    )

    now = datetime.now(UTC)
    # (domain, platform) → postings; failures tracked per pair.
    # Phase 1 — crawl per (domain, platform); failures tracked per pair.
    batches: dict[tuple[str, str], list[dict[str, Any]]] = {}
    failed: set[tuple[str, str]] = set()

    watch_rows = conn.execute(
        "SELECT domain, greenhouse_board, lever_board, ashby_board "
        "FROM watch_sources WHERE tenant_id = %s ORDER BY domain",
        (tenant_id,),
    ).fetchall()
    for row in watch_rows:
        domain, gh, lever, ashby = row
        for platform, token in (
            ("greenhouse", gh),
            ("lever", lever),
            ("ashby", ashby),
        ):
            if not token:
                continue
            try:
                postings = crawl_careers(fetcher, board=token, platform=platform)
            except (RobotsDisallowed, FetchFailed, ValueError):
                report.careers_boards_failed += 1
                failed.add((domain, platform))  # snapshot unknown: no reconcile
                continue
            report.careers_boards_ok += 1
            batches[(domain, platform)] = postings

    # Phase 2 — anchor domain → org, then AGGREGATE by (org, platform): a
    # multi-domain org's boards persist as ONE merged batch, or per-domain
    # reconciliation closes the other domain's live postings (gate review, W9).
    org_platforms: dict[tuple[Any, str], list[dict[str, Any]]] = {}
    incomplete: set[tuple[Any, str]] = set()
    for (domain, platform), postings in batches.items():
        org_row = conn.execute(
            "SELECT id FROM organizations WHERE tenant_id = %s AND %s = ANY(domains) LIMIT 1",
            (tenant_id, domain),
        ).fetchone()
        if org_row is None:
            org_row = conn.execute(
                "INSERT INTO organizations (tenant_id, name_canonical, domains) "
                "VALUES (%s, %s, %s) RETURNING id",
                (tenant_id, domain, [domain]),
            ).fetchone()
            assert org_row is not None
        org_id = org_row[0]
        key = (org_id, platform)
        org_platforms.setdefault(key, []).extend(postings)

    # Phase 2b — FAILED pairs also resolve to orgs, and their aggregates are
    # marked incomplete: a failed board's old postings share the (org, platform)
    # aggregate with the successful board's, and an un-fetched board's snapshot
    # is unknown — reconcile would close its live postings (W9 r2). Failed
    # domains that resolve to no org are simply dropped (nothing to protect).
    for (domain, platform) in sorted(failed):
        org_row = conn.execute(
            "SELECT id FROM organizations WHERE tenant_id = %s AND %s = ANY(domains) LIMIT 1",
            (tenant_id, domain),
        ).fetchone()
        if org_row is not None:
            incomplete.add((org_row[0], platform))

    # Phase 3 — persist per (org, platform); reconcile only COMPLETE batches.
    for (org_id, platform), merged in sorted(org_platforms.items()):
        post_stats = WriteStats()
        persist_postings(
            conn, tenant_id, org_id, merged,
            source_type=platform, retrieved_at=now, stats=post_stats,
            reconcile=(org_id, platform) not in incomplete,
        )
        report.postings_written += post_stats.postings_written

    # Phase 4 — one hiring snapshot per ORG (aggregated across all boards).
    for org_id in sorted({org for (org, _p) in org_platforms}, key=str):
        write_hiring_activity_claim(conn, tenant_id, org_id, stats=report.stats)


def run_cycle_for_tenant(
    conn: psycopg.Connection,
    tenant_id: Any,
    tenant_name: str,
    fetcher: Fetcher,
    report: TenantCycleReport,
) -> None:
    """One tenant: crawl → detect → deliver (to the tenant's OWN webhook —
    delivery destinations are per-tenant; a global webhook would route every
    tenant's alerts to one Slack, breaking tenant isolation). Careers failures
    are isolated; a detection or delivery failure aborts THIS tenant's cycle
    (recorded in the report) but not others'."""
    try:
        _careers_cycle_isolated(conn, tenant_id, fetcher, report)
        detect_stats = detect_for_tenant(conn, tenant_id, first_run=None)
        report.job_changes_detected = detect_stats.job_changes + detect_stats.promotions
        sink_row = conn.execute(
            "SELECT slack_webhook_url FROM tenants WHERE id = %s", (tenant_id,)
        ).fetchone()
        tenant_webhook = sink_row[0] if sink_row else None
        sink = SlackWebhookSink(webhook_url=tenant_webhook) if tenant_webhook else None
        delivery = deliver_pending(conn, tenant_id, sink)
        report.events_delivered = delivery.delivered
        if sink is None:
            report.delivery_unconfigured = delivery.skipped_not_configured
    except Exception as exc:  # noqa: BLE001 — isolation IS the contract here
        report.error = f"{type(exc).__name__}: {exc}"
        conn.rollback()


def run_cycle_all(
    conn: psycopg.Connection,
    fetcher: Fetcher,
) -> CycleReport:
    """One full cycle across every tenant, isolating failures per tenant.
    Delivery destinations resolve per tenant (tenants.slack_webhook_url)."""
    report = CycleReport()
    for tenant_id, tenant_name in _tenant_cycles(conn):
        report.tenants += 1
        tenant_report = TenantCycleReport(tenant=tenant_name)
        run_cycle_for_tenant(conn, tenant_id, tenant_name, fetcher, tenant_report)
        # Board failures count toward cycle failure status (W9 r2): `scheduler
        # --once` must exit nonzero when boards died even without an exception.
        if tenant_report.error or tenant_report.careers_boards_failed:
            report.errors += 1
        report.per_tenant[tenant_name] = tenant_report.as_dict()
    return report


def _log_cycle_result(log: Callable[[str], None], message: str) -> None:
    """Logging failures must never stop the scheduler: fall back to stderr
    (gate review, W9 — a broken log file killed the loop from the success
    path, and the error handler re-raised it through the same broken logger)."""
    try:
        log(message)
    except Exception:  # noqa: BLE001
        import sys

        print(message, file=sys.stderr)


def run_forever(
    cycle: Callable[[], CycleReport],
    *,
    interval_seconds: int,
    stop: Callable[[], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> None:
    """Run the cycle on an interval until `stop()` returns True (checked between
    cycles — a SIGTERM handler flips the flag; the in-flight cycle completes)."""
    while stop is None or not stop():
        started = time.monotonic()
        try:
            report = cycle()
            message = f"cycle: {report.errors} errors across {report.tenants} tenants"
        except Exception as exc:  # noqa: BLE001 — the loop outlives any cycle
            report = CycleReport()
            message = f"cycle FAILED: {type(exc).__name__}: {exc}"
        _log_cycle_result(log, message)
        elapsed = time.monotonic() - started
        remaining = interval_seconds - elapsed
        if remaining > 0:
            # Sleep in slices so a stop signal is honored mid-sleep.
            waited = 0.0
            while waited < remaining and (stop is None or not stop()):
                slice_seconds = min(5.0, remaining - waited)
                sleep(slice_seconds)
                waited += slice_seconds

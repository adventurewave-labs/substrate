"""Crawl orchestration: fetch → parse → anchor (deterministic) → persist.

Plain deterministic functions + checkpoint reuse — Dagster was the PLAN §1 ruling,
but it does not wheel for Python 3.14 yet; deviation recorded in PLAN §1. The
functions here wrap into Dagster assets unchanged when that lands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import psycopg

from substrate.sources.careers import crawl_careers
from substrate.sources.edgar import crawl_edgar
from substrate.sources.http import Fetcher, FetchFailed, RobotsDisallowed
from substrate.sources.llm import LlmGateway
from substrate.sources.press import extract_funding_events, funding_candidates
from substrate.sources.writer import (
    AmbiguousAnchorError,
    WriteStats,
    find_org_by_domain,
    persist_funding_events,
    persist_postings,
    resolve_org_by_domain,
    supersede_claim,
    write_hiring_activity_claim,
)
from substrate.store import slugify

_HOSTNAME_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$"
)


def normalize_domain(value: str) -> str | None:
    """LLM-supplied domain → bare hostname, or None. Deterministic validation:
    scheme/path stripping, www removal, hostname syntax check. Junk in, None out —
    junk never becomes an org."""
    v = value.strip().lower()
    if "://" in v:
        v = urlparse(v).netloc
    v = v.split("/")[0].strip(".")
    if v.startswith("www."):
        v = v[4:]
    if not _HOSTNAME_RE.match(v):
        return None
    return v


def name_corroborated(name: str, title: str) -> bool:
    """Deterministic guard for the name-slug fallback: the LLM-supplied company
    name must appear (word-bounded) in the source title before a slug match may
    attach a claim to an existing org. Same principle as domain corroboration:
    hallucinated names cannot steer claims onto real customers."""
    n = name.strip().lower()
    if not n:
        return False
    pattern = re.compile(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])")
    return bool(pattern.search(title.lower()))


def domain_corroborated(domain: str, title: str, url: str = "") -> bool:
    """Deterministic corroboration before an LLM-extracted domain may attach a
    claim to an EXISTING org. Two precise paths (PR #5 review round 3):
      * URL host equality: the article URL's host IS the domain or its subdomain;
      * title word-boundary match: the full domain appears with non-domain
        characters on both sides — "notacme.com" cannot corroborate "acme.com",
        and a claimed victim.co.uk cannot ride on an example.co.uk URL host."""
    d = normalize_domain(domain)
    if not d:
        return False
    if url:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if host == d or host.endswith("." + d):
            return True
    if title:
        pattern = re.compile(r"(?<![a-z0-9.-])" + re.escape(d) + r"(?![a-z0-9.-])")
        if pattern.search(title.lower()):
            return True
    return False


@dataclass
class CrawlReport:
    source: str
    stats: WriteStats = field(default_factory=WriteStats)
    watched_orgs: int = 0
    boards_crawled: int = 0
    boards_failed: int = 0
    events_seen: int = 0
    truncated_events: int = 0
    skipped_unanchored: int = 0
    would_create: int = 0
    anchor_errors: int = 0

    def as_dict(self) -> dict[str, Any]:
        # stats carries its own skipped_unanchored (draft-level); report-level event
        # skips are merged here so the CLI JSON shows the TRUE total, not the stats
        # value clobbering it (round-3 gate review).
        stats = {
            k: v for k, v in self.stats.as_dict().items() if k != "skipped_unanchored"
        }
        return {
            "source": self.source,
            "watched_orgs": self.watched_orgs,
            "boards_crawled": self.boards_crawled,
            "boards_failed": self.boards_failed,
            "events_seen": self.events_seen,
            "truncated_events": self.truncated_events,
            "skipped_unanchored": self.skipped_unanchored + self.stats.skipped_unanchored,
            "would_create": self.would_create,
            "anchor_errors": self.anchor_errors,
            **stats,
        }


def _org_slug_index(conn: psycopg.Connection, tenant_id: Any) -> dict[str, list[Any]]:
    index: dict[str, list[Any]] = {}
    for row in conn.execute(
        "SELECT id, name_canonical FROM organizations WHERE tenant_id = %s", (tenant_id,)
    ).fetchall():
        index.setdefault(slugify(row[1] or ""), []).append(row[0])
    return index


def watch_rows(conn: psycopg.Connection, tenant_id: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT domain, greenhouse_board, lever_board, ashby_board, sec_cik "
        "FROM watch_sources WHERE tenant_id = %s ORDER BY domain",
        (tenant_id,),
    ).fetchall()
    return [
        {
            "domain": r[0],
            "greenhouse_board": r[1],
            "lever_board": r[2],
            "ashby_board": r[3],
            "sec_cik": r[4],
        }
        for r in rows
    ]


def crawl_careers_for_tenant(
    conn: psycopg.Connection,
    tenant_id: Any,
    fetcher: Fetcher,
    *,
    dry_run: bool = False,
) -> CrawlReport:
    """Every configured careers board → postings + hiring_activity claim.
    One dead board (robots, 404, network) is counted and skipped — it never kills
    the tenant crawl (PR #5 review round 1, finding 7)."""
    report = CrawlReport(source="careers")
    now = datetime.now(UTC)
    # Phase 1 — crawl every board, MERGING postings per (domain, platform) across
    # watch rows: two domains can resolve to the SAME org (acme.com + acme.io in
    # one CRM org), and per-row reconciliation would flip-flop their postings
    # forever (round-6 gate review).
    per_domain: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in watch_rows(conn, tenant_id):
        report.watched_orgs += 1
        domain = row["domain"]
        for platform, board_key in (
            ("greenhouse", "greenhouse_board"),
            ("lever", "lever_board"),
            ("ashby", "ashby_board"),
        ):
            board = row.get(board_key)
            if not board:
                continue
            try:
                postings = crawl_careers(fetcher, board=board, platform=platform)
            except (RobotsDisallowed, FetchFailed, ValueError):
                report.boards_failed += 1
                continue
            report.boards_crawled += 1
            report.events_seen += len(postings)
            per_domain.setdefault(domain, {}).setdefault(platform, []).extend(postings)

    if dry_run:
        return report

    # Phase 2 — anchor, merge across domains into (org, platform) batches, persist
    # once per batch, reconcile once per (org, platform), then one claim per org.
    org_platform: dict[tuple[Any, str], list[dict[str, Any]]] = {}
    orgs_seen: set[Any] = set()
    for domain, platforms in per_domain.items():
        try:
            org_id, created = resolve_org_by_domain(conn, tenant_id, domain)
        except AmbiguousAnchorError:
            report.anchor_errors += 1  # two orgs claim the domain — ER decides, not us
            continue
        report.stats.orgs_created += int(created)
        orgs_seen.add(org_id)
        for platform, postings in platforms.items():
            org_platform.setdefault((org_id, platform), []).extend(postings)

    for (org_id, platform), merged in org_platform.items():
        persist_postings(
            conn, tenant_id, org_id, merged,
            source_type=platform, retrieved_at=now, stats=report.stats,
        )
    for org_id in orgs_seen:
        write_hiring_activity_claim(conn, tenant_id, org_id, stats=report.stats)
    conn.commit()
    return report


def crawl_edgar_for_tenant(
    conn: psycopg.Connection,
    tenant_id: Any,
    fetcher: Fetcher,
    *,
    start: date | None = None,
    end: date | None = None,
    dry_run: bool = False,
) -> CrawlReport:
    """Form D filings in a window → funding events, anchored by exact name-slug
    match against the tenant's orgs; ambiguous or unmatched events are counted and
    skipped, never guessed."""
    report = CrawlReport(source="edgar")
    end = end or date.today()
    start = start or (end - timedelta(days=30))
    events, total = crawl_edgar(fetcher, start=start, end=end)
    report.events_seen = len(events)
    report.truncated_events = max(0, total - len(events))  # pagination is honest

    slug_index = _org_slug_index(conn, tenant_id)
    cik_map, conflicting_ciks = _cik_org_map(conn, tenant_id, dry_run=dry_run, stats=report.stats)
    now = datetime.now(UTC)
    for event in events:
        cik = str(event.get("cik") or "")
        key = cik.lstrip("0") if cik else ""
        if key and key in conflicting_ciks:
            # Known-ambiguous identity: skip before any fallback — a unique name
            # slug must not rescue an event whose CIK is contested (round-4 review).
            report.anchor_errors += 1
            continue
        org_id = cik_map.get(key) if key else None
        if org_id is None:
            matches = slug_index.get(slugify(event["company_name"]), [])
            if len(matches) == 1:
                org_id = matches[0]
        if org_id is None:
            report.skipped_unanchored += 1
            continue
        if dry_run:
            continue
        persist_funding_events(
            conn,
            tenant_id,
            org_id,
            [{**event, "source_type": "edgar", "retrieved_at": now}],
            stats=report.stats,
        )
    if not dry_run:
        conn.commit()
    return report


def _cik_org_map(
    conn: psycopg.Connection, tenant_id: Any, *, dry_run: bool, stats: WriteStats
) -> tuple[dict[str, Any], set[str]]:
    """watch_sources.sec_cik → (org map, conflicting-cik keys). Conflicting CIKs
    (two domains claiming one CIK) are ambiguous identity — removed from the map
    and returned so callers skip their events, never resolved by sort order."""
    mapping: dict[str, Any] = {}
    conflicts: set[str] = set()
    from substrate.sources.writer import count_orgs_by_domain

    for row in watch_rows(conn, tenant_id):
        cik = (row.get("sec_cik") or "").strip().lstrip("0")
        if not cik:
            continue
        try:
            org = find_org_by_domain(conn, tenant_id, row["domain"])
            if org is None and not dry_run:
                org, created = resolve_org_by_domain(conn, tenant_id, row["domain"])
                stats.orgs_created += int(created)
            elif org is None and dry_run:
                # Dry-run must reach the SAME ambiguity verdicts as real runs —
                # find_org_by_domain returns None for ambiguous AND absent, so
                # probe the count (round-5 gate review).
                if count_orgs_by_domain(conn, tenant_id, row["domain"]) > 1:
                    conflicts.add(cik)
                continue
        except AmbiguousAnchorError:
            conflicts.add(cik)
            continue
        if org is None:
            continue
        if cik in mapping and mapping[cik] != org:
            conflicts.add(cik)
        mapping[cik] = org
    for cik in conflicts:
        mapping.pop(cik, None)
    return mapping, conflicts


def crawl_press_for_tenant(
    conn: psycopg.Connection,
    tenant_id: Any,
    fetcher: Fetcher,
    llm: LlmGateway,
    feed_url: str,
    *,
    dry_run: bool = False,
) -> CrawlReport:
    """Press feed → LLM extracts → anchor by domain (creates: press discovers new
    companies) or exact name-slug (ambiguous → skipped). Unanchorable: counted.
    Funding-event URLs are the REAL article URLs (stamped from the feed item, never
    LLM output) — provenance invariant (PR #5 review round 1)."""
    report = CrawlReport(source="press")
    extracts, press_stats = extract_funding_events(
        fetcher, llm, feed_url, persist_cache=not dry_run
    )
    report.events_seen = press_stats.candidates

    slug_index = _org_slug_index(conn, tenant_id)
    now = datetime.now(UTC)
    for extract in extracts:
        org_id: Any | None = None
        created = False
        domain = normalize_domain(extract.domain) if extract.domain else None
        if domain:
            existing = find_org_by_domain(conn, tenant_id, domain)
            if existing is not None:
                # Attach to a KNOWN org only with deterministic corroboration — a
                # hallucinated domain must not steer claims onto a real customer.
                if domain_corroborated(domain, extract.source_title, extract.source_url):
                    org_id = existing
            elif not dry_run:
                try:
                    org_id, created = resolve_org_by_domain(
                        conn, tenant_id, domain, display_name=extract.company_name
                    )
                except AmbiguousAnchorError:
                    report.anchor_errors += 1
                    continue  # ambiguous identity: skip this item, keep the run alive
                report.stats.orgs_created += int(created)
            else:
                # find_org_by_domain returned None for absent AND ambiguous — probe
                # the count so dry-run reports the write path's actual verdict
                # (round-11 review: ambiguous ≠ new org).
                from substrate.sources.writer import count_orgs_by_domain

                if count_orgs_by_domain(conn, tenant_id, domain) > 1:
                    report.anchor_errors += 1
                    continue  # ambiguous: same verdict as the write path
                report.would_create += 1  # dry-run: would be created, tagged press_claimed
                continue  # counted once — never also as unanchored
        if org_id is None:
            # Slug fallback: the LLM name itself must appear in the source title —
            # hallucinated names cannot steer claims onto real customers (round 4).
            matches = slug_index.get(slugify(extract.company_name), [])
            if (
                len(matches) == 1
                and name_corroborated(extract.company_name, extract.source_title)
            ):
                org_id = matches[0]
        if org_id is None:
            report.skipped_unanchored += 1
            continue
        if dry_run:
            continue
        persist_funding_events(
            conn,
            tenant_id,
            org_id,
            [
                {
                    "round_type": extract.round_type,
                    "amount_usd": extract.amount_usd,
                    "announced_on": extract.announced_on,
                    "source_type": "press",
                    "url": extract.source_url,
                    "retrieved_at": now,
                }
            ],
            stats=report.stats,
        )
        if created:
            # Explicit decision (review round 1): orgs created from LLM-extracted
            # domains carry a press-claimed verification tag with article
            # provenance — downstream treats them as unverified discoveries.
            supersede_claim(
                conn, tenant_id, "organization", org_id, "verification_status",
                "press_claimed", source_type="press", source_id=extract.source_url,
                url=extract.source_url,
            )
            report.stats.claims_written += 1
    if not dry_run:
        conn.commit()
    return report


__all__ = [
    "CrawlReport",
    "crawl_careers_for_tenant",
    "crawl_edgar_for_tenant",
    "crawl_press_for_tenant",
    "funding_candidates",
    "watch_rows",
]

"""SEC EDGAR Form D crawler via the EDGAR full-text search JSON API.

A Form D filing = a private-placement funding event, free and citable. v0 records
the event (company, CIK, filed date, filing URL) without the offering-amount XML
drill-down — the amount arrives via press corroboration; "unknown" beats guessed.

SEC fair-access rules require a declared User-Agent with contact info: set
SUBSTRATE_SEC_CONTACT (e.g. "Ops <ops@example.com>") in the environment before
running against sec.gov.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from typing import Any

from substrate.sources.http import Fetcher

_EFTS_URL = (
    "https://efts.sec.gov/LATEST/search-index?q=%22Form+D%22&forms=D"
    "&dateRange=custom&startdt={start}&enddt={end}"
)
_FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/index.json"


def sec_user_agent() -> str:
    contact = os.environ.get("SUBSTRATE_SEC_CONTACT", "").strip()
    if not contact:
        raise SystemExit(
            "SUBSTRATE_SEC_CONTACT is required for SEC fetches (fair-access UA: name + email)"
        )
    return f"substrate-crawler/0.1 ({contact})"


def parse_efts_response(payload: object) -> tuple[list[dict[str, Any]], int]:
    """EDGAR full-text search hits → (funding-event dicts, total reported).

    The second element is hits.total.value: when it exceeds the page length,
    results were truncated — callers must count that, never silently drop.
    Fixture-pinned; only file_type == 'D' entries become events."""
    if not isinstance(payload, dict):
        raise ValueError("efts: payload is not a dict")
    hits = payload.get("hits")
    if not isinstance(hits, dict):
        raise ValueError("efts: missing hits block — upstream shape changed")
    entries = hits.get("hits")
    if not isinstance(entries, list):
        raise ValueError("efts: hits.hits is not a list — upstream shape changed")
    total_block = hits.get("total")
    total = int(total_block.get("value", 0)) if isinstance(total_block, dict) else len(entries)

    out: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("efts: non-dict hit entry")
        source = entry.get("_source")
        if not isinstance(source, dict):
            raise ValueError("efts: hit without _source")
        if str(source.get("file_type") or "").strip() != "D":
            continue  # the query asks for Form D; belt-and-braces on every hit
        adsh = str(source.get("adsh") or "").strip()
        if not adsh:
            continue
        ciks = source.get("ciks") or []
        first_cik = str(ciks[0]) if ciks else str(source.get("cik") or "")
        filed_raw = str(source.get("file_date") or "")
        announced = None
        if len(filed_raw) == 10 and filed_raw[4] == "-":
            try:
                announced = date.fromisoformat(filed_raw)
            except ValueError:
                announced = None  # well-shaped but invalid (2026-13-45): skip the hit
        if announced is None or not first_cik:
            continue  # unverifiable events are skipped, never guessed
        accession_nodash = adsh.replace("-", "")
        out.append(
            {
                "company_name": str(source.get("company_name") or ""),
                "cik": first_cik,
                "announced_on": announced,
                "round_type": None,  # Form D XML drill-down is a later enhancement
                "amount_usd": None,
                "url": _FILING_URL.format(cik=first_cik, accession_nodash=accession_nodash),
            }
        )
    return out, total


def crawl_edgar(
    fetcher: Fetcher,
    *,
    start: date,
    end: date,
) -> tuple[list[dict[str, Any]], int]:
    """Fetch recent Form D filings in a date window (inclusive) → (events, total)."""
    url = _EFTS_URL.format(start=start.isoformat(), end=end.isoformat())
    resp = fetcher.fetch(url, headers={"User-Agent": sec_user_agent()})
    if resp.status != 200:
        raise ValueError(f"edgar: search endpoint returned HTTP {resp.status}")
    return parse_efts_response(resp.json())


def _parse_ts(raw: object) -> datetime | None:  # pragma: no cover — reserved for XML drill-down
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None

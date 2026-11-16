"""Funding-press RSS crawler + LLM extraction of structured funding events.

The only LLM path in the source layer: unstructured headlines → typed
FundingExtract. LLMs extract and normalize ONLY (repo invariant) — the entity
anchor is resolved deterministically afterward (domain match, then exact name-slug
match against the tenant's watched orgs; unanchorable items are counted, skipped,
never guessed).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Any

from pydantic import BaseModel

from substrate.sources.http import Fetcher, FetchResponse
from substrate.sources.llm import LlmGateway

_FUNDING_HINT = re.compile(
    r"rais(e|ed)|series [a-z]|seed round|funding|closes? \$|secures? \$|millions?", re.I
)


@dataclass(frozen=True)
class PressItem:
    title: str
    url: str
    published: date | None


class FundingExtract(BaseModel):
    """The typed contract the LLM must satisfy. Prompt version pins it.

    ``source_url`` is NOT LLM output — it is stamped from the PressItem the text
    came from, so every press claim traces to a real article (provenance invariant).
    ``announced_on`` is a real date: pydantic rejects non-ISO LLM output, and that
    extraction is skipped instead of crashing the run."""

    company_name: str
    domain: str | None = None
    round_type: str | None = None
    amount_usd: float | None = None
    announced_on: date
    source_url: str = ""   # stamped from the feed item, never LLM output
    source_title: str = ""  # ditto — used for deterministic domain corroboration


def parse_rss(response: FetchResponse) -> list[PressItem]:
    """RSS 2.0 → items. Malformed feeds raise; honesty over guessing."""
    try:
        root = ET.fromstring(response.body)
    except ET.ParseError as exc:
        raise ValueError(f"press: unparseable RSS from {response.url}: {exc}") from exc

    items: list[PressItem] = []
    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        pub_el = item.find("pubDate")
        if title_el is None or title_el.text is None:
            continue
        title = title_el.text.strip()
        url = link_el.text.strip() if link_el is not None and link_el.text else ""
        published: date | None = None
        if pub_el is not None and pub_el.text:
            try:
                published = parsedate_to_datetime(pub_el.text).date()
            except (ValueError, TypeError):
                published = None
        if title and url:
            items.append(PressItem(title=title, url=url, published=published))
    return items


def funding_candidates(items: list[PressItem]) -> list[PressItem]:
    """Keyword gate: only plausibly-funding items pay for an LLM call (budget)."""
    return [item for item in items if _FUNDING_HINT.search(item.title)]


@dataclass
class PressRunStats:
    items_seen: int = 0
    candidates: int = 0
    extracted: int = 0
    anchored: int = 0
    skipped_unanchored: int = 0
    drafts: list[Any] = field(default_factory=list)


def extract_funding_events(
    fetcher: Fetcher,
    llm: LlmGateway,
    feed_url: str,
    *,
    persist_cache: bool = True,
) -> tuple[list[FundingExtract], PressRunStats]:
    """Feed → candidates → typed extracts. No anchoring here — caller anchors."""
    stats = PressRunStats()
    items = parse_rss(fetcher.fetch(feed_url))
    stats.items_seen = len(items)
    candidates = funding_candidates(items)
    stats.candidates = len(candidates)

    extracts: list[FundingExtract] = []
    run_cache: dict[str, dict[str, Any]] = {}  # dry-run: read-through, never writes

    def read_through_lookup(key: str) -> Any:
        hit = run_cache.get(key)
        if hit is not None:
            return hit
        return llm.lookup_db_cache(key)  # a real run's cache: dry-run pays $0 for it

    def run_cache_store(key: str, response: dict[str, Any], cost: float) -> None:
        run_cache.setdefault(key, response)

    for item in candidates:
        prompt_input = {
            "title": item.title,
            "url": item.url,
            "published": item.published.isoformat() if item.published else None,
        }
        if persist_cache:
            payload = llm.extract_json("funding_event_v1", prompt_input, FundingExtract)
        else:
            payload = llm.extract_json(
                "funding_event_v1",
                prompt_input,
                FundingExtract,
                cache_lookup=read_through_lookup,
                cache_store=run_cache_store,
            )
        if payload is None:
            continue
        extracts.append(
            payload.model_copy(update={"source_url": item.url, "source_title": item.title})
        )
        stats.extracted += 1
    return extracts, stats

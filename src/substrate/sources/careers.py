"""Careers-page crawlers: public job-board JSON APIs (Greenhouse, Lever, Ashby).

These are structured APIs — deterministic parsing, no LLM in the path. Payload
shapes are pinned by fixture tests; upstream changes fail loudly instead of
writing garbage claims. ToS-safe by construction: public postings endpoints,
polite fetch layer, robots honored.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from substrate.sources.http import Fetcher

_GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
_LEVER_URL = "https://api.lever.co/v0/postings/{board}?mode=json"
_ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{board}"

# Canonical function taxonomy for destination intelligence (F3: "hiring for the
# champion's function"). Titles that match nothing map to None — never guessed.
FUNCTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "engineering": (
        "engineer", "developer", "software", "backend", "frontend", "devops", "data", "sre"
    ),
    "sales": (
        "account executive", "sales", "business development", "account manager",
    ),
    "marketing": ("marketing", "growth", "demand gen", "content", "brand"),
    "product": ("product manager", "product design", "designer", "ux"),
    "customer_success": ("customer success", "support", "cs ", "implementation"),
    "finance": ("finance", "accounting", "controller", "fp&a"),
}


def classify_function(title: str) -> str | None:
    t = title.lower()
    for function, keywords in FUNCTION_KEYWORDS.items():
        if any(k in t for k in keywords):
            return function
    return None


def parse_greenhouse(payload: object) -> list[dict[str, Any]]:
    jobs = _require(payload, "jobs", list)
    out: list[dict[str, Any]] = []
    for job in jobs:
        if not isinstance(job, dict):
            raise ValueError("greenhouse: non-dict job entry")
        title = _require_str(job, "title")
        url = _require_str(job, "absolute_url")
        departments = job.get("departments") or []
        if not isinstance(departments, list):
            raise ValueError("greenhouse: departments is not a list — shape changed")
        department = ""
        if departments and isinstance(departments[0], dict):
            department = str(departments[0].get("name") or "")
        out.append(
            {
                "title_norm": title,
                "function": classify_function(f"{title} {department}"),
                "location": _first_office(job),
                "url": url,
                # posted_at means when the job was posted — first_published wins
                # over updated_at (a re-listing bumps updated_at without reposting).
                "posted_at": _parse_ts(job.get("first_published") or job.get("updated_at")),
            }
        )
    return out


def parse_lever(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("lever: expected a list of postings")
    out: list[dict[str, Any]] = []
    for job in payload:
        if not isinstance(job, dict):
            raise ValueError("lever: non-dict posting entry")
        title = _require_str(job, "text")
        url = _require_str(job, "hostedUrl")
        categories = job.get("categories") or {}
        team = str(categories.get("team") or "") if isinstance(categories, dict) else ""
        created_ms = job.get("createdAt")
        posted_at = None
        if isinstance(created_ms, (int, float)):
            try:
                posted_at = datetime.fromtimestamp(created_ms / 1000, tz=UTC)
            except (OverflowError, OSError, ValueError) as exc:
                # Malformed timestamps escape as ValueError so the BOARD fails in
                # isolation — never OverflowError, which aborts the tenant crawl.
                raise ValueError(f"lever: createdAt out of range ({created_ms!r})") from exc
        out.append(
            {
                "title_norm": title,
                "function": classify_function(f"{title} {team}"),
                "location": _lever_location(job),
                "url": url,
                "posted_at": posted_at,
            }
        )
    return out


def parse_ashby(payload: object) -> list[dict[str, Any]]:
    jobs = _require(payload, "jobs", list)
    out: list[dict[str, Any]] = []
    for job in jobs:
        if not isinstance(job, dict):
            raise ValueError("ashby: non-dict job entry")
        title = _require_str(job, "title")
        url = _require_str(job, "jobUrl")
        out.append(
            {
                "title_norm": title,
                "function": classify_function(f"{title} {job.get('department') or ''}"),
                "location": str(job.get("location")) if job.get("location") else None,
                "url": url,
                "posted_at": _parse_ts(job.get("publishedAt")),
            }
        )
    return out


def crawl_careers(
    fetcher: Fetcher,
    board: str,
    platform: str,
) -> list[dict[str, Any]]:
    """Fetch + parse one board. platform: greenhouse | lever | ashby."""
    urls: dict[str, tuple[str, Callable[[object], list[dict[str, Any]]]]] = {
        "greenhouse": (_GREENHOUSE_URL.format(board=board), parse_greenhouse),
        "lever": (_LEVER_URL.format(board=board), parse_lever),
        "ashby": (_ASHBY_URL.format(board=board), parse_ashby),
    }
    if platform not in urls:
        raise ValueError(f"unknown careers platform {platform!r}")
    url, parser = urls[platform]
    resp = fetcher.fetch(url)
    if resp.status != 200:
        raise ValueError(f"{platform}: board {board!r} returned HTTP {resp.status}")
    return parser(resp.json())


# -- helpers ------------------------------------------------------------------


def _require(payload: object, key: str, kind: type) -> Any:
    if not isinstance(payload, dict):
        raise ValueError(f"payload is not a dict (missing {key!r})")
    value = payload.get(key)
    if not isinstance(value, kind):
        raise ValueError(f"payload.{key} is not {kind.__name__} — upstream shape changed")
    return value


def _require_str(obj: dict[str, Any], key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing or empty {key!r} — upstream shape changed")
    return value.strip()


def _first_office(job: dict[str, Any]) -> str | None:
    offices = job.get("offices") or []
    if not isinstance(offices, list):
        raise ValueError("greenhouse: offices is not a list — shape changed")
    if offices and isinstance(offices[0], dict) and offices[0].get("name"):
        return str(offices[0]["name"])
    return None


def _lever_location(job: dict[str, Any]) -> str | None:
    categories = job.get("categories") or {}
    location = categories.get("location") if isinstance(categories, dict) else None
    return str(location) if location else None


def _parse_ts(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None

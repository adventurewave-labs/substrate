"""Blocking keys (PLAN §4 step 1): recall is measured, never assumed.

Blocking recall (golden 'same' pairs that never share a block = silent misses) is a
separate, non-negotiable metric — the eval harness measures it (eval/golden.py).
v0 keys are deliberately conservative-extra: missing a block is unrecoverable in v0,
a redundant block costs only candidate-pair volume.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from substrate.er.phonetics import soundex

FREE_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "hotmail.com",
        "outlook.com",
        "live.com",
        "icloud.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
    }
)


@dataclass
class PersonRecord:
    person_id: str
    emails: list[str] = field(default_factory=list)
    name_given: str | None = None
    name_family: str | None = None
    employer_slug: str | None = None  # slugified current-org name; None = unanchored
    email_domain: str | None = None
    has_title: bool = False  # drives the audit's title_population (a measured metric)


def slugify(name: str) -> str:
    if not name.strip():
        return "unknown"
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    if not s:
        # Non-ASCII-dominant names (CJK etc.) would collapse every org into one
        # "unknown" bucket — fall back to a stable digest of the original.
        import hashlib

        return f"org-{hashlib.sha256(name.strip().lower().encode()).hexdigest()[:8]}"
    return s


def normalize_email(email: str) -> str:
    return email.strip().lower()


def email_domain(email: str) -> str | None:
    _, _, domain = email.partition("@")
    return domain.lower() or None


def normalize_name_part(part: str | None) -> str | None:
    if part is None:
        return None
    s = re.sub(r"\s+", " ", part.strip().lower())
    return s or None


def first_email(emails: list[str] | tuple[Any, ...] | None) -> str | None:
    """First usable email — Postgres text[] can carry NULLs and empty strings."""
    for email in emails or ():
        if isinstance(email, str) and email.strip():
            return normalize_email(email)
    return None


def blocking_keys(person: PersonRecord) -> set[str]:
    """The key sets a pair must share to become ER candidates. Deterministic.

    Iteration order of the returned set is per-process randomized — consumers must
    never depend on it (stratum classification reads the full shared-key set, not
    first-arrival order)."""
    keys: set[str] = set()
    for email in person.emails:
        if not isinstance(email, str) or not email.strip():
            continue  # empty strings would fuse strangers into one em: bucket
        keys.add(f"em:{normalize_email(email)}")
    family = normalize_name_part(person.name_family)
    given = normalize_name_part(person.name_given)
    if family:
        fx = soundex(family)
        if given:
            keys.add(f"nm:{fx}:{soundex(given)}")
            keys.add(f"nf:{fx}:{given[0]}")
        if person.employer_slug:
            keys.add(f"no:{person.employer_slug}:{fx}")
    if person.email_domain and person.email_domain not in FREE_EMAIL_DOMAINS and family:
        keys.add(f"dom:{person.email_domain}:{soundex(family)}")
    return keys


_MAX_CANDIDATE_BUCKET = 200  # role-inbox scale: a shared address stops being identity evidence


def candidate_pairs(persons: list[PersonRecord]) -> set[tuple[str, str]]:
    """All pairs sharing at least one blocking key. Order-independent, deduplicated,
    bounded: buckets over _MAX_CANDIDATE_BUCKET (info@ inboxes with thousands of
    members) are deterministically subsampled — pairing them wholesale is O(n²)
    REVIEW noise, and the shared key carries no identity signal at that scale.
    ER v1 (W7–8) reintroduces these with bucket-size-aware features."""
    index: dict[str, list[str]] = {}
    for person in persons:
        for key in blocking_keys(person):
            index.setdefault(key, []).append(person.person_id)
    pairs: set[tuple[str, str]] = set()
    for key in sorted(index):
        members = sorted(index[key])
        if len(members) < 2:
            continue
        if len(members) > _MAX_CANDIDATE_BUCKET:
            step = len(members) / _MAX_CANDIDATE_BUCKET
            members = [members[int(i * step)] for i in range(_MAX_CANDIDATE_BUCKET)]
        for i, left in enumerate(members):
            for right in members[i + 1 :]:
                pairs.add((min(left, right), max(left, right)))
    return pairs

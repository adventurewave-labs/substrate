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

from substrate.er.phonetics import soundex

_FREE_EMAIL_DOMAINS = frozenset(
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
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "unknown"


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


def blocking_keys(person: PersonRecord) -> set[str]:
    """The key sets a pair must share to become ER candidates. Deterministic."""
    keys: set[str] = set()
    for email in person.emails:
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
    if person.email_domain and person.email_domain not in _FREE_EMAIL_DOMAINS and family:
        keys.add(f"dom:{person.email_domain}:{soundex(family)}")
    return keys


def candidate_pairs(persons: list[PersonRecord]) -> set[tuple[str, str]]:
    """All pairs sharing at least one blocking key. Order-independent, deduplicated."""
    index: dict[str, list[str]] = {}
    for person in persons:
        for key in blocking_keys(person):
            index.setdefault(key, []).append(person.person_id)
    pairs: set[tuple[str, str]] = set()
    for members in index.values():
        if len(members) < 2:
            continue
        for i, left in enumerate(members):
            for right in members[i + 1 :]:
                pairs.add((min(left, right), max(left, right)))
    return pairs

"""Seniority banding — the single source of truth for title → band mapping.

Unknown seniority (None) never ranks: a lateral retitle with unparseable levels
must not read as a promotion (conservative by design).
"""

from __future__ import annotations

SENIORITY_RANK: dict[str, int] = {
    "intern": 0,
    "ic": 1,
    "senior_ic": 2,
    "lead": 3,
    "principal": 4,
    "manager": 5,
    "senior_manager": 6,
    "director": 7,
    "senior_director": 8,
    "vp": 9,
    "svp": 10,
    "c_level": 11,
}

# Checked most-specific first. "ic" is the DEFAULT band for known IC titles —
# the most common promotion in real data is ic → anything, so a working ic band
# is what makes promotion detection functional at all (gate review, W7–8 r2).
_SENIORITY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("c_level", ("chief", "cto", "ceo", "cfo", "coo", "cmo", "cro", "c-suite")),
    ("svp", ("svp", "senior vice president", "evp", "executive vice president")),
    ("vp", ("vp", "vice president")),
    ("senior_director", ("senior director", "sr. director")),
    ("director", ("director",)),
    ("senior_manager", ("senior manager", "sr. manager")),
    ("manager", ("manager",)),
    ("principal", ("principal", "staff engineer", "distinguished")),
    ("lead", ("lead", "head of")),
    ("senior_ic", ("senior", "sr")),
    ("intern", ("intern", "apprentice")),
    # Default IC band: known individual-contributor titles with no seniority word.
    ("ic", (
        "engineer", "developer", "designer", "analyst", "associate",
        "account executive", "specialist", "coordinator", "consultant",
        "architect", "scientist", "recruiter", "administrator", "executive",
    )),
]


def classify_seniority(title_norm: str | None) -> str | None:
    """Keyword → seniority band via word-boundary matching.

    Word boundaries are load-bearing: substring matching would classify
    "International Account Executive" as intern (gate review, W7–8 r2).
    None = unknown; never guessed."""
    if not title_norm:
        return None
    import re

    t = title_norm.lower().strip()
    for band, keywords in _SENIORITY_KEYWORDS:
        for keyword in keywords:
            if re.search(r"\b" + re.escape(keyword) + r"\b", t):
                return band
    return None

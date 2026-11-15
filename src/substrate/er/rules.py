"""Deterministic v0 decision rules — precision-first (PLAN §4).

v0 emits decisions only where the evidence is near-conclusive; borderline pairs go to
the internal review queue, never to the customer. Learned scoring (LightGBM) arrives
with ER v1 at W7–8; these rules then become the constraint layer around it.

Every rule is a pure function of the candidate pair — testable without a database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from substrate.er.blocking import PersonRecord, normalize_email, normalize_name_part

FEATURESET_VERSION = "er-v0.0-deterministic"


class Decision(StrEnum):
    AUTO_MERGE = "auto_merge"
    REVIEW = "review"
    REJECT = "reject"


@dataclass(frozen=True)
class Outcome:
    decision: Decision
    score: float
    rule: str


def _emails(person: PersonRecord) -> set[str]:
    return {normalize_email(e) for e in person.emails if e}


def _full_name(person: PersonRecord) -> tuple[str | None, str | None]:
    return normalize_name_part(person.name_given), normalize_name_part(person.name_family)


def _email_local(email: str) -> str:
    return normalize_email(email).split("@", 1)[0]


_ALNUM_LOCAL = re.compile(r"^[a-z0-9._-]+$")


def decide(left: PersonRecord, right: PersonRecord) -> Outcome | None:
    """Evaluate one candidate pair. None = no v0 decision (leave unmerged, unqueued).

    Order matters: the first matching rule wins, rules are ordered most-specific
    first. Precision targets come from PLAN §4 bands (≥0.995 auto-merge).
    """
    le, re_ = _emails(left), _emails(right)
    shared_emails = le & re_

    # R1 — exact shared email + same family name: near-conclusive.
    if shared_emails:
        lf, rf = _full_name(left)[1], _full_name(right)[1]
        if lf is not None and lf == rf:
            return Outcome(Decision.AUTO_MERGE, 0.999, "R1_exact_email_same_family")

        # R2 — exact shared email, names differ or unknown: shared inboxes and
        # info@ aliases exist; humans decide.
        return Outcome(Decision.REVIEW, 0.950, "R2_exact_email_name_differs")

    # R3 — same person-shaped local parts on the same corporate domain, same
    # family name: e.g. j.smith@ and smithj@. Two distinct people do share
    # domains — review, never auto.
    ld, rd = left.email_domain, right.email_domain
    if ld is not None and ld == rd and ld != "":
        lf, rf = _full_name(left)[1], _full_name(right)[1]
        if lf is not None and lf == rf:
            lloc, rloc = _email_local(min(le) if le else ""), _email_local(min(re_) if re_ else "")
            if (
                lloc
                and rloc
                and lloc != rloc
                and _ALNUM_LOCAL.match(lloc)
                and _ALNUM_LOCAL.match(rloc)
            ):
                # initials-vs-fullname shape (j.smith / smithj / jsmith)
                fam = lf.replace(" ", "")
                given_init = (_full_name(left)[0] or lf)[:1]
                initials = {f"{given_init}.{fam}", f"{given_init}{fam}", fam, f"{fam}.{given_init}"}
                if lloc in initials or rloc in initials or lloc in rloc or rloc in lloc:
                    return Outcome(Decision.REVIEW, 0.900, "R3_corporate_local_shape")

    return None

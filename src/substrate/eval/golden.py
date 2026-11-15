"""Golden-set tooling (PLAN §4): stratified sampler + metric harness.

Contract (PLAN §4): 500 stratified pairs — exact-email dupes / fuzzy same-org /
fuzzy diff-org / hard negatives (40% of the sample) — hand-labeled in a worksheet,
then measured: merge precision (decisions vs labels) and blocking recall (labeled
'same' pairs that never share a block are silent misses; ≥99% or the keys change).

Honest-measurement note (gate review, PR #4): block-derived strata cannot reveal a
missed block by construction — a pair that shares a key was found *through* that
key. The ``random`` stratum samples pairs irrespective of blocks; only labels in
that stratum (plus hard negatives) can exercise blocking recall truthfully.

Sampling is deterministic (no RNG; sorted keys + evenly spaced strides) so a
worksheet can be regenerated and stay stable. Pure logic — DB adapter in engine.py.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import dataclass
from typing import Any

from substrate.er.blocking import PersonRecord, blocking_keys
from substrate.er.phonetics import soundex
from substrate.er.rules import Decision, Outcome

WORKSHEET_COLUMNS = (
    "pair_kind",
    "left_person_id",
    "right_person_id",
    "label",  # 'same' | 'different'; blank until hand-labeled
)
PAIR_KINDS = ("exact_email", "fuzzy_same_org", "fuzzy_diff_org", "hard_negative", "random")
DEFAULT_STRATUM_CAPS = {
    "exact_email": 100,
    "fuzzy_same_org": 100,
    "fuzzy_diff_org": 50,
    "hard_negative": 200,  # PLAN §4: hard negatives are 40% of the 500-pair sample
    "random": 50,
}


@dataclass(frozen=True)
class GoldenPair:
    pair_kind: str
    left_id: str
    right_id: str
    label: str | None = None  # 'same' | 'different' | None (unlabeled)


def _sample_evenly(candidates: list[tuple[str, str]], cap: int) -> list[tuple[str, str]]:
    candidates = sorted(set(candidates))
    if len(candidates) <= cap:
        return candidates
    step = len(candidates) / cap
    return [candidates[int(i * step)] for i in range(cap)]


def sample_pairs(
    persons: list[PersonRecord],
    caps: dict[str, int] | None = None,
) -> list[GoldenPair]:
    """Stratified sample over one tenant's persons. Deterministic; no RNG.

    Inverted index over blocking keys — candidate strata come from key buckets
    (O(n·k) to build), never the O(n²·k) pairwise rescan.
    """
    caps = {**DEFAULT_STRATUM_CAPS, **(caps or {})}
    ids = sorted(p.person_id for p in persons)
    by_id = {p.person_id: p for p in persons}

    exact_email: list[tuple[str, str]] = []
    fuzzy_same_org: list[tuple[str, str]] = []
    fuzzy_diff_org: list[tuple[str, str]] = []
    hard_negative: list[tuple[str, str]] = []
    random_pairs: list[tuple[str, str]] = []

    seen: set[tuple[str, str]] = set()

    def add(bucket: list[tuple[str, str]], left: str, right: str) -> None:
        pair = (min(left, right), max(left, right))
        if pair not in seen:
            seen.add(pair)
            bucket.append(pair)

    # Block-derived strata, from key buckets.
    index: dict[str, list[str]] = {}
    keys_by_id: dict[str, set[str]] = {}
    for person in persons:
        keys_by_id[person.person_id] = blocking_keys(person)
        for key in keys_by_id[person.person_id]:
            index.setdefault(key, []).append(person.person_id)

    for key, members in index.items():
        if len(members) < 2 or key.startswith(("dom:", "nf:")):
            continue  # dom/nf keys are rule- or negative-sampling concerns, not strata
        for i, left in enumerate(members):
            for right in members[i + 1 :]:
                same_org = (
                    by_id[left].employer_slug is not None
                    and by_id[left].employer_slug == by_id[right].employer_slug
                )
                if key.startswith("em:"):
                    add(exact_email, left, right)
                elif key.startswith("nm:"):
                    if same_org:
                        add(fuzzy_same_org, left, right)
                    else:
                        add(fuzzy_diff_org, left, right)
                elif key.startswith("no:"):
                    add(fuzzy_same_org, left, right)

    # Hard negatives: same phonetic family + same given initial, nothing else shared.
    by_phonetic: dict[tuple[str, str], list[PersonRecord]] = {}
    for person in persons:
        family = person.name_family
        if family:
            neg_key = (
                soundex(family),
                person.name_given[:1].lower() if person.name_given else "",
            )
            by_phonetic.setdefault(neg_key, []).append(person)
    for group in by_phonetic.values():
        for i, left_p in enumerate(group):
            for right_p in group[i + 1 :]:
                shared = blocking_keys(left_p) & blocking_keys(right_p)
                if not shared or all(k.startswith("nf:") for k in shared):
                    add(hard_negative, left_p.person_id, right_p.person_id)

    # Random stratum: fixed-stride pairs over sorted ids, independent of blocks —
    # the only stratum that can sample a true silent miss (same person, no shared key).
    stride = max(1, len(ids) // max(caps["random"], 1))
    for i in range(0, len(ids) - stride, stride):
        add(random_pairs, ids[i], ids[i + stride])

    out: list[GoldenPair] = []
    for kind, bucket in (
        ("exact_email", exact_email),
        ("fuzzy_same_org", fuzzy_same_org),
        ("fuzzy_diff_org", fuzzy_diff_org),
        ("hard_negative", hard_negative),
        ("random", random_pairs),
    ):
        for left_id, right_id in _sample_evenly(bucket, caps[kind]):
            out.append(GoldenPair(pair_kind=kind, left_id=left_id, right_id=right_id))
    return out


def write_worksheet(pairs: list[GoldenPair]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(WORKSHEET_COLUMNS)
    for pair in pairs:
        writer.writerow([pair.pair_kind, pair.left_id, pair.right_id, pair.label or ""])
    return buf.getvalue()


def read_worksheet(text: str) -> list[GoldenPair]:
    pairs: list[GoldenPair] = []
    for row in csv.DictReader(io.StringIO(text)):
        label = (row.get("label") or "").strip().lower()
        if label and label not in ("same", "different"):
            raise ValueError(f"invalid label {label!r} — must be 'same', 'different', or blank")
        pairs.append(
            GoldenPair(
                pair_kind=row["pair_kind"],
                left_id=row["left_person_id"],
                right_id=row["right_person_id"],
                label=label or None,
            )
        )
    return pairs


@dataclass
class EvalReport:
    labeled_pairs: int
    same_pairs: int
    blocking_recall: float | None  # None when no 'same' pairs yet
    missed_blocks: list[tuple[str, str]]
    auto_merge_precision: float | None
    auto_merge_on_different: list[tuple[str, str]]
    review_share_of_same: float | None
    decision_counts: dict[str, int]
    per_kind: dict[str, dict[str, int]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "labeled_pairs": self.labeled_pairs,
            "same_pairs": self.same_pairs,
            "blocking_recall": self.blocking_recall,
            "missed_blocks": self.missed_blocks,
            "auto_merge_precision": self.auto_merge_precision,
            "auto_merge_on_different": self.auto_merge_on_different,
            "review_share_of_same": self.review_share_of_same,
            "decision_counts": self.decision_counts,
            "per_kind": self.per_kind,
        }


def evaluate(
    pairs: list[GoldenPair],
    persons: list[PersonRecord],
    decide_fn: Any,
) -> EvalReport:
    """Measure the rule set against hand labels.

    ``decide_fn(left, right) -> Outcome | None`` — injectable so the harness scores
    v0 rules today and the v1 scorer at W7–8 without rewrite.

    ``blocking_recall`` is only as trustworthy as the labeled pair mix: block-derived
    strata share a block by construction, so the metric moves only through labels
    on the random and hard_negative strata. Interpret accordingly until a fully
    labeled pass exists (M2 gate evidence).
    """
    by_id = {p.person_id: p for p in persons}
    labeled = [p for p in pairs if p.label is not None]
    same = [p for p in labeled if p.label == "same"]

    missed_blocks: list[tuple[str, str]] = []
    for pair in same:
        left, right = by_id[pair.left_id], by_id[pair.right_id]
        if not (blocking_keys(left) & blocking_keys(right)):
            missed_blocks.append((pair.left_id, pair.right_id))
    blocking_recall = (
        round(1 - len(missed_blocks) / len(same), 4) if same else None
    )

    auto_merge_total = 0
    auto_merge_on_different: list[tuple[str, str]] = []
    review_on_same = 0
    decision_counts: Counter[str] = Counter()
    per_kind: dict[str, Counter[str]] = {}

    for pair in labeled:
        left, right = by_id[pair.left_id], by_id[pair.right_id]
        outcome: Outcome | None = decide_fn(left, right)
        decision = outcome.decision.value if outcome else "none"
        decision_counts[decision] += 1
        per_kind.setdefault(pair.pair_kind, Counter())[decision] += 1
        if outcome is not None and outcome.decision == Decision.AUTO_MERGE:
            auto_merge_total += 1
            if pair.label == "different":
                auto_merge_on_different.append((pair.left_id, pair.right_id))
        if outcome is not None and outcome.decision == Decision.REVIEW and pair.label == "same":
            review_on_same += 1

    return EvalReport(
        labeled_pairs=len(labeled),
        same_pairs=len(same),
        blocking_recall=blocking_recall,
        missed_blocks=missed_blocks,
        auto_merge_precision=(
            round((auto_merge_total - len(auto_merge_on_different)) / auto_merge_total, 4)
            if auto_merge_total
            else None
        ),
        auto_merge_on_different=auto_merge_on_different,
        review_share_of_same=(
            round(review_on_same / len(same), 4) if same else None
        ),
        decision_counts=dict(decision_counts),
        per_kind={k: dict(v) for k, v in per_kind.items()},
    )

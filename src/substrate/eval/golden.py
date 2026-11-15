"""Golden-set tooling (PLAN §4): stratified sampler + metric harness.

Contract (PLAN §4): 500 stratified pairs — exact-email dupes / fuzzy same-org /
fuzzy diff-org / hard negatives (40% of the sample) — hand-labeled in a worksheet,
then measured: merge precision (decisions vs labels) and blocking recall (labeled
'same' pairs that never share a block are silent misses; ≥99% or the keys change).

Honest-measurement note (gate reviews, PR #4): block-derived strata cannot reveal a
missed block by construction — a pair that shares a key was found *through* that
key. That includes hard negatives: they are grouped by (soundex(family), initial),
which is exactly the ``nf:`` block key, so a hard-negative pair is block-found too.
ONLY the ``random`` stratum is block-independent, and ONLY random-stratum labels
exercise blocking recall truthfully. Honest caveat: a random pair is a same-person
pair with probability ≈ duplicate_rate/N, so the gated metric stays ``None`` on
most real worksheets until a fully-labeled pass exists (the M2 gate evidence
comes from labeling a full audit sample, not from this worksheet alone).

Sampling is deterministic (no RNG; sorted keys + evenly spaced strides) so a
worksheet can be regenerated and stay stable. Pure logic — DB adapter in engine.py.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import dataclass
from typing import Any

from substrate.er.blocking import PersonRecord, blocking_keys, normalize_name_part
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


def _classify_shared_keys(
    shared: set[str], left: PersonRecord, right: PersonRecord
) -> str | None:
    """Stratum from the FULL shared-key set, by fixed priority — never first-arrival
    order (set iteration is per-process randomized; classification must not be).

    Priority: em > (no or nm-same-org) > nm-diff-org. nf/dom-only sharing -> None
    (those pairs belong to the hard-negative/random machinery, not these strata).
    """
    if any(k.startswith("em:") for k in shared):
        return "exact_email"
    same_org = (
        left.employer_slug is not None and left.employer_slug == right.employer_slug
    )
    no_shared = any(k.startswith("no:") for k in shared)
    nm_shared = any(k.startswith("nm:") for k in shared)
    if no_shared or (nm_shared and same_org):
        return "fuzzy_same_org"
    if nm_shared:
        return "fuzzy_diff_org"
    return None


# Buckets above this size are deterministically subsampled before pairing, so a
# single role-inbox bucket cannot blow up pair generation.
_MAX_BUCKET = 300


def sample_pairs(
    persons: list[PersonRecord],
    caps: dict[str, int] | None = None,
) -> list[GoldenPair]:
    """Stratified sample over one tenant's persons. Deterministic across processes.

    Two determinism rules (gate finding: set iteration order is per-process
    randomized): strata are classified from each pair's full shared-key set by fixed
    priority (see _classify_shared_keys), and every collection loop walks sorted
    keys/ids. No RNG.
    """
    caps = {**DEFAULT_STRATUM_CAPS, **(caps or {})}
    ids = sorted(p.person_id for p in persons)
    by_id = {p.person_id: p for p in persons}

    # Inverted index, then pair→shared-keys unioned from all its buckets.
    index: dict[str, list[str]] = {}
    for person in persons:
        for key in blocking_keys(person):
            index.setdefault(key, []).append(person.person_id)

    pair_keys: dict[tuple[str, str], set[str]] = {}
    for key in sorted(index):
        members = sorted(index[key])  # sorted: bucket order must not depend on person order
        if len(members) < 2 or key.startswith(("dom:", "nf:")):
            continue  # dom/nf keys are rule/negative-sampling concerns, not strata
        if len(members) > _MAX_BUCKET:
            # Role-inbox-scale buckets: deterministic even subsample before pairing.
            step = len(members) / _MAX_BUCKET
            members = [members[int(i * step)] for i in range(_MAX_BUCKET)]
        for i, left in enumerate(members):
            for right in members[i + 1 :]:
                pair = (min(left, right), max(left, right))
                pair_keys.setdefault(pair, set()).add(key)

    strata: dict[str, list[tuple[str, str]]] = {kind: [] for kind in PAIR_KINDS}
    for pair in sorted(pair_keys):
        left_p, right_p = by_id[pair[0]], by_id[pair[1]]
        kind = _classify_shared_keys(pair_keys[pair], left_p, right_p)
        if kind is not None:
            strata[kind].append(pair)

    # Hard negatives: same phonetic family + same given initial, nothing else shared.
    # Capped like block buckets, set-deduped, normalized initials — same determinism
    # and blow-up rules as the block strata above.
    by_phonetic: dict[tuple[str, str], list[PersonRecord]] = {}
    for person in persons:
        family = person.name_family
        if family:
            given_norm = normalize_name_part(person.name_given)
            neg_key = (soundex(family), given_norm[:1] if given_norm else "")
            by_phonetic.setdefault(neg_key, []).append(person)
    hard_seen: set[tuple[str, str]] = set()
    for neg_key in sorted(by_phonetic):
        group = sorted(by_phonetic[neg_key], key=lambda p: p.person_id)
        if len(group) > _MAX_BUCKET:
            step = len(group) / _MAX_BUCKET
            group = [group[int(i * step)] for i in range(_MAX_BUCKET)]
        for i, left_p in enumerate(group):
            for right_p in group[i + 1 :]:
                shared = blocking_keys(left_p) & blocking_keys(right_p)
                if not shared or all(k.startswith("nf:") for k in shared):
                    pair = (left_p.person_id, right_p.person_id)
                    if pair not in hard_seen:
                        hard_seen.add(pair)
                        strata["hard_negative"].append(pair)

    # Random stratum: fixed-stride pairs over sorted ids, independent of blocks —
    # the only stratum that can sample a true silent miss (same person, no shared key).
    # One pair, one stratum: block-classified pairs are never re-added here.
    assigned: set[tuple[str, str]] = set()
    for kind in PAIR_KINDS:
        assigned.update(strata[kind])
    stride = max(1, len(ids) // max(caps["random"], 1))
    for i in range(0, len(ids) - stride, stride):
        pair = (ids[i], ids[i + stride])
        if pair not in assigned:
            strata["random"].append(pair)
            assigned.add(pair)

    out: list[GoldenPair] = []
    for kind in PAIR_KINDS:
        for left_id, right_id in _sample_evenly(strata[kind], caps[kind]):
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
    blocking_recall: float | None  # random stratum ONLY — the one block-independent stratum
    blocking_recall_block_independent_pairs: int
    # every labeled 'same' pair — near-1.0 by construction, reported for transparency
    blocking_recall_all_labeled: float | None
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
            "blocking_recall_scope": "random stratum only (the sole block-independent stratum)",
            "blocking_recall_block_independent_pairs": (
                self.blocking_recall_block_independent_pairs
            ),
            "blocking_recall_all_labeled": self.blocking_recall_all_labeled,
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

    ``blocking_recall`` (the gated metric, ≥99% or the keys change) is computed over
    the random stratum ONLY. Block-derived strata — including hard negatives, which
    share the ``nf:`` block by construction — cannot reveal a missed block, so they
    stay out of the gated number. The all-labeled figure is reported separately for
    transparency.
    """
    by_id = {p.person_id: p for p in persons}
    labeled = [p for p in pairs if p.label is not None]
    same = [p for p in labeled if p.label == "same"]
    independent = [p for p in same if p.pair_kind == "random"]

    def _missed(pair_list: list[GoldenPair]) -> list[tuple[str, str]]:
        missed: list[tuple[str, str]] = []
        for pair in pair_list:
            left, right = by_id[pair.left_id], by_id[pair.right_id]
            if not (blocking_keys(left) & blocking_keys(right)):
                missed.append((pair.left_id, pair.right_id))
        return missed

    missed_blocks = _missed(same)  # all known silent misses, any stratum (operator report)
    missed_independent = _missed(independent)  # drives the gated metric
    blocking_recall = (
        round(1 - len(missed_independent) / len(independent), 4) if independent else None
    )
    blocking_recall_all = round(1 - len(missed_blocks) / len(same), 4) if same else None

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
        blocking_recall_block_independent_pairs=len(independent),
        blocking_recall_all_labeled=blocking_recall_all,
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

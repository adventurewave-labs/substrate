import pytest

from substrate.er.blocking import PersonRecord, slugify
from substrate.er.rules import decide
from substrate.eval.golden import (
    DEFAULT_STRATUM_CAPS,
    EvalReport,
    GoldenPair,
    evaluate,
    read_worksheet,
    sample_pairs,
    write_worksheet,
)


def _p(pid, *, emails=(), given=None, family=None, employer=None):
    return PersonRecord(
        person_id=pid,
        emails=list(emails),
        name_given=given,
        name_family=family,
        employer_slug=slugify(employer) if employer else None,
        email_domain=emails[0].split("@", 1)[1] if emails else None,
    )


def _population():
    return [
        _p("1", emails=("a@acme.com",), given="Ann", family="Lee", employer="Acme"),
        _p("2", emails=("A@Acme.com",), given="Anne", family="Lee", employer="Acme"),  # dupe
        _p("3", emails=("bob@acme.com",), given="Bob", family="Wu", employer="Acme"),
        _p("4", emails=("bo@beta.com",), given="Bo", family="Wu", employer="Beta"),  # diff org
        _p("5", emails=("cy@gamma.com",), given="Cy", family="Ray", employer="Gamma"),
        _p("6", emails=("craig@gamma.com",), given="Craig", family="Ray", employer="Delta"),
    ]


def test_sample_is_deterministic_and_capped():
    pairs1 = sample_pairs(_population())
    pairs2 = sample_pairs(_population())
    assert pairs1 == pairs2
    kinds = {p.pair_kind for p in pairs1}
    assert kinds <= {"exact_email", "fuzzy_same_org", "fuzzy_diff_org", "hard_negative", "random"}


_OVERLAP_SCRIPT = """
import json, sys
from substrate.er.blocking import PersonRecord
from substrate.eval.golden import sample_pairs, write_worksheet

raw = json.load(open(sys.argv[1]))
persons = [
    PersonRecord(
        person_id=p["person_id"], emails=p["emails"], name_given=p["name_given"],
        name_family=p["name_family"], employer_slug=p["employer_slug"],
        email_domain=p["email_domain"], has_title=False,
    )
    for p in raw
]
print(write_worksheet(sample_pairs(persons)), end="")
"""


def test_sample_determinism_survives_hash_randomization(tmp_path):
    # Gate finding: blocking_keys() returns sets — per-process string-hash
    # randomization changes iteration order, so first-arrival stratum assignment
    # differs across processes. Classification must be priority-based; this test
    # proves it with two different PYTHONHASHSEED values.
    import json
    import os
    import subprocess
    import sys

    raw_rows = [
        ("p1", ["a@acme.com"], "Ann", "Lee", "acme", "acme.com"),
        ("p2", ["A@ACME.com"], "Anne", "Lee", "acme", "acme.com"),
        ("p3", ["bob@beta.com"], "Bob", "Wu", "beta", "beta.com"),
        ("p4", ["bo@beta.com"], "Bo", "Wu", "gamma", "beta.com"),
        ("p5", ["cy@gamma.com"], "Cy", "Ray", None, "gamma.com"),
        ("p6", ["craig@gamma.com"], "Craig", "Ray", None, "gamma.com"),
    ]
    population = [
        {
            "person_id": pid, "emails": emails, "name_given": given,
            "name_family": family, "employer_slug": slug, "email_domain": domain,
        }
        for pid, emails, given, family, slug, domain in raw_rows
    ]
    fixture = tmp_path / "population.json"
    fixture.write_text(json.dumps(population))

    outputs = []
    for seed in ("1", "99"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        proc = subprocess.run(
            [sys.executable, "-c", _OVERLAP_SCRIPT, str(fixture)],
            capture_output=True, text=True, env=env, check=True,
        )
        outputs.append(proc.stdout)
    assert outputs[0] == outputs[1]

    # The overlap case is classified by priority, not arrival order: p1/p2 share
    # em + nm + no keys — always exact_email.
    from substrate.eval.golden import read_worksheet

    pairs = {p.left_id + p.right_id: p.pair_kind for p in read_worksheet(outputs[0])}
    assert pairs["p1p2"] == "exact_email"


def test_evaluate_headline_recall_is_block_independent():
    # exact_email AND hard_negative pairs are block-found by construction (the
    # hard-negative grouping key IS the nf: block) — only random labels count.
    persons = _population()
    pairs = [
        GoldenPair("exact_email", "1", "2", "same"),
        GoldenPair("hard_negative", "3", "4", "same"),  # shares nf: block
        GoldenPair("random", "3", "5", "same"),  # no shared block
    ]
    report = evaluate(pairs, persons, decide)
    assert report.blocking_recall == 0.0  # honest: the random same-pair is missed
    assert report.blocking_recall_block_independent_pairs == 1
    # all-labeled: (1,2) share em:, (3,4) share nf:, (3,5) missed → 2/3
    assert report.blocking_recall_all_labeled == 0.6667
    # (3,4) is NOT in missed_blocks — it was FOUND through the nf: block, which is
    # exactly why hard negatives can't measure recall; only (3,5) is a silent miss.
    assert report.missed_blocks == [("3", "5")]


def test_evaluate_no_independent_labels_recall_is_none():
    persons = _population()
    pairs = [GoldenPair("exact_email", "1", "2", "same")]
    report = evaluate(pairs, persons, decide)
    assert report.blocking_recall is None
    assert report.blocking_recall_all_labeled == 1.0


def test_sample_caps_match_plan_contract():
    # PLAN §4: 500 pairs, hard negatives are 40% of the sample.
    caps = DEFAULT_STRATUM_CAPS
    assert sum(caps.values()) == 500
    assert caps["hard_negative"] == 200
    assert "random" in caps  # the sole block-independent stratum (gated recall)


def test_sample_produces_random_stratum_pairs():
    pairs = sample_pairs(_population())
    assert any(p.pair_kind == "random" for p in pairs)


def test_worksheet_roundtrip():
    pairs = sample_pairs(_population())
    text = write_worksheet(pairs)
    back = read_worksheet(text)
    assert back == pairs


def test_worksheet_rejects_bad_label():
    text = write_worksheet([GoldenPair("exact_email", "1", "2", None)]).replace(
        "exact_email,1,2,", "exact_email,1,2,maybe"
    )
    with pytest.raises(ValueError):
        read_worksheet(text)


def test_evaluate_blocks_misses_and_precision():
    persons = _population()
    # Label the shared-email pair same (1-2); everything else different.
    pairs = [
        GoldenPair("exact_email", "1", "2", "same"),
        GoldenPair("fuzzy_diff_org", "3", "4", "different"),
        GoldenPair("fuzzy_diff_org", "5", "6", "different"),
    ]
    report: EvalReport = evaluate(pairs, persons, decide)
    assert report.labeled_pairs == 3
    assert report.same_pairs == 1
    # No block-independent labels yet: the gated metric is None, not a fake 1.0.
    assert report.blocking_recall is None
    assert report.blocking_recall_block_independent_pairs == 0
    assert report.blocking_recall_all_labeled == 1.0
    assert report.auto_merge_precision == 1.0  # the auto_merge lands on the 'same' pair
    assert report.decision_counts.get("auto_merge") == 1


def test_evaluate_catches_false_auto_merge():
    # Adversarial pair: same-name colleagues sharing a role inbox — R1 fires, the
    # hand label says different. The harness must catch it; that is its whole job.
    persons = [
        _p("1", emails=("info@acme.com",), given="Pat", family="Lee"),
        _p("2", emails=("info@acme.com",), given="Pat", family="Lee"),
    ]
    pairs = [GoldenPair("exact_email", "1", "2", "different")]
    report = evaluate(pairs, persons, decide)
    assert report.auto_merge_precision == 0.0
    assert report.auto_merge_on_different == [("1", "2")]

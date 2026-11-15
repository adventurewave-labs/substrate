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


def test_sample_caps_match_plan_contract():
    # PLAN §4: 500 pairs, hard negatives are 40% of the sample.
    caps = DEFAULT_STRATUM_CAPS
    assert sum(caps.values()) == 500
    assert caps["hard_negative"] == 200
    assert "random" in caps  # the only stratum that can catch a silent miss


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
    assert report.blocking_recall == 1.0  # 1/2 share the em: block
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

from substrate.er.blocking import PersonRecord, blocking_keys, candidate_pairs, slugify
from substrate.er.rules import Decision, decide


def _p(pid, *, emails=(), given=None, family=None, employer=None):
    domain = None
    for email in emails:
        if isinstance(email, str) and "@" in email:
            domain = email.split("@", 1)[1]
            break
    return PersonRecord(
        person_id=pid,
        emails=list(emails),
        name_given=given,
        name_family=family,
        employer_slug=slugify(employer) if employer else None,
        email_domain=domain,
    )


def test_blocking_keys_exact_email_shared():
    a = _p("a", emails=("j.smith@acme.com",), given="Jane", family="Smith", employer="Acme")
    b = _p("b", emails=("J.Smith@Acme.com",), given="Janet", family="Smith", employer="Acme")
    assert blocking_keys(a) & blocking_keys(b)


def test_blocking_keys_phonetic_collision():
    a = _p("a", emails=("jane@acme.com",), given="Jane", family="Smyth", employer="Acme")
    b = _p("b", emails=("john@acme.com",), given="John", family="Smith", employer="Acme")
    assert blocking_keys(a) & blocking_keys(b)  # nm: soundex(Smyth)==soundex(Smith)


def test_candidate_pairs_order_independent():
    a = _p("b-id", emails=("x@acme.com",), family="Smith")
    b = _p("a-id", emails=("x@acme.com",), family="Smith")
    c = _p("c-id", emails=("y@other.com",), family="Wu")
    assert candidate_pairs([a, b, c]) == {("a-id", "b-id")}


def test_slugify_deterministic():
    assert slugify("Acme Corp!") == slugify("acme corp") == "acme-corp"
    assert slugify("Ünïcode AG") == "unicode-ag"


def test_empty_emails_never_fuse_a_bucket():
    # Gate finding: "" emails would put every such person into one em: bucket.
    a = _p("a", emails=("",), family="Wu")
    b = _p("b", emails=("   ",), family="Wu")
    c = _p("c", emails=("",), family="Wu")
    assert candidate_pairs([a, b, c]) == set()


def test_first_email_skips_nulls_and_blanks():
    from substrate.er.blocking import first_email

    assert first_email([None, "", " A@B.com "]) == "a@b.com"
    assert first_email([None]) is None
    assert first_email([]) is None
    assert first_email(None) is None


# ---- rules ----


def test_r1_exact_email_same_family_auto_merge():
    a = _p("a", emails=("j.smith@acme.com",), given="Jane", family="Smith")
    b = _p("b", emails=("j.smith@acme.com",), given="Janet", family="Smith")
    outcome = decide(a, b)
    assert outcome is not None and outcome.decision == Decision.AUTO_MERGE


def test_whitespace_emails_never_auto_merge():
    # Gate round-4: "   " normalizes to "" — two blank-email persons must not
    # 'share' an address and R1-merge with zero evidence.
    a = _p("a", emails=("   ",), given="Jane", family="Wu", employer="Acme")
    b = _p("b", emails=("  ",), given="John", family="Wu", employer="Acme")
    assert decide(a, b) is None or decide(a, b).decision == Decision.REVIEW


def test_r1_conflicting_given_initials_review():
    # Pat Lee vs Chris Lee on info@acme.com: same family, different initial —
    # role-inbox smell, humans decide (gate round-4).
    a = _p("a", emails=("info@acme.com",), given="Pat", family="Lee")
    b = _p("b", emails=("info@acme.com",), given="Chris", family="Lee")
    outcome = decide(a, b)
    assert outcome is not None and outcome.decision == Decision.REVIEW
    assert outcome.rule == "R1_exact_email_initial_conflict"


def test_r1_same_given_initial_still_auto_merges():
    a = _p("a", emails=("info@acme.com",), given="Pat", family="Lee")
    b = _p("b", emails=("info@acme.com",), given="Patty", family="Lee")
    outcome = decide(a, b)
    assert outcome is not None and outcome.decision == Decision.AUTO_MERGE


def test_r2_exact_email_different_family_review():
    a = _p("a", emails=("info@acme.com",), given="Pat", family="Lee")
    b = _p("b", emails=("info@acme.com",), given="Sam", family="Wu")
    outcome = decide(a, b)
    assert outcome is not None and outcome.decision == Decision.REVIEW


def test_r3_corporate_local_shape_review():
    a = _p("a", emails=("j.smith@acme.com",), given="Jane", family="Smith")
    b = _p("b", emails=("jsmith@acme.com",), given="Janet", family="Smith")
    outcome = decide(a, b)
    assert outcome is not None and outcome.decision == Decision.REVIEW
    assert outcome.rule == "R3_corporate_local_shape"


def test_different_people_same_corporate_domain_no_decision():
    a = _p("a", emails=("jane@acme.com",), given="Jane", family="Smith")
    b = _p("b", emails=("bob@acme.com",), given="Bob", family="Wu")
    assert decide(a, b) is None


def test_no_email_no_decision():
    a = _p("a", given="Jane", family="Smith")
    b = _p("b", given="Janet", family="Smith")
    assert decide(a, b) is None


def test_decide_is_symmetric():
    a = _p("a", emails=("j.smith@acme.com",), given="Jane", family="Smith")
    b = _p("b", emails=("jsmith@acme.com",), given="Janet", family="Smith")
    assert decide(a, b) == decide(b, a)


def test_decide_symmetric_with_differing_initials():
    # Gate finding: shapes built from one side's given initial broke symmetry.
    a = _p("a", emails=("j.smith@acme.com",), given="Jane", family="Smith")
    b = _p("b", emails=("bsmith@acme.com",), given="Bob", family="Smith")
    assert decide(a, b) == decide(b, a)
    assert decide(a, b) is not None and decide(a, b).decision == Decision.REVIEW


def test_r3_skips_free_mail_domains():
    # j.smith@gmail.com vs jsmith@gmail.com: two different Smiths — no employer
    # signal on free mail, no review-queue noise.
    a = _p("a", emails=("j.smith@gmail.com",), given="Jane", family="Smith")
    b = _p("b", emails=("jsmith@gmail.com",), given="John", family="Smith")
    assert decide(a, b) is None


def test_candidate_pairs_caps_role_inbox_buckets():
    # 500 people on one info@ address: wholesale pairing is 125k REVIEW pairs of
    # noise — bounded deterministic subsample instead.
    crowd = [
        _p(f"p{i}", emails=("info@acme.com",), given=f"G{i}", family="Wu")
        for i in range(500)
    ]
    pairs = candidate_pairs(crowd)
    max_pairs = 200 * 199 // 2  # capped bucket size
    assert len(pairs) <= max_pairs
    assert len(pairs) > 0

    # And it's deterministic across orderings.
    assert candidate_pairs(list(reversed(crowd))) == pairs


def test_slugify_digests_non_ascii_names():
    # CJK org names must not collapse every org into one "unknown" bucket.
    assert slugify("株式会社スタート") != slugify("北京科技有限公司")
    assert slugify("株式会社スタート") == slugify("株式会社スタート")  # stable
    assert slugify("") == "unknown"  # genuinely empty stays unknown

from substrate.er.blocking import PersonRecord, blocking_keys, candidate_pairs, slugify
from substrate.er.rules import Decision, decide


def _p(pid, *, emails=(), given=None, family=None, employer=None):
    domain = emails[0].split("@", 1)[1] if emails else None
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


# ---- rules ----


def test_r1_exact_email_same_family_auto_merge():
    a = _p("a", emails=("j.smith@acme.com",), given="Jane", family="Smith")
    b = _p("b", emails=("j.smith@acme.com",), given="Janet", family="Smith")
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

from substrate.seniority import SENIORITY_RANK, classify_seniority
from substrate.signals.detector import PositionSnapshot, diff_positions


def _snap(pid, pos, org, org_name, title, seniority):
    return PositionSnapshot(
        person_id=pid, position_id=pos, org_id=org, org_name=org_name,
        title_norm=title, seniority=seniority,
    )


def test_org_change_is_job_change():
    old = _snap("p1", "pos1", "org1", "Acme", "VP Engineering", "vp")
    new = _snap("p1", "pos2", "org2", "Beta", "CTO", "c_level")
    signal = diff_positions(old, new)
    assert signal is not None and signal.event_type == "job_change"
    assert signal.old_state["org_name"] == "Acme"
    assert signal.new_state["org_name"] == "Beta"
    assert signal.confidence == 1.0


def test_seniority_increase_same_org_is_promotion():
    old = _snap("p1", "pos1", "org1", "Acme", "Engineer", "ic")
    new = _snap("p1", "pos2", "org1", "Acme", "Senior Engineer", "senior_ic")
    signal = diff_positions(old, new)
    assert signal is not None and signal.event_type == "promotion"


def test_lateral_retitle_is_silence():
    old = _snap("p1", "pos1", "org1", "Acme", "Engineer", "ic")
    new = _snap("p1", "pos2", "org1", "Acme", "Platform Engineer", "ic")
    assert diff_positions(old, new) is None


def test_unknown_seniority_never_reads_as_promotion():
    old = _snap("p1", "pos1", "org1", "Acme", "Ninja Rockstar", None)
    new = _snap("p1", "pos2", "org1", "Acme", "Senior Ninja Rockstar", None)
    assert diff_positions(old, new) is None  # conservative: silence over noise


def test_no_change_is_silence():
    old = _snap("p1", "pos1", "org1", "Acme", "VP Engineering", "vp")
    new = _snap("p1", "pos2", "org1", "Acme", "VP Engineering", "vp")
    assert diff_positions(old, new) is None


def test_idempotency_key_is_stable_per_new_position():
    old = _snap("p1", "pos1", "org1", "Acme", "VP Engineering", "vp")
    new1 = _snap("p1", "pos2", "org2", "Beta", "CTO", "c_level")
    new2 = _snap("p1", "pos2", "org2", "Beta", "CTO", "c_level")
    assert diff_positions(old, new1).key == diff_positions(old, new2).key


def test_idempotency_key_changes_with_new_position():
    old = _snap("p1", "pos1", "org1", "Acme", "VP Engineering", "vp")
    a = diff_positions(old, _snap("p1", "pos2", "org2", "Beta", "CTO", "c_level"))
    b = diff_positions(old, _snap("p1", "pos3", "org2", "Beta", "CTO", "c_level"))
    assert a.key != b.key


def test_classify_seniority_bands():
    assert classify_seniority("Chief Executive Officer") == "c_level"
    assert classify_seniority("VP Engineering") == "vp"
    assert classify_seniority("Senior Director of Sales") == "senior_director"
    assert classify_seniority("Sr. Director") == "senior_director"  # gate r12: sr. banding
    assert classify_seniority("Sr. Manager") == "senior_manager"
    assert classify_seniority("Senior Engineer") == "senior_ic"
    assert classify_seniority("Product Designer") == "ic"  # default IC band
    assert classify_seniority("Account Executive, Mid-Market") == "ic"


def test_word_boundaries_block_substring_false_bands():
    # Gate round-2: substring matching classified "International ..." as intern.
    assert classify_seniority("International Account Executive") == "ic"
    assert classify_seniority("Internal Communications Manager") == "manager"


def test_rank_table_is_total_over_bands():
    assert set(SENIORITY_RANK) == {
        "intern", "ic", "senior_ic", "lead", "principal", "manager",
        "senior_manager", "director", "senior_director", "vp", "svp", "c_level",
    }
    assert max(SENIORITY_RANK.values()) == SENIORITY_RANK["c_level"]

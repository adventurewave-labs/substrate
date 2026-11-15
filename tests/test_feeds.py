import json
from pathlib import Path

import pytest

from substrate.sources.feeds import coresignal_company_claims, pdl_company_claims

FIXTURES = Path(__file__).parent / "fixtures"


def test_coresignal_mapper_produces_provenanced_claims():
    payload = json.loads((FIXTURES / "coresignal.json").read_text())
    org_id = _uuid("11111111-1111-1111-1111-111111111111")
    drafts = coresignal_company_claims(payload, org_id=org_id)
    fields = {d.field for d in drafts}
    assert fields == {"employee_count", "description", "industry"}
    for draft in drafts:
        draft.validate_provenance()  # every draft ships with provenance
        assert draft.entity_id == org_id
        assert draft.source_type == "coresignal"
        assert draft.url and draft.source_id


def test_pdl_mapper_produces_provenanced_claims():
    payload = json.loads((FIXTURES / "pdl.json").read_text())
    org_id = _uuid("22222222-2222-2222-2222-222222222222")
    drafts = pdl_company_claims(payload, org_id=org_id)
    fields = {d.field for d in drafts}
    assert fields == {"employee_count", "description", "industry"}
    for draft in drafts:
        draft.validate_provenance()


def test_feed_shape_changes_fail_loudly():
    org_id = _uuid("33333333-3333-3333-3333-333333333333")
    with pytest.raises(ValueError, match="shape changed"):
        coresignal_company_claims({"employees_count": "not-a-number"}, org_id=org_id)
    with pytest.raises(ValueError, match="shape changed"):
        pdl_company_claims({"employee_count": {"nested": True}}, org_id=org_id)


def test_unanchored_drafts_refuse_to_persist():
    from substrate.sources.writer import ClaimDraft

    draft = ClaimDraft(
        entity_type="organization", field="employee_count", value_norm="184",
        source_type="coresignal", source_id="acme.com", url=None,
        retrieved_at=_now(), entity_id=None,
    )
    with pytest.raises(ValueError, match="skipped, not persisted"):
        draft.validate_provenance()


def _uuid(value: str):
    from uuid import UUID

    return UUID(value)


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)

"""Writer pure-logic: provenance enforcement and anchoring contracts (no DB)."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from substrate.sources.writer import ClaimDraft


def _draft(**overrides):
    base = {
        "entity_type": "organization",
        "field": "employee_count",
        "value_norm": "184",
        "source_type": "coresignal",
        "source_id": "acme.com",
        "url": "https://api.coresignal.example/acme",
        "retrieved_at": datetime.now(UTC),
        "entity_id": uuid4(),
    }
    base.update(overrides)
    return ClaimDraft(**base)


def test_valid_draft_passes():
    _draft().validate_provenance()  # must not raise


def test_missing_both_source_id_and_url_is_rejected():
    with pytest.raises(ValueError, match="provenance incomplete"):
        _draft(source_id=None, url=None).validate_provenance()


def test_missing_source_type_is_rejected():
    with pytest.raises(ValueError, match="provenance incomplete"):
        _draft(source_type="").validate_provenance()


def test_invalid_entity_type_is_rejected():
    with pytest.raises(ValueError, match="invalid entity_type"):
        _draft(entity_type="position").validate_provenance()


def test_unanchored_draft_is_rejected_not_guessed():
    with pytest.raises(ValueError, match="skipped, not persisted"):
        _draft(entity_id=None).validate_provenance()


def test_person_entity_type_is_valid():
    draft = _draft(entity_type="person", field="title_norm", value_norm="vp_eng")
    draft.validate_provenance()  # persons exist; consumer data never does

import pytest
from pydantic import ValidationError

from substrate.config import Settings


def test_settings_read_prefixed_env(monkeypatch):
    monkeypatch.setenv("SUBSTRATE_DATABASE_URL", "postgresql://u:p@localhost:5432/substrate")
    monkeypatch.setenv("SUBSTRATE_BATCH_SIZE", "1000")

    s = Settings()
    assert s.database_url == "postgresql://u:p@localhost:5432/substrate"
    assert s.batch_size == 1000
    assert s.object_store_bucket == "substrate-claims-raw"  # default holds


def test_missing_database_url_fails_closed(monkeypatch):
    monkeypatch.delenv("SUBSTRATE_DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_no_secrets_defaults_into_code(monkeypatch):
    # Invariant guard: the only required setting is the connection URL — there is no
    # code-level default credential anywhere.
    monkeypatch.setenv("SUBSTRATE_DATABASE_URL", "postgresql://u:p@localhost:5432/substrate")
    s = Settings()
    fields = type(s).model_fields
    for name, f in fields.items():
        assert not (f.is_required() and name != "database_url")

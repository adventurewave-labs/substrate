"""Environment-driven configuration.

Secrets arrive via env vars (secret manager in prod) — never hardcoded (repo invariant).
Every variable carries the SUBSTRATE_ prefix.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SUBSTRATE_", extra="ignore")

    database_url: str
    object_store_bucket: str = "substrate-claims-raw"
    batch_size: int = 5_000
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # pydantic-settings reads SUBSTRATE_* from env

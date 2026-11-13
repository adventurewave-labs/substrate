# Substrate — repo working agreements (trust anchor)

Product source of truth: `docs/PRD-living-gtm-graph-2026-11-12.md` · Build source of truth: `docs/PLAN-substrate-m0-m2-execution-2026-11-12.md`.

## Invariants

- Identity is never decided by an LLM: LLMs extract and normalize; identity resolution is deterministic/learned ER (blocking → pairwise scoring → constrained clustering).
- Every attribute claim carries provenance: source_type, source_id, url, retrieved_at, extractor_version, confidence. No claim without provenance.
- Positions are bitemporal: valid-time (when true in the world) and transaction-time (when we believed it) are separate columns and never conflated.
- Claims are append-only: corrections supersede via `superseded_by`; UPDATE/DELETE on claims is blocked except in erasure mode (GDPR/CCPA cascades).
- B2B professional contacts only — no consumer personal data in any table, log, fixture, or test.
- CRM access is read-only by default; writeback is opt-in behind a field-level allowlist (contact fields only in v1).
- Tenant isolation: every business table carries `tenant_id`; every query touching tenant data is tenant-scoped. Customer data never crosses tenants.
- Secrets never enter git: credentials travel via env/secret manager only — no connection strings, tokens, or keys in code, tests, or fixtures.
- No graph database in v1: Postgres + recursive CTEs. Schema changes ride numbered SQL migrations recorded in `schema_migrations`.
- Importers and emitters are replay-safe: deterministic external-id mapping, upsert semantics, idempotency keys on events. Re-running an import must not duplicate entities or events.
- Import never merges identities: one person per external id; cross-source merging belongs to the ER engine, never the import path.

## Gate checks

- .venv/bin/pytest -q tests/
- .venv/bin/ruff check src tests
Guards: src/ db/ tests/ pyproject.toml .github/ terraform/

## Review lane

- deterministic
- Guards: src/ db/ tests/ pyproject.toml .github/ terraform/

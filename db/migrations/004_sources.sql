-- 004_sources.sql — W5–6 source layer: watch list, job postings, funding events,
-- and the LLM extraction cache. PLAN §7: crawlers + extraction + 2 feed adapters.

-- What each tenant wants observed. Board tokens are per-platform watch config —
-- deterministic, no YAML, no secrets (tokens are public board slugs).
CREATE TABLE watch_sources (
    tenant_id        uuid NOT NULL REFERENCES tenants (id),
    domain           text NOT NULL,
    greenhouse_board text,
    lever_board      text,
    ashby_board      text,
    sec_cik          text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, domain)
);

-- Careers signals (F3 destination intelligence raw material).
-- Ownership is enforced at the DB level: an org row belongs to exactly one tenant,
-- so source tables reference the (tenant_id, org_id) PAIR (round-2 gate review).
ALTER TABLE organizations ADD CONSTRAINT organizations_id_tenant_key UNIQUE (id, tenant_id);

CREATE TABLE job_postings (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants (id),
    org_id      uuid NOT NULL,
    FOREIGN KEY (tenant_id, org_id) REFERENCES organizations (tenant_id, id),
    title_norm  text NOT NULL,
    function    text,                  -- engineering, sales, ... (normalized)
    location    text,
    source_type text NOT NULL,         -- 'greenhouse' | 'lever' | 'ashby' | feed names
    url         text NOT NULL,
    posted_at   timestamptz,
    retrieved_at timestamptz NOT NULL,
    closed_at   timestamptz,           -- delisted from the board; NOT the GDPR erasure column
    UNIQUE (tenant_id, org_id, source_type, url)  -- one posting = one URL; matches the writer's ON CONFLICT target
);
CREATE INDEX idx_job_postings_org ON job_postings (org_id, retrieved_at DESC);

-- Funding signals (Form D + press corroboration).
CREATE TABLE funding_events (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES tenants (id),
    org_id        uuid NOT NULL,
    FOREIGN KEY (tenant_id, org_id) REFERENCES organizations (tenant_id, id),
    round_type    text,                -- seed, series_a, ... (normalized; NULL if unknown)
    amount_usd    numeric(16, 2),
    announced_on  date NOT NULL,
    source_type   text NOT NULL,       -- 'edgar' | 'press' | feed names
    url           text NOT NULL,
    corroborated_by uuid[],            -- other source rows backing the same event
    closed_at     timestamptz,         -- NOT the GDPR erasure column
    retrieved_at  timestamptz NOT NULL,
    UNIQUE (org_id, announced_on, source_type, url)  -- replay-safe idempotency
);
CREATE INDEX idx_funding_org ON funding_events (org_id, announced_on DESC);

-- LLM extraction cache: keyed by content, model, and prompt version — the budget
-- ceiling is respected across reruns, and identical text never re-extracts.
-- Global, NON-business table: extracted text only, no tenant identifiers, no
-- tenant scoping (documented decision, PR #5 review round 1).
CREATE TABLE llm_cache (
    cache_key   text PRIMARY KEY,      -- sha256(model + prompt_version + canonical input)
    model       text NOT NULL,
    prompt_version text NOT NULL,
    response    jsonb NOT NULL,
    cost_usd    numeric(10, 6) NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Watch-list management helper for the CLI (upsert one row).
CREATE OR REPLACE FUNCTION watch_upsert(
    p_tenant uuid, p_domain text,
    p_greenhouse text, p_lever text, p_ashby text, p_cik text
) RETURNS void AS $$
    INSERT INTO watch_sources (tenant_id, domain, greenhouse_board, lever_board, ashby_board, sec_cik)
    VALUES (p_tenant, p_domain, p_greenhouse, p_lever, p_ashby, p_cik)
    ON CONFLICT (tenant_id, domain) DO UPDATE SET
        greenhouse_board = COALESCE(EXCLUDED.greenhouse_board, watch_sources.greenhouse_board),
        lever_board      = COALESCE(EXCLUDED.lever_board, watch_sources.lever_board),
        ashby_board      = COALESCE(EXCLUDED.ashby_board, watch_sources.ashby_board),
        sec_cik          = COALESCE(EXCLUDED.sec_cik, watch_sources.sec_cik);
$$ LANGUAGE sql;

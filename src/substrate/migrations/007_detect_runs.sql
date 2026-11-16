-- 007_detect_runs.sql — records whether detection has EVER run for a tenant.
-- Auto-first-run semantics (gate r14): "first run" is a fact about the tenant's
-- history, not an inference from zero events — a genuine first move must alert,
-- only the pre-watch BACKLOG is suppressed.
CREATE TABLE IF NOT EXISTS detect_runs (
    tenant_id uuid PRIMARY KEY REFERENCES tenants (id),
    ran_at    timestamptz NOT NULL DEFAULT now()
);

-- 001_init.sql — Substrate core schema (PRD §7, PLAN §3)
-- PostgreSQL >= 15. Extensions: btree_gist (bitemporal exclusion), pg_trgm (name blocking).
-- No BEGIN/COMMIT here: the migration runner wraps each file in its own transaction.
--
-- Design contracts (repo invariants, see AGENTS.md):
--   * claims are append-only; corrections supersede via superseded_by
--   * positions are bitemporal: valid_start/valid_end (world truth) vs txn_from/txn_to (our belief)
--   * every business table is tenant-scoped
--   * import never merges identities — merging belongs to the ER engine (merge_decisions/review_queue)

CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE tenants (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name       text NOT NULL UNIQUE,
    crm_type   text NOT NULL CHECK (crm_type IN ('salesforce', 'hubspot', 'csv')),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Entities (canonical nodes; clustering happens above these via merge_decisions)
-- ---------------------------------------------------------------------------

CREATE TABLE persons (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  uuid NOT NULL REFERENCES tenants (id),
    name_full  text,
    name_given text,
    name_family text,
    emails     text[] NOT NULL DEFAULT '{}',
    erased_at  timestamptz,           -- tombstone; erasure cascades honor this
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE organizations (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      uuid NOT NULL REFERENCES tenants (id),
    name_canonical text,
    domains        text[] NOT NULL DEFAULT '{}',
    hq_city        text,
    hq_country     text,
    size_band      text,
    industry       text,
    erased_at      timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

-- Stable per-tenant identity anchors. This is what makes imports replay-safe:
-- (tenant_id, system, external_id) -> one entity, always the same one.
-- ER may later re-point external ids to a merged canonical entity.
CREATE TABLE external_ids (
    tenant_id   uuid NOT NULL REFERENCES tenants (id),
    system      text NOT NULL,        -- 'sfdc' | 'hubspot' | 'csv' | feed names
    external_id text NOT NULL,
    entity_type text NOT NULL CHECK (entity_type IN ('person', 'organization')),
    entity_id   uuid NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, system, external_id)
);
CREATE INDEX idx_external_ids_entity ON external_ids (entity_type, entity_id);

-- ---------------------------------------------------------------------------
-- Claims: append-only, provenance-backed attribute assertions
-- ---------------------------------------------------------------------------

-- entity_type/entity_id is a polymorphic reference (person|organization|position);
-- Postgres cannot FK polymorphic pairs, so referential integrity is enforced in the
-- application layer and audited by a nightly integrity check (W3+).
CREATE TABLE claims (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES tenants (id),
    entity_type       text NOT NULL CHECK (entity_type IN ('person', 'organization', 'position')),
    entity_id         uuid NOT NULL,
    field             text NOT NULL,
    value_norm        text,
    value_raw_ref     text,          -- object-store pointer to the raw extraction
    raw_sha256        text,
    source_type       text NOT NULL, -- 'sfdc' | 'hubspot' | 'csv' | feed names
    source_id         text,          -- external id of the record the claim came from
    url               text,
    retrieved_at      timestamptz NOT NULL,
    extractor_version text NOT NULL,
    confidence        numeric(4, 3) NOT NULL DEFAULT 1.000 CHECK (confidence >= 0 AND confidence <= 1),
    superseded_by     uuid REFERENCES claims (id),
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_claims_current
    ON claims (entity_type, entity_id, field)
    WHERE superseded_by IS NULL;
CREATE INDEX idx_claims_source ON claims (source_type, source_id);

-- Append-only enforcement: the only admitted mutation outside erasure mode is a
-- supersede (setting superseded_by on an otherwise unchanged row) — the correction
-- path used by replay-safe imports. Everything else requires
-- SET substrate.erasure_mode = 'on' inside the erasure-cascade transaction.
CREATE OR REPLACE FUNCTION claims_append_only_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF current_setting('substrate.erasure_mode', true) IS DISTINCT FROM 'on' THEN
            RAISE EXCEPTION 'claims are append-only (delete requires substrate.erasure_mode=on)';
        END IF;
        RETURN OLD;
    END IF;
    -- TG_OP = 'UPDATE'
    IF NEW.superseded_by IS NOT DISTINCT FROM OLD.superseded_by THEN
        IF current_setting('substrate.erasure_mode', true) IS DISTINCT FROM 'on' THEN
            RAISE EXCEPTION 'claims are append-only (no-op or non-supersede update blocked)';
        END IF;
        RETURN NEW;
    END IF;
    IF (NEW.id, NEW.tenant_id, NEW.entity_type, NEW.entity_id, NEW.field, NEW.value_norm,
        NEW.value_raw_ref, NEW.raw_sha256, NEW.source_type, NEW.source_id, NEW.url,
        NEW.retrieved_at, NEW.extractor_version, NEW.confidence, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.tenant_id, OLD.entity_type, OLD.entity_id, OLD.field, OLD.value_norm,
        OLD.value_raw_ref, OLD.raw_sha256, OLD.source_type, OLD.source_id, OLD.url,
        OLD.retrieved_at, OLD.extractor_version, OLD.confidence, OLD.created_at) THEN
        RAISE EXCEPTION 'claims are immutable except superseded_by';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER claims_append_only
    BEFORE UPDATE OR DELETE ON claims
    FOR EACH ROW EXECUTE FUNCTION claims_append_only_guard();

-- ---------------------------------------------------------------------------
-- Positions: bitemporal employment history (immutable versions)
-- ---------------------------------------------------------------------------

-- App contract: a new version closes the prior row (txn_to = now) in the same
-- transaction; the partial exclusion below then guarantees that concurrently-
-- current rows can never overlap in valid time for the same person+org.
CREATE TABLE positions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants (id),
    person_id   uuid NOT NULL REFERENCES persons (id),
    org_id      uuid NOT NULL REFERENCES organizations (id),
    title_norm  text,
    seniority   text,
    valid_start date NOT NULL DEFAULT CURRENT_DATE,
    valid_end   date,                  -- NULL = still true in the world
    txn_from    timestamptz NOT NULL DEFAULT now(),
    txn_to      timestamptz,           -- NULL = currently believed
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT positions_no_valid_overlap
        EXCLUDE USING gist (
            tenant_id WITH =,
            person_id WITH =,
            org_id WITH =,
            daterange(valid_start, valid_end) WITH &&
        ) WHERE (txn_to IS NULL)
);

CREATE INDEX idx_positions_current_person ON positions (person_id) WHERE txn_to IS NULL;
CREATE INDEX idx_positions_current_org ON positions (org_id) WHERE txn_to IS NULL;
CREATE INDEX idx_positions_history ON positions (person_id, txn_from);

-- ---------------------------------------------------------------------------
-- Relationship edges (evidence-typed; unverifiable edges are never written)
-- ---------------------------------------------------------------------------

CREATE TABLE edges (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES tenants (id),
    person_a_id   uuid NOT NULL REFERENCES persons (id),
    person_b_id   uuid NOT NULL REFERENCES persons (id),
    edge_type     text NOT NULL,       -- 'coworked_history' | 'shared_employer_now' | 'customer_colleague' | 'co_traveled_deal'
    evidence_type text NOT NULL,       -- provenance of the edge claim itself
    valid_start   date,
    valid_end     date,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT edges_no_self CHECK (person_a_id <> person_b_id)
);

CREATE INDEX idx_edges_a ON edges (tenant_id, person_a_id, edge_type);
CREATE INDEX idx_edges_b ON edges (tenant_id, person_b_id, edge_type);

-- ---------------------------------------------------------------------------
-- Events: the observable output (typed signals with provenance + verdicts)
-- ---------------------------------------------------------------------------

CREATE TABLE events (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES tenants (id),
    event_type      text NOT NULL,     -- 'job_change' | 'promotion' | ...
    entity_id       uuid NOT NULL,     -- person the event is about
    old_state       jsonb,
    new_state       jsonb,
    confidence      numeric(4, 3),
    provenance_refs uuid[] NOT NULL DEFAULT '{}',  -- claim ids backing the event
    detected_at     timestamptz NOT NULL DEFAULT now(),
    delivered_at    timestamptz,
    customer_verdict text CHECK (customer_verdict IN ('validated', 'false_positive', 'unknown')),
    idempotency_key text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT events_unique_key UNIQUE (tenant_id, idempotency_key)
);

CREATE INDEX idx_events_tenant_time ON events (tenant_id, detected_at DESC);

-- ---------------------------------------------------------------------------
-- ER machinery: golden set, merge decisions, human review queue
-- ---------------------------------------------------------------------------

CREATE TABLE golden_set (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid REFERENCES tenants (id),  -- NULL = rig-wide benchmark pairs
    pair_kind         text NOT NULL,   -- 'exact_email' | 'fuzzy_same_org' | 'fuzzy_diff_org' | 'hard_negative'
    left_system       text NOT NULL,
    left_external_id  text NOT NULL,
    right_system      text NOT NULL,
    right_external_id text NOT NULL,
    label             text NOT NULL CHECK (label IN ('same', 'different')),
    labeled_by        text NOT NULL,
    labeled_at        timestamptz NOT NULL DEFAULT now(),
    notes             text
);

CREATE TABLE merge_decisions (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          uuid NOT NULL REFERENCES tenants (id),
    cluster_a          uuid NOT NULL,  -- person id
    cluster_b          uuid NOT NULL,  -- person id
    score              numeric(5, 4),
    decision           text NOT NULL CHECK (decision IN ('auto_merge', 'review', 'reject')),
    featureset_version text NOT NULL,
    decided_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_merge_decisions_pair ON merge_decisions (tenant_id, cluster_a, cluster_b);

CREATE TABLE review_queue (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          uuid NOT NULL REFERENCES tenants (id),
    left_person_id     uuid NOT NULL REFERENCES persons (id),
    right_person_id    uuid NOT NULL REFERENCES persons (id),
    score              numeric(5, 4) NOT NULL,
    featureset_version text NOT NULL,
    status             text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'merged', 'rejected')),
    decided_by         text,
    decided_at         timestamptz,
    created_at         timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Import plumbing
-- ---------------------------------------------------------------------------

CREATE TABLE import_checkpoints (
    tenant_id     uuid NOT NULL REFERENCES tenants (id),
    object_name   text NOT NULL,       -- 'contact' | 'account' | ...
    watermark     timestamptz,
    rows_imported bigint NOT NULL DEFAULT 0,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, object_name)
);

-- 003_review_queue_pair_guard.sql — one pending queue row per pair, enforced in SQL.
-- ER reruns (--force) append-only queue inserts; the partial unique index makes the
-- no-duplicate-pending-pair contract hold even under concurrent runs.
CREATE UNIQUE INDEX IF NOT EXISTS uq_review_queue_pending_pair
    ON review_queue (tenant_id, left_person_id, right_person_id)
    WHERE status = 'pending';

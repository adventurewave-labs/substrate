-- 003_review_queue_pair_guard.sql — one pending queue row per pair, enforced in SQL.
-- ER reruns (--force) append-only queue inserts; the partial unique index makes the
-- no-duplicate-pending-pair contract hold even under concurrent runs.
-- Pre-dedupe keeps the earliest pending row per pair so the index builds cleanly
-- on instances that predate the contract.
DELETE FROM review_queue a
USING review_queue b
WHERE a.status = 'pending'
  AND b.status = 'pending'
  AND a.tenant_id = b.tenant_id
  AND a.left_person_id = b.left_person_id
  AND a.right_person_id = b.right_person_id
  AND (a.created_at > b.created_at
       OR (a.created_at = b.created_at AND a.id::text > b.id::text));

CREATE UNIQUE INDEX IF NOT EXISTS uq_review_queue_pending_pair
    ON review_queue (tenant_id, left_person_id, right_person_id)
    WHERE status = 'pending';

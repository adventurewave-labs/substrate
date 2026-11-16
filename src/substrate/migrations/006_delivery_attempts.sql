-- 006_delivery_attempts.sql — bounded retry: permanently-failing events retire
-- after MAX_DELIVERY_ATTEMPTS instead of pinning the oldest-first batch forever
-- (gate review, W7–8 round 9: head-of-queue stall).
ALTER TABLE events ADD COLUMN IF NOT EXISTS delivery_attempts int NOT NULL DEFAULT 0;

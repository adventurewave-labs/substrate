-- 008_tenant_delivery.sql — per-tenant delivery destination (gate review, W9:
-- a single global webhook routed every tenant's alerts to the same Slack).
-- NULL = delivery not configured for that tenant (counted, never guessed).
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS slack_webhook_url text;

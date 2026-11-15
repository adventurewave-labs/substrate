-- 002_decision_rule.sql — store the rule identity on ER decisions.
-- Reviewer finding (gate, PR #4): featureset_version alone can't trace a stored
-- decision back to the rule that produced it (R1/R2/R3). Add the rule id.
ALTER TABLE merge_decisions ADD COLUMN IF NOT EXISTS rule text;
ALTER TABLE review_queue ADD COLUMN IF NOT EXISTS rule text;

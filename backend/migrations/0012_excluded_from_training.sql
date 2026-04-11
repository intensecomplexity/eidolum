-- Ship #12 — historical data cleanup (training-set hygiene pass)
-- Adds soft-exclusion flags so the fine-tune loader can skip rows
-- flagged by ship_12_audit.py without deleting them from production.
-- Leaderboard / consensus / activity / evaluator queries are untouched.

ALTER TABLE predictions
  ADD COLUMN IF NOT EXISTS excluded_from_training BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS exclusion_reason VARCHAR(64) NULL,
  ADD COLUMN IF NOT EXISTS exclusion_flagged_at TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS exclusion_rule_version VARCHAR(16) NULL;

ALTER TABLE disclosures
  ADD COLUMN IF NOT EXISTS excluded_from_training BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS exclusion_reason VARCHAR(64) NULL,
  ADD COLUMN IF NOT EXISTS exclusion_flagged_at TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS exclusion_rule_version VARCHAR(16) NULL,
  ADD COLUMN IF NOT EXISTS source_prediction_id BIGINT NULL
    REFERENCES predictions(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_predictions_excluded
  ON predictions (excluded_from_training) WHERE excluded_from_training = TRUE;

CREATE INDEX IF NOT EXISTS idx_disclosures_excluded
  ON disclosures (excluded_from_training) WHERE excluded_from_training = TRUE;

CREATE INDEX IF NOT EXISTS idx_disclosures_source_prediction
  ON disclosures (source_prediction_id) WHERE source_prediction_id IS NOT NULL;

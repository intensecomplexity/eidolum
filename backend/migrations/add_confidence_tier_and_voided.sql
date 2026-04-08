-- Add confidence_tier, prediction_type, and voided outcome state.
--
-- Purpose:
--   confidence_tier  — multiplier for weighting vibes/conviction predictions
--                      less than explicit targets (default 1.0 = full weight)
--   prediction_type  — distinguishes new classes of predictions from the
--                      default 'price_target' flow
--   'voided' outcome — for conditional predictions where the condition
--                      never materialized
--
-- The outcome column is a plain VARCHAR (see backend/models.py:80), so
-- no enum ALTER is actually needed — the DO $$ block is defensive in
-- case a future migration converts it to a true pg_type enum.
--
-- Idempotent: safe to re-run.

BEGIN;

-- 1. confidence_tier: 1.0 = full weight (default for everything existing)
ALTER TABLE predictions
    ADD COLUMN IF NOT EXISTS confidence_tier NUMERIC(3,2) NOT NULL DEFAULT 1.0;

-- 2. prediction_type: classifies what kind of prediction this row is
ALTER TABLE predictions
    ADD COLUMN IF NOT EXISTS prediction_type VARCHAR(32) NOT NULL DEFAULT 'price_target';

-- 3. Index for filtering by type
CREATE INDEX IF NOT EXISTS idx_predictions_type
    ON predictions(prediction_type);

-- 4. If outcome is ever converted to a pg_type enum, ensure 'voided' is valid.
--    On the current schema (VARCHAR), this block finds no enum and does nothing.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'outcome_enum') THEN
        BEGIN
            ALTER TYPE outcome_enum ADD VALUE IF NOT EXISTS 'voided';
        EXCEPTION WHEN duplicate_object THEN
            NULL;
        END;
    END IF;
END$$;

-- 5. Verification: confirm every existing row has the expected defaults.
SELECT
    COUNT(*)                                              AS total_predictions,
    COUNT(*) FILTER (WHERE confidence_tier = 1.0)         AS full_weight,
    COUNT(*) FILTER (WHERE prediction_type = 'price_target') AS price_target_type
FROM predictions;

COMMIT;

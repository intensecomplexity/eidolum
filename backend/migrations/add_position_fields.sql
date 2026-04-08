-- Position disclosure tracking columns.
--
-- Purpose: support prediction_type='position_disclosure' — tweets like
-- "New position in $NVDA" that are real signals but lack explicit price
-- targets. Each position has an open/add lifecycle and is closed by a
-- later trim/exit tweet from the same forecaster (or a fixed 365-day
-- fallback horizon, whichever comes first).
--
-- Idempotent: safe to re-run.

BEGIN;

-- Timestamp of the tweet that closed this position (NULL while open).
-- On close, the ingestion pipeline also sets evaluation_date = this value
-- so the evaluator will score at the next cycle.
ALTER TABLE predictions
    ADD COLUMN IF NOT EXISTS position_closed_at TIMESTAMP;

-- Which kind of position action this row represents.
-- Values: 'open', 'add', 'trim', 'exit' (NULL for non-position predictions).
ALTER TABLE predictions
    ADD COLUMN IF NOT EXISTS position_action VARCHAR(16);

-- Partial index for the position_matcher lookup: find the most recent
-- OPEN position for a given forecaster+ticker. Including prediction_type
-- in the WHERE narrows the index to just position rows.
CREATE INDEX IF NOT EXISTS idx_predictions_position_open
    ON predictions(forecaster_id, ticker, prediction_date DESC)
    WHERE prediction_type = 'position_disclosure' AND position_closed_at IS NULL;

COMMIT;

-- 2026-06-02 reported-speech audit.
-- Flags predictions whose source quote is third-party attribution
-- ("analysts expect", "consensus price target", "<firm> says") rather
-- than the forecaster's own conviction call. Rows are kept in the DB
-- for audit/retraining; user-facing surfaces filter them out via
-- routers._prediction_filters.hedged_filter_sql (bundled).

ALTER TABLE predictions
  ADD COLUMN IF NOT EXISTS is_reported_speech BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS ix_predictions_is_reported_speech
  ON predictions (is_reported_speech) WHERE is_reported_speech = TRUE;

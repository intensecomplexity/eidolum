-- 2026-06-14 quote-accountability population pass (n=200 audit 2c7bd35).
-- TRUE = NOT_ACCOUNTABLE: no claim-bearing sentence for the ticker exists anywhere
-- in the ±90s transcript window / tweet — only commentary, narration, a past recap,
-- or a bare mention. These are not real scored predictions: hidden from every user
-- surface via routers/_prediction_filters.hedged_filter_sql (bundled; kill switch
-- HIDE_NO_CLAIM, default on) AND taken off the accuracy board (outcome='unresolved').
-- Rows stay in the DB for audit. Mirrors is_holding_disclosure (0022) /
-- is_reported_speech (0017). LLM-judged per row by scripts/accountability_pass_2026_06_14.py.
-- Run manually as owner (RUN_STARTUP_DDL=false in prod):
--   psql "$DATABASE_PUBLIC_URL" -f backend/migrations/0023_is_no_claim.sql

ALTER TABLE predictions
  ADD COLUMN IF NOT EXISTS is_no_claim BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS ix_predictions_is_no_claim
  ON predictions (is_no_claim) WHERE is_no_claim = TRUE;

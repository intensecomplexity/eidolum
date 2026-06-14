-- 2026-06-14 holdings taxonomy ship.
-- TRUE = a PASSIVE holding disclosure ("I'm happy to keep holding", "my biggest
-- position", "I own it long term") rather than an active buy/sell recommendation.
-- These are NOT scored calls: they are taken off the accuracy board (outcome set
-- to 'unresolved') AND hidden from EVERY user-facing surface via
-- routers/_prediction_filters.hedged_filter_sql (bundled; kill switch
-- HIDE_HOLDING_DISCLOSURES, default on). Rows stay in the DB for audit and a
-- future holdings surface. Mirrors is_reported_speech (0017) / is_ambiguous_symbol
-- (0020) / is_weak_basket_call. LLM-judged per row by scripts/
-- reclass_holdings_2026_06_14.py. Run manually as owner (RUN_STARTUP_DDL=false in prod):
--   psql "$DATABASE_PUBLIC_URL" -f backend/migrations/0022_is_holding_disclosure.sql

ALTER TABLE predictions
  ADD COLUMN IF NOT EXISTS is_holding_disclosure BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS ix_predictions_is_holding_disclosure
  ON predictions (is_holding_disclosure) WHERE is_holding_disclosure = TRUE;

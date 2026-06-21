-- 2026-06-21 no-gradeable-claim detector (gold-anchor root cause, GOLD_FINDINGS 47.6%).
-- TRUE = NOT_GRADEABLE: the row has NEITHER a number (price target / % / level) NOR a
-- stock-direction stance on the ticker — vague preference ("I like it", "great company"),
-- a buy-wishlist ("on my watchlist", "I'd love to own it someday"), or a hedged non-call.
-- These are not gradeable forward predictions: hidden from every user surface via
-- routers/_prediction_filters.hedged_filter_sql (bundled; kill switch HIDE_NO_GRADEABLE_CLAIM,
-- default on) AND taken off the accuracy board (outcome='unresolved').
--
-- Distinct from is_no_claim (0023, quote-accountability: "no claim-bearing sentence in the
-- window"). This flag is about SCOREABILITY of the call itself, not the provenance of the
-- quote — a row can carry a claim-bearing sentence yet still be NOT_GRADEABLE ("great
-- company"). A separate column keeps the before/after precision measurement and the
-- reversibility surgical. Rows stay in the DB for audit. Mirrors is_no_claim (0023) /
-- is_holding_disclosure (0022) / is_reported_speech (0017).
--
-- app_worker already holds table-level SELECT+UPDATE on predictions, which covers columns
-- added later — no new GRANT needed (same as 0023; verified before ship).
--
-- Run manually as the DB OWNER (RUN_STARTUP_DDL=false in prod):
--   psql "$DATABASE_PUBLIC_URL" -f backend/migrations/0024_is_no_gradeable_claim.sql

ALTER TABLE predictions
  ADD COLUMN IF NOT EXISTS is_no_gradeable_claim BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS ix_predictions_is_no_gradeable_claim
  ON predictions (is_no_gradeable_claim) WHERE is_no_gradeable_claim = TRUE;

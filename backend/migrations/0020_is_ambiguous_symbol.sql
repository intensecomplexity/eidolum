-- 2026-06-10 symbol disambiguation ship.
-- TRUE = prediction can't be reliably attributed to a tradeable asset:
--   * ticker-reuse stale eras (LB = L Brands pre-2021-08, APC = Anadarko,
--     ARB = Arbitron) — the company no longer trades under the symbol;
--   * dead-equity crypto collisions (SOL = Emeren, SAND = Sandstorm Gold,
--     ETH = Ethan Allen era) — analyst rows on a coin symbol whose equity
--     identity is delisted/renamed, so neither coin nor equity scoring is
--     truthful.
-- Rows stay in the DB for audit/admin; user-facing surfaces hide them via
-- routers/_prediction_filters.hedged_filter_sql (bundled, kill switch
-- HIDE_AMBIGUOUS_SYMBOLS). Mirrors the is_reported_speech pattern (0017).

ALTER TABLE predictions
  ADD COLUMN IF NOT EXISTS is_ambiguous_symbol BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS ix_predictions_is_ambiguous_symbol
  ON predictions (is_ambiguous_symbol) WHERE is_ambiguous_symbol = TRUE;

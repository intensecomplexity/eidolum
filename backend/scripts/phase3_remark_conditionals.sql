-- Phase 3 (2026-06-11): re-mark the 51 flat-scored "if/then" price-conditional
-- ticker_calls that were hard-scored HIT/NEAR/MISS before conditional_call
-- extraction went live. They are spurious flat scorings of contingent calls
-- (24 MISS + 23 HIT + 4 NEAR). FLAG-NOT-DELETE: set outcome='unresolved' so
-- they drop from accuracy (numerator + denominator) on every user/leaderboard
-- surface while staying in the DB for admin visibility/audit.
--
-- Idempotent: re-running is a no-op (the outcome IN (...) guard skips already-
-- unresolved rows). Pinned to the exact 51 audited ids. Run manually against
-- prod (DATABASE_PUBLIC_URL, as owner). Then refresh forecaster stats.
--
--   psql "$DATABASE_PUBLIC_URL" -f backend/scripts/phase3_remark_conditionals.sql
--   curl -XPOST .../api/admin/refresh-forecaster-stats   (server-side, 70s)

UPDATE predictions
SET outcome = 'unresolved',
    evaluation_summary = 'Phase-3 re-mark: flat-scored conditional (if/then) -> unresolved (excluded from accuracy)',
    evaluated_at = NOW()
WHERE id IN (
    606858, 606862, 607589, 608143, 608629, 608721, 609014, 609098, 609150,
    609233, 609243, 609514, 610096, 610119, 610827, 610932, 611182, 612087,
    612135, 612161, 612166, 612564, 612578, 612588, 612609, 612626, 612635,
    612656, 612669, 612670, 612678, 612915, 612916, 613840, 614322, 614677,
    614727, 614888, 615674, 616280, 619086, 623761, 624017, 625903, 625931,
    626237, 626317, 626318, 626417, 626947, 628745
)
AND outcome IN ('hit', 'near', 'miss', 'correct', 'incorrect');

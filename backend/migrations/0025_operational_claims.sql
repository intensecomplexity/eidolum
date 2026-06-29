-- 2026-06-29 Operational prediction scoring — grade forecasts about company financials
-- (revenue, free cash flow, diluted EPS, net income, margins) against reported actuals,
-- not just price. Phase 1 schema.
--
-- NEW AXIS, additive and orthogonal to the existing `metric_forecast_call` category
-- (metric_type/metric_target/metric_period/metric_actual/...): `claim_type` tags EVERY
-- prediction price-vs-operational; `metric_kind` captures the claim SHAPE (absolute target
-- / growth% / CAGR / direction) which the existing metric_forecast columns do not model.
-- The price path is untouched — every existing row reads claim_type='price' (the default),
-- so all current scoring/filters behave exactly as before.
--
-- DEPLOY-SAFE: nullable columns — plus one constant-DEFAULT column (claim_type) — are
-- metadata-only in PG11+ (no table rewrite; the default is stored as attmissingval and
-- applied virtually). `lock_timeout` caps the brief ACCESS EXCLUSIVE wait so a busy
-- predictions table can never be blocked behind this. Every ADD is IF NOT EXISTS
-- (idempotent / re-runnable).
--
-- app_worker holds table-level SELECT+UPDATE+INSERT on predictions, which covers columns
-- added later — no new GRANT needed (verified before ship; same as 0023/0024).
--
-- Run manually as the DB OWNER (RUN_STARTUP_DDL=false in prod):
--   psql "$DATABASE_PUBLIC_URL" -f backend/migrations/0025_operational_claims.sql

SET lock_timeout = '4s';

ALTER TABLE predictions
  ADD COLUMN IF NOT EXISTS claim_type           TEXT      DEFAULT 'price',  -- 'price' | 'operational'
  ADD COLUMN IF NOT EXISTS metric_kind          TEXT,                       -- 'absolute'|'growth_pct'|'cagr'|'direction'
  ADD COLUMN IF NOT EXISTS metric_target_value  NUMERIC,                    -- e.g. 133e9 (FCF $) / 11.0 (% / CAGR%) / NULL (direction)
  ADD COLUMN IF NOT EXISTS metric_target_period TEXT,                       -- 'FY2027' | 'Q2-2026' | '+5y'
  ADD COLUMN IF NOT EXISTS metric_actual_value  NUMERIC,                    -- filled by the evaluator at resolution
  ADD COLUMN IF NOT EXISTS metric_resolved_at   TIMESTAMP;                  -- when the operational outcome was set

-- Tiny partial index: only operational rows (the evaluator + backfill scan target),
-- keyed by resolution status so "find pending operational claims" is an index scan.
CREATE INDEX IF NOT EXISTS ix_predictions_operational
  ON predictions (metric_resolved_at)
  WHERE claim_type IS DISTINCT FROM 'price' AND claim_type IS NOT NULL;

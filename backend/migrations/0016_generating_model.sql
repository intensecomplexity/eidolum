-- Ship: generating_model column (2026-04-19)
-- Isolates Haiku-era from Qwen-era YouTube predictions during the
-- grounding audit phase so we can report error rates, leaderboard
-- filters, and consensus queries per model without mixing the two.
--
-- Backfill source: predictions.verified_by, not created_at. The
-- classifier stamps verified_by at insert time based on which model
-- actually answered — including Haiku-fallback runs after the
-- USE_FINETUNED_MODEL flip. A naive `created_at < '2026-04-16'`
-- rule would mis-tag the 506 post-cutover Haiku-fallback rows.
--
-- Values:
--   'haiku'         — verified_by = 'youtube_haiku_v1'
--   'qwen_lora_v1'  — verified_by = 'youtube_qwen_v1'
--   NULL            — non-LLM sources (benzinga/fmp/x_scraper/etc.)
--                     and older yt_scraper title-parsed rows

ALTER TABLE predictions
  ADD COLUMN IF NOT EXISTS generating_model VARCHAR(32) NULL;

CREATE INDEX IF NOT EXISTS idx_predictions_generating_model
  ON predictions (generating_model)
  WHERE generating_model IS NOT NULL;

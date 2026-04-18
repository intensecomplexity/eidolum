-- Ship: grounding classifier (2026-04-18)
-- Adds a grounding classification to every prediction so we can tell
-- rows where the ticker came from an explicit mention in the quote
-- apart from rows inferred by Haiku/Qwen without any in-text backing.
-- Phase 2 is columns-only; Phase 3 backfills after operator approval.
--
-- grounding_type values:
--   'explicit'        — ticker symbol appears as a whole word in the window text
--   'implicit_alias'  — an alias mapped to this ticker appears as a whole word
--   'inferred'        — neither appears; the classifier relied on context alone
--   'no_window_text'  — window text was NULL / empty at classification time
--   NULL              — not yet classified (pre-backfill default)
--
-- grounding_matched_term records the actual substring that produced a
-- non-'inferred'/non-'no_window_text' classification. Useful for debugging
-- false positives ("BA" matching "Bay") and for building the follow-up
-- evaluator that stratifies accuracy by grounding bucket.

ALTER TABLE predictions
  ADD COLUMN IF NOT EXISTS grounding_type VARCHAR(32) NULL,
  ADD COLUMN IF NOT EXISTS grounding_matched_term VARCHAR(128) NULL;

CREATE INDEX IF NOT EXISTS idx_predictions_grounding_type
  ON predictions (grounding_type)
  WHERE grounding_type IS NOT NULL;

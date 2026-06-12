-- 2026-06-12: re-mark id 607365 (ORCL bearish, Dividend Data, video 8K8_Goan8k8)
-- -> 'unresolved'. LLM-judged over-inference (verdict a, same rubric as phase3b):
-- the transcript window shows NO committed bearish ORCL call — the host says
-- "I think the AI bubble is dramatically overstated" (bullish-on-AI) and calls
-- the Oracle CEOs' answers "pretty good"; the stored verbatim quote is a STITCH
-- of the host's sentences + the CEO's "AI is applicable to everything" line.
-- The classifier's own stored context note even reads "This is news reporting,
-- not [a prediction]" — the rejection reasoning was inserted as the call.
-- Direction was inferred from the selloff-news framing (video title:
-- "Oracle Stock is Selling Off After Risky A.I. Bet").
--
-- FLAG-NOT-DELETE, phase3b pattern: outcome='unresolved' drops it from accuracy
-- on every surface; row kept for audit. Original evaluation preserved inline.
-- Idempotent (outcome guard). Run manually against prod:
--   psql "$DATABASE_PUBLIC_URL" -f backend/scripts/remark_orcl_607365_over_inference.sql

UPDATE predictions
SET outcome = 'unresolved',
    evaluation_summary = 'Over-inference re-mark 2026-06-12: no committed bearish ORCL call in transcript; stitched bullish-on-AI quote; direction inferred from selloff news -> unresolved (excluded from accuracy). Original: ' || COALESCE(evaluation_summary, '(none)'),
    evaluated_at = NOW()
WHERE id = 607365
AND outcome IN ('hit', 'near', 'miss', 'correct', 'incorrect');

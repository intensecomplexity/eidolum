# Ship queue

Pending follow-up ships uncovered while triaging other work. Each entry
captures the symptom, the suspected file, and the fix shape so the next
person picking it up can size the work in 30 seconds.

---

## Ship #12.1 — snowflake date decoder bounds check

**Symptom**
Prediction `427048` (`AIXI`, source_type `x`) has `prediction_date = 1900-04-06 01:53:41`. Twitter did not exist in 1900. The row's `source_platform_id = x_2040971170816626747_AIXI` decodes correctly via the live snowflake helper (yields a 2026 timestamp), so the broken row was inserted before the current decoder was wired in — and nothing has gone back to fix the historical bad rows.

**Suspected file**
`backend/jobs/x_scraper.py:475-486` — `tweet_id_to_datetime(tweet_id)` decodes the snowflake using `TWITTER_EPOCH_MS = 1288834974657`. The function already returns `None` on parse failure but does NOT bounds-check the resulting datetime; an out-of-range tweet ID (or one decoded against the wrong epoch in older code) silently produced a 1900 date.

**Fix shape**
1. Inside `tweet_id_to_datetime`, after the `datetime.fromtimestamp` call, reject results outside `[2006-03-21, NOW + 1 day]` and return `None`. 2006-03-21 is the day Twitter launched; anything before is impossible.
2. Add a one-shot backfill script that scans `predictions WHERE source_type='x' AND (prediction_date < '2006-03-21' OR prediction_date > NOW())`, re-decodes each row's `tweet_id` via `tweet_id_to_datetime`, and either:
   - rewrites `prediction_date` if the re-decode succeeds, or
   - marks the row `excluded_from_training=TRUE`, `exclusion_reason='snowflake_decode_failed'` if it does not.
3. Add a unit test that asserts `tweet_id_to_datetime(0)` returns `None` (rather than 2010-11-04 from the epoch alone).

**Why we file it now**
The bug is dormant for new rows (the live decoder hasn't produced a 1900 date in months) but the historical bad rows are still poisoning the audit funnel — Phase A v2 saw `427048` because v12.2 was greedy enough to flag it for an unrelated reason. We want it cleaned out before fine-tune data export.

**Out of scope for this ship**
Anything else in `x_scraper.py`. Do not refactor the rejection-logging path while you're in there.

---

## Ship #12.2 — window_days upper cap + parser warning

**Symptom**
Prediction `605750` (`NVDA`, Nanalyze) has `window_days = 3651` because the speaker said "semiconductors will outperform over the next decade because of AI buildouts" and Haiku translated "next decade" literally into `2036-12-31`. The parser then computed the day delta and stored it without an upper bound. A 10-year window will never score in any reasonable timeframe and corrupts the leaderboard's pending-prediction count for the entire decade.

**Suspected files**
1. `backend/jobs/youtube_classifier.py:3126-3147` — `_parse_evaluation_date(timeframe_str, prediction_date)`. Builds `window = (d - prediction_date).days` and returns it unbounded. This is the actual leak path for `605750`.
2. `backend/jobs/youtube_classifier.py:3268-3349` — `_resolve_metadata_enrichment` already gates `inferred_timeframe_days` to `0 < n <= 2000`, so the metadata path is mostly safe but the cap is 5.5 years which is also too generous.
3. The Haiku system prompt at `backend/jobs/youtube_classifier.py:278-324` (constant `HAIKU_SYSTEM`) — does not currently tell the model to refuse multi-year claims. **Do not edit `HAIKU_SYSTEM` directly without Nimrod's approval.**

**Fix shape**
1. In `_parse_evaluation_date`, after computing `window = (d - prediction_date).days`, clamp to `min(window, 1825)` (5 years). When clamping fires, log a `WARN` with the original timeframe string and the prediction's ticker so we can audit the regression rate.
2. Drop the `_resolve_metadata_enrichment` ceiling from 2000 to 1825 to keep both paths consistent.
3. Persist a `window_clamped: True` marker on the prediction (either as a new column or as a `metadata` JSONB key — no schema add until we know the volume).
4. Add a guidance line to `HAIKU_SYSTEM` (NEEDS APPROVAL): "Reject timeframe claims longer than 5 years — those are directional statements, not actionable predictions. If the speaker says 'next decade', do not emit a price target."
5. Backfill: re-clamp every row in `predictions WHERE window_days > 1825` to 1825 and recompute `evaluation_date = prediction_date + 1825 days`. The historical evaluator will pick them up on the next pass.

**Why we file it now**
The audit's `invented_timeframe` rule v12.2 currently flags 351,836 rows as a single bucket — most of those are window=90 defaults, but the long-window rows hide inside the same pile and get buried. Clamping the upper bound is a precondition for tuning the `invented_timeframe` rule.

**Out of scope for this ship**
The 90-day default behavior. That tuning is the rule-fix work blocking the rest of Ship #12 (`invented_timeframe`).

---

## Known extractor misses

Cases where the basket_shoehorn rule correctly *survives* a row even though Nimrod has eyeballed it as a real basket — the issue is upstream in the YouTube extractor, not in the audit rule. Filed as stubs so they don't get lost.

### Ship #12.3 — YouTube extractor under-emits from basket-style segments

**Symptom**
Prediction `606046` (`NXPI`, Chip Stock Investor, video `yt_cOhILhZQ-GE_`) was eyeballed as a real basket shoehorn — the speaker named multiple "Key Automotive suppliers" in the same segment, but the extractor only retained NXPI. The basket_shoehorn rule (v12.3+) requires signal 1 (multi-ticker co-occurrence: ≥3 distinct ticker_call rows from the same `yt_<video_id>_` prefix) and that signal correctly fails on a 1-ticker video, so the row survives Phase A.

This is the right call from the audit rule's perspective — a 1-ticker row genuinely is not a basket from the database's vantage point. The bug is upstream: the extractor saw a basket and only kept one ticker.

**Suspected file**
`backend/jobs/youtube_classifier.py:278-324` (`HAIKU_SYSTEM` constant — DO NOT EDIT WITHOUT NIMROD'S APPROVAL) and the per-prediction validation in `insert_youtube_prediction` around line 3404 onward. Possibly also the chunked-transcript pass — basket-style segments may be getting split mid-list across chunks, with each chunk only seeing one ticker name.

**Fix shape (sketch — needs design review)**
1. Add a `basket_context_phrase` extraction field to Haiku's response schema. When the extractor sees basket phrasing ("Key Automotive suppliers", "the magnificent seven", "my top three names") it should emit ALL the tickers from that breath, not just the first one it locked onto.
2. Backfill: for any row where the rule's signal 2 fires (basket phrasing in `context`) but signal 1 fails (single-ticker video), surface as `extractor_under_emit` candidates for manual review. Do NOT auto-fix — these need a person to read the transcript.
3. Consider a chunked-transcript stitching pass: if the same `basket_context_phrase` appears in adjacent chunks, merge the ticker lists before deduping.

**Why we file it now**
The basket_shoehorn rule v12.3 trades a known false-negative on NXPI-style cases for the broader correctness gain (no more false positives shutting down legit predictions). Phase A v3 (v12.4) further tightens to remove already-scored hits from the flagged set. Both moves are correct for the audit rule, but they also mean we're knowingly leaving real baskets in the training set whenever the extractor under-emits. The fix-up is genuine extractor work, not audit work.

**Out of scope for this ship**
- Audit rule changes (the rule is correct given the data it sees).
- Any retroactive prediction-row writes — manual review only until the extractor emits multi-ticker output natively.
- HAIKU_SYSTEM edits without explicit approval.

**Known examples for the eventual review queue**
- `606046 NXPI` Chip Stock Investor, `yt_cOhILhZQ-GE_` — only NXPI extracted from a multi-supplier segment. Phase A eyeball, 2026-04-11.

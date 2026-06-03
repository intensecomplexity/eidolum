-- 2026-06-03 manual flag — surgical follow-up to the 0017 reported-speech audit.
-- The tightened regex used by the 2026-06-02 audit deliberately dropped
-- ambiguous patterns like "their forecast" / "their target" (eyeball FP rate
-- was ~77% on those patterns), so the user-visible NVDA April 10 case from
-- BWB - Business With Brian (id=616638) was not captured by the bulk UPDATE.
-- Quote: "Nvidia has some of the best fundamentals out there, and their
-- forecast shows it with over 55% upside." → relayed third-party forecast,
-- not the speaker's own conviction call.
--
-- Loose-regex sweep over the 3 highest-concentration channels (BWB,
-- Dividend Data, Fast Graphs) surfaced 4 additional candidates; eyeball
-- review confirmed exactly 1 true positive (the NVDA case). The other 3
-- (id=611899 ELV Fast Graphs DCF, id=616649 MSFT "for me" personalized
-- fair value, id=616662 DDOG own-thesis correction call) are the
-- speaker's own predictions and stay visible.

UPDATE predictions
   SET is_reported_speech = TRUE
 WHERE id = 616638
   AND COALESCE(is_reported_speech, FALSE) = FALSE;

-- Forecaster aggregate recompute is applied surgically to forecaster_id
-- 10247 (BWB) in the same transaction by the deploy script; the worker
-- cron's refresh_all_forecaster_stats will reproduce the same numbers on
-- next 2-hour tick because the bundled hedged_filter_sql helper picks up
-- the new flag.

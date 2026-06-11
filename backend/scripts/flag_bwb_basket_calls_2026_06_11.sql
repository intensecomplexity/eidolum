-- BWB basket-embedded single-name sweep (2026-06-11): flag Rule 15
-- BLIND-SPOT rows — basket members whose verbatim quote was narrowed to the
-- single name at extraction, so the >=3-name enumeration that Rule 15
-- detects on QUOTE TEXT lives only in the surrounding transcript.
-- Origin case: id 616174 (BWB AMZN bullish 90d, scored HIT +15.2%, video
-- W4YHbcyxFBQ t=7:03) — human-reviewed: one member of the "retail and
-- consumer discretionary ... winner bucket" (Target, Walmart, Costco,
-- Amazon), most-hedged member, explicitly framed long-term, mis-booked as a
-- clean individual 90-day call. Siblings WMT/COST/AA from the same video
-- were already flagged by the 2026-06-10 sweep (their quotes retained the
-- enumeration → Rule 15 fired); AMZN's quote did not (1 named item found).
--
-- Sweep: all 226 unflagged BWB (forecaster_id 10247) youtube ticker_calls,
-- ALL outcomes (pattern decides, not outcome — stats may move both ways).
-- 36 missing video transcripts fetched + persisted via persist_transcript()
-- first (51/51 coverage). Pre-filter (>=3 enumerated names in a ±1500-char
-- transcript window around the quote, OR group-framing vocab) kept 110;
-- per-row claude -p Sonnet judge (conservative KEEP-on-doubt, mirrors the
-- 2026-06-10 basket judge) returned 11 (a) basket-weak / 86 (b) genuine /
-- 13 (c) reported-speech-or-hypothetical. Two manual overrides toward KEEP:
--   616184 ADM  judge said (a) but its own reason concedes only TWO named
--               companies ("Deere and ADM") — fails the >=3-name bar → kept.
--   616645 SPY  judge said (c) as pure HYPOTHETICAL, not reported speech;
--               no matching flag column and this ship cannot re-mark
--               outcomes → left visible (future conditional re-mark
--               candidate, phase3b pattern).
-- Rule 15 (jobs/classifier_validation.check_basket_enumeration) fires on
-- 0/10 of the flagged (a) rows — the quantified blind-spot input for a
-- future eval-gated context-window Rule 15b. Rule 15 itself is UNTOUCHED.
--
-- FLAG-NOT-DELETE: no DELETEs, no outcome/actual_return changes. Hiding
-- flows through the existing hedged_filter_sql bundle + assets.py _WEAK_NA;
-- kill switches HIDE_WEAK_BASKET_CALLS / HIDE_REPORTED_SPEECH. Idempotent:
-- the flag=FALSE guard makes re-runs no-ops. Run manually against prod:
--   psql "$DATABASE_PUBLIC_URL" -f backend/scripts/flag_bwb_basket_calls_2026_06_11.sql
--   then POST /api/admin/refresh-forecaster-stats (server-side, ~70s).

-- (a) basket-derived weak calls — judge-confirmed members of an enumerated
-- group/sector thesis with no first-person per-name commitment:
--   616138 ASML  semis-equipment bucket (ASML, Lam, AMAT, KLA)
--   616145 LIN   helium/industrial-gas bucket of a five-bucket thesis
--   616146 APD   "positioned similarly" to Linde, same bucket
--   616156 CSCO  silicon-photonics layered thesis (NVDA, AVGO, CSCO, ...)
--   616174 AMZN  THE ORIGIN CASE — retail winner bucket (TGT, WMT, COST, AMZN)
--   616179 F     autos bucket of the same tariff-winners video (F, GM, TSLA)
--   616180 GM    autos bucket of the same tariff-winners video (F, GM, TSLA)
--   616341 LAES  penny-stock lottery bucket (QUBT, LAES, ARQQ, ...)
--   629145 WDC   ten-name supply-constraint "clean filter" basket
--   629150 POWL  same ten-name supply-constraint basket
UPDATE predictions
SET is_weak_basket_call = TRUE
WHERE id IN (
    616138, 616145, 616146, 616156, 616174,
    616179, 616180, 616341, 629145, 629150
)
AND is_weak_basket_call = FALSE;

-- (c) reported speech — the upside figure is explicitly attributed to
-- analysts/forecast data, not the speaker's own call ("Analysts give ARM a
-- 44% upside", "analysts see them with over 100% upside", SMH-holdings
-- analyst-forecast recaps):
--   616203 ARM, 616615 APLD, 616630 ARQQ, 616636 RGTI, 616637 MSFT,
--   616638 NVDA, 616640 INTC, 616641 LAES, 616642 AMZN, 616679 TSM,
--   616680 ASML, 616681 AMD
UPDATE predictions
SET is_reported_speech = TRUE
WHERE id IN (
    616203, 616615, 616630, 616636, 616637, 616638,
    616640, 616641, 616642, 616679, 616680, 616681
)
AND is_reported_speech = FALSE;

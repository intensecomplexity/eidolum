# Forward conditional guard — eval (2026-06-14)

Insert-time safety net so trigger-gated calls the classifier emits as FLAT
ticker_calls (the "if X then Y" class, cleaned up in da47210+aae459c) can't be
flat-scored again. Guard: `jobs/representativeness_guard.py::conditional_decide`,
hooked into `insert_youtube_prediction` BEFORE the representativeness guard.
Classifier STOPPED for the ship; takes effect on Nimrod's restart. Eval before merge.

## Behavior (cost-gated, fail-open, gated by ENABLE_CONDITIONAL_GUARD)
A ticker_call insert that trips the conditional regex (quote+context; **20.9%** of
inserts on an unbiased sample) gets ONE Sonnet verify over the ±90s window:
- **event_macro** (unverifiable from price) -> insert `outcome='unresolved'` (tagged, reversible)
- **price_trigger** (clean type+ticker+level) -> route to `insert_youtube_conditional_prediction`
  so `_process_conditional_calls` fires it via price_bars and scores it PROPERLY;
  a price_trigger with no clean numeric level degrades to `unresolved` (never a broken conditional row)
- **keep** -> normal flat ticker_call, no change
Runs before the representativeness guard so a route/unresolve short-circuits its second-pass (no double LLM call).

## Eval (311 gold rows from the da47210+aae459c LLM-judged set with cached transcripts: 46 a / 38 b / 227 c)
First prompt (aggressive) FAILED: **22.5% (c) false-route** — disqualifying per "merge only if (c) false-route near-zero."
Tightened to "keep is the strong default; only override when the WHOLE call is contingent":

| metric | aggressive | **shipped (conservative)** |
|---|---|---|
| (c) FALSE-ROUTE | 22.5% | **1.8% (4/227)** — all -> unresolved (reversible), 0 -> route_price |
| (a) event/macro recall | 98% | 61% |
| (b) price-trigger recall | 92% | 55% (17/38 cleanly routed) |
| a/b/c reproduction | 77.5% | 85.9% |

**Merge rationale:** the hard bar is near-zero (c) false-route (a wrongly-gated real call is the worst
outcome) — met at 1.8%, and every false-route is a reversible `unresolved`, never a scoring-breaking
route. Recall is deliberately traded down to buy that safety: a missed conditional just stays flat
(status quo, no regression), so the conservative setting is the correct asymmetry for a forward net-new
guard. Recall can be tuned up later (eval-gated) if desired.

## Knobs (default-on after passing eval)
- `ENABLE_CONDITIONAL_GUARD` (default true) — kill switch
- `REPRESENTATIVENESS_VERIFY_MODEL` (default sonnet) — shared with the rep guard
No HAIKU_SYSTEM edits; CLASSIFIER_VALIDATION_GATE stays shadow; fail-open throughout.

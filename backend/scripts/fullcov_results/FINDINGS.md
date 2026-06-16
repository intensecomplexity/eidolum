# Full-coverage judge over ALL visible predictions (2026-06-16)

Goal (per the ship): judge EVERY visible row (no cost-gate), fix the real errors,
and produce a LABELED DATASET + ranked systematic-error analysis that improves the
classifier prompt and feeds the future fine-tune. NOT "100% clean".

## Method
- **Cohort:** all 15,232 visible predictions (10,861 YouTube + 4,371 X), no
  suspect gate.
- **No fetch:** judged from STORED plain-text transcripts (YouTube, whole
  transcript per call; quote-centered only for the rare >24k giant) and the tweet
  (X). 4,750 transcripts dumped locally; 93% of YT rows had stored text.
- **Judge:** one `claude -p` per row, full taxonomy. **Model = Haiku** (the Sonnet
  Max-limit was exhausted; speed-mode per the operator). 34 concurrent (box CPU
  plateau ~52/min; latency-bound, not rate-limited except one transient Haiku
  window of ~1,291 ERROR that a resume pass cleared → final ERROR 0).
  Checkpointed JSONL, resumable; errors recorded as ERROR (never silently OK).
- **Deterministic pre-pass (zero-LLM):** 58 wrong-side targets → direction-only +
  1 X wrong-cashtag, applied first.

## Verdict distribution (15,232; deduped last-per-id)
| verdict | n | % | yt | x |
|---|---|---|---|---|
| **OK** | 10,457 | 68.7 | 7,403 | 3,054 |
| no_claim | 1,267 | 8.3 | 1,224 | 43 |
| target_error | 1,089 | 7.1 | 352 | 737 |
| conditional | 817 | 5.4 | 540 | 277 |
| direction_mismatch | 620 | 4.1 | 505 | 115 |
| hedged | 319 | 2.1 | 282 | 37 |
| reported_speech | 268 | 1.8 | 206 | 62 |
| wrong_ticker | 195 | 1.3 | 190 | 5 |
| holding | 120 | 0.8 | 105 | 15 |
| chart_commentary | 69 | 0.5 | 44 | 25 |
| other | 11 | 0.1 | 10 | 1 |

**~69% OK.** Consistent with the prior audits (unbiased extraction ~95%+ clean on
*core* ticker+direction; the bulk of "errors" are accountability/representativeness
classes, not wrong scoring). **Caveat:** these are HAIKU labels (a v1 *silver*
corpus) — good but not Sonnet-grade; a Sonnet re-verification of the review
artifact + a no_claim audit is the recommended next step (Sonnet now available).

## RANKED systematic error patterns (the learning output)
1. **no_claim — unnamed-instrument macro (1,267, 8.3%; ~all YouTube).** An ETF/index
   ticker (IVW, DBC, SH, GLD, SPY) extracted from broad "commodities / growth
   stocks / the market" talk where that ticker is never named with a call. Also
   intros/narration/retrospective recaps.
2. **target_error (1,089 = 872 MISSING + 217 WRONG).**
   - MISSING (872, mostly **X**): tweet states an explicit "$30 PT / +633% target"
     but stored target is None — X extraction drops numeric targets.
   - WRONG (217): a moving-average level / P-E multiple / EPS / DCF per-share
     figure extracted as a *price target* (the AVGO $34, ISRG $66 class), or a
     target on the wrong side of spot.
3. **conditional (817, 5.4%).** "If/when X then..." gated calls. (The
   `conditional_decide` guard already exists; this confirms its value.)
4. **direction_mismatch (620, 4.1%; mostly YouTube).** Direction inverted/wrong vs
   what the host says — the biggest *scoring-integrity* class.
5. **hedged (319, 2.1%).** Low-conviction musings presented as committed calls.
6. **reported_speech (268, 1.8%).** Third-party attribution ("Wall Street sees $X",
   "analysts expect"). NOTE the false-hide nuance — speakers often relay a Wall
   St PT AND add their own call (RE 626557).
7. **wrong_ticker (195, 1.3%; YouTube).** Mis-attribution (e.g. quote about
   "Newmont" stored as PANW).
8. **holding (120) / chart_commentary (69).** Passive position disclosures; pure
   technical-level description with no committed call.

## STEP 3 — applied (flag-not-delete, eval-gated, protect real calls)
- **AUTO-APPLIED: no_claim → is_no_claim (1,267).** Passed a 14-row hand spot-check
  (all genuine narration/macro/unnamed-ticker; whole-transcript judged). Scored
  rows also set outcome='unresolved'. `[pre_remediation]` preserved, idempotent,
  marker `fullcov_noclaim_2026_06_16`. (Caveat: Haiku-labeled; recommend a Sonnet
  audit of a no_claim sample.)
- **DEFERRED to review (NOT auto-applied):** holding, reported_speech,
  chart_commentary — the spot-check found false-hides (RE reported as third-party
  while the speaker made an own call; PYPL "is a short" ambiguous; NVDA capex
  thesis / CRSP "big play" read as holdings). `direction_mismatch`, `wrong_ticker`,
  `target_error`, `conditional`, `hedged` are by-policy review-only. Artifact:
  `review_artifact.jsonl` (1,489 rows) for a Sonnet/human pass.
- Deterministic target/cashtag fixes (58 + 1) applied in the pre-pass.

## STEP 4 — PROPOSED classifier-prompt fixes (PROPOSE ONLY — eval-gate before any merge; do NOT auto-edit)
Each maps to a ranked pattern; all require passing the classifier fixture eval
(TPR/FPR/parse-rate) before merge (sacred rule):
1. **Unnamed-instrument REJECT:** "Do not emit an ETF/index ticker unless that ETF
   or its underlying index is explicitly named AND given a directional call. Broad
   'commodities / growth stocks / the market' commentary is not a per-ticker call."
   → cuts the #1 pattern (no_claim).
2. **Valuation-narration REJECT:** "A DCF / intrinsic-value / multiple walkthrough
   is not a prediction unless the speaker states a buy/sell/hold stance or a
   forward price target."
3. **Target hygiene:** "target_price = an explicit forward PRICE target the speaker
   states for the stock — never a moving-average/support/resistance level, P/E,
   EPS, or a third party's PT. Bullish ⇒ target above current; bearish ⇒ below
   (else omit)." → cuts target_error WRONG + direction/target contradictions.
4. **X numeric-target capture:** "On X, capture an explicit numeric price target or
   %-move when present ('$30 PT', '+633% target')." → cuts target_error MISSING
   (the 872, mostly X).
5. **Direction from own stance:** "Set direction from the speaker's own forward
   stance on THIS ticker; never infer from surrounding macro. A target on the
   wrong side of price signals a direction/target extraction error." → cuts
   direction_mismatch.
6. **Reported-speech nuance:** "If a call is attributed to a third party AND the
   speaker adds no own conviction → reported. If the speaker states their OWN
   target/stance alongside, keep it as their call." → avoids the RE-class false
   hide while still catching pure relays.
7. **Chart-only REJECT:** "Pure technical-level description (support/resistance,
   inside bar, moving averages) with no committed directional conviction is not a
   scored call."

## Artifacts
- `labels.jsonl` — 15,232 rows (id, src, ticker, direction, verdict, why) = the
  silver labeled corpus for prompt-eval / fine-tune.
- `review_artifact.jsonl` — 1,489 rows for Sonnet/human verification (deferred
  hides + direction/ticker/wrong-target).
- `fullcov_judge_2026_06_16.py` — the judge harness.

## Safe to restart? YES
Only one reversible hide-flag (is_no_claim) was auto-applied on a spot-checked
class; all riskier classes were deferred to review. The classifier was NOT edited
(prompt fixes are proposals, eval-gated). When the classifier resumes, the
existing insert-time guards run unchanged.

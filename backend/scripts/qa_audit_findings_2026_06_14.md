# Random quality audit of VISIBLE SCORED predictions (READ-ONLY, 2026-06-14)

Goal: stop reacting to single cards — measure the true error rate on a random sample so we know if the
data is ~3% or ~20% wrong, and what to fix first. NO writes of any kind (SELECT-only).

## Method
- Seeded random sample (seed 20260614, md5-ordered) of **310 visible-scored** rows (pass the
  hedged_filter bundle + scored outcome; YouTube also passes the timestamp-visible filter). Stratified
  & OVER-weighted the small sources so each gets a real rate: **210 youtube + 40 x + 60 structured**
  (true pool: youtube 4,332 / x 124 / structured 455,931 — structured is 99% of the population).
- Per-row claude -p **Sonnet** judge (one call/row, checkpointed), 8 error classes, multi-flag allowed,
  conservative (OK when fine). Sample ids: `qa_audit_sample_ids_2026_06_14.json`; per-row verdicts:
  `qa_audit_results_2026_06_14.json`.
- Manually eyeballed ~30 flagged rows to calibrate judge strictness (below).

## Headline — TWO TIERS (the distinction matters)
**Tier 1 — HARD scoring errors** (wrong ticker OR flipped direction → the HIT/MISS is plainly wrong):
| source | rate | 95% CI |
|---|---|---|
| youtube | **8.1%** (17/210) | 5–13% |
| x | 37.5% (15/40) | 24–53% |
| structured | 15% raw (9/60) → **~7% firm** | 8–26% |

**Tier 2 — ANY quality flag** (adds not_a_prediction / unrepresentative_quote / timeframe / conditional):
| source | rate | 95% CI |
|---|---|---|
| youtube | **67.6%** (142/210) | 61–74% |
| x | 87.5% (35/40) | 74–95% |
| structured | 15% (9/60) | 8–26% |

Pool-weighted (structured = 99% of population): hard-error ≈ **7–15%** platform-wide (swing = the
structured convention question below); the per-source rates are the actionable view.

## Error-class frequency (count, % of n=310)
| class | count | % | note |
|---|---|---|---|
| not_a_prediction | 83 | 27% | **biggest**; incl. genuine no-calls/narration/reported-speech AND debatable "holds" |
| unrepresentative_quote | 50 | 16% | displayed quote doesn't reflect the call (intro/stitched/basket) |
| timeframe_wrong | 28 | 9% | long-term thesis on short window (some debatable, e.g. ~400d "long term") |
| conditional_flat | 27 | 9% | if/then gated call flat-scored |
| wrong_ticker | 24 | 8% | incl. name→symbol collisions + X multi-cashtag misattribution |
| direction_mismatch | 17 | 5% | quote opposite to stored direction |
| target_or_number_error | 3 | 1% | |
| other | 1 | 0% | |

## Calibration caveats (judged honestly, both directions)
1. **The judge is somewhat STRICT on two fuzzy patterns**, inflating Tier 2:
   - "Holds": "I'm happy to keep holding MO" → flagged not_a_prediction, though a bullish hold is a
     defensible call. ~⅓ of not_a_prediction are holds → product decision whether these count.
   - Structured "Maintains Buy/Outperform" stored direction=**neutral** → flagged direction_mismatch
     (5 of the 9 structured errors). This is likely a deliberate "reiteration = no new direction"
     CONVENTION, not an error. Removing it drops structured hard-error from 15% → ~7% (2 real ticker
     collisions + 2 clear Buy-stored-bearish flips: CSU, CC).
2. **The judge UNDER-counts representativeness** where it lacked the transcript (only 61/210 YT rows had
   a cached ±90s window; judged on quote+context). Per the spec, the true representativeness-error rate
   is at-or-above the measured one. (Windowed vs no-window YT error was similar — 70% vs 66% — so window
   absence is not the driver of the high YT rate.)
3. **X first-pass was a harness artifact** (source_verbatim_quote is empty for X; the tweet lives in
   context). Re-judged with the tweet as the quote → 87.5% (down from a spurious 92.5%); the residual is
   real: X is dominated by analyst-rating-RELAY tweets (reported speech, e.g. "Goldman upgrades NFLX" —
   not the account's own call; X gate is loose-by-design) + **multi-cashtag wrong-ticker** (e.g. a $INTC
   tweet stored as GOOGL — 22% of X). X is only 124 rows of the population.

## VERDICT
The platform's **core scoring is mostly sound**: getting the ticker and direction right is wrong only
~**8% on YouTube** and ~**7% on structured** (the 99% of the population). It is NOT 60% "wrong" in the
sense that misleads users on accuracy. **The dominant systemic problem is YouTube QUOTE/representativeness
quality**: ~half-to-two-thirds of visible YouTube rows carry a quote that doesn't cleanly evidence a
committed forward call — holds counted as predictions, intro/narration quotes, unrepresentative/basket
quotes, and flat-scored conditionals. The top two classes by volume are **not_a_prediction (27%)** and
**unrepresentative_quote (16%)**, both concentrated in the youtube_haiku_v1 cohort — the same weakness
this week's cohort cleanups (note-as-quote sweep, requote, conditional remediation) addressed in
SPECIFIC flagged sets but which remains pervasive at population scale. Fix-first: a population-scale
quote-representativeness pass on youtube_haiku_v1 (the forward guards already shipped reduce NEW inflow).
Smaller, sharply-defined wins: X multi-cashtag wrong-ticker, and a product decision on holds-as-neutral
and analyst-maintains-as-neutral conventions.

No data was modified. Artifacts committed: sample ids, per-row results, this doc.

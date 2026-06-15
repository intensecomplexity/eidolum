# Recent-YouTube quality audit (n=200, READ-ONLY, transcript-backed) — 2026-06-15

**Goal:** measure the CURRENT quality of the most-recent YouTube predictions. No
writes to `predictions` (only ±90s transcripts fetched/persisted for judging).

## Method
- **Sample:** the 200 most-recent `source_type='youtube'` rows by `prediction_date`
  (DESC, id DESC tiebreak). All 200 are from **2026-06-11** videos, all
  `generating_model = cc_sonnet_recovery_2026_05_17`, all `outcome='pending'`
  except 1 (`miss`, hidden). So this measures **extraction quality on fresh
  rows**, not scoring outcomes.
- **Visible/hidden split:** visible = passes the `hedged_filter_sql` hide-bundle
  AND has a non-NULL `source_timestamp_seconds`.
- **Judge:** one `claude -p` Sonnet call per VISIBLE row against the **±90s
  transcript window** (Webshare-fetched, 4s pacing; 79/85 videos fetched, 6
  transient-failed). Conservative prompt: OK unless the window clearly shows the
  problem; a bare directional stance counts as OK. Harness:
  `yt_audit_judge_2026_06_15.py`.

## STEP 0 — sample composition
| | count |
|---|---|
| total sampled | 200 |
| **visible** | **140** |
| **hidden/flagged** | **60** |

**Every hidden row is hidden by `conviction_level` only** — hedged 57,
hypothetical 3. The five boolean guards (`is_no_claim`, `is_holding_disclosure`,
`is_weak_basket_call`, `is_reported_speech`, `is_ambiguous_symbol`) fired
**0 times** across all 200 rows. So on fresh data the *only* active quality
gate is the classifier's own hedged/hypothetical conviction tag (28.5% of rows).

## STEP 1 — per-row verdicts (visible)
Judged **126 / 140** visible (14 unjudged — rows on the 6 transcript-fetch-fail
videos).

| verdict | raw | confirmed real (hand-checked) |
|---|---|---|
| OK | 117 | — |
| not_a_prediction | 4 | ~3 (631548, 631555, 631473) |
| wrong_ticker | 2 | ~1 (631386; 631561 likely OK) |
| direction_mismatch | 1 | 0 (631550 stored bearish defensible) |
| target_or_number_error | 1 | 1 (631403) |
| holding_not_call | 1 | 1 (631378) |

**Raw flagged: 9/126 = 7.1%.** Hand-checking every flag found **3 judge
false-positives** (stored row is actually fine):
- **631379 NVDA** — "I still prefer nvidia, my top pick" is a valid bullish
  stance, not a no-call.
- **631550 COIN** — "call credit spread" is a bearish/neutral structure, so the
  stored `bearish` is defensible.
- **631561 HII** — "contract renegotiations with the US government" fits
  Huntington **Ingalls** (defense), not Bancshares; stored ticker likely correct.

**Confirmed real error rate ≈ 6/126 ≈ 4.8%.**

### Confirmed leaks (example ids)
- **holding_not_call:** `631378` (GOOG) — "I'll be holding my shares of Google …
  for a real long time" — a passive holding that **leaked past the forward
  holding guard** (`holding_decide` did not flag it; `is_holding_disclosure` is
  false).
- **not_a_prediction (recap / mention):** `631548` (SBUX, position recap "up
  $969"), `631555` (META named only as an OBV-disconnect example), `631473`
  (GOOGL soft "minor setback" aside, window is about ASML).
- **target_or_number_error:** `631403` (AVGO target stored **$34**; host's
  "up 64% from here" implies ~$185 current → host said ~**$304**, ASR/extraction
  dropped a digit).
- **wrong_ticker:** `631386` (GOOGL stored, but the forward call in the window is
  on Tesla's neural-net/robotics thesis).

## STEP 2 — verdict
**Recent YouTube core-extraction quality is CLEAN: ~95% of visible rows are
correct (≈4.8% confirmed error), with no dominant error class.** This is a large
improvement over the 2026-06-14 historical audit (66.9% any-flag) — but the two
measure different things (see caveats).

**Is a specific class still leaking?** Only at low volume: a handful of
no-claim/recap rows and **one holding disclosure** got past guards that fired
**zero times** on this fresh cohort. The forward `holding_decide` /
representativeness / reported-speech guards are effectively dormant on recent
data — they catch ~nothing, and the small residual no-claim/holding/recap leakage
(~3–4%) is exactly what they were meant to catch. Worth a targeted look at why
`holding_decide` missed 631378 and whether the no-claim forward guard (deferred
from the accountability ship) should be revived for the insert path.

### Caveats (do not overclaim)
1. **This judges the ±90s WINDOW** (is it a real, correctly-attributed call),
   **not displayed-quote self-accountability.** The separate representativeness
   axis (the 2026-06-14 audit's ~30% NOT_ACCOUNTABLE) is **not re-measured here**;
   a truncated quote whose claim exists elsewhere in the window scores OK.
2. All rows are **pending/unscored** — this is extraction quality, not accuracy.
3. **14/140 visible rows unjudged** (transcript fetch fail) and the judge is
   deliberately conservative, so the true error rate is at-or-near this estimate.
4. The high hedged-hide rate (28.5%) is the dominant handling mechanism; whether
   the classifier *over*-marks hedged (false-hiding real calls) is a separate
   question not assessed here.

**No data modified.** Artifacts: `yt_audit_2026_06_15_sample_ids.json`,
`yt_audit_2026_06_15_results.json`, `yt_audit_judge_2026_06_15.py`.

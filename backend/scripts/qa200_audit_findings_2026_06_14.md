# YouTube+X audit (n=200) — errors + quote-accountability (READ-ONLY, transcript-backed)

Goal: (1) measure what's wrong in the LLM-extracted sources at CURRENT state; (2) on the new
quote-accountability axis, size what's requote-fixable vs must-hide, to design the fix. No data writes.

## Method
Seeded random sample of 200 visible-scored rows, source in (youtube, x) ONLY, **excluding any row with a
2026-06-14 remediation marker** (so we audit the current/unfixed state). 160 youtube + 40 x. Per-row
claude -p Sonnet judge with the **±90s transcript window FETCHED for YouTube** (100/106 missing videos
fetched via Webshare) — representativeness is judged for real, fixing the prior audit's blind spot. For X
the tweet (in `context`) is the judged evidence. Artifacts: sample ids + per-row results committed.

## Error rate (consistent with the f11eb2e audit)
| | rate | 95% CI |
|---|---|---|
| overall (any error class) | 71.0% (142/200) | 64.4–76.8 |
| youtube | 66.9% (107/160) | 59.3–73.7 |
| x | 87.5% (35/40) | 73.9–94.5 |

Error classes (% of 200): not_a_prediction 30.5 · timeframe_wrong 16.5 · holding_not_call 13.0 ·
conditional_flat 13.0 · wrong_ticker 11.0 · direction_mismatch 10.5 · target_or_number_error 3.0.

## THE NEW AXIS — quote accountability (transcript-backed)
| verdict | share | 95% CI | meaning |
|---|---|---|---|
| **SELF_ACCOUNTABLE** | **59.0%** (118) | 52–66 | the displayed quote conveys the checkable claim — fine as-is |
| **REQUOTE_FIXABLE** | **11.5%** (23) | 8–17 | quote is weak/truncated BUT a claim-bearing sentence exists in the window — re-quote fixes it |
| **NOT_ACCOUNTABLE** | **29.5%** (59) | 24–36 | no claim-bearing sentence anywhere — should NOT stand as a scored prediction (must hide) |

Per source: youtube 55% self / 14% requote-fixable / 31% not-accountable; x 75% self / 0% requote-fixable
/ 25% not-accountable (a tweet has no surrounding window to re-quote from — binary).

Calibration (eyeballed ~13): the split is trustworthy and actionable. REQUOTE_FIXABLE are real truncations
(607325 NVDA quote stops before "Nvidia is a buy here"; 608145 ABNB → "my Buy price is 146"; 617219 CVX
quote ends before CVX is named). NOT_ACCOUNTABLE are genuine no-claim rows (624770 HCA window is Canadian
retirement-healthcare advice; 612543 SPY is "don't panic-sell" coaching; 612728 TWLO is a past recap;
606675 TPL is a bare "a share of TPL" mention). The judge is somewhat strict on holds / ~400-day "long
term" / rhetorical conditionals, so NOT_ACCOUNTABLE is a slight over-estimate — true rate is at-or-below.

## VERDICT — how big is the quote problem, and what's fixable
Transcript-backed, the quote problem is real and large on YouTube: **~41% of visible-scored YouTube+X
rows are not self-accountable** (the shown quote doesn't convey the prediction). But it splits cleanly
into two very different fixes:
- **~12% is REQUOTE-FIXABLE** — a claim-bearing sentence exists in the window; the requote machinery
  already built this week (requote_evidence_*) re-points the displayed quote, NO scoring change. This is
  the cheap, high-value fix.
- **~30% is NOT-ACCOUNTABLE** — no claim exists anywhere; these aren't real scored predictions and
  should be hidden+off-board (the holdings/representativeness/conditional flags + the is_* hide bundle
  already provide the mechanism; many already carry not_a_prediction/holding/conditional/wrong_ticker
  flags here). This is the must-hide backlog.
Recommended fix design: a population-scale pass that, per row, REQUOTES when the window has a claim and
HIDES (unresolved + a hide flag) when it doesn't — exactly the SELF/REQUOTE/NOT_ACCOUNTABLE trichotomy,
run at scale on youtube_haiku_v1. Core scoring (ticker+direction) remains the smaller problem
(wrong_ticker 11% / direction_mismatch 10.5%, overlapping the not-accountable set). No data modified.

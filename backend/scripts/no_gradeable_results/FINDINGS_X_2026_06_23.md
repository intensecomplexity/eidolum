# No-gradeable-claim detector — X cohort extension (2026-06-23)

Extends the YouTube-only no-gradeable detector ([`FINDINGS.md`](FINDINGS.md), 2026-06-21/22)
to **X** — the messiest, never-guarded source. Same detector
(`jobs/representativeness_guard.gradeable_decide`), same judge/apply scripts reused
**verbatim**. Sonnet verify. Precision over recall — false-hiding a real call is the
cardinal sin.

## Cohort
- Visible X `ticker_call` (`source_type='x'`), scored+pending, **not already flagged**:
  **4,232** (378 scored + 3,854 pending; 32 delisted/unresolved/no_data outcomes excluded).
- **Suspects** (cheap gate `is_gradeable_suspect`: NO digit AND NO direction word):
  **7 (0.2%)** — vs **14%** on YouTube. X tweets are number/direction-dense (cashtag +
  price/level + buy/sell/long/short/calls/puts), so the gate **auto-keeps 99.8% with no
  LLM call**. The whole X suspect universe (any outcome/flag) is also just 7.

## Spot-check — 7/7 = 100% of the X suspect universe (not a 20-sample; only 7 exist)
All 7 suspects ran the Sonnet verify. **All 7 → GRADEABLE (kept). 0 false-hides.** Each is
a real terse call the gate's plural-only word list missed:

| id | ticker | tweet (terse call) | verify |
|---|---|---|---|
| 632627 | SPY | `$SPY Call here NFA` | bullish → KEEP |
| 632634 | TSLA | `$TSLA put Opened with SL` | bearish → KEEP |
| 634846 | NVDA | `load the boat on $nvda` | bullish → KEEP |
| 633491 | NFLX | `play a … call position on $NFLX for earnings` | bullish → KEEP |
| 633498 | NFLX | `Entered modest $NFLX call position` | bullish → KEEP |
| 633812 | BTC | `unloading on these discounts … bottom will be in` | bullish → KEEP |
| 633255 | IREN | `results will probably disappoint` | bearish → KEEP |

The verify recognized options jargon (singular `call`/`put` — the gate list only has the
plurals), "load the boat", "buy the dip", and "disappoint" as directional. Cardinal sin
avoided with full margin. (`x_cohort_spot_verdicts_7.jsonl`.)

## Result: 0 flagged — clean no-op
- Full-cohort census: **4,232/4,232 GRADEABLE, 0 NOT_GRADEABLE.** Apply: nothing to apply.
  **No DB writes.**
- Before → after: X `is_no_gradeable_claim` **0 → 0**; overall **112 → 112**. No scored row
  changed → **forecaster-stats refresh moot** (skipped).

## Why 0 is the right answer (recall sanity)
12 random auto-kept X rows were all genuine calls with explicit numbers/directions
("TP3 hit target 319.93", "pt remains at $164", "Short Entry 0.64126", "breakout up to
$255", "BELOW $423.23 DOWNSIDE"). The gate isn't blind — X carries the signals. X's
"messiness" lives in OTHER classes (reported-speech, ambiguous tickers, spam) handled by
their own flags; the no-gradeable **vague-preference** class is near-absent on X. Precision
preserved; recall ceiling accepted (same rationale as the YouTube pass). A wider gate can't
be validated safely until a larger gold sample exists — deferred, Nimrod's call.

## Reproduce (≤3 workers — classifier shares the box)
```
NG_WORKERS=3 python3 backend/scripts/no_gradeable_judge_2026_06_21.py \
    /tmp/ngx_cohort_ids.json /tmp/ngx_cohort_verdicts.jsonl
python3 backend/scripts/no_gradeable_apply_2026_06_21.py /tmp/ngx_cohort_verdicts.jsonl   # 0 to apply
```
Cohort/suspect builders live in the run log; no schema or HAIKU_SYSTEM changes. Forward
guard for X is NOT wired here (this is a backfill census that found the cohort clean).

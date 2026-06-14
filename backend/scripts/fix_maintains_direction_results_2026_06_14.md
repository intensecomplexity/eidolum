# Fix "Maintains/Reiterates Buy stored neutral" — historical backfill (2026-06-14)

From the QA audit (f11eb2e): older analyst rows stored a BULLISH/BEARISH rating as direction='neutral'.

## Root cause + scope decision
Both current structured writers already use "destination rating wins" and NEVER store a bull/bear
rating as neutral — Benzinga's `_get_direction` returns bullish/bearish, or **None (skip)** for a
no-PT-change maintains/reiterates reaffirmation. The neutral-bullish rows are from OLDER logic. Per
product decision: **forward behavior unchanged (reaffirmation-skip preserved); historical backfill only.**
No writer code changed — instead an invariant TEST locks "a bull/bear rating can never be stored neutral"
(`backend/tests/test_rating_direction_invariant.py`, passes on current code).

## Mislabel signal (0 ambiguous)
source_type='article', direction='neutral', context carries the rating-derived label ': Bullish —' /
': Bearish —' (diverges from the stored neutral). Genuine neutrals (': Neutral —' / hold-family, 143,186
rows) never touched.

## Backfill (id-criteria-pinned, idempotent, flag-not-delete; ran on worker over price_bars)
- **16,745 scored rows re-evaluated** through the evaluator's OWN ticker_call branch (sanity_check_target
  / classify / bounded_return / tolerances / _calc_spy_return / _build_summary), reusing the stored
  entry_price and price_bars for eval_price — same entry/window/price path, no hand-computed outcomes.
- **4,318 pending rows** direction-corrected (evaluator scores later); **193** un-priceable rows requeued pending.
- [pre_remediation] JSON saved on every row; marker `maintains_direction_fix_2026_06_14`.

### Outcome changes (re-score)
miss→hit 6,077 · hit→miss 1,710 · near→hit 760 · near→miss 980 · miss→near 820 · hit→near 94 ·
near→near 386 · hit→hit 1,043 · miss→miss 4,875. Net UP (reaffirmed Buys where the stock rose were
neutral-MISS under |move|≤5% scoring; now correctly bullish-HIT).

## Forecaster moves (after refresh)
1,737 forecasters moved — **1,436 up / 294 down** (net up, as expected). Most are long-tail 1–2-call
analysts (below leaderboard floors). Spot-checked NSC/REGN (bullish/miss) and UPS (bullish/hit) — all
now directional with recomputed outcomes. Safety: 0 fixed rows still neutral; 0 genuine-neutrals marked.

## Forward correctness
Unchanged by design (reaffirmation-skip kept). The invariant test guarantees no future bull/bear rating
is ever stored neutral. Note: the writer still SKIPS no-PT reaffirmations (does not store them bullish) —
that is the deliberate "no new information" behavior the user chose to retain.

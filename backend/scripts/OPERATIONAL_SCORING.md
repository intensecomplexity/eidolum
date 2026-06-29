# Operational Prediction Scoring Engine (2026-06-29)

Grades forecasts about **company financials** (revenue, free cash flow, diluted EPS,
net income, margins) against reported actuals — not just price. Data + scoring only
(no UI). Built end-to-end across the phases below. Sacred rules obeyed: classifier
prompt change eval-gated, deploy-safe DDL, price path never touched, verify-don't-invent,
explicit-path commits.

## Architecture (a row is price OR operational)
`predictions.claim_type` tags every row. `claim_type='operational'` rows carry
`metric_type` (reused — the canonical metric name), `metric_kind`, `metric_target_value`,
`metric_target_period`, and are routed off the price path via **`evaluation_deferred=TRUE`**
(the existing "owned by a different scorer" mechanism — so `evaluator.py` is NOT modified).
The operational evaluator owns them and writes `outcome` / `metric_actual_value` /
`metric_resolved_at`.

| phase | file | what |
|---|---|---|
| 0 audit | (this doc) | confirmed local FMP fundamentals + coverage |
| 1 schema | `migrations/0025_operational_claims.sql`, `models.py` | additive nullable cols + claim_type default 'price' |
| 2 extract | `scripts/operational_extractor.py`, `jobs/_fixtures/operational_extraction.json`, `scripts/eval_operational_extraction.py` | claude -p tagger, EVAL-GATED |
| 3 actuals | `services/financial_actuals.py` | reported actual + look-ahead-safe report date |
| 4 evaluator | `jobs/operational_evaluator.py` | branch by metric_kind; never touches price |
| 5 backfill | `scripts/operational_backfill.py` | extract+route+score over gold + population |
| 6 verify | `scripts/operational_phase6_verify.py` | end-to-end + price-unaffected |

## PHASE 0 — data coverage (verified against live data)
| metric | source table.column | granularity |
|---|---|---|
| revenue | `fmp_income_statements.revenue` + `fmp_earnings.revenue_actual` | annual + ALL quarters |
| diluted EPS | `fmp_income_statements.eps_diluted` + `fmp_earnings.eps_actual` | annual + ALL quarters |
| net income | `fmp_income_statements.net_income` | annual + Q1 only |
| free cash flow | `fmp_cash_flows.free_cash_flow` | annual + Q1 only |
| gross/op/net margin | `fmp_ratios.{gross,operating,net}_profit_margin` | annual + Q1 only |
| report date | `fmp_earnings.date` (actuals NULL until reported) | look-ahead safe |

70,497 statement symbols; **85%** of predictions tickers have fundamentals.
**GAP:** statement tables hold only `FY`+`Q1` — **Q2–Q4 FCF / net-income / margins are NOT
local** (revenue+EPS quarterly are, via `fmp_earnings`). Filling Q2–Q4 = an FMP `/stable/...
?period=quarter` backfill = **FMP spend, NOT done (awaiting approval)**. This is the only
thing blocking the AAPL "cash-flows decline Q2" gold case (resolves `not_local`).

## PHASE 2 — extraction eval gate (PASS)
operational **4/4** (AMZN abs FCF, ON rev cagr, CRDO rev growth_pct, AAPL FCF direction),
price no-regression **5/5**, not_a_prediction **2/2**. Iterated once under the gate: company
financial guidance relayed by the speaker (CRDO revenue) is gradeable; share-price targets
(OSCR $45-55) and sell-side estimates are not operational.

## PHASE 4 — scoring (validated on real past-period data)
absolute (AMZN FCF FY2020 $25.9B → HIT / $40B → MISS), growth_pct (CRDO FY2025 YoY +126%),
cagr (ON FY2020→24 7.75%), direction (AAPL Q2 YoY). Resolves only when every needed actual
is reported; else pending. Bands are v1 (abs 10%/25%; growth/cagr hybrid 15%-or-5pp / 35%-or-12pp).

## PHASE 5/6 — backfill + verify
Forward-pass: 26 candidates → 7 operational tagged (4 gold + AMAT/INTC/MDT), all correctly
pending (future periods / AAPL not_local). Old-pass (period-passed rows): 22 candidates → 4
operational, **3 scored (2 hit / 1 miss, hit-rate 0.667)**, 1 pending. Eye-checked:
- META revenue-direction FY2023 $134.9B > FY2022 $116.6B (bullish) → **HIT** ✓
- DOCU revenue growth FY2023 +19.4% vs 16% target (≤5pp) → **HIT** ✓
- CNR eps_diluted +20% target vs actual "+1261%" → was a false **MISS**. **FIXED 2026-06-29.**
  Diagnosis (verified): NOT a split/collision — shares were stable FY2021→FY2022 and `fmp_splits`
  shows none in-window; it's a **depressed base** ($0.96 recovering from a FY2020 loss) exploding
  the YoY %. Also verified `fmp_income_statements.eps_diluted` is **already split-adjusted** at the
  source (AAPL FY2019 reads 2.97 / 18.47B shares post-2020-split), so split *adjustment* is
  unnecessary and would double-count. **EPS growth/CAGR now degrades to `unresolved`** (off the
  scoreboard, not a fabricated hit/miss) on: non-positive/sign-flip base, near-zero base, or an
  absurd multiple (normal-range target vs |actual| beyond the cap — the depressed/collision/
  unadjusted-split backstop). Branch-local to eps_diluted growth/cagr; revenue/FCF/direction and
  the price path untouched. CNR re-scored miss→unresolved (`operational_epsfix_rescore.py`,
  snapshot `operational_epsfix_before_snapshot.json`). Guards: `jobs/operational_evaluator.py`
  (NEARZERO_EPS, ABSURD_CAP); split-awareness `services/financial_actuals.split_in_window`.

**Price path unaffected:** 730,033 price rows untouched (forward pass), the operational rows
rerouted via `evaluation_deferred=TRUE`, zero collateral. Every touched row's before-state is
snapshotted in `operational_backfill_before_snapshot.json` (fully reversible).

## To run
```
DATABASE_URL=$DATABASE_PUBLIC_URL python3 scripts/eval_operational_extraction.py   # gate
DATABASE_URL=$DATABASE_PUBLIC_URL python3 scripts/operational_backfill.py 50        # forward
DATABASE_URL=$DATABASE_PUBLIC_URL BACKFILL_OLD=1 python3 scripts/operational_backfill.py 50  # period-passed
DATABASE_URL=$DATABASE_PUBLIC_URL python3 scripts/operational_phase6_verify.py      # verify
```

## Daily worker job (wired 2026-06-29)
`jobs.operational_evaluator.run_operational_evaluation()` is registered in `worker.py` as a
daily `"cron"` job (02:10 UTC, `executor='maintenance'`, mirrors `price_bars_daily_increment`).
It scores outcome='pending', claim_type='operational' rows whose period has reported and leaves
the rest pending — branch-strict on claim_type (never touches the price path or
evaluation_deferred), idempotent (only `outcome='pending'` rows; safe to re-run). **Gated by
`ENABLE_OPERATIONAL_EVALUATOR` (default OFF), lazy import (boot-safe).**

## ⚠ FRESHNESS — NOT SOLVED (blocker; flip the job ON only after this lands)
The local actuals tables (`fmp_earnings` / `fmp_income_statements` / `fmp_cash_flows` /
`fmp_ratios`) are a **one-time harvest frozen at 2026-06-10** — verified: nothing in the worker
writes them; latest reported actual is 2026-06-11. So any operational row whose period reports
AFTER the harvest can never resolve until a refresh feed exists. Today this blocks nothing
(all 8 pending rows target FY2026+/FY2027/FY2029 or Q2-2026-not_local → 0 scoreable now), but it
WILL block them when those periods report.

**Refresher BUILT 2026-06-29 (`jobs/operational_freshness.py`, gated `ENABLE_OPERATIONAL_FRESHNESS`,
daily 02:00 UTC just before the evaluator).** Need-based: refreshes ONLY the distinct pending-
operational tickers (8 today: AAPL/AMAT/AMZN/CRDO/D/INTC/MDT/ON) via per-ticker `/stable/{earnings,
income-statement,cash-flow-statement,ratios}` (annual+quarter), `_get_json` 429-backoff, paced,
`upsert conflict="update"` (fills NULL earnings actuals + the Q2-Q4 statement gap for those
tickers). Volume guard: 7 calls/ticker, STOP if the set would exceed 300/day (56 today). NEVER
bulk. **Verified OFFLINE:** compiles; dry_run = 8 tickers / 56 calls (under guard); map_rows field
mapping correct (epsActual→eps_actual, freeCashFlow→free_cash_flow, margins).

**⛔ LIVE RUN + ENABLE BLOCKED (2026-06-29): FMP key is temporarily throttled** — a single paced
per-ticker call 429s even after 155s of backoff (today's repeated bulk+per-ticker attempts tripped
a key-level "abuse" restriction). Both flags LEFT OFF; not shipping/enabling an unverified 429-ing
fetch, and not hammering (risks a harder restriction). **TO FINISH:** let the key cool down (stop
all FMP calls), re-run `run_operational_freshness()` once (should refresh the 8 tickers + unlock
AAPL 630302's Q2-2026 FCF), confirm the evaluator resolves it, THEN set
`ENABLE_OPERATIONAL_FRESHNESS=true` + `ENABLE_OPERATIONAL_EVALUATOR=true` on the worker.

## Open / next
- **Cool-down then verify+enable** the freshness refresher (above) — the only remaining step;
  blocked solely by the temporary FMP throttle.
- **Quarterly Q2–Q4 FCF/NI/margins** need an FMP quarterly backfill (bulk BLOCKED on the
  downgraded plan; per-ticker ruled out) — approval pending.
- The live classifier could gain the operational tag (additive block, eval-gated, controlled
  restart) so NEW predictions are tagged at insert; today the standalone extractor backfills.
- Tolerance bands are v1 — tune on a labeled operational sample.

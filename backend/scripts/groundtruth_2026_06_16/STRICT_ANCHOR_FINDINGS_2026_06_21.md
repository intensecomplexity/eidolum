# Strict-anchor ground-truth retighten (2026-06-21)

Retroactive application of the **FINAL STRICT** validity rule to the gold set.
Supersedes the `OK`/`conditional` validity bar used in `GOLD_FINDINGS.md`.

## MASTER RULE
A row stays valid (`OK`/`conditional`) **only if** its quote has a **NUMBER/LEVEL
or an explicit TIMEFRAME, AND** it isn't hedged / reported-speech / bare-stance.
Otherwise → `not_a_prediction`.

Scope: the **gt_gold 200** (the OK-150 is AI-presort only, not human-gold, not in
any writable table — out of scope for applied flips). All Part-1 and Part-2-example
ids live in gt_gold.

## PART 1 — applied (10 flips, gt_gold only)
`gold_verdict OK → not_a_prediction`, `gold_valid TRUE → FALSE`,
`strict_reason='strict_anchor_rule_2026_06_21'`, `prior_verdict='OK'`
(two audit columns added: `prior_verdict`, `strict_reason`, `strict_flipped_at`).
Before-state preserved in `strict_anchor_before_snapshot_2026_06_21.json` (reversible).

| id | ticker | quote gist | why |
|---|---|---|---|
| 612065 | COIN | "their stock will go higher" | no number/timeframe anchor |
| 625296 | TTD | "next gen magnificent 7 in the future" | no anchor |
| 609069 | PYPL | "paypal is a short" | bare stance, no anchor |
| 614711 | DB | "the stock goes even lower" | bare stance, no anchor |
| 614086 | TLT | "long-term rates to decline over time" | macro, no anchor (hidden: no_claim) |
| 609365 | BTC | "broke below ... the bare market" | chart commentary, no fwd anchor |
| 627490 | PROP | "moving a lot higher" + reported $20 | own call anchorless; $20 reported |
| 623883 | RDDT | "I've been bullish on Reddit" | bare; 7-9% is the ad *industry*, not RDDT |
| 626776 | KMB | "Kimberly Clark is undervalued" | no number |
| 633156 | SOFI | "I'm bullish" + "short-term trade" | bare stance, vague horizon |

Result: gt_gold valid 79 → **69** (OK 64→54, conditional 15, +10 not_a_prediction).

## PART 2 — scan of the 69 remaining OK/conditional rows (REPORTED, not changed)
9 candidates pending confirmation (full list + quotes in
`strict_anchor_part2_candidates_2026_06_21.json`). 60 rows pass (real
number/level or timeframe + own directional call — incl. all the crypto/stock
entry-TP-SL setups and explicit fair-value / price-target calls).

**CLEAR (7)** — 3 APPLIED 2026-06-29 (batch 2, same `strict_reason`); 4 still pending:
- ✅ 633185 CRWV — "price target remains UNCHANGED", number not in quote *(task example)* — APPLIED (prior=OK)
- ✅ 634815 OSCR — $45-55 target is the **CEO's** (reported); rest operational *(task example)* — APPLIED (prior=OK)
- ✅ 625629 GOOGL — "ATH on the table", no number, vague *(task example)* — APPLIED (prior=**conditional**)
- ⬜ 630302 AAPL — operational cash-flow, no price call *(task example)* — pending
- ⬜ 607205 ON — operational outlook through 2027, no price target — pending
- ⬜ 609156 AMZN — FCF projection $38B→$133B, no price/return target — pending
- ⬜ 634843 CRDO — revenue inflection/ramp, no stock price target — pending

**BORDERLINE (2)** — each has a timeframe but is inferred/hedged/bare:
- 612120 TLT — "expecting a rate cut by June"; TLT direction inferred, no level
- 605954 XOM — "oil & gas ... stocks will likely follow suit"; sector-sympathy, hedged

## PART 3 — recomputed metrics (full arc)
Method: post-stratify the gold sample by Haiku verdict class to the **visible
population** weights (`GOLD_FINDINGS.md`). Weights are a population property and are
held **fixed**; only per-class gold-valid rates change. Reconstruction validated to
reproduce the published 47.6% before applying flips.

| metric | original census | post batch-1 (10) | post batch-2 (+3) |
|---|---|---|---|
| raw 200-sample valid-rate | 79/200 = 39.5% | 69/200 = 34.5% | 66/200 = **33.0%** |
| visible-sample valid-rate (147) | 74/147 = 50.3% | 66/147 = 44.9% | 63/147 = **42.9%** |
| **headline user-facing precision** | **47.6%** | **38.7%** | **36.2%** |

Batch-2 (the 3 confirmed Part-2 CLEAR rows: 633185 OK-class, 634815 target_error,
625629 conditional — all visible) moved the headline 38.7% → **36.2%** (−2.5 pp;
the OK-class flip alone is −2.1 pp at 76.5% weight). Cumulative from the original
census: **47.6% → 36.2%** (−11.4 pp) over 13 strict flips. The 4 remaining CLEAR
Part-2 flags (630302/607205/609156/634843, all visible) would push it lower still.

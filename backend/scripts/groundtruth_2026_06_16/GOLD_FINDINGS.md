# Gold-anchored ground-truth precision (2026-06-21)

Nimrod human-labeled all 200 blind ground-truth rows. These GOLD labels replace the
Haiku silver labels for these 200 ids and re-anchor the precision census.

## Buckets
- VALID prediction: `OK` (64) + `conditional` (15) = **79**
- INVALID: `not_a_prediction` (120) + `wrong_direction` (1) = **121**
- Coverage: 200/200 ids (the stratified blind sample). No overlap, no dupes.

## Persistence (the permanent lock)
- Postgres table **`gt_gold`** (prediction_id PK, gold_verdict, gold_valid,
  haiku_verdict, cohort, labeled_by). 200 rows. `predictions` table NOT touched.
- File: `gold_verdicts_200.jsonl` (this dir) — durable backup of the same rows.

## GOLD-anchored precision (post-stratified to population, same method as the silver census)
| measure | value |
|---|---|
| Raw 200-sample gold valid-rate | 79/200 = **39.5%** (== the "~40%" — stratification artifact) |
| 3a) gold valid on the **user-visible** sample subset | 74/147 = **50.3%** (still stratified) |
| 3b) reweighted to FULL population (gold analog of silver 68.7%) | **43.6%** |
| 3b) reweighted to **VISIBLE** population — TRUE user-facing | **47.6%** (95% CI 35–60%) |

**HEADLINE: gold-anchored true user-facing precision = ~47.6%** (95% bootstrap CI
35–60%), vs the **silver 76.5%**. The silver census overstated user-facing quality
by ~29 points.

## Why silver was so wrong: Haiku rubber-stamps its own OK bucket
Per-Haiku-class gold-valid rate on the visible sample (weight = visible-population share):

| Haiku class | gold-valid | visible weight |
|---|---|---|
| **OK** | **17/37 = 46%** | **76.5%** |
| target_error | 29/35 = 83% | 7.8% |
| conditional | 16/27 = 59% | 6.0% |
| direction_mismatch | 4/20 = 20% | 4.5% |
| hedged | 2/10 = 20% | 2.3% |
| wrong_ticker | 2/6 = 33% | 1.4% |
| reported_speech | 1/2 = 50% | 0.8% |
| holding | 0/2 = 0% | 0.3% |
| chart_commentary | 2/2 = 100% | 0.2% |
| other | 1/6 = 17% | 0.1% |

The OK class carries 76.5% of the visible weight and is only **46% truly-valid** by
gold — that single fact drives the whole headline down to ~47.6%. `target_error`
rows are mostly genuine calls (83% valid; a real prediction with a wrong target
field), but they're a small slice.

## Haiku vs gold agreement (200 rows)
- Agreement: **123/200 = 61.5%**.
- Haiku OVER-flagged 46 (gold-valid that Haiku called bad) — mostly `target_error`
  (29): a real call dinged for a target-field issue.
- Haiku UNDER-flagged 31 (gold-invalid that Haiku passed) — `OK` 20 + `conditional`
  11: **false-OKs**. This is the damaging direction — Haiku passes non-predictions
  as OK, and OK is the dominant class.

The earlier Opus "Haiku over-flags" finding was real but only examined the FLAGGED
pile; the bigger leak is false-OKs inside the unflagged OK majority, which the
flagged-only reviews never sampled.

## Caveats
- The headline CI is wide (35–60%) because the dominant OK class has only n=37 gold
  rows. A larger gold sample of the OK bucket would tighten it materially.
- Single labeler (the product owner) = the authoritative definition of "valid".
- Method = post-stratification of the 200 gold labels by Haiku verdict class to the
  current visible-population class frequencies (`labels.jsonl` × live hide-flags);
  exact math, gold labels underneath. `predictions` untouched.

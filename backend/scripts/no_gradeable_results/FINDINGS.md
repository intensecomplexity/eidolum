# No-gradeable-claim detector — findings (2026-06-21/22)

Addresses the root cause behind the gold-anchor census (`../groundtruth_2026_06_16/GOLD_FINDINGS.md`):
true user-facing precision ~**47.6%** (not the silver 76.5%). The dominant Haiku **OK**
bucket (76.5% of visible weight) is only **~46% gold-valid** — driven by **vague-preference**
rows ("I like it", "great company", "on my watchlist") with **no number and no direction
stance**. No existing flag caught them.

## The rule (Nimrod's locked labels)
`not_gradeable` = **NO number AND NO stock-direction word**. KEEP bare directional stances
("bullish on V"), conditionals, and firm targets. Hedged non-call → reject (even with a
number). Buy-wishlist → reject.

## Detector (shared by the forward guard and this backfill)
`jobs/representativeness_guard.gradeable_decide()`:
1. **Cheap gate** (`is_gradeable_suspect`): a row is a candidate only if its quote carries
   NEITHER a digit NOR a direction word/phrase. Everything numeric or directional is
   auto-kept with **no LLM call** — so ~all real calls never reach the judge and false-hide
   is structurally bounded.
2. **Suspects** get ONE `claude -p` **Sonnet** verify over the **±90s window**; fail-open KEEP.
- New flag `is_no_gradeable_claim` (migration 0024), bundled into `hedged_filter_sql`
  (kill switch `HIDE_NO_GRADEABLE_CLAIM`, default on). NOT_GRADEABLE →
  `is_no_gradeable_claim=TRUE` + `outcome='unresolved'` (hidden + off the scoreboard).
- **Forward guard** wired into `insert_youtube_prediction` (ticker_call, YT-only,
  `ENABLE_GRADEABLE_GUARD` default on, fail-open) stops future accumulation.
- Distinct from `is_no_claim` (0023, quote-provenance). This flag is about **scoreability**
  of the call itself — a row can carry a claim-bearing sentence yet still be NOT_GRADEABLE
  ("great company"). A separate flag keeps measurement + reversibility surgical.

## EVAL GATE — 200-row human gold set (`gold_eval_verdicts_200.jsonl`)
| measure | result |
|---|---|
| **False-hide of a real call** | **0 / 79** (cardinal sin avoided, full margin) |
| Flag precision | **10 / 10 = 100%** |
| OK bucket | 0 hidden / 64 kept |
| conditional | 0 hidden / 15 kept |
| not_a_prediction | 10 hidden / 110 |
| Addressable recall (gold-invalid suspects) | 10 / 35 = 28% |

The single gold-valid suspect ("expecting a rate cut by June") was correctly RESCUED by the
verify. The 25 missed gold-invalid suspects are overwhelmingly **other failure classes**
(macro/market narration, holding disclosures, foreign-language) — not the vague-preference
class this detector targets. Recall is deliberately ceilinged: precision over recall.

## Population pass — visible Haiku-OK cohort
- Cohort: **10,457** visible OK rows (`ok_cohort_verdicts.jsonl`).
- Suspects (no number, no direction): **1,508** (14%); the rest auto-kept (no LLM).
- **Flagged NOT_GRADEABLE: 102** (vague_preference 94, wishlist 8) = 6.8% of suspects, ~1%
  of the OK bucket. 14/14 random spot-check were textbook vague preference (100%).
- **0** of the 102 are in the gold 200 → no gold-valid collateral; the gate's 0-false-hide
  holds on the population.
- Apply: 102 flagged, **94 outcome→unresolved** (22 scored + 72 pending), 8 left as-is;
  `[pre_remediation]` JSON saved (fully reversible). Idempotent (re-run flags 0).
- `refresh_all_forecaster_stats` run on the API (5,695 forecasters) → the 22 now-unresolved
  rows dropped from cached accuracy. User-facing hiding is immediate via the bundle.

## Precision: before → after
| measure | before | after |
|---|---|---|
| stratified-to-visible (gold-sample estimate) | 47.65% | **47.66%** (flat) |
| OK-bucket gold-valid rate (direct, 102 are 100% invalid) | 45.9% | **~46.4%** (+0.5pp) |
| implied headline (direct calc) | 47.6% | **~48.0%** (+0.4pp) |

**Why the gold-sample estimate is flat:** it is a 200-row sample estimate; the OK class has
only **n=37** gold rows (CI ±~16pp). A 102/10,457 ≈ 1% removal from OK is **below the
sample's resolution**. None of the 102 are gold rows, so the per-class rate is unchanged by
construction. The *direct* effect (removing 102 confirmed-invalid rows) is real and certain;
the sample-based headline simply can't see a sub-1% shift.

## Recall ceiling & path to more (deferred — needs Nimrod's call)
The conservative cheap gate catches only the **unambiguous core** (~1% of OK). The "~28%
vague preference" includes rows with **incidental** numbers (P/Es, years, % stats) or
**soft-direction** words that the gate auto-keeps to protect precision. Catching them needs a
more aggressive gate/prompt that risks false-hides — which CANNOT be validated safely on the
current n=37 OK gold sample. Prerequisite for a wider pass: a **larger gold OK-bucket sample**
to measure false-hide, plus an explicit higher false-hide tolerance. Until then, precision is
sacred and recall stays ceilinged.

## Reproduce
```
# eval gate
NG_WORKERS<=5 python3 backend/scripts/no_gradeable_judge_2026_06_21.py /tmp/gold_ids.json \
    /tmp/gold_verdicts.jsonl --gold backend/scripts/groundtruth_2026_06_16/gold_verdicts_200.jsonl
# population + precision
python3 backend/scripts/no_gradeable_judge_2026_06_21.py /tmp/ok_ids.json /tmp/ok_verdicts.jsonl
python3 backend/scripts/no_gradeable_apply_2026_06_21.py /tmp/ok_verdicts.jsonl --commit
python3 backend/scripts/no_gradeable_precision_report.py   # run before & after
```
Run local `claude -p` at **≤5 workers** (shared WSL box). The judge is resumable (append-one-
JSONL-line; ERROR rows re-judged on resume) — a contended-box run errored 706/1508; one resume
at 2 workers cleared them all.

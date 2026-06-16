# Opus re-verification of the Haiku review pile + blind ground truth (2026-06-16)

Authoritative re-judge of the Haiku full-coverage review pile
([[project_fullcov_judge_2026_06_16]]) with **Opus** (apply-classes) + **Sonnet**
(direction/ticker), plus a blind human ground-truth sheet. Two-judge, eval-gated,
precision-first. Classifier untouched.

## TRACK A — blind ground-truth sheet (for Nimrod)
Stratified 200-row sample (seeded, reproducible) across sources + Haiku classes.
Blind CSV (NO AI verdict shown) → Drive **eidolum.prompts/ "2026-06-16-ground-truth-blind-200"**
(Sheet `1cHqF0SNYCN981OuFu_IrNoOwNfNdeVcVFhi8mHqdboY`). Haiku verdicts saved
separately (`groundtruth_2026_06_16/haiku_verdicts_for_200.json`) for the eventual
human-vs-Haiku-vs-Sonnet-vs-Opus agreement (STEP D, pending Nimrod's labels).

## TRACK B — model re-verification (blind to Haiku label, tight quote+context)
Cohort = the 1,489 Haiku-flagged-but-not-applied rows. Scoped (operator decision):
**Opus on the apply-classes** (holding/reported/chart/target_error = 674);
**Sonnet on direction/ticker** (620 dm + 195 wt = 815). 0 / 1 ERROR.

### Cost probe (STEP 0)
- Sonnet 100: 77s, 0 rate-limit. Opus 100: 239s, 1 transient error. Full Opus
  ~55-60 min, ~1.5M tokens (Opus meter-heavy) — hence the scope split.

### Headline: Haiku massively over-flags; Opus/Sonnet spare most
| Haiku class | n | verifier confirms | overturned mostly to |
|---|---|---|---|
| holding | 120 | Opus **35%** | OK 37, no_claim 31 |
| reported_speech | 268 | Opus **37%** | OK 85, no_claim 53, target 21 |
| chart_commentary | 69 | Opus **26%** | OK 28, no_claim 18 |
| target_error | 217 | Opus **13%** | **OK 144** |
| direction_mismatch | 620 | Sonnet **29%** | (Opus said 18% on the probe-100) |
| wrong_ticker | 194 | Sonnet **57%** | — |

On the probe-100 (all Haiku direction_mismatch): **Opus↔Sonnet agreed only 51%**,
all-three-agree just 14% — `direction_mismatch` is genuinely ambiguous, so it is
NEVER auto-flipped.

## STEP C — applied (Opus-authoritative, flag-not-delete, [pre_remediation], idempotent)
Applied the **Opus** verdict where it is a hide-class (spared the 294 Opus=OK rows
— Haiku false-flags now correctly left visible). 12-row hand spot-check before
apply: all correct + well-reasoned (~0 false-hide). Marker `opus_2026_06_16`.
- **is_no_claim: 141** (Opus no_claim 119 + chart_commentary 22; scored→unresolved)
- **is_holding_disclosure + unresolved: 44**
- **is_reported_speech: 103**
- **target → direction-only (null target, scored→pending): 49**
- **Total applied: 337.** Spared (Opus=OK): 294.

## STEP C — direction/ticker → review (NO blind auto-flip; score-changing = human sign-off)
`review_dirtick_haiku_sonnet_agree.jsonl` — **296 rows** where Haiku AND Sonnet
agree (185 direction_mismatch + 111 wrong_ticker). For Nimrod's final sign-off;
the rest (where Sonnet overturned Haiku) are dropped (left as-is).

## STEP D — agreement (pending human labels)
`agreement_results.json` has the full Haiku/Sonnet/Opus per-class table. The
human-vs-each accuracy awaits Nimrod's hand-labeled 200 (Drive sheet) — then we
get the honest accuracy + which judge to trust.

## Which judge to trust (so far)
Opus's spot-checked verdicts were uniformly correct and well-justified; it spares
Haiku's heavy false-positives while catching genuine hides. **Recommendation: treat
Opus as the authoritative judge** for the hide-classes; confirm against the human
200 before locking it in for the fine-tune labels.

## Safe to restart? YES
Only reversible hide-flags / target-drops applied (flag-not-delete), all Opus-
verified + spot-checked; direction/ticker changes deferred to human review;
classifier untouched.

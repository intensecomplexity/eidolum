# Insert-time guard tightening — measured frontier (2026-06-14)

Attempt to raise recall on the two eval-gated insert-time guards (conditional +
representativeness) while holding their hard precision floors. Classifier STOPPED;
no restart. Reused the committed fixtures: conditional = the 311 LLM-judged rows
with cached transcripts (46 a / 38 b / 227 c) from the da47210+aae459c cleanup;
representativeness = the 203-row fixture from the c64e38f/e1fed93 ships.

## HARD FLOORS (non-negotiable)
- Conditional: gold-(c) false-route ≤ 3% AND 0 scoring-breaking routes.
- Representativeness: 0% clean hard-reject; clean soft-flag ≤ ~7%.

## CONDITIONAL GUARD — frontier (4 rounds)
| prompt | (a) recall | (b) recall | (c) false-route | route_price on (c) | floor |
|---|---|---|---|---|---|
| **R0 (shipped)** | **61%** | **55%** | **1.8%** | 0 | **HELD ✓** |
| R1 soft-macro+fewshot | 83% | 42% | 5.3% | 0 | breach |
| R2 +exclusion list | 83% | 37% | 5.3% | 0 | breach |
| R3 named-event discriminator | 74% | 55% | 4.0% | 0 | breach |
| R4 +hard-keep rules | 52% | 39% | 3.1% | 0 | breach (and recall < R0) |

**Verdict: KEEP R0.** No prompt raised recall while holding the ≤3% floor. The
frontier is steep and intrinsic: gold-(a) soft-macro "if"s and the false-routed
gold-(c) "if"s are linguistically the same family (the audit judge itself drew a
fuzzy line). Every recall gain (R3: a 61→74) pushed false-route to ≥4%, breaching
the hard floor by ≥1pp; the one round that neared the floor (R4: 3.1%) collapsed
recall below baseline. R0 (1.8% false-route, all reversible unresolved, 0 broken
routes) dominates. R3 is the documented "+13pp recall for +2.2pp false-route" point
if the floor is ever relaxed to ≤4%.

## REPRESENTATIVENESS GUARD — frontier (1 round)
Honest soft-flag metric now counts reported-flags on clean rows too (not just no-call weak-flags).
| prompt | clean hard-reject | clean soft-flag | no-call catch | reported | flips |
|---|---|---|---|---|---|
| baseline (shipped) | 0% | 8.8% (7/80)* | 43% | 4/7 | 4/6 |
| R1 expanded reported lexicon | 0% | 6.2% (5/80)* | 43% | 4/7 | 4/6 |
*soft-flag swing is Sonnet run-variance on the no-call weak-flag, not the lexicon.

**Verdict: KEEP shipped.** The lexicon expansion produced NO measured recall gain
(reported 4/7, no-call 43%, flips 4/6 unchanged) — the fixture's reported rows
aren't matched by the new patterns, and the verify already handles them as before.
Under the honest metric the guard already sits at the ~7% soft-flag edge (6–9% across
runs), so there is negative headroom: raising no-call/reported catch would push clean
soft-flag past the floor. No merge on an unmeasured improvement → revert to shipped.

## Net result
No code changes merge. Both guards were already shipped at their precision-respecting
frontier; tightening upward is infeasible without breaching the hard floors. Documented
the frontier so a future relax-the-floor decision (e.g. conditional ≤4% → adopt R3 for
+13pp (a) recall) is a one-line prompt swap, eval-gated. Safe to restart unchanged.

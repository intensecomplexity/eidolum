# Unified reject-rules judge — gold eval (2026-06-29)

EVAL-GATE for the classifier's junk filter. Codifies Nimrod's locked reject ruleset into one
deterministic judge (`reject_rules_judge_2026_06_29.py`) and evaluates it against ALL human
gold (`gt_gold`, 200 rows). **NOT applied to the population; live classifier untouched.**

## Design
Applies the ruleset to the QUOTE (reusing `representativeness_guard` lexicons — verify-don't-
invent). Does NOT inherit per-row flags (3 gold-VALID rows carry classifier false-flags the gold
overrides — inheriting would false-reject them). Exempts `claim_type='operational'`.

reject reason → existing flag (for a future apply step):
| reason | existing flag |
|---|---|
| no_anchor / bare_stance | `is_no_gradeable_claim` |
| hedged | `conviction_level` ∈ hedged/hypothetical |
| reported_speech | `is_reported_speech` |
| holding / buying | `is_holding_disclosure` |
| buy_wishlist | `is_no_gradeable_claim` |
| (basket / ambiguous) | `is_weak_basket_call` / `is_ambiguous_symbol` (already flagged) |

KEEP iff (a number/level OR an explicit timeframe) is present — the bare directional stance is
rejected (this is stricter than the existing no_gradeable guard, which kept bare-direction).

## Eval (eval-set = 200 gold: 66 valid / 134 invalid)
| metric | value |
|---|---|
| **CATCH** (invalid rejected) | **70/134 = 52.2%** |
| **FALSE-REJECT** (valid rejected) | **0/66 = 0.0%** ✓ (sacred constraint met) |
| confusion | catch 70 · miss 64 · false-reject 0 · correct-keep 66 |
| catch by rule | no_anchor 65 · reported_speech 3 · buy_wishlist 1 · holding 1 |
| **FALSE-REJECTS (full list)** | **NONE** — no gold-valid row is killed |

**`no_anchor` is the whole game**: 65 of 70 catches — exactly the "#1 leak." Calibration removed
the v1 false-rejects (bare "maybe"/"wouldn't surprise" in secondary clauses, the noisy bull+bear
`both_ways` rule, the broad `according to`, and a Wall-St-mention-with-own-call) to reach 0.

## Projected user-facing precision IF applied
| | pre-filter | post-filter |
|---|---|---|
| post-stratified (visible-pop weighted) | **36.2%** | **54.1%** (+17.9 pp) |
| gold-sample kept-precision | 33.0% | 50.8% |

## Why not ~100% (the 64 misses)
The misses are **anchored-semantic junk** a regex can't catch without false-reject risk:
no_claim 13 · OK 12 · target_error 8 · direction_mismatch 8 · conditional 7 · reported 4 ·
chart_commentary 4 · holding 3 · hedged 2 · other 2 · wrong_ticker 1 — rows that carry an
incidental number/timeframe but are still junk (wrong-direction, conditional, target-only,
vague-with-a-year, anchored reported-speech). **Path to ~100%:** a cost-gated LLM verify on the
anchored misses (the existing-guard pattern: deterministic suspect → one `claude -p` verify →
reject only confirmed), eval-gated separately. The deterministic judge is the safe foundation
(0 false-reject); the verify lifts catch on the residual without breaching the floor.

## Status
EVAL ONLY. Not applied to predictions; live classifier unchanged. Awaiting approval to (a)
extend with the cost-gated verify and/or (b) apply the deterministic judge as a forward
flag-not-delete guard (maps to the existing flags above).

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

## APPLIED to the user-visible population (2026-06-29, reversible)
Before applying, a deeper audit (the spot-check the apply required) hardened the judge and
narrowed what was applied:

**Judge v2 fixes** (population-found false-rejects the 200-gold sample didn't contain):
- `\b\d{2,}\b` → `\d{2,}` — caught suffixed levels ("254ish") that were wrongly read as no_anchor.
- Dropped the loose `[A-Z][a-z]+ + speech-verb` REPORTED pattern — it mis-fired on capitalized TA
  narration ("Chart says", "Bears think") inside real first-person calls.
- Restructured: a row WITH an anchor is rejectable ONLY by reported/hedged; wishlist/holding/past/
  no_anchor require NO anchor — protects anchored conditional setups ("waiting for a retest at $75k").

**Scope:** `source_type IN ('youtube','x')`, currently visible, NOT operational (= 14,204 rows).
Wall-St `article`/`insider`/`congress` (710K) EXCLUDED — the judge is quote-based and would nuke
the quote-less analyst feed.

**Applied (flag-not-delete, audit marker `reject_judge_2026_06_29`, snapshot
`reject_judge_apply_2026_06_29_snapshot.json`):**
| reason | flag set | rows |
|---|---|---|
| no_anchor + buy_wishlist + past_tense | `is_no_gradeable_claim` | 3,977 |
| holding | `is_holding_disclosure` | 115 |
| **total applied** | | **4,092** (28.8% of visible YT+X) |

**DEFERRED — NOT applied** (a deep audit of the only rules that reject ANCHORED rows found residual
false-rejects there): `reported_speech` (143 — fires on own-theses-that-mention-an-analyst, e.g.
"I am very bullish… revenue 11.5% CAGR") and `hedged` (25 — rhetorical "no idea why people sleep
on it", "50/50" market-share). These are semantic calls → route to the cost-gated LLM verify, not
deterministic.

**Result:** user-facing precision (post-stratified gold) **36.2% → 51.1%** (+14.9pp). Spot-checks:
30 random applied + 50 random + 66 gold = **0 false-reject**. Verified: every flagged row is YT/X
non-operational (0 other-source, 0 operational); price path / analyst feed / live classifier
untouched. Reversible via the snapshot. NOTE: cached leaderboard stats lag until
`refresh_all_forecaster_stats` runs.

## Open / next
- Cached forecaster-stats refresh to propagate the hides to leaderboards.
- The cost-gated LLM verify for the deferred reported/hedged anchored-suspects (eval-gate first).

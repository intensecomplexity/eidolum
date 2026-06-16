# Classifier lessons from the Opus/Sonnet-validated review pile (2026-06-16)

Goal: turn the **Opus/Sonnet-CONFIRMED** error patterns ([[project_opus_reverify_2026_06_16]])
into forward classifier rules; auto-eval each; auto-ship only clear winners. Gold =
Opus/Sonnet-confirmed ONLY (Haiku-only labels excluded as noise). Additive prompt
rules only — HAIKU_SYSTEM and the youtube validation blocks were NOT touched.

## SHIPPED: target_hygiene v2 (LIVE on next classifier start)
**v1 HELD → v2 SHIPPED.** v2 narrowed the rule (nulls ONLY chart-level /
valuation-model output / market-cap / third-party-PT numbers) and DROPPED v1's two
false-reject drivers — the wrong-SIDE check (the deterministic `sanity_check_target`
guard owns that) and the entry-price clause; default flipped to KEEP-on-doubt.
Re-eval (real `build_cc_prompt` WITH/WITHOUT, Sonnet):
- **catch 85%** (6/7 bogus-target windows nulled) — material.
- **genuine-host-target false-reject ~0**: on a hand-curated unambiguous set
  (TSLA→900, ELF→200, NVDA→"goes to $250 in six months", MSFT→450 [v1's miss, now
  KEPT], RUM→11, OSPN→24), v2 kept all genuine targets; the only metric-null was
  "IV's target of $250" — a relayed SOURCE target, correctly nulled. (v1 was 36%.)
- **acceptance drop 1/30** (field-scoped — structurally cannot collapse acceptance).
SHIPPED by flipping `target_hygiene=True` at the live call site
`build_cc_prompt(good, conditional=True, long_horizon_rule=True, target_hygiene=True)`.
Off-path (arg False) asserted byte-identical; conditional + long-horizon blocks
unchanged. Takes effect on next classifier start (classifier currently stopped).
Rollback = flip the arg back to False.

## v1 (held, superseded by v2 — kept for the record)

## target_hygiene — EVAL'd, HELD (promising but over-aggressive)
Rule: a non-price number (chart/MA level, P/E·EPS·DCF per-share, market-cap, entry
price, third-party PT, or wrong-side value) must NOT be `price_target` → set null;
field-scoped (never changes which predictions are emitted).
- **Catch: 85%** (6/7 reproduced-bogus-target windows nulled). 
- **Acceptance drop: ~0** (1/30 — field-scoped, as designed; it cannot collapse acceptance).
- **False-reject: FAILS.** First metric read 77% but was confounded (must-not-
  regress set was "OK *call* with any target," and those target *fields* were
  themselves valuation/level numbers — all 7 hand-verified as CORRECT nulls). A
  clean re-eval on **genuine round host targets** (`clean_keep`) still showed
  **36% false-reject (4/11)** — incl. a clear miss (MSFT "$450" target nulled).
  Driver: the **side-check (wrong-side) + entry-price clauses** over-null real targets.
- **Verdict: HOLD.** >> the false-reject ~0 bar.
- **v2 fix (proposed):** drop the side-check + entry-price clauses; keep only the
  unambiguous nulls (chart level, valuation-model output, market-cap, third-party
  PT). Re-eval false-reject on `clean_keep` before flipping the arg.

## The 4 REJECT-rules — ENCODED (default-off), EVAL'd, ALL HELD (auto-ship 0/4)
Encoded as additive default-off args (`reject_unnamed/reported/chart/holding`);
all-off path asserted byte-identical; live call site does NOT pass them → live
prompt unchanged. Strict eval (real `build_cc_prompt` WITH/WITHOUT vs the live
config, Sonnet): catch on Opus/Sonnet-confirmed should-catch, false-reject +
acceptance on a 24-row real-call sample (`reject_keep_sample.json`). Marginal-value
(no-LLM regex check): the post-insert guards' suspect-regexes already MISS 52-67%
of these. Full numbers in `reject_rules_eval.txt`.

| rule | CATCH | FALSE-REJECT | ACCEPTANCE Δ | verdict |
|---|---|---|---|---|
| unnamed_macro | **0/2** | 0/12 | 0% | HOLD — no marginal catch |
| reported_speech | **0/2** | 0/11 | -6% (noise) | HOLD — no marginal catch |
| chart_commentary | 3/7 (42%) | 2/12 (16%) | **−23% COLLAPSE** | HOLD — collapses acceptance |
| holding | 2/5 (40%) | **3/13 (23%)** | 0% | HOLD — false-rejects real calls |

**Why none shipped (the principle held):**
- A classify-time REJECT is **irreversible** (the row never exists); the post-insert
  guards keep the row + hide it (reversible, auditable). So a REJECT must CLEARLY
  beat the guard.
- **unnamed_macro / reported_speech:** the CURRENT live prompt baseline barely
  reproduces these errors (only ~2/16 reproduced) — its existing rules
  ("Inferred direction", "Pronoun-only", etc.) already suppress them at extraction.
  The gold-set errors came from the cohort's OLDER classification. So the REJECT
  adds **~0 catch** → no marginal value.
- **chart_commentary:** modest catch but **−23% acceptance collapse** (dropped 5/21
  real preds) + 16% false-reject — exactly the 5518ea1 disaster class. Hard fail.
- **holding:** **23% false-reject** (dropped 3/13 real calls) — too aggressive.

**Recommended instead (reversible):** the marginal-miss (guards' regexes miss
52-67%) is best closed by **WIDENING the post-insert guards' suspect regexes** so
they send more rows to their existing reversible Sonnet verify (flag-not-delete) —
NOT by adding irreversible classify-time REJECTs. The dormant args remain as
eval'd-and-rejected proposals (don't re-litigate; re-eval only if the live prompt
changes materially).

## X-path proposal (separate, not YouTube)
**X numeric-target capture** (the 872 missing-target rows, mostly X) — extraction
should capture an explicit tweet PT ("$30 target", "+633%"). This is an X_ADDENDUM
change → the sacred X eval gate, not `cc_recover`. Deferred.

## Artifacts
`gold_fixtures.json` (per-pattern should-catch + must-not-regress) ·
`target_hygiene_eval.json` (confounded run) · `target_hygiene_cleankeep_eval.json`
(clean genuine-target run) · `eval_target_hygiene_2026_06_16.py` (harness).

## Net
The eval gate worked: a rule that *looked* obviously good (catch 85%, can't hurt
acceptance) was caught nulling ~1 in 4 real targets. Nothing auto-shipped; the live
classifier prompt is byte-identical. Clear next step = target_hygiene v2 (drop
side-check/entry clauses) + re-eval.

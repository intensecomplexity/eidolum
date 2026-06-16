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

## HELD as proposals (not encoded live — overlap existing guards + acceptance-collapse risk)
Each has a gold fixture in `gold_fixtures.json` (should-catch = Opus/Sonnet-confirmed,
must-not-regress = Opus=OK). REJECT-type rules can collapse acceptance, so they need
the full WITH/WITHOUT + acceptance eval before any merge.
1. **unnamed-instrument / macro invention** (Opus no_claim, 119) — "don't emit an
   ETF/index ticker from broad macro/'the market' talk without an explicit call on
   it." Overlaps the existing "Inferred direction" REJECT; thin must-not-regress (10).
2. **reported-speech** (Opus reported_speech, 103) — third-party PT/stance relays.
   Overlaps the post-insert `is_reported_speech` guard; the RE-class nuance (speaker
   adds own call) makes it false-reject-prone.
3. **chart-commentary-as-call** (Opus chart_commentary, 22) — pure TA levels, no
   conviction. Small N.
4. **holding-as-call** (Opus holding, 44) — passive position disclosure. Overlaps
   the post-insert `holding_decide` guard.

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

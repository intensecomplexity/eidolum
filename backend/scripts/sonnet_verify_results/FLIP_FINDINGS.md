# Opus authoritative flips of the direction/ticker review rows (2026-06-16)

The 297 Haiku∩Sonnet-agree review rows (185 direction_mismatch + 112 wrong_ticker)
re-judged BLIND by **Opus**; only Opus-confirmed corrections applied (now
triple-agreement Haiku+Sonnet+Opus); re-scored through the real evaluator.
Reversible. Classifier stayed stopped.

## Opus verdicts (blind, conservative — ambiguous→KEEP)
| verdict | n |
|---|---|
| FLIP (direction wrong, corrected) | 100 |
| RETICKER (call about a different company) | 74 |
| KEEP (stored value correct / ambiguous) | 123 |
Opus confirmed **174/297 (59%)**, KEPT 123 (41%).

## Applied (id-pinned, idempotent, reversible)
- **100 FLIP** → corrected direction (entry_price kept).
- **66 RETICKER** → corrected ticker (entry_price nulled to re-resolve); 6 of the 72
  excluded for non-US-pattern symbols (not auto-applied).
- Each set `outcome='pending'` + `evaluated_at=NULL`; the BEFORE state (ticker /
  direction / outcome / entry / actual_return) is saved in
  `flip_before_snapshot.json` (the reversibility record — `evaluate_batch` rewrites
  evaluation_summary on re-score, so the in-row marker does not persist; the
  snapshot file is the source of truth. NOTE: do NOT re-run flip_apply — the marker
  is gone from the row, so a re-run would double-apply).

## Re-scored via the real evaluator (evaluate_batch, worker)
74 scored (38 hit / 36 miss), 64 tickers; 5 no_data. Outcome transitions on the
166 confirmed:
- **win→loss 18 · loss→win 20** (balanced — these correct genuinely-wrong
  directions in both directions; not an accuracy inflation),
- pending→scored 25, same 16,
- **still pending 87** — X rows (x_filter excludes X from scoring) + non-US/no-data
  retickers: corrected but off-board until scoreable. None regressed scored→pending.

## Spot-check (DB-authoritative, the evaluator's own summaries)
- BTC bearish→bullish: "+18.3% ✓" miss→hit.
- AMC bearish→bullish: "+30.2% ✓" miss→hit.
- ONDS bullish→bearish: "−2.0% ✓" →hit.
All 3 corrections re-scored correctly. (Public eidolum.com/api/* route differs from
the probed paths → not checked via HTTP; the site reads the same DB and reflects
after the 5-min cache.)

## Reversible + validation
Fully reversible from `flip_before_snapshot.json`. The pending hand-labeled 200
ground-truth sheet will independently validate Opus's flips afterward. `refresh_all_forecaster_stats` run.

## Artifacts
`opus_flip_judge_2026_06_16.py` · `flip_verdicts.jsonl` (297 Opus verdicts) ·
`flip_before_snapshot.json` (reversibility).

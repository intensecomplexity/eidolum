# Opus adjudication of the LEFTOVER dir/ticker candidates (2026-06-23)

Finishes the 2026-06-16 full-coverage Haiku dir/ticker adjudication. The first pass
([`FLIP_FINDINGS.md`](FLIP_FINDINGS.md)) judged the **297 Haiku∩Sonnet-agree** rows.
This pass judges everything left: the **518** fullcov `direction_mismatch` +
`wrong_ticker` candidates **NOT** in that 297 — i.e. the rows Haiku flagged but
**Sonnet spared** (Haiku-only signal). Same machinery reused: `opus_flip_judge_2026_06_16.py`
(blind Opus, conservative ambiguous→KEEP) + the `/tmp/flip_apply.py` shape, re-homed as
`flipx_apply_2026_06_23.py` with a distinct marker, its own snapshot, and added precision guards.

## Cohort
518 leftover (435 direction_mismatch + 83 wrong_ticker; 449 YouTube + 69 X), built from
**current** DB state, none already flip-marked. YouTube context = ±-window transcript
around the quote; X = the tweet.

## Opus blind verdicts (conservative)
| verdict | n |
|---|---|
| KEEP (stored correct / ambiguous) | 419 |
| FLIP (direction wrong) | 80 |
| RETICKER (different company) | 19 |
Opus confirmed corrections on **99/518 (19%)** of the Sonnet-spared pile — KEPT 81%.
(1 row briefly hit the Opus cap → fail-safe-KEEP; stripped + re-judged so all 518 carry a real verdict.)

## Applied: 74 FLIP + 8 RETICKER = 82  (precision-sacred filtering)
The spot-check (all 19 retickers + 25 score-impacting flips) surfaced two systematic
error classes the conservative guards now route to **review, never mutate**:
- **Inverse / inverse-leveraged ETFs** (`SH`, `TBT`, `VXX`, …): Opus conflates the *market*
  call with the *ETF's* direction (got `SH` wrong both ways: "market crash → SH bearish",
  but inverse SH is bullish on a crash). 4 FLIP/RETICKER routed to review.
- **X analyst-roundup tweets** (≥3 cashtags, e.g. `$DPZ` in an RBC multi-name note): per-ticker
  direction is unreliable — Opus's bearish `DPZ` flip contradicted the cited "Outperform". 2 routed to review.
- Plus 10 no-op/unvalidated retickers (target == stored, `None`, or not in `ticker_sectors`'s
  12,746-symbol universe — e.g. `ETHA→ETH-USD`, `CAN→ETERNAL`) and 1 no-op flip.
**Review total: 436** (`flipx_review.json`). Retickers applied are sharp company fixes:
`MO→MOWI` (Norwegian salmon, not Altria), `WMT→WM` (Waste Management), `BA→BAESY` (BAE Systems),
`RTX→NOC` ("ticker symbol NOC" stated), `PSTG→PATH`, `LNG→CQP`, `AIR→MAA`, `INTU→SPY`.

## Re-scored via the real evaluator (evaluate_batch) — BALANCED, not inflation
Applied rows set `outcome='pending'`, `evaluated_at=NULL`; re-scored through `evaluate_batch`
(45 scored, 48 tickers). Transitions on the 82 (snapshot vs after):
- **win→loss 10 · loss→win 8** (both directions — genuine corrections; **net −2**, the *opposite*
  of accuracy inflation),
- off-board→scored: **win 12 · loss 11** (delisted/unresolved rows now scoreable, balanced),
- win→win 3, loss→loss 2, off→off(no_data) 1,
- **still pending 35** — X rows (`x_filter` excludes X from scoring) + non-due; corrected but off-board.
`refresh_all_forecaster_stats` run (evaluate_batch updated the 24 affected forecasters inline).

## Reversible
Full BEFORE state (ticker/direction/outcome/entry/actual_return) in `flipx_before_snapshot.json`
(82 rows). `evaluate_batch` rewrites `evaluation_summary`, so the marker is gone from re-scored
rows — the snapshot is the audit record. **Do NOT re-run `flipx_apply`** (would double-apply).
Classifier (`cc_recover`) left running; ≤2 workers throughout; HAIKU_SYSTEM/Rule-14 untouched.

## Artifacts
`flipx_apply_2026_06_23.py` · `flipx_verdicts.jsonl` (518 Opus verdicts) ·
`flipx_before_snapshot.json` · `flipx_applied_ids.json` · `flipx_review.json`.

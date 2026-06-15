# Insert-time guard tightening from the recent-audit leaks (2026-06-15)

Precision-first, eval-gated. Driven by the n=200 recent-audit leaks
([[yt_audit_2026_06_15]]). READ-ONLY STEP 0 reframed the ship; the user approved
the revised plan.

## STEP 0 — per-leak cause (read-only)

| id | class | cause |
|---|---|---|
| 631403 AVGO | target ($34 vs spot $385, bullish) | **Deterministic gap (NEW).** `sanity_check_target` caps magnitude only (88% < 200%); a target on the WRONG SIDE of entry passes. |
| 631378 GOOG | holding | **Pre-guard** (inserted 06-11; guards shipped 06-14). Shipped holding guard re-run → **HOLDING**. |
| 631386 GOOGL | wrong-ticker/no-call | **Pre-guard.** Shipped rep guard re-run → **REJECT_NO_CALL**. |
| 631548 SBUX | no-claim (recap) | **Pre-guard.** Shipped rep guard re-run → **REJECT_NO_CALL**. |
| 631555 META | no-claim (example) | **Pre-guard.** Shipped rep guard re-run → **REJECT_NO_CALL**. |
| 631473 GOOGL | no-claim (orphan-only) | Recall gap, **deliberately left open** — orphan-only isn't a suspect; that trigger was rejected at the 06-14 merge (23.5% false-reject). |

**Two reframing facts:** (1) **Zero YouTube rows inserted since 06-14** — the
forward guards have never actually run at insert in prod; every existing flag was
set by *backfill*. The leaks are pre-guard, not guard failures. (2) A naive
ratio/directional band flags **447** rows, mostly garbage `price_bars` reference
(SPX $0.05, BTC $33). The only zero-false-hide formulation is **degrade-to-
direction-only** (never hide).

## STEP 1 — deterministic target wrong-side rule

`services/target_sanity.sanity_check_target(entry, target, window, direction=)`
extended: a **bullish** target `< 0.5×entry` or a **bearish** target `> 2.0×entry`
returns `None` → **direction-only** (same degrade the magnitude cap already uses;
never hides → zero-false-hide by construction). Wired at all 3 call sites
(insert `youtube_classifier`, `historical_evaluator`, `retry_no_data`). Band is
deliberately wide so conservative near-entry targets are untouched. Unit test:
`tests/test_target_sanity_wrong_side.py` (5 pass).

## STEP 2 — DROPPED (contraindicated)

Recall-widening was unnecessary: 4/6 leaks are already suspects under the
**unchanged** shipped regexes and are caught when re-run (proven, read-only). The
one true recall gap (631473, orphan-only) was deliberately rejected at merge.
Per the precision-first constraint (do not raise LLM-judge aggressiveness), no
regex change shipped.

## STEP 3 — eval-gate (PASS)

Extended rule over **637** scored YouTube rows with target+entry → **6 newly
dropped**, ALL hand-checked as genuine wrong-side extraction errors (ADBE
$62/$511, UNH $68/$525, LMT $58/$423 = EPS/DCF misread; META $100/$636; ETH
$340/$2945 dropped-digit; SPY bearish $1181 > entry). **Zero legit targets
dropped; zero rows hidden** (direction-only). AVGO 631403 (pending) self-heals at
next eval.

## STEP 4 — backfill (`guard_tighten_backfill_2026_06_15.py`, applied)

- **Part A (target):** 6 scored wrong-side rows → target nulled (original in
  `[pre_remediation]`) + reset to `pending` so the canonical evaluator re-scores
  direction-only (robust regardless of deploy state). AVGO 631403 target nulled.
- **Part B (confirmed pre-guard leaks):** 631378 → `is_holding_disclosure` +
  unresolved; 631386/631548/631555 → `is_weak_basket_call` (matches exactly what
  `insert_youtube_prediction` would set). flag-not-delete, idempotent.

### Scoped follow-up (NOT in this ship)
The full pre-guard unguarded cohort is **11,209 visible rows (~3,707 suspects:
363 holding + 3,378 rep)** — accountability-pass scale, and precise verification
needs the ±90s transcript window per row. Recommend a dedicated checkpointed
campaign (re-running the **unchanged** shipped guards) rather than a lower-quality
window-less mass-flag. This ship handles the confirmed leaks + the deterministic
target gap.

## Verdict
The one genuine NEW gap (wrong-side target) is closed forward + backfilled, zero
false-hide. The other leaks were pre-guard rows the existing guards already
handle. **Safe to restart:** yes — the forward target rule degrades (never hides),
the guards are unchanged, and the classifier path is untouched.

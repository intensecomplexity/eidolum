# Pre-guard cohort cleanup — run the shipped guards over rows that never saw them (2026-06-15/16)

The forward guards (holding / representativeness / target-sanity) shipped 2026-06-14,
but **no YouTube row had been inserted since** (classifier stopped), so they had
never actually run at insert. This campaign re-ran the **UNCHANGED** shipped
guards over the historical pre-guard cohort. No new judge logic; no aggressiveness
change ([[project_guard_tighten_2026_06_15]]).

## Cohort (STEP 0)
Pre-guard (`created_at < 2026-06-14`), VISIBLE, no existing guard flag:
**11,205 rows** (3,635 scored / 6,597 pending / 973 other). Cost-gated to the same
regex suspects prod uses: **3,703 suspects** (362 holding + 3,375 rep). The other
~7,500 non-suspects skip the LLM, exactly as at insert. Target wrong-side = 0 new
(prior ship `ee1a97b` already swept all scored rows; pending self-heal).

## Method
- **Transcripts:** Webshare, 4s pacing, persisted, checkpoint/resume; suspect
  videos only (2,397 distinct; 858 pre-cached). Final: **1,415 fetched ok / 124
  unhealable** (transient/terminal — no transcript).
- **Judge:** the unchanged `representativeness_guard.holding_decide()` +
  `decide()` over each ±90s window (claude -p, bills Max), checkpointed, via a
  self-looping driver. Scope (user-approved): apply **HOLDING → is_holding_disclosure
  + unresolved**, **REJECT_NO_CALL → is_weak_basket_call**, **reported_speech →
  is_reported_speech**; direction-corrections excluded (avoid scored-outcome churn).

## Results (cumulative, final)
- **Judged: 3,515 / 3,703 suspects** (188 UNHEALABLE — no transcript, left untouched/counted).
- **Verdicts:** HOLDING 21 · NO_CALL 228 · REPORTED 95 · keep 3,171.
- **Flags applied: 344** (21 + 228 + 95), all id-pinned, idempotent, flag-not-delete,
  `[pre_remediation]` preserved. DB-verified 21/21 + 228/228 + 95/95.

### The headline finding
**All 344 flags came from wave 0** — the 1,321 suspects whose transcripts were
already cached *from prior remediation audits* (accountability pass, recent-audit),
which are **selection-biased toward problem content** (26% flag rate). The
**2,194 freshly-fetched suspects judged 0 flags.** Verified real (not a bug):
the judge ran cleanly (synchronous re-judge of equity post-wave-0 keeps: 0/8 and
0/12 flips), and the fresh batches are dominated by genuine directional calls.
This confirms the [[project_yt_recent_audit_2026_06_15]] finding: **unbiased
YouTube extraction quality is high (~95%+ clean)**; the guards correctly flag few
on an average slice.

## Eval-gate (protect real calls) — PASS
~26 flags hand-checked across waves (smoke 7 + wave-0 13 + final 6): all defensible
— passive holdings ("I own/plan to hold X"), past recaps, macro/valuation
commentary, enumerated examples, third-party news relays, and a caught wrong-ticker
(PANW quote was about Newmont). **No committed "buy/target" call hidden.** Verdicts
match the shipped forward guard's behavior (we applied it unchanged). `refresh_all_forecaster_stats` run on the worker.

## Gotchas
- Long-lived DB connection over the multi-hour public-proxy run got reset
  (psycopg2 SSL-closed crash at teardown). Fixed: the judge closes the connection
  right after warming the cached alias/name maps (guards only read the warm cache).
- `pgrep -f preguard_cohort_judge` self-matches the launching command — verify
  liveness by verdicts-file mtime, not pgrep alone.

## Safe to restart? YES
Guards unchanged (no aggressiveness change); only reversible hide-flags set on
historical rows (flag-not-delete). When the classifier resumes, these same guards
run at insert for the first time in prod. The 188 unhealable rows remain only if
their transcripts ever become fetchable.

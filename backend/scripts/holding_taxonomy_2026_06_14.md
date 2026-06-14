# Holdings taxonomy — passive holds off-scoreboard + hidden (2026-06-14)

Decision (Nimrod): passive holding statements ("happy to keep holding", "my biggest position", "I own
it long term") are NOT scored calls — taken off the accuracy board AND hidden from all user surfaces.
Active recommendations ("buy here", "I'm adding", target $X) stay as scored calls. No holdings UI built.

## Hide mechanism
New column **`is_holding_disclosure`** (migration `0022_is_holding_disclosure.sql`; RUN_STARTUP_DDL=false
so applied manually as owner), added to `hedged_filter_sql` behind **`HIDE_HOLDING_DISCLOSURES`** (default
on) — the single visibility chokepoint hides it on every surface. Off-scoreboard via `outcome='unresolved'`
(independent of the flag, so accuracy drops immediately). Mirrors is_weak_basket_call / is_reported_speech.

## Candidates + judge
Passive holds are a SPOKEN-source phenomenon. Broadened hold regex over visible-scored ticker_call,
NO active-buy pre-filter (LLM splits). Initial broadened match was 30,736 — but 30,533 were `article`
rows matching "Downgraded to **Hold**" analyst ratings (genuine neutrals, NOT holdings) → correctly
excluded by scoping to spoken sources. Real candidates: **203** (200 youtube + 3 x). Per-row claude -p
Sonnet judge: **96 HOLDING · 100 CALL · 7 OTHER** (CALL/OTHER untouched).

## Eval-gate (protect real buy-recs)
Fixture of clean forward-active buy-recs (gold=CALL). First fixture showed 11% "false-reclass" but all 5
were holding-flavored rows my regex wrongly included ("as of right now I consider Apple a hold") — the
judge was RIGHT. Cleaned fixture (forward-active only, exclude hold/own/bought): **false-reclass 1/45 =
2.2%**, and the 1 (WM) is a generic dividend-strategy/ownership row, not a sharp buy-rec. True
false-reclass on real recommendations ≈ 0 → **gate passed**.

## Backfill (id-pinned, idempotent, flag-not-delete)
96 HOLDING rows → `is_holding_disclosure=TRUE` + `outcome='unresolved'`, `[pre_remediation]` saved,
marker `holding_reclass_2026_06_14`. Verified: 0/96 still visible under the new bundle; 0/96 still
scored; 50/50 CALL-judged rows untouched & still scored. 18 forecasters moved (small; e.g. Andrei Jikh
−2.1 as scored holdings drop out).

## Forward guard
`representativeness_guard.holding_decide` hooked into `insert_youtube_prediction` (runs first,
short-circuits the conditional/rep guards). Cost-gated to hold-suspects (regex); one verify; HOLDING →
insert `is_holding_disclosure=TRUE` + `outcome='unresolved'` (never a bullish call). Default-on behind
**`ENABLE_HOLDING_GUARD`**; fail-open (keep-as-call on any error). No HAIKU_SYSTEM edits.

## Safe to restart?
Yes. Backfill is flag-not-delete/reversible ([pre_remediation]); forward guard is fail-open and
eval-gated (≈0 false-reclass of real recs); accuracy impact is immediate via outcome=unresolved; surface
hiding activates on the API/worker redeploy this commit triggers. Kill switches: HIDE_HOLDING_DISCLOSURES
(visibility), ENABLE_HOLDING_GUARD (forward). No holdings UI built (surfaced later).

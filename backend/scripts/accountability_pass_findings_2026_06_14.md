# Quote-accountability population pass — youtube_haiku_v1 (+X) (2026-06-14/15)

Applies the n=200-validated trichotomy (audit 2c7bd35) cohort-wide: per visible-scored youtube/x
ticker_call, the displayed quote is SELF_ACCOUNTABLE (keep) / REQUOTE_FIXABLE (re-quote to the claim
sentence) / NOT_ACCOUNTABLE (hide, off-board). Transcript-backed (±90s window).

## Mechanism
New flag `is_no_claim` (migration 0023, applied to prod) bundled into hedged_filter_sql behind
HIDE_NO_CLAIM (default on); NOT_ACCOUNTABLE rows also set outcome='unresolved'. REQUOTE is evidence-only
(source_verbatim_quote + resolved source_timestamp_seconds; outcome/direction/return untouched).
flag-not-delete, idempotent, [pre_remediation] saved on hides. No UI.

## Eval-gate (protect real calls) — passed
Ran the accountability judge over the n=200 labeled rows. First pass had one true false-hide
("I'm very bullish on Visa" wrongly hidden) → tightened: a bare directional STANCE (no target) counts as
SELF. Re-eval: raw 5% disagreement vs the single-draw gold, but HAND-CHECKING every flip showed ~0 true
false-hides (the disagreements are the new judge correctly catching no-claim rows the lenient gold marked
SELF). Cohort NOT spot-check (6 rows) confirmed at scale: all genuine no-claim (Berkshire-holding reports,
guidance recaps, "we don't know how it'll go") — zero real calls hidden.

## FINAL (cohort 3,943 = 3,818 yt + 125 x) — completed across 3 waves + full fetch
- Transcripts: 606 pre-cached + ~840 fetched this campaign (Webshare, 4s pace, persisted, checkpointed).
- Fetch COMPLETE: 1,266 ok / 85 transient-failed of 1,351; **judged 3,607 / 3,943** → **SELF 2,674 (74%) · NOT_ACCOUNTABLE 635 (18%) · REQUOTE_FIXABLE 298 (8%)**.
- **Applied: 298 requoted** (all timestamps resolved; evidence-only, outcome untouched) + **635 hidden** (is_no_claim + unresolved).
- Verified: 0/635 visible, 0/635 scored, 298/298 requoted-with-outcome-untouched, SELF untouched.
- 71 forecasters moved (21 up / 41 down — hiding no-claim "hit" rows pulls some down; Simply Wall St
  +22 as its no-claim misses drop; several 1/1→0 below leaderboard floors).

## REMAINDER
**336 rows unjudged** (genuinely unhealable: 85 transient-failed videos + 106 known-unrecoverable; no transcript exists to judge accountability — left untouched, scored as-is). Originally 804 after wave 2; the completed fetch closed 468 of them in wave 3.

(historical note) **804 rows** — their videos weren't fetched yet (the Webshare campaign slowed under
rate-limiting; ~513 videos still pending + 106 known-unrecoverable). Re-running the fetch + the
checkpointed cohort judge (skips already-judged) + this apply (idempotent) finishes them. The fetcher
was left running; a follow-up run judges + applies the remainder. No data lost — fully resumable.

## Safe to restart?
Yes. All changes flag-not-delete/reversible ([pre_remediation]); requotes are evidence-only; the
eval-gate (hand-checked ~0 false-hide) protected real calls; accuracy impact immediate via unresolved;
surface-hiding activates on the API/worker redeploy this commit triggers. Kill switch HIDE_NO_CLAIM.

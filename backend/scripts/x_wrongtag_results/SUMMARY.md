# X wrong-ticker guard + backfill — 2026-06-15 (Option B)

Scope: extend the wrong-ticker correction to the X path **deterministically**
(no 2nd LLM call, no X_ADDENDUM change). The X_ADDENDUM v3 no-claim change was
DEFERRED to a separate eval-gated ship. X stays loose-by-design (crypto passes;
no reported-speech / min-length / equity-only filters added).

## (1) Forward guard — `x_scraper._cashtag_mismatch` (LIVE, kill switch `X_CASHTAG_GUARD`)

Flags `is_ambiguous_symbol=TRUE` at insert (hidden via `hedged_filter_sql`,
**not** dropped) when a tweet carries explicit cashtags but the stored ticker is
referenced **neither as a cashtag nor by company name/alias**. Precision-first
exemptions: crypto tickers, no-cashtag tweets (bare-symbol / sector calls),
symbol/base cashtag match (case-insensitive), and company-name/alias presence
(via `representativeness_guard.ticker_terms` over `company_name_aliases` +
`ticker_sectors.company_name`). Fail-open throughout.

## (2) Backfill — scored X cohort

- Scored X rows: **115** (20 crypto, untouched).
- Deterministic "stored ticker not among cashtags": **1** (323165, AMZN) — but
  the full tweet raises "Amazon"'s PT by name ($GOOGL/$META cashtagged), so it
  is a **real name-referenced call**. The final guard exempts it.
- Multi-cashtag scored rows LLM-judged (Sonnet, `x_wrongtag_judge_2026_06_15.py`):
  **25 → all SUBJECT** (each stored ticker genuinely carries its own call).
- **Result: 0 wrong-ticker rows to flag. No DB writes, no stats refresh.**

## Eval-gate (protect real X calls) — PASS

Forward guard run over the last **1,412** X rows (scored + pending):
- **Flagged: 1 (0.07%)** — id 630105 (MU, *pending*), whose visible tweet
  ("I still feel bullish… $META") does not name Micron/MU as the subject;
  defensible hide, reversible via kill switch. Left untouched (pending, out of
  the scored-backfill scope, unverifiable without a tweet refetch).
- **0 false-hides** on the 25 hand-judged real multi-cashtag calls.
- All **308** crypto rows in the sample exempt.
- Synthetic hallucinations (ticker absent as cashtag *and* name) correctly flag.

## Deferred
- X_ADDENDUM v3 no-claim / claim-subject change → separate eval-gated ship
  (touches the sacred X classifier gate: ≥95% recall, ≥90% agreement re-run).

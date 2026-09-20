# Testing & Validation Logic

This document details the data-validation approach behind Eidolum's Seven Pillars ruleset (see main [README](../README.md)), written from a QA/test-design perspective: precise acceptance criteria, deterministic pass/fail checks, and edge-case handling for a dataset with no manual moderation fallback.

## Validation Pipeline Overview

Eidolum enforces prediction quality with a 3-stage approach:

1. **L1 - Ingestion filter**: runs at scrape time, rejecting malformed entries before they are even queued for validation.
2. **L2 - Rule validator**: applies the Seven Pillars criteria (see below) as deterministic assertions against every incoming prediction.
3. **L3 - Periodic re-validation**: an hourly job re-checks stored predictions against the same ruleset, catching drift or edge cases the initial pass missed.

## The Seven Pillars as Test Assertions

Each pillar is implemented as an independent, composable check. A prediction is accepted only if every check returns true - functionally identical to a test suite requiring all assertions to pass.

| # | Rule | What It Rejects | Test-Style Assertion |
|---|------|------------------|----------------------|
| 1 | Specific ticker or sector ETF | Generic "tech stocks" commentary | `assert ticker in valid_symbols` |
| 2 | Identifiable direction | Ambiguous sentiment with no call | `assert direction in {"bullish","bearish","buy","sell"}` |
| 3 | Specific asset | Baskets or "the market" | `assert is_single_instrument(asset)` |
| 4 | Verifiable source | Unsourced claims | `assert source_url or tweet_id is not None` |
| 5 | Bounded timeframe | Open-ended predictions | `assert eval_window in ALLOWED_WINDOWS` |
| 6 | Authoritative date | User-supplied/parsed date strings | `assert date_source == "metadata"` |
| 7 | Immutable record | Post-hoc edits | `assert not record.is_mutable` |

## Edge Cases Handled

Building this ruleset against real-world, adversarial input surfaced edge cases that a naive implementation would miss:

- **Forecaster alias collisions**: the same institution appears under multiple names (e.g., "BofA" = "Bank of America" = "BofA Securities"). Aliases are mapped to one canonical identity before scoring, preventing accuracy from being split or duplicated across name variants.
- **"Maintains" ratings without a price-target change**: a rating labeled "maintains" is only counted as a valid new prediction if the price target actually changed - otherwise it is treated as noise, not a fresh call.
- **Sentiment without measurable action**: statements like "UBS wary of NKE" are rejected outright - they carry no specific, checkable claim (Rule 2 failure).
- **Platform vs. forecaster attribution**: content sourced from Yahoo Finance, CNBC, YouTube, or X is never itself the forecaster - attribution is always routed to the underlying analyst or firm, not the distribution platform.
- **Past-tense reports**: retrospective summaries of what already happened are rejected, since they make no forward-looking, evaluable claim.

## Why This Matters

With 577K+ predictions processed and zero manual review, the validation layer is the only thing standing between a trustworthy public leaderboard and a leaderboard full of noise. Every rule above had to be specified precisely enough to run unattended, which meant thinking through failure modes the way a test engineer would: what's the malicious input, what's the ambiguous input, and what happens when the data is technically well-formed but semantically wrong.


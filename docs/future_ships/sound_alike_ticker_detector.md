# Future Ship: Sound-Alike Ticker Detector

**Status:** draft — audit findings captured 2026-04-19, code not yet written.

## Problem

The Haiku classifier sometimes picks the wrong ticker when two publicly traded companies have similar tickers or similar names. In the eyeball-sampled MIS pile these cases were common:

| id | Haiku tag | speaker meant | confusion |
|---:|---|---|---|
| 610419 | `BMI` (Badger Meter) | `BitMine` | "BMI" ≈ first 3 letters of "BitMine" |
| 610861 | `VTR` (Ventas) | `VICI Properties` | VTR / VICI are both REITs, speaker said "Vichi" |
| 611396 | `WYN` (Wyndham) | `WYNN` (Wynn Resorts) | WYN vs WYNN — Haiku dropped the trailing N |
| 611870 | `FSRV` (Finserv Acq Corp) | `FI` (Fiserv) | Fiserv → FSRV via fuzzy company name |

These aren't topic drift (the speaker is talking about A, Haiku extracts the quote, but Haiku can't distinguish A from B when the ticker strings overlap). A mechanical detector would catch most of them.

## Rule

For each Haiku-tagged prediction, compute:

1. **Company name presence in the quote** — does `ticker_sectors.company_name` for the tagged ticker appear (case-insensitive, fuzzy-match ≥ 0.80) anywhere in the quote?
   - If yes → accept, no flag.
   - If no, continue to step 2.

2. **Candidate detection** — for every ticker in `ticker_sectors`, check whether the company_name of that OTHER ticker appears in the quote (fuzzy-match ≥ 0.85). Collect candidates.

3. **Adjudicate:**
   - 0 candidates → not a sound-alike; leave for a different pipeline (topic drift / semantic) to handle.
   - 1 candidate `T'` with high confidence → flag as `RETAG_CANDIDATE(ticker → T')`.
   - >1 candidates → flag as `AMBIGUOUS_RETAG`, write to review table.

Fuzzy matching is via `rapidfuzz.fuzz.partial_ratio` on the company_name; threshold tuned on the sample-set above.

## Sample rows the detector should catch

All four from commit `c60d36e`'s eyeball sample:

- **id=610419 BMI → BitMine**: speaker says "BitMine" repeatedly; ticker_sectors has an entry for BitMine (BMNR) that fuzzy-matches to 95+.
- **id=610861 VTR → VICI**: speaker says "vichi" which fuzzy-matches VICI Properties Inc (VICI) at ~90.
- **id=611396 WYN → WYNN**: speaker says "Win Resorts" which fuzzy-matches "Wynn Resorts, Limited" at ~90.
- **id=611870 FSRV → FI**: speaker says "Fiserv" which is an exact substring match to "Fiserv, Inc." (FI).

## Edge cases

- **Speaker uses an abbreviation that is ALSO the tagged ticker.** Example: speaker says "GE" while discussing General Electric — both the ticker symbol and the natural abbreviation collide. Detector should accept without flag because step-1 company-name check succeeds: "General Electric" also tends to be present.
- **Speaker says the company name without ever saying the ticker.** Fine — step 1 matches, no flag.
- **ETF name collisions.** `BITO` vs `BTC` vs `IBIT` all mean "Bitcoin exposure" to a speaker. This is better handled by the crypto-equity collision sweep (separate doc).
- **Penny stocks / OTC tickers with near-duplicate names.** Many such pairs exist (`FSRV` vs `FI`, both related to Fiserv). The detector must consider the candidate's market-cap / exchange listing to prefer the primary listing.

## Action when flagged

Three output states, same policy framework as the Sonnet-v2 RETAG logic (commit `8ab67db`):

1. **High-confidence single candidate** → queue a `RETAG` UPDATE (ticker swap). Log to `audit/sound_alike_retag_log_<date>.md`.
2. **High-confidence candidate same as Sonnet-v2 MIS verdict** → promote Sonnet's verdict from MIS to RETAG retroactively; the detector reuses Sonnet's `suggested_ticker` if present.
3. **Ambiguous / low-confidence** → write to `prediction_review` table with `reason='sound_alike_ambiguous'`; keep visible but flag in the admin UI.

## Cost

Mechanical — no LLM calls. One sweep over predictions joined to ticker_sectors; per-row work is O(tickers × fuzz_op) which is ~10k × 300µs ≈ 3s. Whole run in minutes even against the 560k-row predictions table.

## Expected haul

From the eyeball-sample rate (4 of 15 = ~27% of the non-crypto MIS pile): running against the 132 remaining MIS rows after the crypto-collision sweep would likely recover ~35 additional rows as RETAGs, shrinking the true-MIS residual further.

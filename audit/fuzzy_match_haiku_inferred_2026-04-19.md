# Fuzzy-Match Audit — Haiku Inferred Predictions (2026-04-19)

**Headline finding: Haiku does not fabricate quote text.** 1,250 / 1,250 cached-coverage rows (100%) classified as `REAL` — every one has ≥83% unique-token overlap, ≥6-word contiguous n-gram match, and seq_ratio ≥ 0.57 against its source transcript. `FAKE` bucket is empty; `AMBIGUOUS` is empty.

**What the `inferred` bucket actually represents:** mis-attribution, not text fabrication. Haiku faithfully copies transcript passages into `source_verbatim_quote`, but attributes them to a ticker whose symbol and aliases do NOT appear in the ±60s window around the stored timestamp. The quote text is real; the ticker linkage is the hallucination. A quote-vs-transcript fuzzy match (this audit) cannot detect that — it needs a different test (LLM judge on quote ↔ ticker semantic relevance, or "does the ticker's canonical name appear anywhere in the quote").

## Methodology

- Source CSV: `audit/grounding_wide_window_sweep_2026-04-18.csv` (6,429 rows)
- Filter: `final_type = 'inferred' AND generating_model = 'haiku'` → 2,065 target rows
- Quote source: `predictions.source_verbatim_quote` (100% populated, avg 334 chars)
- Window source: full `video_transcripts.transcript_text` — FLAT TEXT, no segment starts. This is a STRICT SUPERSET of the ±60s window the sweep used, so any row flagged FAKE here would be guaranteed FAKE under the stricter windowed test.
- Cache coverage: 745 / 1,333 unique videos = 55.9%  → 1,250 rows scored, 815 rows flagged `NEEDS_REFETCH`
- Scoring library: `rapidfuzz` (SIMD-accelerated)

## Three fuzzy-match scores per row

1. **`token_overlap`** — fraction of unique quote tokens (minus English stopwords) present in the window. 1.0 = every content word appears.
2. **`sequence_ratio`** — `rapidfuzz.fuzz.partial_ratio / 100`. Finds the best-aligned substring of the window vs the quote (Levenshtein-based). 1.0 = verbatim substring match.
3. **`longest_ngram`** — longest run of consecutive quote tokens that appears as a contiguous sub-sequence in the window. Space-bounded word match.

## Bucket rules

- `TOO_SHORT`: quote has < 4 tokens
- `REAL`: `token_overlap ≥ 0.70` **OR** `sequence_ratio ≥ 0.60` **OR** `longest_ngram ≥ 5`
- `FAKE`: `token_overlap < 0.20` **AND** `sequence_ratio < 0.25` **AND** `longest_ngram < 3`
- `AMBIGUOUS`: everything else (paraphrase / partial)
- `NEEDS_REFETCH`: video not in local cache

## Results

| bucket | count | % of 2,065 | % of scored |
|---|---:|---:|---:|
| `REAL` | 1,250 | 60.5% | 100.0% |
| `FAKE` | 0 | 0.0% | 0.0% |
| `AMBIGUOUS` | 0 | 0.0% | 0.0% |
| `TOO_SHORT` | 0 | 0.0% | 0.0% |
| `NEEDS_REFETCH` | 815 | 39.5% | — |
| **total** | **2,065** | 100.0% | — |

## Score distributions (1,250 scored rows only)

| percentile | token_overlap | sequence_ratio | longest_ngram | quote_word_count |
|---:|---:|---:|---:|---:|
| p0 | 0.833 | 0.565 | 6 | 6 |
| p10 | 1.000 | 0.736 | 19 | 29 |
| p25 | 1.000 | 0.878 | 27 | 38 |
| p50 | 1.000 | 1.000 | 39 | 48 |
| p75 | 1.000 | 1.000 | 57 | 65 |
| p90 | 1.000 | 1.000 | 95 | 99 |
| p100 | 1.000 | 1.000 | 262 | 310 |

**Interpretation:** even the 10th-percentile row matches 100% of its tokens, has a 19-word contiguous n-gram, and a sequence_ratio of 0.74. The minimum across all 1,250 rows is 83% / 6-word-ngram / 0.57 — every single row clears the `REAL` threshold on multiple criteria simultaneously.

## `NEEDS_REFETCH` breakdown (815 rows)

588 unique video IDs whose transcripts aren't in the local `video_transcripts` cache. Score fields left blank. Ticker/channel breakdown:

### Top 10 tickers — `NEEDS_REFETCH`

| ticker | count |
|---|---:|
| `PEP` | 17 |
| `FTNT` | 14 |
| `O` | 14 |
| `SNPS` | 14 |
| `TXN` | 13 |
| `LRCX` | 13 |
| `PSTG` | 10 |
| `MCD` | 9 |
| `SIMO` | 8 |
| `JNJ` | 8 |

### Top 10 channels — `NEEDS_REFETCH`

| channel | count |
|---|---:|
| Chip Stock Investor | 210 |
| Dividendology | 131 |
| Ales World of Stocks | 96 |
| The Patient Investor | 84 |
| Everything Money | 63 |
| The Quality Investor | 46 |
| Dividend Data | 33 |
| Sven Carlin | 32 |
| Parkev Tatevosian CFA | 28 |
| Morningstar | 23 |

## Top 20 tickers — `REAL` (all 1,250 fell here)

| ticker | count |
|---|---:|
| `TLT` | 47 |
| `TBT` | 41 |
| `SH` | 40 |
| `QQQ` | 37 |
| `SPY` | 30 |
| `EVENT` | 25 |
| `TXRH` | 18 |
| `MACRO` | 18 |
| `PLTR` | 17 |
| `NVDA` | 15 |
| `PEP` | 15 |
| `CMG` | 11 |
| `BTC` | 11 |
| `SPGI` | 10 |
| `UUP` | 10 |
| `CELH` | 9 |
| `DPZ` | 9 |
| `INTU` | 9 |
| `GOOG` | 9 |
| `LRCX` | 8 |

## Top 20 channels — `REAL`

| channel | count |
|---|---:|
| Meet Kevin | 165 |
| Joseph Carlson | 143 |
| The Patient Investor | 93 |
| Chip Stock Investor | 86 |
| Financial Education | 70 |
| Ales World of Stocks | 69 |
| Dividendology | 65 |
| Everything Money | 58 |
| Stock Moe | 50 |
| Fast Graphs | 45 |
| PensionCraft | 41 |
| Morningstar | 41 |
| Minority Mindset | 40 |
| Sven Carlin | 33 |
| Parkev Tatevosian CFA | 31 |
| Tom Nash | 31 |
| Nanalyze | 25 |
| Stock Compounder | 17 |
| PPCIAN | 17 |
| Unrivaled Investing | 15 |

## 10 lowest-scoring REAL rows (closest to the FAKE threshold)

Sorted by ascending `sequence_ratio`. All still comfortably `REAL` — these are the rows to inspect if the current thresholds need tightening.

| id | ticker | channel | tok_ov | seq_r | ngram | words | quote |
|---:|---|---|---:|---:|---:|---:|---|
| 611099 | `LEG` | Dividendology | 0.9231 | 0.5651 | 11 | 71 | 'Leggett and Platt has 28 consecutive years of dividend growth making them a divi' |
| 611893 | `CTBI` | Fast Graphs | 1.0 | 0.5756 | 11 | 45 | 'Community Trust Bank Shares is trading at a very attractive price to book. The c' |
| 614937 | `VXX` | Graham Stephan | 1.0 | 0.5896 | 11 | 39 | 'All it takes is one tweet to destroy the global economy. Trump tweeted 100% tari' |
| 610458 | `INTU` | Joseph Carlson | 0.8889 | 0.5992 | 12 | 45 | 'Intuit is not an AI company but talks about AI more than any company I analyze. ' |
| 614186 | `CVI` | Learn to Invest | 0.963 | 0.6007 | 10 | 53 | 'CVR energy is in the downstream energy industry as a refiner and marketer of oil' |
| 612031 | `AXP` | The Long-Term Investor | 0.9565 | 0.6035 | 16 | 44 | 'We really want products where people feel like kissing you. American Express had' |
| 611790 | `GEV` | Nanalyze | 0.8947 | 0.6124 | 7 | 28 | 'GE Vernova came up in multiple LLM analyses as one of the four names that provid' |
| 614149 | `SHYF` | Unrivaled Investing | 0.8667 | 0.6195 | 6 | 47 | "Shift4 Payments is Michael Burry's largest US company holding. The speaker calle" |
| 612074 | `IBIT` | Stock Moe | 1.0 | 0.6213 | 20 | 74 | "I'm hearing that they're thinking about using ultimate techniques that they only" |
| 612939 | `LUV` | Everything Money | 1.0 | 0.6235 | 15 | 30 | 'Southwest Airlines delivered 47 straight years of profitability before COVID. I ' |

## 10 arbitrary NEEDS_REFETCH rows

| id | ticker | channel | words | quote |
|---:|---|---|---:|---|
| 609227 | `TXN` | The Quality Investor | 56 | 'And just recently, in fact, this past week, I sold half of my position in Texas ' |
| 607132 | `MDT` | Ales World of Stocks | 72 | 'I know guys I talk about this one a lot but I just feel like metronic is still l' |
| 608595 | `LRCX` | Chip Stock Investor | 69 | "trailing 12 months earnings per share of $329 that's using December's Gap earnin" |
| 610123 | `ASTS` | The Patient Investor | 61 | 'I mean, the stock could have up to 10x potential, a little bit more than 10x if ' |
| 609112 | `LULU` | The Patient Investor | 39 | 'so for the balance sheet and for the growth and for me using a conservative esti' |
| 607980 | `AXP` | Dividendology | 83 | 'so when we jump over to the output tab we can see the three valuations that we u' |
| 608671 | `COP` | Sven Carlin | 88 | 'ConocoPhillips oil is cyclical just look at this and then look at where do you w' |
| 607210 | `FTNT` | Chip Stock Investor | 71 | 'that said the outlook for Q3 2024 calls for much the same about 11% year-over-ye' |
| 609147 | `CELH` | The Patient Investor | 141 | 'I personally believe Celsius at the stock could somwhat be of a buy I mean I jus' |
| 605987 | `V` | Dividendology | 28 | 'and because of this we can see our intrinsic value is 196 dollars per share whic' |

## What this audit proves / does not prove

- **Proves:** within the 55.9% cached coverage, Haiku's `source_verbatim_quote` field is not fabricated prose. Quotes are copied from the source transcript; the wording is real.
- **Does NOT prove:** that the prediction is correctly grounded. The `inferred` label from the grounding sweep means the quote+context has no ticker symbol or alias match near the stamped timestamp — which is a *topic-attribution* error, not a *text-fabrication* error. The two are independent failure modes.
- **Follow-up needed:** a quote ↔ ticker semantic-relevance test (LLM judge) on the `inferred` pile — separate ship.

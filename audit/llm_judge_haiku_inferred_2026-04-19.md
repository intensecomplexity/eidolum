# LLM-Judge Attribution Audit — 2026-04-19

**Scope:** 1,250 Haiku-inferred predictions from `audit/fuzzy_match_haiku_inferred_2026-04-19.csv` (REAL bucket — quotes verified as extractive). Sonnet 4.6 judged each `(quote, ticker, ±600-char transcript context)` triple: is the quote actually talking about this ticker, or is it a mis-attribution (real text, wrong ticker)?

- Judge model: `claude-sonnet-4-6`
- Temperature: `0` (deterministic)
- Window: ±600 chars around the quote's char offset in the transcript
- Read-only: no DB writes. No predictions table touched.
- Total cost: **$3.8444** (840,412 input + 88,210 output tokens)
- Pricing: Sonnet 4 family $3/M input + $15/M output

## Verdict counts

| verdict | count | % |
|---|---:|---:|
| `REAL_ATTRIBUTION` | 813 | 65.0% |
| `MIS_ATTRIBUTION` | 266 | 21.3% |
| `UNCERTAIN` | 171 | 13.7% |
| **total** | **1,250** | 100.0% |

**Headline:** of the 1,250 Haiku predictions the grounding sweep flagged as `inferred` (no ticker/alias match in the ±60s window), Sonnet confirms **266 (21.3%) are mis-attributions** (real transcript text but wrong ticker tag) and **813 (65.0%) are legitimate** (quote genuinely about the ticker — ticker/alias is in the quote or nearby context, just not matched by the grounding-sweep's word-boundary check). 171 (13.7%) are ambiguous.

## Confidence distributions

| verdict | n | mean | median | p10 | p90 |
|---|---:|---:|---:|---:|---:|
| `REAL_ATTRIBUTION` | 813 | 0.95 | 0.98 | 0.85 | 0.99 |
| `MIS_ATTRIBUTION` | 266 | 0.91 | 0.9 | 0.85 | 0.99 |
| `UNCERTAIN` | 171 | 0.54 | 0.55 | 0.5 | 0.55 |

## Top 15 tickers — MIS_ATTRIBUTION count

| ticker | mis | total judged | mis rate |
|---|---:|---:|---:|
| `SH` | 34 | 40 | 85% |
| `EVENT` | 25 | 25 | 100% |
| `TLT` | 9 | 47 | 19% |
| `TBT` | 9 | 41 | 22% |
| `SPY` | 7 | 30 | 23% |
| `UUP` | 7 | 10 | 70% |
| `SOL` | 6 | 6 | 100% |
| `VTR` | 5 | 6 | 83% |
| `QQQ` | 5 | 37 | 14% |
| `GLD` | 5 | 7 | 71% |
| `INTC` | 5 | 6 | 83% |
| `NVDA` | 5 | 15 | 33% |
| `HYG` | 4 | 4 | 100% |
| `VCI` | 3 | 3 | 100% |
| `TIP` | 3 | 5 | 60% |

## Tickers with ≥50% mis-attribution rate (min 5 judgements)

These are tickers where the grounding-sweep's inferred bucket is dominated by real Haiku mis-attributions — candidates for either quarantine or deeper review.

| ticker | mis rate | mis / total |
|---|---:|---:|
| `EVENT` | 100% | 25 / 25 |
| `SOL` | 100% | 6 / 6 |
| `SH` | 85% | 34 / 40 |
| `VTR` | 83% | 5 / 6 |
| `INTC` | 83% | 5 / 6 |
| `GLD` | 71% | 5 / 7 |
| `UUP` | 70% | 7 / 10 |
| `TIP` | 60% | 3 / 5 |
| `AAPL` | 60% | 3 / 5 |

## Top 15 channels — MIS_ATTRIBUTION count

| channel | count |
|---|---:|
| Meet Kevin | 52 |
| Joseph Carlson | 33 |
| PensionCraft | 22 |
| Minority Mindset | 17 |
| The Patient Investor | 16 |
| Stock Moe | 16 |
| Financial Education | 13 |
| Chip Stock Investor | 12 |
| Nanalyze | 9 |
| Graham Stephan | 9 |
| Fast Graphs | 8 |
| Dividendology | 6 |
| Sven Carlin | 6 |
| Stock Compounder | 6 |
| Everything Money | 5 |

## Common patterns in mis-attribution reasons

Content words Sonnet cites most often when calling MIS_ATTRIBUTION (top 25 after trivial stopword removal):

| word | count |
|---|---:|
| `mention` | 143 |
| `context` | 113 |
| `company` | 98 |
| `surrounding` | 75 |
| `specific` | 73 |
| `market` | 72 |
| `general` | 52 |
| `products` | 44 |
| `without` | 41 |
| `proshares` | 41 |
| `making` | 40 |
| `broadly` | 40 |
| `macroeconomic` | 37 |
| `short` | 34 |
| `broad` | 31 |
| `stock` | 31 |
| `event` | 29 |
| `treasury` | 29 |
| `product` | 28 |
| `refers` | 28 |
| `stocks` | 27 |
| `than` | 26 |
| `policy` | 26 |
| `rate` | 26 |
| `rather` | 25 |

## 10 MIS_ATTRIBUTION examples — quote + reason

### 1. id=612335 `SPY` (State Street SPDR S&P 500 ETF Trust) · bullish · Minority Mindset
- confidence: **0.85**
- quote: _Now, again, we're seeing a big shift happening. This shift is not going to slow down in 2026. is going to accelerate. Could we see a bubble bursting? Absolutely. But that doesn't mean that this trend is going to go away._
- reason: **The quote discusses AI trends and potential bubble dynamics without any mention of SPY, the S&P 500 ETF, or broad market indices — it appears to be about AI sector investments specifically.**

### 2. id=606843 `HSBC` (HSBC Holdings PLC) · bullish · The Compounding Investor
- confidence: **0.99**
- quote: _the third company hon which was spun off from GSK in 2022 is relatively unchanged it could perhaps be a takeover Target in the future so I'm happy to hold for the long term_
- reason: **The quote discusses 'hon' (Haleon), a company spun off from GSK in 2022, with no mention of HSBC anywhere in the surrounding context.**

### 3. id=612932 `SH` (—) · bearish · Everything Money
- confidence: **0.85**
- quote: _The market hasn't crashed not because risk disappeared, but because of a mix of future earnings hope, continued liquidity, AI optimism. These forces can delay or soften a downturn, but they don't eliminate the risk._
- reason: **The quote discusses broad market conditions and risks without any mention of SH (ProShares Short S&P500 ETF) by name, ticker, or product description, making it a general market commentary rather than specific to SH.**

### 4. id=608445 `VTR` (Ventas, Inc.) · bullish · Joseph Carlson
- confidence: **0.85**
- quote: _in the real estate category I only have one holding this one has had a bit of a recovery over the past month V has underperformed so far this year but there's reason to be bullish on this stock_
- reason: **The quote refers to a real estate holding abbreviated as 'V' which is ambiguous, but the surrounding context discusses a personal portfolio with companies like Costco, Texas Roadhouse, and Canadian Pacific — there is no explicit mention of Ventas (VTR), and 'V' more likely refers to Visa or another ticker rather than VTR.**

### 5. id=609858 `QQQ` (—) · bearish · The Patient Investor
- confidence: **0.75**
- quote: _but many grow stocks like the quantum AI the sound hound. a and so many others are down 20 30 40 50 even 60% year to date or from their all-time high it's been a disaster it's been really really bad for the gross companies_
- reason: **The quote discusses individual growth stocks (quantum AI, SoundHound) and mentions NASDAQ broadly, but never specifically references QQQ by name or ticker, making this a general market commentary rather than a QQQ-specific prediction.**

### 6. id=608441 `MCO` (Moody's Corporation) · bullish · Joseph Carlson
- confidence: **0.9**
- quote: _Moody's is up 23% and the performance of this portfolio has been strong with every company either flat or moving up into the green every company has been growing their earnings in free cash flow per share_
- reason: **The surrounding context discusses a portfolio of multiple companies (Chipotle, Texas Roadhouse, Canadian Pacific, etc.) and the quote about 'every company either flat or moving up into the green' refers to the entire portfolio, not specifically to MCO/Moody's, and Moody's is not mentioned in the visible transcript context.**

### 7. id=610821 `VCI` (—) · bullish · Joseph Carlson
- confidence: **0.95**
- quote: _Blackstone is Fielding offers for half of its interest in the real estate of the Bellagio Hotel in Las Vegas. I think it's incredibly likely that Vichy is on the phone trying to work out a deal that makes sense for the shareholder. I would give the odds right now around 60 percen…_
- reason: **The extracted quote discusses Blackstone, the Bellagio Hotel, and 'Vichy' (likely Vici Properties, ticker VICI), with no connection to VCI (Valassis Communications/Vericast), and the surrounding transcript context is about Seth Klarman, Microsoft, and bubble markets — not VCI.**

### 8. id=612527 `MSFT` (Microsoft Corporation) · bullish · PensionCraft
- confidence: **0.85**
- quote: _The US is big for a reason. It's really good at growing earnings. If you look at the Magnificent 7, they're just cash generating machines. They've been hugely successful and they're likely to remain successful._
- reason: **The quote discusses the 'Magnificent 7' as a group broadly without specifically mentioning Microsoft, and the surrounding context focuses on index composition and Meta's weighting, making attribution to MSFT specifically unsupported.**

### 9. id=611818 `HYG` (—) · bearish · Nanalyze
- confidence: **0.85**
- quote: _The collapse of two companies, First Brands and Tricolor, they say may signal deeper financial risks. $2 trillion warning, cracks are starting to show in the leveraged loan market, specifically referring to these two firms that recently collapsed._
- reason: **The quote discusses the private credit/leveraged loan market and specific company collapses (First Brands, Tricolor) without mentioning HYG or high-yield bond ETFs specifically, though HYG could be tangentially related as a high-yield instrument.**

### 10. id=611860 `LYV` (Live Nation Entertainment, Inc.) · bullish · Fast Graphs
- confidence: **0.98**
- quote: _This is an experiential real estate investment trust. They own MGM and some of these big the Venetian Resort in Vegas, Caesar's Palace. It's got a very consistent record. This is about as cheap as this real estate investment trust has ever been and a dividend yield over 6%._
- reason: **The quote describes an experiential REIT owning MGM, Venetian Resort, and Caesar's Palace — this is VICI Properties or a similar gaming REIT, not Live Nation Entertainment.**

## 10 UNCERTAIN examples — quote + reason

### 1. id=612350 `TLT` · conf 0.55
- quote: _We know that we're going to see more money spending. We're going to see more money printing. We're going to see lower interest rates in 2026. How come? Well, Jerome Powell, who is the current chairperson at the Federal Reserve Bank, is going to see his term end. President Trump w…_
- reason: **The quote discusses lower interest rates which would benefit TLT (long-term Treasury bond ETF), but the surrounding context focuses broadly on owning assets, mortgage rates, and real estate without specifically mentioning TLT or Treasury bonds.**

### 2. id=612509 `TLT` · conf 0.55
- quote: _I suspect next time the argument for cutting, unless we do see a big spike in energy, which persists, um I expect that that'll um be more likely that we'll see a cut at the next meeting._
- reason: **The quote discusses UK interest rate cuts (likely Bank of England), which would be bullish for UK gilts but not directly for TLT (US Treasury ETF), making the attribution to TLT plausible only if the broader rate-cut narrative is being applied, but no specific mention of TLT, US Treasuries, or iShares is made.**

### 3. id=608408 `IONQ` · conf 0.55
- quote: _and then we'll just add another pick here onto Innovation which entered our top seven chip stock Holdings last year we have high hopes for that one_
- reason: **The quote references an unnamed 'Innovation' stock that entered their top seven chip holdings, which could be IonQ but the company is never explicitly named, making attribution uncertain.**

### 4. id=612776 `TBT` · conf 0.55
- quote: _My bigger concern is rising interest rates because I think that's something that's going to continue and that can heavily damage the economy and of course the stock market even further. The fed has literally told you when they plan to stop raising interest rates it's probably goi…_
- reason: **The quote discusses rising interest rates broadly (which is bullish for TBT, an inverse Treasury ETF) but never explicitly mentions TBT, its underlying assets, or any specific product, making it a general macro commentary that could apply to TBT but isn't directly attributed to it.**

### 5. id=612851 `SH` · conf 0.55
- quote: _if something really breaks in 2023 with all the tightening and everything we have and in my opinion there's a very high probability of this actually happening in my opinion at least investors are going to go back to bonds._
- reason: **The quote discusses investors moving to bonds/treasuries during a crisis, which could relate to SH (ProShares Short S&P500 ETF) as a bearish/safety play, but SH is never mentioned by name, ticker, or product description in the surrounding context.**

### 6. id=611233 `QQQ` · conf 0.5
- quote: _Q still rejecting 600 here, not holding._
- reason: **The quote mentions 'Q still rejecting 600' which could refer to QQQ (which trades around 500-600 range) but 'Q' is ambiguous and could refer to another ticker or index level, and the surrounding context doesn't clarify which instrument is meant.**

### 7. id=611470 `TBT` · conf 0.55
- quote: _Uh 10-year popping huge today. Huge, that's a massive move for the 10-year. In the Treasury market in a one-day span, that's a huge move uh for the 10-year up. This is a no bueno situation._
- reason: **The quote discusses rising 10-year Treasury yields, which directly drives TBT (ProShares UltraShort 20+ Year Treasury ETF) performance, but TBT is not explicitly mentioned by name or ticker in the context, making the attribution inferential rather than direct.**

### 8. id=606496 `ADBE` · conf 0.5
- quote: _so whatever it is but this company is definitely overpriced right now you cannot pay this i will tell you right now_
- reason: **The quote discusses a company with a PE of 58 and current price around $460 (which aligns with Adobe's historical price range), but the company is never explicitly named in the surrounding context, making attribution uncertain.**

### 9. id=606526 `NVDA` · conf 0.5
- quote: _so guys we need to fall by 80 percent i mean it's a big drop but you know what look at their pe if we go back to their pe what was it look at that 88 what's 80 lower it's 17._
- reason: **The transcript discusses a company's PE ratio, free cash flow, market cap, and acquisitions, but never explicitly names NVIDIA or any NVIDIA-specific products, making it impossible to confirm this is about NVDA versus another company.**

### 10. id=612943 `NKE` · conf 0.55
- quote: _I have a low price of 50, high price of 110, middle price of 75. Now guys, they do pay a healthy dividend. This includes the dividend here, so don't go adding the dividend on top of that._
- reason: **The quote discusses price targets and dividends for an unspecified stock, and the surrounding context transitions to Sprouts Farmers Market, making it unclear whether the price targets refer to NKE or another stock being analyzed just before Sprouts.**

## What this audit establishes

- **266 rows (21.3%)** are genuine Haiku hallucinations of a *semantic* kind: real quoted text attributed to a ticker the speaker never referenced. Not quote-text fabrication — which the earlier fuzzy-match audit (commit 7db3894) proved doesn't happen — but topic mis-assignment.
- **813 rows (65.0%)** the grounding-sweep wrongly flagged as inferred — the ticker's actual name / symbol / product / subsidiary IS present somewhere in the local context, just not matched by the word-boundary alias-map check. These are recoverable.
- **171 rows (13.7%)** are genuinely ambiguous (thematic / sector-level discussion with weak ticker linkage).

Every verdict carries a confidence score and a one-sentence reason, so downstream quarantine policy can be threshold-driven (e.g. quarantine MIS with conf ≥ 0.8).

## Files

- `audit/llm_judge_haiku_inferred_2026-04-19.csv` — one row per prediction with verdict, confidence, reason, tokens, cost
- `backend/scripts/llm_judge_haiku_inferred.py` — script (resume-safe, crash-safe, cost-capped)

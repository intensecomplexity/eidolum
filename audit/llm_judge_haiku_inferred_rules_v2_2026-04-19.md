# LLM-Judge Re-audit v2 — Nimrod's Attribution Rules (2026-04-19)

**Scope:** the 437 non-REAL rows from commit c11012e (v1 audit) re-scored by Sonnet 4.6 under rules that explicitly accept thematic / sector / commodity-ETF / implicit / conditional attribution as REAL, not ambiguous. The 813 v1-REAL rows are unchanged (locked in).

- Judge model: `claude-sonnet-4-6`
- Temperature: `0`
- Window: ±600 chars around the quote
- Cost: **$1.9102** (442,815 input + 38,782 output tokens)
- Cap: $10 — well clear

## Shift matrix v1 → v2

| v1 → v2 | REAL_ATTRIBUTION | RETAG | MIS_ATTRIBUTION | row total |
|---|---:|---:|---:|---:|
| **MIS_ATTRIBUTION** | 96 | 14 | 156 | 266 |
| **UNCERTAIN** | 162 | 5 | 4 | 171 |
| **column total** | 258 | 19 | 160 | 437 |

**Read-outs:**
- v1 MIS → v2 REAL: **96** rows rehabilitated (v1 over-flagged as mis when speaker's theme/sector/commodity tag was valid)
- v1 MIS → v2 RETAG: **14** rows where the subject is right but the ticker is too narrow
- v1 MIS → v2 MIS: **156** rows genuinely mis-attributed even under the broader rules
- v1 UNCERT → v2 REAL: **162** rows clarified as real (conditional / thematic / implicit — no longer ambiguous)
- v1 UNCERT → v2 MIS: **4** rows the broader rules still can't justify
- v1 UNCERT → v2 RETAG: **5**

## Full population (v1 REAL locked + v2 re-score)

| verdict | count | % of 1,250 |
|---|---:|---:|
| REAL (v1 locked) | 813 | 65.0% |
| REAL (v2 recovered) | 258 | 20.6% |
| **REAL combined** | **1,071** | **85.7%** |
| RETAG | 19 | 1.5% |
| MIS_ATTRIBUTION (remaining) | 160 | 12.8% |
| **total** | **1,250** | 100.0% |

**Headline shift from v1:** the previous audit called **266 MIS + 171 UNCERTAIN = 437 non-REAL** rows suspect. Under Nimrod's rules, those 437 resolve to **258 REAL + 19 RETAG + 160 MIS**. The true-mis-attribution pile shrinks from 266 to **160** — a 40% reduction once thematic/sector/commodity proxies and conditionals are credited as legitimate.

## RETAG suggestions (19 rows)

| current_ticker | suggested_ticker | count |
|---|---|---:|
| `NVDA` | `SMH` | 2 |
| `VCI` | `VNQ` | 1 |
| `MSFT` | `QQQ` | 1 |
| `UNP` | `XLI` | 1 |
| `WYN` | `AWAY` | 1 |
| `QQQ` | `XLC` | 1 |
| `AIR` | `ITA` | 1 |
| `AVB` | `VNQ` | 1 |
| `AAPL` | `QQQ` | 1 |
| `LAND` | `VNQ` | 1 |
| `AMD` | `SMH` | 1 |
| `ONTO` | `SMH` | 1 |
| `GLD` | `SLV` | 1 |
| `AYRWF` | `MSOS` | 1 |
| `CEIX` | `KOL` | 1 |
| `KO` | `XLP` | 1 |
| `AVGO` | `SMH` | 1 |
| `INTC` | `SMH` | 1 |

Most common suggested replacement:

| suggested_ticker | count |
|---|---:|
| `SMH` | 6 |
| `VNQ` | 3 |
| `QQQ` | 2 |
| `XLI` | 1 |
| `AWAY` | 1 |
| `XLC` | 1 |
| `ITA` | 1 |
| `SLV` | 1 |
| `MSOS` | 1 |
| `KOL` | 1 |
| `XLP` | 1 |

## Remaining true-MIS (160 rows)

### Top tickers still flagged MIS

| ticker | count |
|---|---:|
| `EVENT` | 25 |
| `SH` | 12 |
| `UUP` | 6 |
| `SOL` | 6 |
| `TLT` | 5 |
| `INTC` | 5 |
| `SPY` | 3 |
| `GLD` | 3 |
| `NVDA` | 3 |
| `PSTG` | 3 |
| `TIP` | 2 |
| `BYD` | 2 |
| `RR` | 2 |
| `RYM` | 2 |
| `VTR` | 2 |
| `LTC` | 2 |
| `TBT` | 2 |
| `TSLA` | 2 |
| `AAL` | 2 |
| `AAPL` | 2 |

### Top channels still producing MIS

| channel | count |
|---|---:|
| Meet Kevin | 37 |
| Joseph Carlson | 16 |
| The Patient Investor | 12 |
| PensionCraft | 12 |
| Minority Mindset | 11 |
| Stock Moe | 11 |
| Chip Stock Investor | 10 |
| Financial Education | 8 |
| Fast Graphs | 6 |
| Nanalyze | 5 |
| Graham Stephan | 4 |
| The Compounding Investor | 3 |
| Sven Carlin | 3 |
| Dividendology | 3 |
| Stock Compounder | 3 |

## 10 examples — v1 MIS → v2 REAL (rehabilitated)

### 1. id=612932 `SH` · bearish · Everything Money
- v1 → v2: `MIS_ATTRIBUTION` → `REAL_ATTRIBUTION` (conf 0.82)
- quote: _The market hasn't crashed not because risk disappeared, but because of a mix of future earnings hope, continued liquidity, AI optimism. These forces can delay or soften a downturn, but they don't eliminate the risk._
- v2 reason: **SH is an inverse S&P ETF that profits when the market declines, making it a valid thematic proxy for a bearish macro outlook warning of overvaluation, bubble conditions, and elevated downside risk in the broad market.**

### 2. id=608445 `VTR` · bullish · Joseph Carlson
- v1 → v2: `MIS_ATTRIBUTION` → `REAL_ATTRIBUTION` (conf 0.85)
- quote: _in the real estate category I only have one holding this one has had a bit of a recovery over the past month V has underperformed so far this year but there's reason to be bullish on this stock_
- v2 reason: **The speaker references a single real estate holding that has underperformed and is bullish on it; VTR (Ventas) is a REIT that fits the implicit reference to a specific real estate holding being discussed.**

### 3. id=609858 `QQQ` · bearish · The Patient Investor
- v1 → v2: `MIS_ATTRIBUTION` → `REAL_ATTRIBUTION` (conf 0.85)
- quote: _but many grow stocks like the quantum AI the sound hound. a and so many others are down 20 30 40 50 even 60% year to date or from their all-time high it's been a disaster it's been really really bad for the gross companies_
- v2 reason: **The speaker explicitly mentions the NASDAQ being down ~6% YTD and discusses growth stock underperformance, making QQQ (NASDAQ-tracking ETF) a valid thematic/index proxy for the bearish sentiment expressed about growth/tech stocks.**

### 4. id=608441 `MCO` · bullish · Joseph Carlson
- v1 → v2: `MIS_ATTRIBUTION` → `REAL_ATTRIBUTION` (conf 0.92)
- quote: _Moody's is up 23% and the performance of this portfolio has been strong with every company either flat or moving up into the green every company has been growing their earnings in free cash flow per share_
- v2 reason: **The quote explicitly names Moody's as being up 23% and part of a portfolio being reviewed, making this a direct reference to MCO (Moody's Corporation).**

### 5. id=611818 `HYG` · bearish · Nanalyze
- v1 → v2: `MIS_ATTRIBUTION` → `REAL_ATTRIBUTION` (conf 0.85)
- quote: _The collapse of two companies, First Brands and Tricolor, they say may signal deeper financial risks. $2 trillion warning, cracks are starting to show in the leveraged loan market, specifically referring to these two firms that recently col…_
- v2 reason: **HYG is the high-yield corporate bond ETF and serves as a direct proxy for credit market stress/leveraged loan risk, making it a valid thematic/macro ETF attribution for a bearish call on the $2 trillion private credit and leveraged loan market.**

### 6. id=612558 `SH` · bullish · PensionCraft
- v1 → v2: `MIS_ATTRIBUTION` → `REAL_ATTRIBUTION` (conf 0.85)
- quote: _I think there's so much weird coming out of the United States right now that markets cannot absorb it quickly enough maybe some of these tariffs will be good in the long run certainly for the us but I doubt it and I think a lot of people ar…_
- v2 reason: **SH is the Inverse S&P ETF, and the speaker is predicting a market pullback due to tariff uncertainty and weakening economic indicators, which is a bullish thesis for an inverse S&P instrument.**

### 7. id=606471 `DPZ` · bullish · Dividendology
- v1 → v2: `MIS_ATTRIBUTION` → `REAL_ATTRIBUTION` (conf 0.95)
- quote: _again I just added three shares of this to my dividend portfolio low starting dividend yield but a phenomenal history over the past decade of really solid dividend growth I think long term this could be a good play_
- v2 reason: **The speaker explicitly discusses adding shares to their dividend portfolio and references intrinsic value calculations with specific price targets, directly referring to DPZ (Domino's Pizza) as the stock being analyzed before transitioning to JNJ.**

### 8. id=611318 `SH` · bullish · Meet Kevin
- v1 → v2: `MIS_ATTRIBUTION` → `REAL_ATTRIBUTION` (conf 0.85)
- quote: _Consumer spending has only been sustained through a collapse in the savings ratio. Another steep fall in the savings rate is unlikely from these very low levels underpinning what in my view indicates that we are heading for an AI related co…_
- v2 reason: **SH is an inverse S&P ETF, and the quote predicts a consumer crunch and economic downturn, making a bullish SH call a valid conditional/thematic attribution to a bearish macro outlook.**

### 9. id=611817 `SH` · bullish · Nanalyze
- v1 → v2: `MIS_ATTRIBUTION` → `REAL_ATTRIBUTION` (conf 0.85)
- quote: _There's a much more sinister issue lurking in the shadows. It's not as sexy as AI, but it may be the tip of the iceberg that ends up sinking this raging bull market. Today we're going to talk about the $2 trillion private credit market._
- v2 reason: **SH (Inverse S&P ETF) is a valid conditional/thematic proxy for a bearish macro prediction — the speaker is explicitly warning about a systemic risk that could 'sink this raging bull market,' making a bullish SH attribution a reasonable thematic fit for an inverse market position.**

### 10. id=611359 `SPY` · bullish · Financial Education
- v1 → v2: `MIS_ATTRIBUTION` → `REAL_ATTRIBUTION` (conf 0.85)
- quote: _I'm focused on the next decade for the public account. I'm focused on where this portfolio goes between now and 2036. There's going to be so much money to be made the next decade._
- v2 reason: **SPY as the broad S&P 500 ETF is a reasonable proxy for a long-term bullish portfolio growth prediction over the next decade, fitting the macro/broad-market theme ETF pattern.**

## 10 examples — RETAG (quote right, ticker too narrow)

### 1. id=609081 `LAND` → **VNQ** · bullish · Sven Carlin
- v1 → v2: `MIS_ATTRIBUTION` → `RETAG` (conf 0.9)
- quote: _if you're an investor if you want to own RS then you simply buy own the properties get that yield and forget about what happens with the market interest rates yes there are always other opportunities but this is better than being certain to…_
- v2 reason: **The speaker is discussing REITs broadly as a sector/asset class (interest rates, dividend yields, property appreciation), not Gladstone Land Corp specifically, so the sector REIT ETF VNQ is the appropriate ticker rather than the narrow individual stock LAND.**

### 2. id=612552 `AIR` → **ITA** · bullish · PensionCraft
- v1 → v2: `MIS_ATTRIBUTION` → `RETAG` (conf 0.88)
- quote: _if we do get a rearming Europe in order to counter Russia then yeah I mean the profits for these companies are going to be good and I think what worries me about this war in Europe potentially if it does happen is that historically the US h…_
- v2 reason: **The speaker is discussing European defense companies and the broader defense sector rearming theme, not AAR Corp specifically; the appropriate sector ETF for defense is ITA.**

### 3. id=610244 `AVB` → **VNQ** · bullish · The Patient Investor
- v1 → v2: `MIS_ATTRIBUTION` → `RETAG` (conf 0.88)
- quote: _The first one is Jerome Powell's term ending in May 15th of 2026. We're likely gonna have some kind of a hawk or a dovish Fed that's going to be appointed by the president of the United States because they want to lower interest rates and i…_
- v2 reason: **The speaker discusses REITs broadly as a sector catalyst, making the REIT sector ETF (VNQ) the appropriate ticker rather than the individual REIT stock AVB.**

### 4. id=613834 `NVDA` → **SMH** · bullish · The Investor Channel
- v1 → v2: `UNCERTAIN` → `RETAG` (conf 0.88)
- quote: _the big beneficiaries of all of this all of this is going to be the chip makers they are going to see huge flows from Google Microsoft meta and others and the semiconductor index which is still up huge over the past year and year-to-date pr…_
- v2 reason: **The speaker explicitly references 'the semiconductor index' and 'chip makers' as a group, making SMH (semiconductor ETF) the appropriate ticker rather than singling out NVDA specifically.**

### 5. id=612527 `MSFT` → **QQQ** · bullish · PensionCraft
- v1 → v2: `MIS_ATTRIBUTION` → `RETAG` (conf 0.85)
- quote: _The US is big for a reason. It's really good at growing earnings. If you look at the Magnificent 7, they're just cash generating machines. They've been hugely successful and they're likely to remain successful._
- v2 reason: **The speaker is discussing the Magnificent 7 as a group of cash-generating machines, which is a broad tech theme better represented by QQQ than a single-stock attribution to MSFT specifically.**

### 6. id=612115 `GLD` → **SLV** · bearish · Stock Moe
- v1 → v2: `MIS_ATTRIBUTION` → `RETAG` (conf 0.85)
- quote: _My opinion is that the top is in already or will be in in the next seven days. I believe that firmly and I am going to be doing moves based on that. And yes, I was bullish on silver. I believe holding actual silver is the way to go._
- v2 reason: **The speaker is explicitly discussing silver (not gold), predicting its top is in and it will drop, so GLD is a mis-tag for the asset discussed; the correct ETF proxy for silver is SLV.**

### 7. id=611830 `AYRWF` → **MSOS** · bullish · Nanalyze
- v1 → v2: `MIS_ATTRIBUTION` → `RETAG` (conf 0.85)
- quote: _So we want to consider sustainability because until you have federal legalization, these companies need to survive at the minimum, right? And look here, 65% of the market cap in that ETF would consist of three names. So those are names cert…_
- v2 reason: **The speaker is discussing a cannabis ETF and its top constituents by market cap as a group, not specifically attributing a bullish call to AYRWF individually; the appropriate ticker would be a cannabis sector ETF like MSOS rather than a narrow individual cannabis stock.**

### 8. id=614581 `AVGO` → **SMH** · bearish · Meet Kevin
- v1 → v2: `MIS_ATTRIBUTION` → `RETAG` (conf 0.85)
- quote: _I said in the alpha report this morning that I think that you're seeing a fade away from the chip sector from hardware. I expect profit taking in the physical chip exposure to continue and then parenthetically I wrote ago Eric uh Ericle Ora…_
- v2 reason: **The speaker discusses fading the chip/hardware sector broadly (mentioning AMD, Nvidia, Oracle, etc.) rather than singling out AVGO specifically, making a semiconductor sector ETF like SMH more appropriate than an individual stock attribution.**

### 9. id=610821 `VCI` → **VNQ** · bullish · Joseph Carlson
- v1 → v2: `MIS_ATTRIBUTION` → `RETAG` (conf 0.82)
- quote: _Blackstone is Fielding offers for half of its interest in the real estate of the Bellagio Hotel in Las Vegas. I think it's incredibly likely that Vichy is on the phone trying to work out a deal that makes sense for the shareholder. I would …_
- v2 reason: **The quote discusses Vici Properties (a REIT) potentially acquiring Blackstone's real estate interest in the Bellagio, but VCI is Viad Corp (a services company), not Vici Properties (VICI); however, since the actual subject is a real estate/REIT transaction, the appropriate sector ETF would be VNQ, and the correct ticker should have been VICI not VCI.**

### 10. id=612529 `AAPL` → **QQQ** · bullish · PensionCraft
- v1 → v2: `MIS_ATTRIBUTION` → `RETAG` (conf 0.82)
- quote: _The US is big for a reason. It's really good at growing earnings. If you look at the Magnificent 7, they're just cash generating machines. They've been hugely successful and they're likely to remain successful._
- v2 reason: **The speaker is discussing the Magnificent 7 as a group of cash-generating machines, which is a broad tech/mega-cap theme better represented by QQQ than singling out AAPL specifically.**

## 10 examples — v1 MIS held in v2 (genuine mis-attribution)

### 1. id=612335 `SPY` · bullish · Minority Mindset
- v1 → v2: `MIS_ATTRIBUTION` → `MIS_ATTRIBUTION` (conf 0.85)
- quote: _Now, again, we're seeing a big shift happening. This shift is not going to slow down in 2026. is going to accelerate. Could we see a bubble bursting? Absolutely. But that doesn't mean that this trend is going to go away._
- v2 reason: **The quote discusses the AI theme and potential bubble, with no reference to the broad S&P 500 index or SPY; a more fitting ticker would be an AI/tech ETF like QQQ, but the speaker never references the S&P 500 at all.**

### 2. id=606843 `HSBC` · bullish · The Compounding Investor
- v1 → v2: `MIS_ATTRIBUTION` → `MIS_ATTRIBUTION` (conf 0.95)
- quote: _the third company hon which was spun off from GSK in 2022 is relatively unchanged it could perhaps be a takeover Target in the future so I'm happy to hold for the long term_
- v2 reason: **The quote discusses 'hon' (Haleon, spun off from GSK in 2022) and various UK consumer/pharma companies, with no mention of HSBC or any banking/financial theme that would link to HSBC Holdings PLC.**

### 3. id=611860 `LYV` · bullish · Fast Graphs
- v1 → v2: `MIS_ATTRIBUTION` → `MIS_ATTRIBUTION` (conf 0.97)
- quote: _This is an experiential real estate investment trust. They own MGM and some of these big the Venetian Resort in Vegas, Caesar's Palace. It's got a very consistent record. This is about as cheap as this real estate investment trust has ever …_
- v2 reason: **The quote describes an experiential REIT owning MGM Grand, the Venetian, and Caesar's Palace properties — this points to VICI Properties (VICI), not LYV (Live Nation Entertainment, a live events/ticketing company with no connection to casino real estate).**

### 4. id=605647 `SPG` · bullish · Joseph Carlson
- v1 → v2: `MIS_ATTRIBUTION` → `MIS_ATTRIBUTION` (conf 0.97)
- quote: _S&P Global remains my top holding and one of my strongest buys here but there's other opportunities and ones that I think are possibly even more exciting than S&P Global today_
- v2 reason: **The speaker is discussing S&P Global (SPGI), a financial data and analytics company, not SPG (Simon Property Group, a REIT); there is no thematic, sector, or implicit link between the quote and SPG.**

### 5. id=610419 `BMI` · bullish · The Patient Investor
- v1 → v2: `MIS_ATTRIBUTION` → `MIS_ATTRIBUTION` (conf 0.99)
- quote: _And if Ethereum is going to 9x BitMine will likely I don't know 12 13 15x and it's going to generate net income and they're going to buy back stock or issue dividends and do acquisitions and do many different things._
- v2 reason: **The quote discusses BitMine (a crypto/Ethereum-related company) and Ethereum price predictions, with no connection whatsoever to BMI (Badger Meter Inc), a water measurement technology company.**

### 6. id=611624 `TIP` · bearish · Minority Mindset
- v1 → v2: `MIS_ATTRIBUTION` → `MIS_ATTRIBUTION` (conf 0.92)
- quote: _In 2025, our economy is expected to have grown by a little bit over 2% which is higher than our average. In 2025, the stock market grew by around 16%. Which is higher than average. In 2025, the job market was well below average._
- v2 reason: **The quote discusses general macroeconomic conditions (GDP growth, stock market performance, job market weakness) with no mention of inflation-protected securities, TIPS bonds, or any thematic link to TIP ETF.**

### 7. id=611870 `FSRV` · bearish · Fast Graphs
- v1 → v2: `MIS_ATTRIBUTION` → `MIS_ATTRIBUTION` (conf 0.85)
- quote: _So, while the next 12 to 18 months are likely to remain challenging, as clearly illustrated by the fast graphs from at least a a fundamental point of view, the company is now in the midst of a strategic reset with management focusing on thi…_
- v2 reason: **The quote and context are explicitly about Fiserv (ticker FI), but the attributed ticker FSRV does not correspond to Fiserv — FSRV is a different, unrelated company (Finserv Acquisition Corp), making this a mis-attribution.**

### 8. id=611967 `RMG` · bearish · PensionCraft
- v1 → v2: `MIS_ATTRIBUTION` → `MIS_ATTRIBUTION` (conf 0.85)
- quote: _What's your take on the sale of right move relics auto trader due to AI? Do you believe these AI can also can be disrupted to these establishments considering chat GPT has turned a profit?_
- v2 reason: **RMG has no thematic, sector, or implicit link to the discussion about Rightmove, Relics, Auto Trader, or AI disruption of property/auto listing platforms; the speaker is discussing UK property/auto listing companies and AI disruption, not anything related to RMG.**

### 9. id=612490 `AER` · neutral · Nanalyze
- v1 → v2: `MIS_ATTRIBUTION` → `MIS_ATTRIBUTION` (conf 0.95)
- quote: _So you have NASDAQ up 120% in 5 years, but a more suitable benchmark would be defense stocks. Those are up 140% over the same time frame. Then you have Krattos at 189%, Aerero Environment at 217%. Of course, 5-year returns don't mean a whol…_
- v2 reason: **The quote discusses defense/drone companies Kratos and AeroVironment with no mention of AerCap Holdings (an aircraft leasing company), making this a clear mis-attribution with no thematic, sector, or implicit link.**

### 10. id=613158 `BYD` · bullish · New Money
- v1 → v2: `MIS_ATTRIBUTION` → `MIS_ATTRIBUTION` (conf 0.98)
- quote: _Obviously with a significant percentage of the Daily Journal's marketable securities invested in BYYD and Alibaba, you feel differently. We invested some money in China because we could get more value in terms of the strength of the enterpr…_
- v2 reason: **The quote references 'BYYD' (BYD Company, the Chinese EV/battery firm) and Alibaba as Chinese investments, having no connection to Boyd Gaming Corp (BYD), a US casino operator.**

## What this audit establishes

- Under Nimrod's attribution rules, **1,071 / 1,250 (85.7%)** of the grounding-sweep's Haiku-inferred bucket is actually legitimate attribution — the speaker's topic maps to the tagged ticker via thematic / sector / commodity-ETF proxy / implicit reference / conditional language.
- **19** rows are subject-correct but ticker-too-narrow (speaker discussed a sector, Haiku tagged an individual stock instead of the sector ETF). These are recoverable via a ticker swap to the suggested ETF.
- Only **160** rows (12.8% of the full Haiku-inferred pile) are genuine mis-attributions the broader rules still can't justify. This is the real quarantine target.

Compared to the v1 audit (which flagged 266 + 171 = 437 as suspect under generic skepticism), the v2 rules-aware pass shrinks the true-mis pile by **~40%** — the rest was false alarms from over-strict judging.

# MIS Quarantine Log — 2026-04-19

Transaction at `2026-04-19T12:53:04.858473Z`.

- Source CSV: `audit/llm_judge_haiku_inferred_rules_v2_2026-04-19.csv` (commit `c60d36e`)
- Filter: `v2_verdict='MIS_ATTRIBUTION' AND ticker != 'EVENT' AND v2_confidence >= 0.85`
- Manual override: **id=611325** (INTC) excluded from quarantine; Sonnet's prose reason said *"weak REAL_ATTRIBUTION rather than MIS_ATTRIBUTION"* while its JSON output said MIS. Operator flip → stays visible.

- Rows matching filter: 132
- Rows already excluded (prior audits, preserved): 20
- **Rows quarantined this transaction: 112**

## Columns set

| column | value |
|---|---|
| `excluded_from_training` | `TRUE` |
| `exclusion_reason` | `sonnet_rules_v2_mis_attribution` |
| `exclusion_flagged_at` | `NOW()` |
| `exclusion_rule_version` | `c60d36e` (audit CSV commit SHA) |

Transaction guard: `WHERE NOT excluded_from_training`. Any row already excluded by a prior audit was skipped (never overwritten — its earlier exclusion_reason stays as historical provenance).

## Affected forecasters (top 20)

| forecaster_id | name | rows quarantined |
|---:|---|---:|
| 9944 | Meet Kevin | 16 |
| 9902 | Joseph Carlson | 15 |
| 10057 | PensionCraft | 10 |
| 9979 | The Patient Investor | 8 |
| 9891 | Chip Stock Investor | 8 |
| 9897 | Stock Moe | 8 |
| 10055 | Minority Mindset | 6 |
| 10054 | Financial Education | 6 |
| 10056 | Fast Graphs | 5 |
| 9904 | Nanalyze | 5 |
| 9900 | Graham Stephan | 4 |
| 9912 | Dividendology | 3 |
| 9907 | Stock Compounder | 3 |
| 9983 | The Compounding Investor | 2 |
| 10009 | Sven Carlin | 2 |
| 9978 | Ales World of Stocks | 2 |
| 9905 | New Money | 1 |
| 9985 | The Quality Investor | 1 |
| 21 | Morningstar | 1 |
| 9986 | Andrei Jikh | 1 |

## Rows quarantined this run

| id | ticker | direction | confidence | channel | reason |
|---:|---|---|---:|---|---|
| 612335 | `SPY` | bullish | 0.85 | Minority Mindset | The quote discusses the AI theme and potential bubble, with no reference to the broad S&P 500 index or SPY; a more fitting ticker would be an AI/tech ETF like QQQ, but the speaker never references the |
| 606843 | `HSBC` | bullish | 0.95 | The Compounding Investor | The quote discusses 'hon' (Haleon, spun off from GSK in 2022) and various UK consumer/pharma companies, with no mention of HSBC or any banking/financial theme that would link to HSBC Holdings PLC. |
| 612851 | `SH` | bullish | 0.92 | The Patient Investor | The speaker is bullish on bonds/treasuries for safety, which maps to TLT (long treasuries ETF), not SH (inverse S&P ETF), which has no thematic or implicit link to the quote. |
| 605647 | `SPG` | bullish | 0.97 | Joseph Carlson | The speaker is discussing S&P Global (SPGI), a financial data and analytics company, not SPG (Simon Property Group, a REIT); there is no thematic, sector, or implicit link between the quote and SPG. |
| 611624 | `TIP` | bearish | 0.92 | Minority Mindset | The quote discusses general macroeconomic conditions (GDP growth, stock market performance, job market weakness) with no mention of inflation-protected securities, TIPS bonds, or any thematic link to  |
| 611870 | `FSRV` | bearish | 0.85 | Fast Graphs | The quote and context are explicitly about Fiserv (ticker FI), but the attributed ticker FSRV does not correspond to Fiserv — FSRV is a different, unrelated company (Finserv Acquisition Corp), making  |
| 611967 | `RMG` | bearish | 0.85 | PensionCraft | RMG has no thematic, sector, or implicit link to the discussion about Rightmove, Relics, Auto Trader, or AI disruption of property/auto listing platforms; the speaker is discussing UK property/auto li |
| 612490 | `AER` | neutral | 0.95 | Nanalyze | The quote discusses defense/drone companies Kratos and AeroVironment with no mention of AerCap Holdings (an aircraft leasing company), making this a clear mis-attribution with no thematic, sector, or  |
| 613158 | `BYD` | bullish | 0.98 | New Money | The quote references 'BYYD' (BYD Company, the Chinese EV/battery firm) and Alibaba as Chinese investments, having no connection to Boyd Gaming Corp (BYD), a US casino operator. |
| 613079 | `GLD` | bullish | 0.95 | Sven Carlin | The speaker mentions oil, copper, and China as purchases, but never mentions gold or GLD; attaching a bullish GLD tag has no thematic, implicit, or explicit link to the quote. |
| 610482 | `VTR` | bullish | 0.85 | Joseph Carlson | The quote and context are discussing 'vichi' (likely VICI Properties, a gaming/experiential REIT), not Ventas (VTR), a healthcare REIT — the ticker is misattributed to the wrong company. |
| 608911 | `LRCX` | bullish | 0.9 | Chip Stock Investor | The quote and context discuss 'Lattis' (a cyclical company with ~138M shares and $117M FCF), not Lam Research (LRCX), which is a much larger semiconductor equipment company with billions in FCF — the  |
| 606570 | `TEL` | bullish | 0.95 | Chip Stock Investor | The quote and context are entirely about Tokyo Electron (ticker TOELY/8035.T), a Japanese semiconductor equipment maker, with no connection to TEL (TE Connectivity Ltd.), a Swiss connector/sensor comp |
| 609285 | `BRCM` | bullish | 0.95 | The Quality Investor | The quote discusses Netflix, Mastercard, Visa, and the $1 trillion market cap club with no mention of BRCM (Broadcom) anywhere in the surrounding context. |
| 605705 | `NEM` | bearish | 0.97 | Morningstar | The quote and surrounding context are entirely about Nutrien (a fertilizer stock), not Newmont Corporation (NEM), a gold mining company with no thematic or sector link to the discussion. |
| 610877 | `TLT` | bullish | 0.85 | Joseph Carlson | The quote discusses Fed policy pressure on stocks (S&P 500, QQQ, Dow) and the dollar, not long-duration treasuries; TLT has no thematic or implicit link to this discussion about equity portfolio losse |
| 611280 | `SH` | bearish | 0.9 | Meet Kevin | The speaker is discussing oil prices and geopolitical risk as a buy-the-dip scenario, which is bullish framing — SH is an inverse S&P ETF implying a bearish market view, but the speaker explicitly say |
| 611396 | `WYN` | bullish | 0.95 | Financial Education | The speaker is explicitly discussing Wynn Resorts, which trades under ticker WYNN, not WYN (which is Wyndham Hotels & Resorts — a different company entirely). |
| 611502 | `INTC` | bullish | 0.97 | Financial Education | The speaker is discussing Intuit (INTU) — referencing TurboTax and QuickBooks — not Intel Corporation (INTC), making this a ticker extraction error rather than a thematic proxy. |
| 611792 | `TMPO` | bullish | 0.95 | Nanalyze | The speaker is discussing 'Tempest AI' (a genomics/big data company), not TMPO (Tempo Automation Holdings Inc), which is a PCB manufacturing automation company with no thematic link to genomics or the |
| 611863 | `NTNX` | bullish | 0.85 | Fast Graphs | The surrounding context describes a 'leading provider of cloud-based contact center solutions' which does not match Nutanix (a hyper-converged infrastructure/cloud computing company), suggesting the q |
| 612006 | `NVDA` | bullish | 0.97 | PensionCraft | The speaker is discussing UK small-cap stocks screened by quality/value/momentum criteria with no mention of NVIDIA or any semiconductor/AI theme that would link to NVDA. |
| 612145 | `LTC` | bullish | 0.98 | Stock Moe | The speaker is discussing Litecoin (the cryptocurrency, ticker LTC on crypto exchanges), not LTC Properties Inc (a healthcare REIT), so the equity ticker has no thematic or implicit link to the quote. |
| 611641 | `TBT` | bullish | 0.85 | Minority Mindset | TBT is an inverse/leveraged short Treasury ETF (2x short 20+ year Treasuries), but the quote discusses the yen carry trade unwinding and its impact on US stock market buyers, with no mention of US Tre |
| 612324 | `UUP` | bearish | 0.85 | Minority Mindset | The quote discusses the yen carry trade unwinding and its effect on asset markets broadly — there is no mention of the US dollar or UUP; the relevant currency here is the Japanese yen (FXY), not the d |
| 611969 | `GILT` | bullish | 0.99 | PensionCraft | The speaker is discussing UK gilts (government bonds) and UK money market funds, which has no connection to Gilat Satellite Networks Ltd (GILT); the ticker match is purely coincidental based on a simi |
| 612589 | `BYD` | bullish | 0.85 | Stock Moe | The quote discusses robotics and home robots with no connection to Boyd Gaming Corp (BYD); the surrounding context references 'BYD' as a stock chart example for returns, but BYD here likely refers to  |
| 611013 | `CMG` | bullish | 0.85 | Joseph Carlson | The surrounding context discusses Domino's Pizza (DPZ) and general investing philosophy about buying quality companies on dips, with no mention of Chipotle or CMG anywhere in the passage. |
| 610972 | `TSLA` | bearish | 0.95 | Joseph Carlson | The quote discusses general market dollar-cost averaging with no mention of Tesla or any implicit reference to TSLA; the surrounding context is about Google's ad business competition. |
| 612497 | `SH` | bullish | 0.92 | PensionCraft | The speaker is discussing investment grade corporate bonds and LQD specifically, with a bearish/crisis scenario — SH is an inverse S&P ETF with no thematic or implicit link to investment grade credit  |
| 613779 | `TLT` | bullish | 0.88 | Joseph Carlson | The quote argues that low rates push investors into riskier assets (bullish equities), which is bearish for long-duration treasuries like TLT, not bullish — and the broader context is about staying lo |
| 611894 | `CFR` | bullish | 0.95 | Fast Graphs | The quote discusses 'Citizen Financial Services' (ticker CZFS), not Cullen/Frost Bankers (CFR); these are two distinct regional bank companies with no implicit or thematic link between the quote and C |
| 614563 | `SH` | bullish | 0.85 | Meet Kevin | The quote discusses unemployment trends, the Sahm rule, and yield spreads as macro stress indicators — there is no bearish market prediction or inverse S&P thesis explicitly stated that would link to  |
| 614572 | `UUP` | bullish | 0.85 | Meet Kevin | The speaker is discussing China exporting deflation globally, which would be bearish for the dollar (UUP), not bullish, and the quote contains no reference to the dollar, currency markets, or any impl |
| 614578 | `QQQ` | bearish | 0.85 | Meet Kevin | The quote is specifically about Oracle bonds and Jerome Powell's monetary policy, with no thematic, sector, or implicit link to QQQ (Nasdaq-100 ETF); the speaker is discussing Oracle's credit market s |
| 614671 | `BTC` | bullish | 0.95 | Meet Kevin | The quote discusses housing, mortgage companies, renovation, consumer spending, and Fed policy with no mention of Bitcoin or crypto — BTC has no thematic, sector, or implicit link to the housing/consu |
| 614674 | `HOUS` | bullish | 0.85 | Meet Kevin | The speaker is bullish on renovation AI, mortgage companies, and home renovation broadly, but never mentions Anywhere Real Estate Inc (HOUS), a real estate brokerage, which has no thematic link to ren |
| 612710 | `FLAT` | bullish | 0.85 | Andrei Jikh | FLAT has no connection to the yield curve spread discussion; the quote is about the 2-10 year treasury yield inversion predicting recession, which would map to a treasury instrument like TLT, not FLAT |
| 614947 | `SH` | bullish | 0.92 | Graham Stephan | SH is an inverse S&P ETF (bearish instrument), but the quote discusses Fed rate cuts and monetary policy with no bearish market prediction or link to shorting equities; the bullish direction on SH als |
| 614911 | `MSTR` | bearish | 0.85 | Meet Kevin | The bearish quote refers to 'STRC'/'STRTC' (a feeder fund related to Bitcoin/MicroStrategy ecosystem), not MSTR itself — the speaker is discussing what happens *if* MSTR gets flushed out, but the bear |
| 614886 | `SPY` | bullish | 0.9 | Meet Kevin | The speaker is exclusively discussing call options on 'the Q's' (QQQ/Nasdaq), not SPY or the S&P 500, so attaching this bullish prediction to SPY has no thematic or implicit link. |
| 608532 | `NVDA` | bearish | 0.97 | Ales World of Stocks | The entire quote discusses Palantir (PLTR), not NVIDIA — there is no thematic, sector, or implicit link between the content and NVDA. |
| 612554 | `RR` | bullish | 0.98 | PensionCraft | The quote discusses European defense companies (Rolls-Royce, BAE Systems, Airbus) and US defense contractors, with no connection whatsoever to RR (Richtech Robotics Inc), a US robotics company. |
| 608751 | `PSTG` | bearish | 0.9 | The Patient Investor | PSTG is Pure Storage, but the context describes a robotics/AI/automation company trading at $12/share down 49% YTD with ~8-10% growth guidance, which does not match Pure Storage's profile; the ticker  |
| 609846 | `SHLX` | bullish | 0.9 | The Patient Investor | The speaker is discussing 'Shir energy' (likely Seer Energy or a similar company trading around $214-$217/share), not SHLX (Shell Midstream Partners), which is a different company that traded at much  |
| 612079 | `LTC` | bullish | 0.97 | Stock Moe | LTC Properties Inc is a healthcare REIT with no connection to the quote, which discusses Litecoin (LTC the cryptocurrency) and other crypto assets exploding higher under new commodity classification l |
| 611284 | `INTC` | bullish | 0.85 | Meet Kevin | The quote refers to 'into it' which in context appears to be Intuit (INTU) — a software company — not Intel (INTC); the mention of 'software selloff' and price levels (~349, ~468, ~630) are inconsiste |
| 611966 | `LSE` | bearish | 0.95 | PensionCraft | The speaker is referring to the London Stock Exchange as a market/venue where a selloff occurred, not as a company stock, and LSE here is Leishen Energy Holding Co Ltd — a Chinese energy company with  |
| 610861 | `VTR` | bullish | 0.95 | Joseph Carlson | The speaker is discussing 'Vichi' (VICI Properties, ticker VICI), a REIT, not Ventas (VTR); the quote and context contain no reference to VTR whatsoever. |
| 611799 | `USO` | bearish | 0.85 | Nanalyze | The quote discusses natural gas energy production and solar power in the context of AI energy demand, with no bearish signal for crude oil (USO); the relevant proxy would be natural gas (UNG) or energ |
| 611935 | `TBT` | bearish | 0.85 | PensionCraft | TBT is a leveraged inverse Treasury ETF (bearish on bonds/bullish on rates), but the quote is bearish on growth stocks/the US equity market due to higher rates — not a prediction about Treasury bonds  |
| 611992 | `TLT` | bullish | 0.85 | PensionCraft | The quote discusses the Bank of England cutting rates slowly due to UK inflation and wage growth concerns, which has no direct thematic or implicit link to TLT (US long-duration Treasury ETF); a UK gi |
| 611816 | `UUUU` | bullish | 0.9 | Nanalyze | The quote discusses USA Rare Earth (a SPAC) and rare earth metals broadly, while UUUU (Energy Fuels Inc) is a uranium/rare earth miner — though it has some rare earth exposure, the speaker is explicit |
| 611964 | `APVO` | bearish | 0.97 | PensionCraft | The quote discusses AppLovin (APP) and broad AI/tech sector selloffs, with no connection to APVO (Aptevo Therapeutics), a biotech company. |
| 606301 | `CCMP` | bearish | 0.95 | Hamish Hodder | CCMP is Cabot Microelectronics (a semiconductor materials company) and has no thematic, sector, or implicit link to the quote, which discusses a bearish bet against the S&P 500 and NASDAQ index; the c |
| 610464 | `VIX` | bearish | 0.95 | Joseph Carlson | The quote discusses Formula 1 construction disruptions on the Las Vegas Strip and their impact on visitors, with no thematic, sector, or implicit link to VIX (volatility index). |
| 610658 | `VZ` | bullish | 0.97 | The Patient Investor | The quote discusses holding cash and not finding market value generally, with no mention of Verizon or any telecom theme; VZ has no thematic, sector, or implicit link to this macro/cash-positioning di |
| 607435 | `TR` | bullish | 0.9 | Dividendology | The speaker is analyzing 'TRW' (likely TRW Automotive or a spreadsheet ticker code) and discussing Cigna (CI) as the third company, not Tootsie Roll Industries (TR); the quote and context show no conn |
| 609912 | `NAVI` | bullish | 0.92 | Chip Stock Investor | The speaker is discussing 'Navias' (likely Navitas Semiconductor, NVTS), a gallium nitride/silicon carbide power semiconductor company, not Navient Corp (NAVI), a student loan servicer with no connect |
| 609079 | `AAL` | bullish | 0.98 | Sven Carlin | The quote discusses copper miners and emerging markets demand for commodities, with no thematic, sector, or implicit link to American Airlines (AAL). |
| 606048 | `DOOO` | bullish | 0.98 | Chip Stock Investor | The quote and surrounding context are entirely about DigitalOcean (DOCN) and its AI/GPU infrastructure strategy, with no connection to BRP Inc (DOOO), a powersports vehicle manufacturer. |
| 607168 | `PSTG` | bullish | 0.9 | Chip Stock Investor | PSTG is Pure Storage, Inc., not 'Everpure, Inc.'; the quote and context discuss a data storage/AI-adjacent company with ~100% YTD run-up and $3.1B revenue guidance, which aligns with Pure Storage (PST |
| 609127 | `AAPL` | bullish | 0.9 | The Patient Investor | The speaker explicitly names Visa, Amazon, Meta, and the Magnificent Seven broadly, but never mentions Apple specifically, making the AAPL attribution unsupported by the quote or context. |
| 609131 | `GOOGL` | bullish | 0.9 | The Patient Investor | The speaker explicitly names Visa, Amazon, and Meta as the stocks they are bullish on within the Magnificent Seven theme, but never mentions Alphabet/GOOGL specifically, making this a mis-attribution  |
| 609126 | `NVDA` | bullish | 0.85 | The Patient Investor | The quote discusses broad market rotation, rate cuts, and stocks going up together (mentioning Russell 2000, Dow stocks, McDonald's) with no specific reference to NVIDIA or semiconductors, making the  |
| 609132 | `TSLA` | bullish | 0.9 | The Patient Investor | The speaker explicitly mentions Visa, Amazon, Meta, and the Magnificent Seven broadly, but never references Tesla or any implicit proxy for it, making the TSLA attribution unsupported by the quote or  |
| 608403 | `ASML` | bullish | 0.9 | Chip Stock Investor | The quote is entirely about TSMC's (TSM) capex plans as explained by TSMC's CFO Wendel Wong, with no mention of ASML or any implicit link to ASML Holding. |
| 611858 | `CI` | bullish | 0.85 | Fast Graphs | The speaker is discussing a company called 'Credential' (a financial trading at a 7 PE with a 5%+ dividend yield and 15-year dividend growth history), which does not match Cigna Corporation (CI), a he |
| 612682 | `SOL` | bullish | 0.9 | Stock Moe | The speaker is discussing 'Solana' (the cryptocurrency), not Emeren Group Ltd (SOL), which is a solar energy company with no connection to the quote. |
| 612129 | `SOL` | bearish | 0.97 | Stock Moe | The quote refers to Solana (SOL the cryptocurrency) trading at 124, not Emeren Group Ltd (SOL the solar energy stock); the context confirms discussion of crypto assets like Ethereum, Solana, and Doge. |
| 613024 | `TIP` | bearish | 0.85 | Everything Money | TIP is an inflation-protected bond ETF, but the quote discusses a deflationary bust and AI bubble collapse — deflation would actually hurt TIPS relative to nominal bonds, and the broader context is ab |
| 612643 | `SOL` | bearish | 0.95 | Stock Moe | The speaker is discussing Solana (SOL the cryptocurrency) with price levels of $105-$117, not Emeren Group Ltd (SOL), a Chinese solar company — the quote has no thematic or implicit link to Emeren Gro |
| 612066 | `XRP` | bullish | 0.85 | Stock Moe | The quote discusses the probability of crypto legislation being signed by the president, with no specific mention of XRP — the context references broad crypto regulation, making IBIT or a general cryp |
| 612637 | `SOL` | bearish | 0.95 | Stock Moe | The quote and context are entirely about Solana (SOL the cryptocurrency) and Ethereum, with no connection to SOL (Emeren Group Ltd), a Chinese solar energy company. |
| 611595 | `UUP` | bullish | 0.85 | Minority Mindset | The quote discusses broad market stimulus by the Fed/Treasury, which does not specifically reference the US dollar or UUP; a broad market or liquidity theme would more plausibly map to SPY or QQQ, not |
| 611596 | `SH` | bearish | 0.95 | Minority Mindset | The quote and context are explicitly bullish on long-term market investing, not bearish, and SH (Inverse S&P ETF) has no thematic or implicit link to a speaker advocating for long-term ownership of go |
| 612515 | `TLT` | bullish | 0.85 | PensionCraft | The quote discusses Bank of England rate cuts in the UK, not US interest rates or US long-duration treasuries; TLT tracks US Treasury bonds and has no direct link to UK monetary policy discussed here. |
| 613213 | `SH` | bullish | 0.85 | Marko WhiteBoard Finance | The quote discusses bond market pricing, Fed rate hikes/cuts, and treasury yields — which maps to long-duration treasuries (TLT) or possibly TIP, not SH (Inverse S&P), as there is no direct or implici |
| 612834 | `NG` | bullish | 0.99 | The Compounding Investor | The quote is about National Grid (a UK-listed utility company, ticker NG. on the London Stock Exchange), not NovaGold Resources Inc (NG on NYSE/TSX), which is a gold mining company with no connection  |
| 612750 | `VRTX` | bullish | 0.97 | Ales World of Stocks | The quote describes 'vatris' (Viatris, ticker VTRS), a Pfizer/Mylan spin-off generics company, which has no connection to Vertex Pharmaceuticals (VRTX). |
| 611855 | `STAG` | bullish | 0.85 | Fast Graphs | The quote describes 'the monthly income company' — a well-known reference to Realty Income (O), not STAG Industrial; STAG does not carry that branding and the surrounding context mentions 'ONE' (oil/g |
| 611471 | `GLD` | bullish | 0.95 | Financial Education | The speaker is explicitly discussing silver's price performance, not gold; GLD tracks gold, making this a misattribution — the correct ticker would be SLV (silver ETF). |
| 611345 | `TLT` | bullish | 0.85 | Graham Stephan | The quote discusses Powell's term ending and broad stock market outlook, with no mention of bonds, interest rates in a directional sense for TLT, or long treasuries — the bullish TLT attribution has n |
| 611340 | `SH` | bearish | 0.98 | Graham Stephan | The quote discusses Peter Diamandis's philosophy about economics of abundance and AI, with no reference to the S&P 500, inverse funds, or any bearish market thesis that would link to SH (Inverse S&P E |
| 611200 | `SDOT` | bearish | 0.97 | Meet Kevin | The quote discusses SanDisk and Micron (memory/storage companies), while SDOT is Sadot Group Inc (an agricultural commodities company), with no thematic, sector, or implicit link between them. |
| 611168 | `RYM` | bullish | 0.95 | Stock Compounder | The speaker is discussing Ryman Healthcare, a New Zealand/Australian retirement village company, which has no connection to RYM (RYTHM Inc); the ticker symbol coincidentally matches the NZX-listed Rym |
| 611167 | `PRU` | bullish | 0.98 | Stock Compounder | The quote discusses Prosus (a South African holding company) and its Tencent stake — there is no thematic, sector, commodity, or implicit link to PRU (Prudential Financial, Inc.). |
| 611014 | `AAPL` | bearish | 0.95 | Joseph Carlson | The quote discusses broad macroeconomic themes (end of cheap money, inflation, housing, used cars) with no mention of Apple or any implicit reference to AAPL specifically. |
| 610446 | `BKNG` | bullish | 0.99 | Joseph Carlson | The quote is entirely about Berkshire Hathaway (BRK.B), with no mention of or implicit link to Booking Holdings (BKNG). |
| 610205 | `MSCI` | bullish | 0.98 | Dividendology | The quote discusses BDC (Business Development Company) stocks and mentions 'MSC Income Fund' (not MSCI Inc), with no reference to MSCI Inc's index/analytics business whatsoever. |
| 609914 | `LITE` | bullish | 0.85 | Chip Stock Investor | The quote describes 'Light on' (likely 'Liqtech' or a Taiwanese company like 'Lite-On Technology'), a Taiwanese power chip/networking company, which does not match LITE (Lumentum Holdings Inc.), a US- |
| 608971 | `NUE` | bullish | 0.97 | Dividendology | The entire quote discusses GEO Group (GEO), a private prison/detention company; Nucor Corporation (NUE), a steel manufacturer, has no thematic, sector, or implicit connection to anything mentioned in  |
| 608407 | `MTSI` | bullish | 0.92 | Chip Stock Investor | The quote and context are entirely about TSMC's (TSM) capex plans and hyperscaler spending, with no mention of MACOM Technology Solutions (MTSI) or any thematic/sector link to it. |
| 610921 | `KMB` | neutral | 0.99 | Joseph Carlson | The quote and context are entirely about McCormick (MKC), with no mention of or thematic link to Kimberly-Clark (KMB). |
| 614261 | `GTLB` | bullish | 0.95 | Stock Compounder | The quote describes a 'long dated monopoly' severely impacted by COVID with Australian exposure and a 30-year trend, which has no thematic, sector, or implicit link to GitLab Inc (a DevOps software pl |
| 614256 | `SH` | bullish | 0.95 | PPCIAN | SH is an inverse S&P ETF (bearish instrument), but the speaker is bullishly discussing CPG consumer staples stocks like Clorox, Pepsi, and Hershey with no mention of shorting the market or any inverse |
| 614149 | `SHYF` | bullish | 0.97 | Unrivaled Investing | The quote discusses Shift4 Payments (FOUR), a payment processing company, but the ticker assigned is SHYF (Shyft Group Inc), a specialty vehicle manufacturer with no thematic, sector, or implicit link |
| 614301 | `SAND` | bullish | 0.95 | Meet Kevin | The speaker is discussing SanDisk (a flash storage/memory company), not Sandstorm Gold Ltd; SAND has no thematic, sector, or implicit link to high bandwidth memory or SanDisk's financials. |
| 613783 | `WLK` | bullish | 0.98 | Joseph Carlson | The speaker mentions Disney, Costco, Wynn Resorts, and Home Depot as quality companies, with no reference to Westlake Corporation (WLK) or any theme/sector that would serve as a proxy for it. |
| 614569 | `IREN` | bearish | 0.85 | Meet Kevin | The speaker names 'CoreWeave, Enbis, Oracle, and IN' as bearish bag-holding companies — IREN Ltd is not mentioned or implied, and 'IN' likely refers to a different entity; there is no thematic, sector |
| 614624 | `SIM` | bullish | 0.99 | Meet Kevin | The quote is about Symbotic (SYM), a warehouse robotics company, with no connection to SIM (Grupo Simec, a Mexican steel company). |
| 614590 | `SPY` | bearish | 0.85 | Meet Kevin | The quote discusses profit-taking in chip stocks (Broadcom, Oracle) and sector rotation, which would link to SMH or QQQ, not SPY specifically — and the bearish thesis is semiconductor-specific, not a  |
| 614364 | `WM` | bullish | 0.99 | Joseph Carlson | The quote and context are entirely about AT&T (T), not Waste Management (WM), with no thematic, sector, or implicit link between the discussion and WM. |
| 614398 | `SH` | bearish | 0.92 | Joseph Carlson | SH is an inverse S&P ETF (bearish instrument), but the speaker is making a bullish call on beaten-down cyclical/value stocks recovering, with no mention of shorting the market or any inverse position. |
| 614551 | `INTC` | bearish | 0.92 | Meet Kevin | The quote discusses Oracle's stock decline dragging down AMD, Nvidia, and the broader semiconductor/tech sector, with no mention of Intel (INTC) whatsoever. |
| 614404 | `SH` | bearish | 0.9 | Joseph Carlson | The speaker explicitly states they plan to 'buy stocks like crazy,' which is a bullish stance, and SH is an inverse S&P ETF (bearish instrument); the quote describes economic struggles but the speaker |
| 614801 | `GLD` | bullish | 0.97 | Meet Kevin | The quote discusses GLP-1 drug (Ozempic) behavioral effects on consumer spending with no mention of gold, the dollar, or any macro theme that would link to GLD. |
| 614936 | `UUP` | bearish | 0.85 | Graham Stephan | The quote discusses US-China tariff escalation and stock market selloffs broadly, with no specific mention of the US dollar or any dollar-bullish/bearish theme that would link to UUP. |
| 615063 | `WH` | bullish | 0.85 | Financial Education | The speaker is discussing 'Wynn Resorts' (WYNN), a Las Vegas casino/resort company, not Wyndham Hotels & Resorts (WH), which is a separate lodging franchise company with no Las Vegas casino properties |
| 614996 | `PLNT` | bullish | 0.85 | Financial Education | The quote references 'Planet' in the context of a penny stock trading at 75 cents, which does not match Planet Fitness (PLNT), a mid-cap gym chain trading well above that price range; the 'reclassific |
| 614997 | `REVG` | bullish | 0.95 | Financial Education | The speaker is discussing 'Revolve' (RVLV, a fashion e-commerce company) and its relationship to the Russell 2000, not REV Group Inc (REVG), which is a specialty vehicle manufacturer with no connectio |
| 605748 | `CNR` | bullish | 0.95 | Nanalyze | The quote discusses Canadian National Railway (CNI/CNR on TSX), a specific railway company, not Core Natural Resources Inc (CNR), which is a coal/natural resources company — the ticker CNR here refers |

## Deferred / held

- **id=611325 (INTC)** — Sonnet MIS verdict but prose reason flagged as *weak REAL*; kept visible pending manual review.
- **2 rows with v2_confidence < 0.85** — held; low-confidence MIS may be revisited under a tighter sweep.
- **20 rows already excluded** by prior audit passes (reasons include `wrong_ticker_assignment`, `ticker_quote_mismatch`, `not_a_prediction_v2`, `not_a_prediction`). Their original reasons are preserved — no overwrite.

## Reversibility

Every row carries `exclusion_reason='sonnet_rules_v2_mis_attribution'` + `exclusion_rule_version='c60d36e'`. To restore all 112 rows to visible:

```sql
-- DRY-RUN: SELECT first
SELECT COUNT(*) FROM predictions
WHERE exclusion_reason = 'sonnet_rules_v2_mis_attribution'
  AND exclusion_rule_version = 'c60d36e';

-- RESTORE:
UPDATE predictions
SET excluded_from_training = FALSE,
    exclusion_reason = NULL,
    exclusion_flagged_at = NULL,
    exclusion_rule_version = NULL
WHERE exclusion_reason = 'sonnet_rules_v2_mis_attribution'
  AND exclusion_rule_version = 'c60d36e';
```

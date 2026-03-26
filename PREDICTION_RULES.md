# Eidolum Prediction Rules v2.0

## Core Principle
Every prediction must link to a real, publicly accessible article where the prediction was actually made. No generic pages, no aggregated data, no fabricated URLs.

## Required fields — ALL 7 must be present:
1. Specific stock/crypto/ETF ticker (AAPL, BTC, SPY, etc.)
2. Clear direction (bullish/bearish/buy/sell)
3. Real source URL to the actual article/video/tweet
4. Archived proof via Wayback Machine
5. Named forecaster (the person/firm making the call, NOT the platform)
6. Date published
7. Evaluation window (90 days for rating changes, 12 months for price targets)

## CRITICAL: Platform vs Forecaster
Yahoo Finance, Seeking Alpha, MarketWatch, CNBC, YouTube, X = PLATFORMS, not forecasters.
The prediction belongs to whoever made the call:
- "Goldman Sachs Upgrades AAPL" on Yahoo Finance -> forecaster = Goldman Sachs
- "Deep Value Investing: Buy NKE" on Seeking Alpha -> forecaster = Deep Value Investing
- Jim Cramer on CNBC -> forecaster = Jim Cramer
- @michaelburry on X -> forecaster = Michael Burry
Always extract the actual analyst/firm name from the headline. Never attribute to the platform.

## DELETE rules — NOT valid predictions:
- Blog post summaries, RSS feed content
- Aggregated data ("35 buy vs 2 sell")
- Past-tense market reports ("Oil Falls Sharply", "Dell Shares Spike") — these describe what HAPPENED, not predictions
- Press releases (signs agreement, partnership, acquisition, framework agreement, production capacity)
- Clickbait questions ending with ?
- Corporate news (earnings reports, dividends, stock splits, CEO appointments)
- Any prediction with dead/generic/fabricated URLs
- Any prediction without a real ticker or clear direction
- Vague market commentary, sector calls without specific ticker
- Predictions attributed to a platform (Yahoo Finance, Seeking Alpha) instead of the actual analyst/firm

## Supported assets:
- US stocks: YES (AAPL, TSLA, NVDA)
- Crypto: YES (BTC, ETH, SOL)
- ETFs: YES (SPY, QQQ, ARKK)
- Options: YES (reference underlying ticker)
- Sector calls without specific ticker: NO
- Market-wide calls: NO

## Proof rules:
- News articles: Direct link + Wayback archive
- YouTube: Timestamped link + screenshot
- Tweets/X: Direct URL + Wayback archive
- TV clips: Clip URL + Wayback archive
- SEC filings: EDGAR link (permanent)

## Conflict of interest:
Flag when forecaster has financial interest in the stock.

## Sentiment rule
"wary of", "confident of", "cautious on", "optimistic about", "bullish on", "bearish on"
WITHOUT a specific action (upgrade/downgrade/price target) are NOT predictions.
The test: strip the sentiment word — is there still a measurable claim? If no, reject.

## 50 categories of FALSE POSITIVES to reject
1. Press releases  2. Past-tense market reports  3. Clickbait questions
4. Blog summaries  5. Aggregated data  6. Job/rate/tax cuts
7. Earnings reports  8. Corporate news (CEO, dividends, splits)
9. Product upgrades ("Apple Upgrades iPhone")  10. Company targets ("Amazon Targets Same-Day Delivery")
11. Government/regulatory  12. Credit ratings (Moody's/Fitch/S&P on debt)
13. Insider moves  14. Index rebalancing  15. Historical comparisons
16. Options activity  17. Short interest  18. Macro/economic commentary
19. Unnamed sources/rumors  20. Listicles  21. Price milestones
22. Comparison articles (vs)  23. Sentiment without action
24. Earnings previews  25. Speculation with could/might/may
26. Sector rotation  27. Statistical observations
28. Social media buzz  29. Competitor impact  30. Management commentary
31. Dividend articles  32. IPO/SPAC  33. Crypto infrastructure
34. Geopolitical speculation  35. Coverage without rating
36. Buyback announcements  37. Conference attendance
38. No-change reiterations  39. General advice ("buy the dip")
40. Estimates without recommendation  41. ETF flows
42. M&A rumors  43. Company guidance  44. Price reaction reporting
45. Awards  46. Supply chain  47. Legal without prediction
48. Technical analysis without analyst  49. Commentary without action
50. Hypotheticals ("if NVDA hits $200")

## 3-Layer Defense System:
- L1 (scraper): Must have analyst action + rating word. 50 rejection categories + sentiment rule.
- L2 (validator): validate_prediction() checks all 7 fields before DB insert.
- L3 (hourly cleanup): Scans DB, deletes rule violators.

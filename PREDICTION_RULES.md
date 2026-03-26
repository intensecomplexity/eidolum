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

## Sentiment vs prediction — the measurability test
Sentiment words (wary of, confident of, cautious on, optimistic about, etc.) are NOT predictions on their own. The test: strip out the sentiment word — is there still a measurable claim? If yes = valid. If no = reject.

- Reject: "UBS Wary of Nike's Weak Sales" — no measurable action
- Reject: "Analyst Cautious on TSLA Amid Headwinds" — opinion, not a call
- Accept: "Confident NVDA will fall to $200" — measurable claim ($200 target)
- Accept: "Needham Raises NVDA Price Target to $200" — action + target
- Accept: "Goldman Sachs Upgrades AAPL to Buy, Cautious on Macro" — has strong action (upgrades to buy)

## 3-Layer Defense System:
- L1 (scraper): Must have analyst action + rating word. Reject press releases/clickbait/corporate news/past-tense reports.
- L2 (validator): validate_prediction() checks all 7 fields before DB insert.
- L3 (hourly cleanup): Scans DB, deletes rule violators.

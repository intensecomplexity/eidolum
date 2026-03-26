# Prediction Rules

## Core Principle
Every prediction in the database MUST link to a real, publicly accessible article where the prediction was actually made. No generic pages. No aggregate data. No fake links.

## What Counts as a Valid Prediction
- A news article reporting an analyst upgrade/downgrade with a real URL
- A news article reporting a price target change with a real URL
- A tweet, YouTube video, or Reddit post with a direct link to the original content
- Any public statement with a verifiable source link

## What Does NOT Count
- Aggregate analyst consensus data (e.g., "15 buy, 3 sell")
- Generic Yahoo Finance or stockanalysis.com pages
- Finnhub API endpoint URLs
- Any prediction where `source_url` doesn't point to the actual article/post

## Source Requirements
Every prediction MUST have:
1. **`source_url`**: Direct link to the original article (e.g., `https://www.marketwatch.com/story/goldman-sachs-upgrades-apple...`)
2. **`archive_url`**: Wayback Machine archived version (e.g., `https://web.archive.org/web/20260326/https://www.marketwatch.com/story/...`)

## Data Pipeline
1. **DELETE all predictions** at startup (clean slate)
2. **Seed 50 forecasters** (institutional analysts, media, famous investors)
3. **Scrape Finnhub Company News API** for real articles with real URLs
4. **Filter** articles that contain prediction keywords (upgrade, downgrade, price target, etc.)
5. **Extract direction** (bullish/bearish) from headline + summary
6. **Match to forecaster** based on source name and headline content
7. **Archive via Wayback Machine** for permanent proof
8. **Evaluate** predictions against real price data

## Prediction Keywords
Articles must contain at least one of:
- upgrade, downgrade, buy rating, sell rating, hold rating
- price target, raises target, lowers target, cuts target
- overweight, underweight, outperform, underperform
- initiates coverage, reiterates, maintains
- top pick, conviction buy, strong buy/sell
- bullish, bearish

## Direction Classification
- **Bullish**: upgrade, buy, overweight, outperform, raises, strong buy, top pick, conviction, positive
- **Bearish**: downgrade, sell, underweight, underperform, lowers, cuts, negative, reduce

## Forecaster Matching
Articles are matched to forecasters by scanning source name + headline for known keywords (e.g., "Goldman Sachs", "CNBC", "Wedbush"). Unmatched articles fall back to "Wall Street Consensus".

## Archive Strategy
- Every article URL is submitted to the Wayback Machine Save API (`https://web.archive.org/save/{URL}`)
- The archive URL is stored as `https://web.archive.org/web/{YYYYMMDD}/{URL}`
- This ensures proof persists even if the original article is deleted

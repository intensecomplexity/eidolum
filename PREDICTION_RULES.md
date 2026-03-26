# Prediction Rules

## Core Principle
Every prediction in the database MUST link to a real, publicly accessible article where an analyst or firm takes an explicit action (upgrade, downgrade, price target change). No press releases. No corporate news. No clickbait.

## What Counts as a Valid Prediction
An article must have BOTH:
1. **An analyst action**: upgrades, downgrades, initiates coverage, reiterates, maintains, raises/lowers/cuts price target
2. **A rating or target**: buy, sell, hold, overweight, underweight, outperform, underperform, price target of $X

### Examples that PASS
- "Goldman Upgrades AAPL to Buy" (action: upgrades, rating: buy)
- "Needham Raises NVDA Price Target to $200" (action: raises, rating: price target)
- "Morgan Stanley Downgrades TSLA to Underweight" (action: downgrades, rating: underweight)
- "Bernstein Initiates Coverage on ARM with Outperform" (action: initiates, rating: outperform)

### Examples that FAIL
- "Honeywell Signs Supplier Framework Agreement" (no analyst action, no rating)
- "Can the S&P 500 Outrun a Recession?" (clickbait question)
- "ACCESS Newswire Upgrades the ACCESS Platform" (product upgrade, not stock)
- "Waymo Is Scaling Faster Than Expected" (company news, not analyst call)

## What Gets Automatically Rejected
- Headlines ending with `?` (clickbait questions)
- Press releases: signs agreement, partnership, acquisition, merger
- Earnings: reports earnings, quarterly results, beats/misses estimates
- Corporate: dividend, stock split, buyback, repurchase
- Personnel: appoints, names CEO, hires, board of directors
- Regulatory: patent, FDA approval, clinical trial
- Legal: lawsuit, settlement, investigation

## Source Requirements
Every prediction MUST have:
1. **`source_url`**: Direct link to the original article (redirect resolved to final URL)
2. **`archive_url`**: Wayback Machine archived version

## Direction Classification (regex-based, high confidence only)
- **Bullish**: upgrades, raises/boosts price target, buy, overweight, outperform, strong buy, top pick, conviction buy, initiates/reiterates/maintains with buy/overweight/outperform
- **Bearish**: downgrades, lowers/cuts/slashes price target, sell, underweight, underperform, strong sell, initiates/reiterates/maintains with sell/underweight/underperform
- **Skip**: if direction cannot be determined with confidence, the article is not saved

## Data Pipeline
1. DELETE all predictions at startup (clean slate)
2. Seed 50 forecasters
3. Scrape Finnhub Company News API (60 tickers, 60-day lookback)
4. Strict filter: analyst action + rating, no reject keywords, no questions
5. Regex-based direction extraction (skip ambiguous)
6. Resolve redirect URLs to final article URL
7. Match to forecaster by source name + headline
8. Archive via Wayback Machine
9. Evaluate predictions against real price data

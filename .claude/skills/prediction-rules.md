# Prediction Scoring and Rules

## Three-Tier Scoring System
- HIT: prediction was correct (within tolerance of target, or right direction)
- NEAR: prediction was close (right direction, meaningful move, but missed target)
- MISS: prediction was wrong (wrong direction or barely moved)

## Scoring Points
- HIT = 1.0 points
- NEAR = 0.5 points
- MISS = 0 points
- Accuracy = (Hits x 1.0 + Nears x 0.5) / Total x 100

## Tolerance by Timeframe (for HIT when target exists)
- 1 day: 2%
- 1 week: 3%
- 2 weeks: 4%
- 1 month: 5%
- 3 months: 5%
- 6 months: 7%
- 1 year: 10%

## Minimum Movement for NEAR (right direction but missed target)
- 1 day: 0.5%
- 1 week: 1%
- 2 weeks: 1.5%
- 1 month: 2%
- 3 months: 2%
- 6 months: 3%
- 1 year: 4%

## Three Directions
- bullish: expects stock to go up
- bearish: expects stock to go down
- neutral: expects stock to stay flat

## Neutral Rating Classification
These ratings map to direction = "neutral":
hold, neutral, market_perform, equal_weight, sector_perform, in_line, peer_perform, market_weight, sector_weight

Still bullish: buy, strong_buy, outperform, overweight, positive
Still bearish: sell, strong_sell, underperform, underweight, negative, reduce

## Neutral Scoring
- Stock moved less than 5% either way: HIT
- Stock moved 5-10%: NEAR
- Stock moved more than 10%: MISS

## No-Target Predictions
- Only HIT or MISS possible (no NEAR without a target to measure distance from)
- Bullish: HIT if price went up, MISS if down
- Bearish: HIT if price went down, MISS if up

## Deduplication
- Key: ticker + forecaster_id + prediction_date + direction
- Check across ALL scrapers (massive_benzinga, fmp_grades, etc.)
- external_id field for per-source dedup (e.g., bz_{benzinga_id})

## Rejection Rules
- No ticker: reject
- No direction determinable: reject
- Question mark in headline (speculative articles): reject
- "Maintains" or "Reiterates" without price target change: reject (except neutral ratings, which are always accepted)
- Forecaster name longer than 50 characters: truncate

## Display Labels
- Use HIT/NEAR/MISS, not Correct/Close/Wrong
- Outcome column shows colored badges: HIT (green), NEAR (yellow), MISS (red)

## Alias Dictionary
- Firms have multiple names: "Bank of America" = "BofA" = "BofA Securities" = "Merrill Lynch"
- Maintained in jobs/seed_magazines.py
- merge_duplicate_forecasters() runs on startup to consolidate

# Scraper Rules

## Locking
- ALL scrapers share SCRAPER_LOCK (threading.Lock)
- Only ONE scraper or evaluator runs at a time
- Stats refresh is exempt from the lock
- Each scraper must acquire lock with blocking=False
- If lock is held, skip this cycle, log it, try next time
- Always release lock in finally: block

## Rate Limiting
- 300ms minimum between external API calls
- Finnhub: 60 calls/minute on free tier
- FMP: respect their rate limits
- Benzinga: batch requests, 500 per call

## Work Limits Per Cycle
- FMP grades scraper: 50 tickers per cycle
- Benzinga incremental: 24 hours of data per cycle
- Evaluator: 500 tickers per batch
- If more work remains, it continues next cycle

## Storage Guard
- Check DB size before every insert batch
- Stop all ingestion at 40GB
- Use pg_database_size(current_database()) to check

## Connection Pattern
```python
# 1. Read from DB (short connection)
db = BgSessionLocal()
try:
    pending = db.execute(query).fetchall()
finally:
    db.close()

# 2. Fetch external data (NO DB connection held)
for ticker in tickers:
    prices[ticker] = fetch_price(ticker)
    time.sleep(0.3)  # rate limit

# 3. Write results (short connection)
db = BgSessionLocal()
try:
    for update in updates:
        db.execute(update_query)
    db.commit()
finally:
    db.close()
```

## Logging
- Log progress: "[ScraperName] Processed X, inserted Y, skipped Z dupes"
- Log errors: "[ScraperName] Error for {ticker}: {error}"
- On error: log it, skip that item, continue (never crash the whole job)

## Backfill
- Store progress in database config table (survives restarts)
- auto_resume_backfill() checks where it left off and continues
- Backfill runs as its own daemon thread, not via the scheduler

## Source Tracking
- Every prediction has a verified_by field: "massive_benzinga", "fmp_grades", etc.
- Every prediction from Benzinga has external_id = "bz_{benzinga_id}"
- Cross-scraper dedup checks all sources before inserting

## Current Scrapers and Schedule
- massive_benzinga: every 2 hours (daily analyst ratings from Benzinga API)
- fmp_grades: every 4 hours (analyst grades from Financial Modeling Prep)
- evaluator (auto_evaluate): every 1 hour (scores expired predictions)
- stats refresh: every 2 hours (recalculates forecaster accuracy/alpha)
- sweep_stuck: every 24 hours (marks old stuck predictions as no_data)
- watchdog: every 5 minutes (monitors health, releases stuck locks)

## Stagger
- First runs are staggered after boot: benzinga at +90s, evaluator at +95s, stats at +100s
- This prevents all jobs from hitting the DB simultaneously

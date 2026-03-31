# Database Safety Rules

## Connection Management
- Never hold DB connections during external API calls
- Always use context managers or try/finally to close connections
- Pattern: read from DB, close connection, call external API, open new connection, write results

## Locking
- SCRAPER_LOCK: all scrapers and the evaluator share ONE threading.Lock
- Stats refresh does NOT need the lock (lightweight SQL only)
- If lock is held, job SKIPS this cycle and tries next time
- Stuck job watchdog: force-release lock after 30 minutes

### Adding a new background job
```python
def my_job():
    if not SCRAPER_LOCK.acquire(blocking=False):
        print("[my_job] Skipped, another job running")
        return
    try:
        db = BgSessionLocal()
        try:
            # do work
        finally:
            db.close()
    finally:
        SCRAPER_LOCK.release()
```

## Connection Pools
- User-facing pool: pool_size=3, max_overflow=5 (8 max connections)
- Background job pool: pool_size=2, max_overflow=3 (5 max connections)
- Total: 13 max connections

## Timeouts
- User queries: 5 second statement_timeout (set on engine connect event)
- Background queries: 30 second statement_timeout
- Request timeout middleware: 8 seconds for all API endpoints

## Storage Guard
- Check DB size before insert batches, stop at 40GB
- Use pg_database_size(current_database()) to check

## Startup Rules
- Health endpoint (/health) must return 200 with ZERO database calls
- Never run migrations or heavy SQL synchronously in lifespan() before yield
- All startup DB work (table creation, migrations, seeds, admin promotion) goes in _startup_init() background thread
- Background thread starts 10 seconds after boot to let the app bind its port first

## Error Handling
- Always db.rollback() in except blocks to prevent PostgreSQL transaction abort cascade
- A failed query in PostgreSQL aborts the entire transaction; all subsequent queries on that session fail silently
- Use try/except with rollback around every independent query block

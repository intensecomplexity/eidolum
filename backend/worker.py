"""
Eidolum Background Worker
Runs all scheduled jobs independently from the API server.
Deploy as a separate Railway service so API pushes don't restart jobs.

Start: python worker.py
Health: GET http://localhost:$PORT/health
"""
import os
import sys
import time
import logging
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.executors.pool import ThreadPoolExecutor as APThreadPool
from sqlalchemy import text as sql_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("worker")

# Install API-key scrubber on httpx/urllib3/root loggers BEFORE any scraper
# imports so the very first request line is already protected. FMP /stable/
# only supports ?apikey= query auth, so this filter is the only thing
# keeping the FMP key out of plaintext logs.
from log_filter import install_key_scrubber
install_key_scrubber()

# Database
from database import BgSessionLocal, engine, Base

# Circuit breaker
from circuit_breaker import (
    db_is_healthy, mark_job_running, mark_job_done,
    acquire_job_lock, release_job_lock, watchdog_check,
    db_storage_ok, check_site_health_and_pause,
)

scheduler_last_run = {}


# ── Health check (Railway needs a port to monitor) ──────────────────────────
class _Health(BaseHTTPRequestHandler):
    def do_GET(self):
        import json
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", "service": "worker",
            "jobs": {k: v.isoformat() if v else None for k, v in scheduler_last_run.items()}
        }).encode())
    def log_message(self, *a): pass


# ── Job wrappers ────────────────────────────────────────────────────────────
def _guarded(name, fn):
    """Uses global SCRAPER_LOCK — only one guarded job at a time."""
    def wrapper():
        scheduler_last_run[name] = datetime.utcnow()
        if not db_is_healthy(name): return
        if not db_storage_ok(name): return
        if not acquire_job_lock(name): return
        mark_job_running(name)
        try:
            db = BgSessionLocal()
            try: fn(db)
            except Exception as e: log.error(f"[{name}] {e}")
            finally: db.close()
        finally:
            mark_job_done(name)
            release_job_lock(name)
    return wrapper

def _standalone(name, fn):
    """No global lock — runs independently."""
    def wrapper():
        scheduler_last_run[name] = datetime.utcnow()
        if not db_is_healthy(name): return
        mark_job_running(name)
        try: fn()
        except Exception as e: log.error(f"[{name}] {e}")
        finally: mark_job_done(name)
    return wrapper


# ── Job functions ───────────────────────────────────────────────────────────
def _massive_benzinga(db):
    from jobs.massive_benzinga import scrape_massive_ratings
    scrape_massive_ratings(db)

def _evaluator():
    from jobs.historical_evaluator import evaluate_batch, refresh_all_forecaster_stats
    # max_tickers=None → plan-aware default (5000 on Ultimate, 500 on Starter)
    r = evaluate_batch()
    if r.get("predictions_scored", 0) > 0: refresh_all_forecaster_stats()

def _refresh_stats():
    from jobs.historical_evaluator import refresh_all_forecaster_stats
    refresh_all_forecaster_stats()

def _fmp_grades():
    db = BgSessionLocal()
    try:
        from jobs.upgrade_scrapers import scrape_fmp_grades
        scrape_fmp_grades(db)
    finally: db.close()

def _sweep(db):
    from jobs.evaluator import sweep_stuck_predictions
    sweep_stuck_predictions(db)

def _retry_no_data():
    db = BgSessionLocal()
    try:
        from jobs.retry_no_data import retry_no_data_batch
        retry_no_data_batch(db, max_tickers=1000)
    finally: db.close()

def _analyst_notif(db):
    from jobs.analyst_notifications import run_analyst_notifications
    run_analyst_notifications(db)

def _url_backfill():
    db = BgSessionLocal()
    try:
        from jobs.backfill_urls import backfill_real_urls
        backfill_real_urls(db, max_per_run=2000)
    finally: db.close()

def _tournament():
    try:
        from routers.tournaments import score_active_tournaments
        db = BgSessionLocal()
        try: score_active_tournaments(db)
        finally: db.close()
    except Exception: pass

def _youtube():
    try:
        from jobs.youtube_scraper import run_youtube_scraper
        db = BgSessionLocal()
        try: run_youtube_scraper(db)
        finally: db.close()
    except Exception as e: log.error(f"[youtube] {e}")


def _drain_scraper_job_queue():
    """Drain pending rows from scraper_job_queue. Called on a 60s
    interval by APScheduler. Cross-service work queue: the eidolum
    API service INSERTs jobs here from admin endpoints; the worker
    (this service, hopeful-expression) actually runs them because
    scraping env vars (YOUTUBE_API_KEY, WEBSHARE_PROXY_*, etc.) live
    on this container.

    Currently handles exactly one job_type: 'youtube_fetch_channel'.
    Extend the if-ladder below when more job types are added. Per-job
    exceptions are caught and written to the `error` column so a
    single poison-pill row can't stall the whole queue.
    """
    db = BgSessionLocal()
    try:
        rows = db.execute(sql_text("""
            SELECT id, job_type, payload
            FROM scraper_job_queue
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT 10
        """)).fetchall()
        if not rows:
            return
        for row in rows:
            job_id, job_type, payload = row[0], row[1], row[2]
            # Mark running BEFORE starting work so a restart mid-job
            # doesn't redo it in an infinite loop (the drain only
            # picks up status='pending'). A job stuck in 'running'
            # is visible in the queue and can be manually reset.
            try:
                db.execute(sql_text("""
                    UPDATE scraper_job_queue
                    SET status = 'running', started_at = NOW()
                    WHERE id = :id AND status = 'pending'
                """), {"id": job_id})
                db.commit()
            except Exception as e:
                log.warning(f"[drain] mark-running failed for {job_id}: {e}")
                db.rollback()
                continue

            err = None
            try:
                if isinstance(payload, str):
                    import json as _json
                    payload_dict = _json.loads(payload)
                else:
                    payload_dict = payload or {}

                if job_type == "youtube_fetch_channel":
                    cid = payload_dict.get("channel_id")
                    cname = payload_dict.get("channel_name", cid)
                    log.info(f"[drain] youtube_fetch_channel {cid} ({cname})")
                    from jobs.youtube_channel_monitor import fetch_channel_now
                    fetch_channel_now(cid)
                else:
                    err = f"unknown job_type: {job_type}"
                    log.warning(f"[drain] {err}")
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:500]}"
                log.error(f"[drain] job {job_id} failed: {err}")

            try:
                db.execute(sql_text("""
                    UPDATE scraper_job_queue
                    SET status = :status, finished_at = NOW(), error = :err
                    WHERE id = :id
                """), {
                    "id": job_id,
                    "status": "error" if err else "done",
                    "err": err,
                })
                db.commit()
            except Exception as e:
                log.warning(f"[drain] finalize failed for {job_id}: {e}")
                db.rollback()
    finally:
        db.close()

def _enrich():
    try:
        from jobs.enrich_source_urls import enrich_batch
        db = BgSessionLocal()
        try: enrich_batch(db)
        finally: db.close()
    except Exception as e: log.error(f"[enrich] {e}")

def _watchlist_queue():
    try:
        from jobs.watchlist_notifier import queue_watchlist_notifications
        queue_watchlist_notifications()
    except Exception: pass

def _watchlist_digest():
    try:
        from jobs.watchlist_notifier import send_daily_digest
        send_daily_digest()
    except Exception: pass

def _weekly_digest():
    try:
        from jobs.weekly_digest import run_weekly_digest
        db = BgSessionLocal()
        try: run_weekly_digest(db)
        finally: db.close()
    except Exception: pass

def _watchdog():
    watchdog_check()
    check_site_health_and_pause()


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info("[Worker] Eidolum Background Worker starting")
    log.info(f"[Worker] MASSIVE_API_KEY: {bool(os.getenv('MASSIVE_API_KEY', '').strip())}")
    log.info(f"[Worker] FMP_KEY: {bool(os.getenv('FMP_KEY', '').strip())}")
    log.info(f"[Worker] TIINGO_API_KEY: {bool(os.getenv('TIINGO_API_KEY', '').strip())}")
    log.info(f"[Worker] APIFY_API_TOKEN: {bool(os.getenv('APIFY_API_TOKEN', '').strip())}")
    log.info("=" * 60)

    # Health server
    port = int(os.environ.get("PORT", 8081))
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", port), _Health).serve_forever(), daemon=True).start()
    log.info(f"[Worker] Health on :{port}")

    # Tables
    try:
        Base.metadata.create_all(bind=engine)
        log.info("[Worker] Tables OK")
    except Exception as e:
        log.error(f"[Worker] Table error: {e}")

    # Pillar 4: ensure predictions.tweet_id column exists on existing DBs.
    # Base.metadata.create_all does not ALTER existing tables, so we add it explicitly.
    try:
        with engine.connect() as conn:
            conn.execute(sql_text(
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS tweet_id BIGINT"
            ))
            conn.execute(sql_text(
                "CREATE INDEX IF NOT EXISTS idx_predictions_tweet_id "
                "ON predictions(tweet_id) WHERE tweet_id IS NOT NULL"
            ))
            conn.commit()
        log.info("[Worker] predictions.tweet_id column ensured")
    except Exception as e:
        log.error(f"[Worker] tweet_id migration error: {e}")

    # Bug 1: ensure x_scraper_rejections.rejected_at has a Postgres DEFAULT NOW().
    # The model previously used a Python-only default, so existing tables have
    # no server-side default and raw INSERTs leave the column NULL. Adding the
    # default here is idempotent — re-running it is safe.
    try:
        with engine.connect() as conn:
            conn.execute(sql_text(
                "ALTER TABLE x_scraper_rejections "
                "ALTER COLUMN rejected_at SET DEFAULT NOW()"
            ))
            conn.commit()
        log.info("[Worker] x_scraper_rejections.rejected_at default ensured")
    except Exception as e:
        # Table may not exist yet on a fresh DB — create_all above will have
        # generated it with the correct server_default already, so this is
        # safe to skip.
        log.warning(f"[Worker] rejected_at default migration: {e}")

    # Add closeness_level column + index for the rejection viewer filter.
    # Idempotent: safe to re-run.
    try:
        with engine.connect() as conn:
            conn.execute(sql_text(
                "ALTER TABLE x_scraper_rejections "
                "ADD COLUMN IF NOT EXISTS closeness_level SMALLINT"
            ))
            conn.execute(sql_text(
                "CREATE INDEX IF NOT EXISTS idx_x_rejections_closeness "
                "ON x_scraper_rejections(closeness_level)"
            ))
            conn.commit()
        log.info("[Worker] x_scraper_rejections.closeness_level ensured")
    except Exception as e:
        log.warning(f"[Worker] closeness_level migration: {e}")

    # youtube_channels — auto-pruning columns. Channels with 5 reached-Haiku
    # videos and 0 inserted predictions get soft-deactivated by the channel
    # monitor. Idempotent: ALTER ... IF NOT EXISTS, safe on every boot.
    # Backfill happens in main.py / channel_monitor on startup so the
    # counters reflect historical reality on first deploy.
    try:
        with engine.connect() as conn:
            for ddl in (
                "ALTER TABLE youtube_channels ADD COLUMN IF NOT EXISTS "
                "videos_processed_count INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE youtube_channels ADD COLUMN IF NOT EXISTS "
                "predictions_extracted_count INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE youtube_channels ADD COLUMN IF NOT EXISTS "
                "deactivated_at TIMESTAMP",
                "ALTER TABLE youtube_channels ADD COLUMN IF NOT EXISTS "
                "deactivation_reason VARCHAR(50)",
            ):
                conn.execute(sql_text(ddl))
            conn.commit()
        log.info("[Worker] youtube_channels pruning columns ensured")
    except Exception as e:
        log.warning(f"[Worker] youtube_channels pruning migration: {e}")

    # One-time backfill of the new counters from youtube_videos. Only
    # touches rows whose counters are still 0 (i.e. never written by
    # the live counter increment). Safe to re-run: a row that already
    # has positive counters is left alone. transcript_status values
    # 'ok_inserted' / 'ok_no_predictions' are the "reached Haiku and
    # got a verdict" set; classifier_error is excluded so a Haiku outage
    # cannot retroactively poison the pruning threshold.
    try:
        with engine.connect() as conn:
            conn.execute(sql_text("""
                UPDATE youtube_channels c
                SET videos_processed_count = COALESCE((
                    SELECT COUNT(*) FROM youtube_videos v
                    WHERE v.channel_name = c.channel_name
                      AND v.transcript_status IN ('ok_inserted', 'ok_no_predictions')
                ), 0)
                WHERE videos_processed_count = 0
            """))
            conn.execute(sql_text("""
                UPDATE youtube_channels c
                SET predictions_extracted_count = COALESCE((
                    SELECT COUNT(*) FROM youtube_videos v
                    WHERE v.channel_name = c.channel_name
                      AND v.predictions_extracted > 0
                ), 0)
                WHERE predictions_extracted_count = 0
            """))
            conn.commit()
        log.info("[Worker] youtube_channels counter backfill complete")
    except Exception as e:
        log.warning(f"[Worker] youtube_channels counter backfill: {e}")

    # youtube_channel_meta — admin-facing metadata for YouTube channels,
    # FK'd to forecasters. Mirrors the shape of tracked_x_accounts. Backs
    # the /admin/youtube-channels admin page. Idempotent.
    try:
        with engine.connect() as conn:
            conn.execute(sql_text("""
                CREATE TABLE IF NOT EXISTS youtube_channel_meta (
                    id SERIAL PRIMARY KEY,
                    forecaster_id INTEGER NOT NULL REFERENCES forecasters(id) ON DELETE CASCADE,
                    channel_id VARCHAR(30) NOT NULL,
                    tier INTEGER NOT NULL DEFAULT 4,
                    notes TEXT,
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    added_date TIMESTAMP NOT NULL DEFAULT NOW(),
                    last_scraped_at TIMESTAMP,
                    last_scrape_videos_found INTEGER DEFAULT 0,
                    last_scrape_predictions_extracted INTEGER DEFAULT 0,
                    total_videos_scraped INTEGER DEFAULT 0,
                    total_predictions_extracted INTEGER DEFAULT 0,
                    videos_processed_count INTEGER DEFAULT 0,
                    predictions_extracted_count INTEGER DEFAULT 0,
                    deactivated_at TIMESTAMP,
                    deactivation_reason VARCHAR(50),
                    CONSTRAINT uq_yt_meta_forecaster UNIQUE (forecaster_id),
                    CONSTRAINT uq_yt_meta_channel_id UNIQUE (channel_id),
                    CONSTRAINT ck_yt_meta_tier CHECK (tier BETWEEN 1 AND 4)
                )
            """))
            conn.execute(sql_text(
                "CREATE INDEX IF NOT EXISTS idx_yt_meta_active "
                "ON youtube_channel_meta(active)"
            ))
            conn.execute(sql_text(
                "CREATE INDEX IF NOT EXISTS idx_yt_meta_tier "
                "ON youtube_channel_meta(tier)"
            ))
            conn.execute(sql_text("""
                INSERT INTO youtube_channel_meta
                    (forecaster_id, channel_id, tier, active, added_date)
                SELECT f.id, f.channel_id, 4, TRUE, NOW()
                FROM forecasters f
                WHERE f.platform = 'youtube'
                  AND f.channel_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM youtube_channel_meta m
                      WHERE m.forecaster_id = f.id
                  )
            """))
            conn.commit()
        log.info("[Worker] youtube_channel_meta table + backfill ready")
    except Exception as e:
        log.warning(f"[Worker] youtube_channel_meta migration: {e}")

    # sector_etf_aliases — sector → ETF mapping for YouTube sector call
    # extraction. Seeded once on first run with the canonical mappings
    # below; admin can add more via /admin/sector-aliases without a deploy.
    try:
        with engine.connect() as conn:
            conn.execute(sql_text("""
                CREATE TABLE IF NOT EXISTS sector_etf_aliases (
                    id SERIAL PRIMARY KEY,
                    alias VARCHAR(100) NOT NULL UNIQUE,
                    canonical_sector VARCHAR(50) NOT NULL,
                    etf_ticker VARCHAR(10) NOT NULL,
                    notes TEXT
                )
            """))
            conn.execute(sql_text(
                "CREATE INDEX IF NOT EXISTS idx_sector_aliases_canonical "
                "ON sector_etf_aliases(canonical_sector)"
            ))
            _seed_aliases = [
                ('technology', 'technology', 'XLK', 'Tech sector ETF'),
                ('tech', 'technology', 'XLK', 'Tech sector alias'),
                ('big tech', 'technology', 'QQQ', 'Big tech via Nasdaq-100'),
                ('semiconductors', 'semiconductors', 'SOXX', 'Semi sector ETF'),
                ('semis', 'semiconductors', 'SOXX', 'Semi alias'),
                ('chip stocks', 'semiconductors', 'SOXX', 'Semi alias'),
                ('chips', 'semiconductors', 'SOXX', 'Semi alias'),
                ('energy', 'energy', 'XLE', 'Energy sector ETF'),
                ('oil', 'energy', 'XLE', 'Oil alias for energy'),
                ('oil stocks', 'energy', 'XLE', 'Energy alias'),
                ('financials', 'financials', 'XLF', 'Financial sector ETF'),
                ('banks', 'financials', 'KBE', 'Bank sector ETF'),
                ('big banks', 'financials', 'KBE', 'Bank alias'),
                ('healthcare', 'healthcare', 'XLV', 'Healthcare sector ETF'),
                ('health care', 'healthcare', 'XLV', 'Healthcare alias'),
                ('biotech', 'biotech', 'XBI', 'Biotech ETF'),
                ('biotechnology', 'biotech', 'XBI', 'Biotech alias'),
                ('pharma', 'pharma', 'IHE', 'Pharma ETF'),
                ('pharmaceuticals', 'pharma', 'IHE', 'Pharma alias'),
                ('industrials', 'industrials', 'XLI', 'Industrial sector ETF'),
                ('consumer discretionary', 'consumer_discretionary', 'XLY', 'Consumer disc ETF'),
                ('retail', 'consumer_discretionary', 'XRT', 'Retail ETF'),
                ('consumer staples', 'consumer_staples', 'XLP', 'Consumer staples ETF'),
                ('utilities', 'utilities', 'XLU', 'Utility sector ETF'),
                ('real estate', 'real_estate', 'XLRE', 'REIT sector ETF'),
                ('reits', 'real_estate', 'XLRE', 'REIT alias'),
                ('communication services', 'communications', 'XLC', 'Comm services ETF'),
                ('telecom', 'communications', 'XLC', 'Telecom alias'),
                ('materials', 'materials', 'XLB', 'Materials sector ETF'),
                ('gold', 'gold', 'GLD', 'Gold ETF'),
                ('gold miners', 'gold_miners', 'GDX', 'Gold miners ETF'),
                ('silver', 'silver', 'SLV', 'Silver ETF'),
                ('crypto', 'crypto', 'BITO', 'Crypto futures ETF, maps to BTC via BITO'),
                ('bitcoin', 'bitcoin', 'BITO', 'BTC via BITO ETF'),
                ('bonds', 'bonds', 'TLT', '20+ year treasury bonds'),
                ('long bonds', 'bonds', 'TLT', 'Bonds alias'),
                ('short bonds', 'short_bonds', 'SHY', '1-3 year treasuries'),
                ('emerging markets', 'emerging_markets', 'EEM', 'EM ETF'),
                ('china', 'china', 'FXI', 'China large cap ETF'),
                ('chinese stocks', 'china', 'FXI', 'China alias'),
                ('europe', 'europe', 'VGK', 'European stocks ETF'),
                ('small caps', 'small_caps', 'IWM', 'Russell 2000'),
                ('russell 2000', 'small_caps', 'IWM', 'Small caps index'),
                ('large caps', 'large_caps', 'SPY', 'S&P 500 proxy'),
                ('s&p 500', 'sp500', 'SPY', 'S&P 500 index'),
                ('sp500', 'sp500', 'SPY', 'S&P 500 alias'),
                ('nasdaq', 'nasdaq', 'QQQ', 'Nasdaq-100 proxy'),
                # ── Expanded aliases (sub-sectors, thematic, intl, crypto, factors) ──
                # Broad market (expanded)
                ('the market', 'sp500', 'SPY', 'Generic market mention'),
                ('stocks', 'sp500', 'SPY', 'Generic stocks mention'),
                ('equities', 'sp500', 'SPY', 'Formal equities term'),
                ('us stocks', 'sp500', 'SPY', 'US equity mention'),
                ('us equities', 'sp500', 'SPY', 'US equity mention'),
                ('the spy', 'sp500', 'SPY', 'Trader shorthand for S&P 500'),
                ('s and p', 'sp500', 'SPY', 'Verbal S&P alias'),
                ('s&p', 'sp500', 'SPY', 'S&P abbreviation'),
                ('standard and poors', 'sp500', 'SPY', 'Full name'),
                ('dow', 'dow', 'DIA', 'Dow Jones Industrial Average'),
                ('dow jones', 'dow', 'DIA', 'Dow alias'),
                ('industrial average', 'dow', 'DIA', 'Dow alias'),
                ('the dow', 'dow', 'DIA', 'Dow alias'),
                ('qqq', 'nasdaq', 'QQQ', 'Nasdaq 100 ETF ticker'),
                ('nasdaq 100', 'nasdaq', 'QQQ', 'Nasdaq 100'),
                ('tech heavy', 'nasdaq', 'QQQ', 'Nasdaq as tech-heavy proxy'),
                ('total market', 'total_market', 'VTI', 'Vanguard total market'),
                ('all us stocks', 'total_market', 'VTI', 'Total market proxy'),
                ('mid caps', 'mid_caps', 'IJH', 'Mid-cap index'),
                ('mid cap stocks', 'mid_caps', 'IJH', 'Mid-cap alias'),
                ('micro caps', 'micro_caps', 'IWC', 'Micro-cap ETF'),
                # Technology sub-sectors
                ('cloud computing', 'cloud', 'SKYY', 'Cloud computing ETF'),
                ('cloud stocks', 'cloud', 'SKYY', 'Cloud alias'),
                ('saas', 'saas', 'CLOU', 'SaaS cloud ETF'),
                ('software', 'software', 'IGV', 'Software ETF'),
                ('software stocks', 'software', 'IGV', 'Software alias'),
                ('cybersecurity', 'cybersecurity', 'HACK', 'Cybersecurity ETF'),
                ('cyber security', 'cybersecurity', 'HACK', 'Cybersecurity alias'),
                ('cyber', 'cybersecurity', 'HACK', 'Cybersecurity shorthand'),
                ('ai stocks', 'ai', 'BOTZ', 'AI and robotics ETF'),
                ('artificial intelligence', 'ai', 'BOTZ', 'AI alias'),
                ('ai', 'ai', 'BOTZ', 'AI shorthand'),
                ('robotics', 'robotics', 'ROBO', 'Robotics ETF'),
                ('robots', 'robotics', 'ROBO', 'Robotics alias'),
                ('fintech', 'fintech', 'FINX', 'Fintech ETF'),
                ('fin tech', 'fintech', 'FINX', 'Fintech alias'),
                ('payments', 'fintech', 'IPAY', 'Payments ETF'),
                ('internet', 'internet', 'FDN', 'Internet ETF'),
                ('internet stocks', 'internet', 'FDN', 'Internet alias'),
                ('social media', 'social_media', 'SOCL', 'Social media ETF'),
                ('cloud infrastructure', 'cloud', 'WCLD', 'Pure cloud software ETF'),
                ('data centers', 'data_centers', 'SRVR', 'Data center REIT ETF'),
                ('5g', '5g', 'FIVG', '5G network ETF'),
                ('ev', 'ev', 'DRIV', 'Electric vehicle ETF'),
                ('electric vehicles', 'ev', 'DRIV', 'EV alias'),
                ('ev stocks', 'ev', 'DRIV', 'EV alias'),
                ('autonomous vehicles', 'autonomous', 'DRIV', 'Autonomous vehicles proxy'),
                ('self driving', 'autonomous', 'DRIV', 'Self driving alias'),
                ('metaverse', 'metaverse', 'META', 'Meta as metaverse proxy — weak mapping, prefer ticker'),
                ('gaming', 'gaming', 'ESPO', 'Video games ETF'),
                ('video games', 'gaming', 'ESPO', 'Gaming alias'),
                ('esports', 'gaming', 'ESPO', 'Esports ETF'),
                # Semiconductor sub-sectors
                ('chip makers', 'semiconductors', 'SOXX', 'Semi alias'),
                ('semiconductor stocks', 'semiconductors', 'SOXX', 'Semi full name'),
                ('fabless', 'semiconductors', 'SOXX', 'Fabless chip design'),
                ('foundries', 'semiconductors', 'SOXX', 'Chip foundries'),
                ('memory chips', 'semiconductors', 'SOXX', 'Memory semi sub-sector'),
                ('analog chips', 'semiconductors', 'SOXX', 'Analog semi sub-sector'),
                ('sox', 'semiconductors', 'SOXX', 'SOX index alias'),
                # Financials expanded
                ('regional banks', 'regional_banks', 'KRE', 'Regional banks ETF'),
                ('small banks', 'regional_banks', 'KRE', 'Regional banks alias'),
                ('insurance', 'insurance', 'KIE', 'Insurance ETF'),
                ('insurance stocks', 'insurance', 'KIE', 'Insurance alias'),
                ('asset managers', 'asset_managers', 'XLF', 'Asset managers in financial sector'),
                ('brokers', 'brokers', 'IAI', 'Broker dealers ETF'),
                ('broker dealers', 'brokers', 'IAI', 'Brokers alias'),
                ('capital markets', 'capital_markets', 'KCE', 'Capital markets ETF'),
                ('private equity', 'private_equity', 'PSP', 'Listed private equity ETF'),
                ('pe', 'private_equity', 'PSP', 'PE shorthand'),
                # Healthcare sub-sectors
                ('medical devices', 'medical_devices', 'IHI', 'Medical devices ETF'),
                ('med tech', 'medical_devices', 'IHI', 'Medtech alias'),
                ('medtech', 'medical_devices', 'IHI', 'Medtech alias'),
                ('genomics', 'genomics', 'ARKG', 'Genomics ETF'),
                ('gene therapy', 'genomics', 'ARKG', 'Gene therapy'),
                ('cannabis', 'cannabis', 'MSOS', 'US cannabis ETF'),
                ('weed stocks', 'cannabis', 'MSOS', 'Cannabis alias'),
                ('marijuana', 'cannabis', 'MSOS', 'Cannabis alias'),
                ('hospitals', 'hospitals', 'IHF', 'Healthcare providers'),
                # Energy sub-sectors
                ('renewables', 'renewables', 'ICLN', 'Clean energy ETF'),
                ('renewable energy', 'renewables', 'ICLN', 'Renewables alias'),
                ('clean energy', 'renewables', 'ICLN', 'Clean energy alias'),
                ('solar', 'solar', 'TAN', 'Solar ETF'),
                ('solar stocks', 'solar', 'TAN', 'Solar alias'),
                ('wind', 'wind', 'FAN', 'Wind energy ETF'),
                ('wind energy', 'wind', 'FAN', 'Wind alias'),
                ('uranium', 'uranium', 'URA', 'Uranium ETF'),
                ('nuclear', 'nuclear', 'URA', 'Nuclear via uranium'),
                ('nuclear energy', 'nuclear', 'URA', 'Nuclear alias'),
                ('natural gas', 'natural_gas', 'UNG', 'Natural gas ETF'),
                ('gas stocks', 'natural_gas', 'XOP', 'Oil & gas E&P as gas proxy'),
                ('oil and gas', 'energy', 'XLE', 'Oil & gas'),
                ('crude', 'oil', 'USO', 'Crude oil ETF'),
                ('crude oil', 'oil', 'USO', 'Crude oil'),
                ('brent', 'oil', 'BNO', 'Brent crude ETF'),
                ('wti', 'oil', 'USO', 'WTI crude proxy'),
                ('exploration and production', 'energy_e_and_p', 'XOP', 'E&P ETF'),
                ('pipelines', 'pipelines', 'AMLP', 'MLP pipeline ETF'),
                ('mlps', 'pipelines', 'AMLP', 'MLP alias'),
                ('refiners', 'refiners', 'CRAK', 'Oil refiners ETF'),
                # Materials and commodities
                ('copper', 'copper', 'COPX', 'Copper miners ETF'),
                ('copper miners', 'copper', 'COPX', 'Copper miners'),
                ('lithium', 'lithium', 'LIT', 'Lithium and battery ETF'),
                ('battery stocks', 'lithium', 'LIT', 'Battery/lithium alias'),
                ('steel', 'steel', 'SLX', 'Steel ETF'),
                ('aluminum', 'aluminum', 'XME', 'Metals & mining as aluminum proxy'),
                ('mining', 'mining', 'XME', 'Metals & mining ETF'),
                ('miners', 'mining', 'XME', 'Miners alias'),
                ('metals', 'materials', 'XLB', 'Metals/materials'),
                ('commodities', 'commodities', 'DBC', 'Broad commodities ETF'),
                ('broad commodities', 'commodities', 'DBC', 'Commodities alias'),
                ('agriculture', 'agriculture', 'DBA', 'Agriculture commodities ETF'),
                ('ag stocks', 'agriculture', 'DBA', 'Agriculture alias'),
                ('farm', 'agriculture', 'DBA', 'Farming alias'),
                ('timber', 'timber', 'WOOD', 'Timber ETF'),
                ('water', 'water', 'PHO', 'Water ETF'),
                # Consumer and retail
                ('e commerce', 'ecommerce', 'XRT', 'Retail ETF as e-commerce proxy'),
                ('ecommerce', 'ecommerce', 'XRT', 'Ecommerce alias'),
                ('online retail', 'ecommerce', 'XRT', 'Online retail'),
                ('luxury', 'luxury', 'XLY', 'Luxury via consumer discretionary'),
                ('travel', 'travel', 'AWAY', 'Travel ETF'),
                ('travel stocks', 'travel', 'AWAY', 'Travel alias'),
                ('airlines', 'airlines', 'JETS', 'Airlines ETF'),
                ('cruise lines', 'travel', 'AWAY', 'Cruise via travel'),
                ('hotels', 'hotels', 'AWAY', 'Hotels via travel'),
                ('restaurants', 'restaurants', 'EATZ', 'Restaurant ETF'),
                ('food', 'food', 'PBJ', 'Food & beverage ETF'),
                ('beverages', 'food', 'PBJ', 'Beverages via food'),
                ('homebuilders', 'homebuilders', 'XHB', 'Homebuilders ETF'),
                ('home builders', 'homebuilders', 'XHB', 'Homebuilders alias'),
                ('housing', 'homebuilders', 'XHB', 'Housing proxy'),
                ('housing stocks', 'homebuilders', 'XHB', 'Housing alias'),
                # Real estate sub-sectors
                ('commercial real estate', 'real_estate', 'VNQ', 'Commercial REITs'),
                ('cre', 'real_estate', 'VNQ', 'CRE shorthand'),
                ('residential reits', 'residential_reits', 'REZ', 'Residential REITs ETF'),
                ('mortgage reits', 'mortgage_reits', 'REM', 'Mortgage REITs ETF'),
                ('m reits', 'mortgage_reits', 'REM', 'mREITs alias'),
                # Industrials and defense
                ('defense', 'defense', 'ITA', 'Aerospace & defense ETF'),
                ('defense stocks', 'defense', 'ITA', 'Defense alias'),
                ('aerospace', 'defense', 'ITA', 'Aerospace via defense'),
                ('weapons', 'defense', 'ITA', 'Defense alias'),
                ('transports', 'transports', 'IYT', 'Transportation ETF'),
                ('transportation', 'transports', 'IYT', 'Transports alias'),
                ('trucking', 'transports', 'IYT', 'Trucking via transports'),
                ('shipping', 'shipping', 'BOAT', 'Shipping ETF'),
                ('rails', 'rails', 'IYT', 'Rails via transports'),
                ('railroads', 'rails', 'IYT', 'Railroads alias'),
                # Thematic
                ('esg', 'esg', 'ESGU', 'ESG ETF'),
                ('sustainable', 'esg', 'ESGU', 'ESG alias'),
                ('infrastructure', 'infrastructure', 'PAVE', 'US infrastructure ETF'),
                ('infrastructure stocks', 'infrastructure', 'PAVE', 'Infrastructure alias'),
                ('space', 'space', 'UFO', 'Space ETF'),
                ('space stocks', 'space', 'UFO', 'Space alias'),
                ('space exploration', 'space', 'UFO', 'Space alias'),
                ('quantum computing', 'quantum', 'QTUM', 'Quantum computing ETF'),
                ('quantum', 'quantum', 'QTUM', 'Quantum alias'),
                ('blockchain', 'blockchain', 'BLOK', 'Blockchain ETF'),
                ('web3', 'blockchain', 'BLOK', 'Web3 via blockchain'),
                ('disruptive', 'disruptive', 'ARKK', 'Disruptive innovation ETF'),
                ('innovation', 'disruptive', 'ARKK', 'Innovation alias'),
                ('cathie wood', 'disruptive', 'ARKK', 'ARKK nickname'),
                ('ark', 'disruptive', 'ARKK', 'ARK shorthand'),
                # International and country-specific
                ('international stocks', 'international', 'VEA', 'Developed intl ETF'),
                ('developed markets', 'international', 'VEA', 'Developed intl alias'),
                ('japan', 'japan', 'EWJ', 'Japan ETF'),
                ('japanese stocks', 'japan', 'EWJ', 'Japan alias'),
                ('india', 'india', 'INDA', 'India ETF'),
                ('indian stocks', 'india', 'INDA', 'India alias'),
                ('brazil', 'brazil', 'EWZ', 'Brazil ETF'),
                ('mexico', 'mexico', 'EWW', 'Mexico ETF'),
                ('taiwan', 'taiwan', 'EWT', 'Taiwan ETF'),
                ('south korea', 'korea', 'EWY', 'South Korea ETF'),
                ('korea', 'korea', 'EWY', 'Korea alias'),
                ('vietnam', 'vietnam', 'VNM', 'Vietnam ETF'),
                ('indonesia', 'indonesia', 'EIDO', 'Indonesia ETF'),
                ('germany', 'germany', 'EWG', 'Germany ETF'),
                ('uk', 'uk', 'EWU', 'UK ETF'),
                ('united kingdom', 'uk', 'EWU', 'UK alias'),
                ('france', 'france', 'EWQ', 'France ETF'),
                ('canada', 'canada', 'EWC', 'Canada ETF'),
                ('australia', 'australia', 'EWA', 'Australia ETF'),
                ('frontier markets', 'frontier', 'FM', 'Frontier markets ETF'),
                ('em', 'emerging_markets', 'EEM', 'EM shorthand'),
                ('emerging', 'emerging_markets', 'EEM', 'Emerging alias'),
                # Crypto and digital assets
                ('ethereum', 'ethereum', 'ETHE', 'Grayscale Ethereum trust, closest ETH proxy'),
                ('eth', 'ethereum', 'ETHE', 'ETH alias'),
                ('btc', 'bitcoin', 'IBIT', 'Spot Bitcoin ETF (iShares)'),
                ('bitcoin etf', 'bitcoin', 'IBIT', 'Spot Bitcoin ETF'),
                ('crypto stocks', 'crypto_stocks', 'BITQ', 'Crypto-exposed equities ETF'),
                ('blockchain stocks', 'blockchain', 'BLOK', 'Blockchain alias'),
                ('miners crypto', 'crypto_miners', 'WGMI', 'Crypto miners ETF'),
                ('bitcoin miners', 'crypto_miners', 'WGMI', 'BTC miners alias'),
                # Bonds and rates
                ('treasuries', 'bonds', 'TLT', 'Long treasuries'),
                ('treasury bonds', 'bonds', 'TLT', 'Treasuries'),
                ('long term bonds', 'bonds', 'TLT', 'Long bonds'),
                ('20 year bonds', 'bonds', 'TLT', '20-year treasury ETF'),
                ('10 year', 'tenyr', 'IEF', '10-year treasury ETF'),
                ('10 year treasury', 'tenyr', 'IEF', '10-year alias'),
                ('short term bonds', 'short_bonds', 'SHY', 'Short treasuries'),
                ('tbills', 'tbills', 'BIL', 'T-bills ETF'),
                ('t bills', 'tbills', 'BIL', 'T-bills alias'),
                ('corporate bonds', 'corporate_bonds', 'LQD', 'Investment grade corporate'),
                ('investment grade', 'corporate_bonds', 'LQD', 'IG alias'),
                ('high yield', 'high_yield', 'HYG', 'Junk bonds ETF'),
                ('junk bonds', 'high_yield', 'HYG', 'Junk alias'),
                ('hyg', 'high_yield', 'HYG', 'HYG ticker'),
                ('muni bonds', 'munis', 'MUB', 'Municipal bonds ETF'),
                ('municipals', 'munis', 'MUB', 'Munis alias'),
                ('tips', 'tips', 'TIP', 'Treasury inflation protected'),
                ('inflation protected', 'tips', 'TIP', 'TIPS alias'),
                # Volatility and hedges
                ('vix', 'volatility', 'VXX', 'VIX futures ETF'),
                ('volatility', 'volatility', 'VXX', 'Volatility alias'),
                ('fear index', 'volatility', 'VXX', 'VIX alias'),
                ('hedges', 'volatility', 'VXX', 'Generic hedge'),
                # Dividend and factor
                ('dividend stocks', 'dividends', 'SCHD', 'Dividend ETF'),
                ('dividends', 'dividends', 'SCHD', 'Dividends alias'),
                ('dividend growth', 'dividend_growth', 'SCHD', 'Dividend growth alias'),
                ('high dividend', 'high_dividend', 'VYM', 'High dividend ETF'),
                ('yield stocks', 'high_dividend', 'VYM', 'Yield alias'),
                ('value', 'value', 'IVE', 'Value ETF'),
                ('value stocks', 'value', 'IVE', 'Value alias'),
                ('growth', 'growth', 'IVW', 'Growth ETF'),
                ('growth stocks', 'growth', 'IVW', 'Growth alias'),
                ('momentum', 'momentum', 'MTUM', 'Momentum factor ETF'),
                ('quality', 'quality', 'QUAL', 'Quality factor ETF'),
                ('low vol', 'low_vol', 'USMV', 'Low volatility ETF'),
                ('low volatility', 'low_vol', 'USMV', 'Low vol alias'),
                # ── v2 expansion: broader coverage of sub-sectors, countries,
                # commodities, factors, crypto, bonds, volatility. Every alias
                # is lowercase; every etf_ticker is a real US-listed ETF.
                # Overlaps with earlier rows hit ON CONFLICT DO NOTHING and
                # preserve the original mapping — intended behavior.
                # Broad US market indices
                ('stock market', 'sp500', 'SPY', 'Generic'),
                ('american stocks', 'sp500', 'SPY', 'US colloquial'),
                ('spx', 'sp500', 'SPY', 'S&P index abbrev'),
                ('sp 500', 'sp500', 'SPY', 'Alt spelling'),
                ('voo', 'sp500', 'SPY', 'Vanguard S&P alias'),
                ('ivv', 'sp500', 'SPY', 'iShares S&P alias'),
                ('blue chips', 'dow', 'DIA', 'Blue chip stocks'),
                ('blue chip stocks', 'dow', 'DIA', 'Blue chip alias'),
                ('triple q', 'nasdaq', 'QQQ', 'QQQ verbal'),
                ('the nasdaq', 'nasdaq', 'QQQ', 'Nasdaq alias'),
                ('tech index', 'nasdaq', 'QQQ', 'Tech index'),
                ('whole market', 'total_market', 'VTI', 'Total market'),
                ('vti', 'total_market', 'VTI', 'VTI ticker'),
                ('russell two thousand', 'small_caps', 'IWM', 'Russell verbal'),
                ('iwm', 'small_caps', 'IWM', 'IWM ticker'),
                ('small cap', 'small_caps', 'IWM', 'Small cap'),
                ('small cap stocks', 'small_caps', 'IWM', 'Small caps'),
                ('mid cap', 'mid_caps', 'IJH', 'Mid-cap'),
                ('ijh', 'mid_caps', 'IJH', 'IJH ticker'),
                ('micro cap', 'micro_caps', 'IWC', 'Micro-cap'),
                ('micro cap stocks', 'micro_caps', 'IWC', 'Micro caps'),
                ('mega caps', 'mega_caps', 'MGC', 'Mega-cap'),
                ('mega cap stocks', 'mega_caps', 'MGC', 'Mega caps'),
                ('large cap stocks', 'large_caps', 'SPY', 'Large caps'),
                # Technology broad + mag 7
                ('tech sector', 'technology', 'XLK', 'Tech sector'),
                ('tech stocks', 'technology', 'XLK', 'Tech stocks'),
                ('technology sector', 'technology', 'XLK', 'Tech formal'),
                ('xlk', 'technology', 'XLK', 'XLK ticker'),
                ('faang', 'big_tech', 'QQQ', 'FAANG'),
                ('faang stocks', 'big_tech', 'QQQ', 'FAANG'),
                ('mag 7', 'big_tech', 'QQQ', 'Magnificent 7'),
                ('mag seven', 'big_tech', 'QQQ', 'Mag 7 alt'),
                ('magnificent 7', 'big_tech', 'QQQ', 'Mag 7 full'),
                ('magnificent seven', 'big_tech', 'QQQ', 'Mag 7 formal'),
                # Technology sub-sectors
                ('cloud', 'cloud', 'SKYY', 'Cloud'),
                ('the cloud', 'cloud', 'SKYY', 'Cloud colloquial'),
                ('skyy', 'cloud', 'SKYY', 'SKYY ticker'),
                ('saas stocks', 'saas', 'CLOU', 'SaaS alias'),
                ('software as a service', 'saas', 'CLOU', 'SaaS formal'),
                ('clou', 'saas', 'CLOU', 'CLOU ticker'),
                ('enterprise software', 'software', 'IGV', 'Enterprise SW'),
                ('igv', 'software', 'IGV', 'IGV ticker'),
                ('cyber stocks', 'cybersecurity', 'HACK', 'Cyber'),
                ('security stocks', 'cybersecurity', 'HACK', 'Security'),
                ('infosec', 'cybersecurity', 'HACK', 'Infosec'),
                ('hack', 'cybersecurity', 'HACK', 'HACK ticker'),
                ('cibr', 'cybersecurity', 'CIBR', 'CIBR ticker'),
                ('ai theme', 'ai', 'BOTZ', 'AI theme'),
                ('ai play', 'ai', 'BOTZ', 'AI colloquial'),
                ('ai boom', 'ai', 'BOTZ', 'AI boom'),
                ('ai revolution', 'ai', 'BOTZ', 'AI revolution'),
                ('machine learning', 'ai', 'BOTZ', 'ML'),
                ('botz', 'ai', 'BOTZ', 'BOTZ ticker'),
                ('robotics stocks', 'robotics', 'ROBO', 'Robotics'),
                ('robo', 'robotics', 'ROBO', 'ROBO ticker'),
                ('fintech stocks', 'fintech', 'FINX', 'Fintech'),
                ('finx', 'fintech', 'FINX', 'FINX ticker'),
                ('payment stocks', 'payments', 'IPAY', 'Payments'),
                ('digital payments', 'payments', 'IPAY', 'Digital payments'),
                ('ipay', 'payments', 'IPAY', 'IPAY ticker'),
                ('web stocks', 'internet', 'FDN', 'Web stocks'),
                ('fdn', 'internet', 'FDN', 'FDN ticker'),
                ('social media stocks', 'social_media', 'SOCL', 'Social media'),
                ('socl', 'social_media', 'SOCL', 'SOCL ticker'),
                ('data center stocks', 'data_centers', 'SRVR', 'Data centers'),
                ('srvr', 'data_centers', 'SRVR', 'SRVR ticker'),
                ('five g', '5g', 'FIVG', '5G verbal'),
                ('5g stocks', '5g', 'FIVG', '5G stocks'),
                ('fivg', '5g', 'FIVG', 'FIVG ticker'),
                ('evs', 'ev', 'DRIV', 'EVs'),
                ('electric vehicle stocks', 'ev', 'DRIV', 'EV stocks'),
                ('autonomous driving', 'autonomous', 'DRIV', 'Autonomous'),
                ('self driving cars', 'autonomous', 'DRIV', 'Self driving cars'),
                ('driv', 'ev', 'DRIV', 'DRIV ticker'),
                ('video game stocks', 'gaming', 'ESPO', 'Gaming'),
                ('gaming stocks', 'gaming', 'ESPO', 'Gaming'),
                ('espo', 'gaming', 'ESPO', 'ESPO ticker'),
                # Semiconductors
                ('chipmakers', 'semiconductors', 'SOXX', 'Chipmakers'),
                ('chip sector', 'semiconductors', 'SOXX', 'Chip sector'),
                ('semi sector', 'semiconductors', 'SOXX', 'Semi sector'),
                ('soxx', 'semiconductors', 'SOXX', 'SOXX ticker'),
                ('smh', 'semiconductors', 'SMH', 'VanEck semi ETF'),
                ('chip foundries', 'semiconductors', 'SOXX', 'Foundries'),
                ('gpu stocks', 'semiconductors', 'SOXX', 'GPU stocks'),
                # Financials
                ('financial sector', 'financials', 'XLF', 'Financials'),
                ('financial stocks', 'financials', 'XLF', 'Financial stocks'),
                ('xlf', 'financials', 'XLF', 'XLF ticker'),
                ('bank stocks', 'banks', 'KBE', 'Bank stocks'),
                ('banking', 'banks', 'KBE', 'Banking'),
                ('banking sector', 'banks', 'KBE', 'Banking sector'),
                ('money center banks', 'banks', 'KBE', 'Money center banks'),
                ('kbe', 'banks', 'KBE', 'KBE ticker'),
                ('kbwb', 'banks', 'KBWB', 'KBW bank ETF'),
                ('community banks', 'regional_banks', 'KRE', 'Community banks'),
                ('regional bank stocks', 'regional_banks', 'KRE', 'Regional bank stocks'),
                ('kre', 'regional_banks', 'KRE', 'KRE ticker'),
                ('insurers', 'insurance', 'KIE', 'Insurers'),
                ('insurance sector', 'insurance', 'KIE', 'Insurance sector'),
                ('kie', 'insurance', 'KIE', 'KIE ticker'),
                ('broker stocks', 'brokers', 'IAI', 'Broker stocks'),
                ('iai', 'brokers', 'IAI', 'IAI ticker'),
                ('kce', 'capital_markets', 'KCE', 'KCE ticker'),
                ('pe firms', 'private_equity', 'PSP', 'PE firms'),
                ('psp', 'private_equity', 'PSP', 'PSP ticker'),
                # Healthcare
                ('healthcare sector', 'healthcare', 'XLV', 'Healthcare'),
                ('healthcare stocks', 'healthcare', 'XLV', 'Healthcare stocks'),
                ('health stocks', 'healthcare', 'XLV', 'Health stocks'),
                ('xlv', 'healthcare', 'XLV', 'XLV ticker'),
                ('biotech stocks', 'biotech', 'XBI', 'Biotech stocks'),
                ('biotech sector', 'biotech', 'XBI', 'Biotech sector'),
                ('xbi', 'biotech', 'XBI', 'XBI ticker'),
                ('ibb', 'biotech', 'IBB', 'IBB alt biotech'),
                ('drug stocks', 'pharma', 'IHE', 'Drug stocks'),
                ('pharma stocks', 'pharma', 'IHE', 'Pharma stocks'),
                ('big pharma', 'pharma', 'IHE', 'Big pharma'),
                ('ihe', 'pharma', 'IHE', 'IHE ticker'),
                ('medical device stocks', 'medical_devices', 'IHI', 'Med device stocks'),
                ('ihi', 'medical_devices', 'IHI', 'IHI ticker'),
                ('crispr stocks', 'genomics', 'ARKG', 'CRISPR stocks'),
                ('arkg', 'genomics', 'ARKG', 'ARKG ticker'),
                ('weed', 'cannabis', 'MSOS', 'Weed'),
                ('marijuana stocks', 'cannabis', 'MSOS', 'Marijuana stocks'),
                ('pot stocks', 'cannabis', 'MSOS', 'Pot stocks'),
                ('msos', 'cannabis', 'MSOS', 'MSOS ticker'),
                ('hospital stocks', 'hospitals', 'IHF', 'Hospital stocks'),
                ('health insurers', 'hospitals', 'IHF', 'Health insurers'),
                ('managed care', 'hospitals', 'IHF', 'Managed care'),
                ('ihf', 'hospitals', 'IHF', 'IHF ticker'),
                # Energy
                ('energy sector', 'energy', 'XLE', 'Energy sector'),
                ('energy stocks', 'energy', 'XLE', 'Energy stocks'),
                ('oil & gas', 'energy', 'XLE', 'O&G'),
                ('fossil fuels', 'energy', 'XLE', 'Fossil fuels'),
                ('xle', 'energy', 'XLE', 'XLE ticker'),
                ('wti crude', 'oil_commodity', 'USO', 'WTI crude'),
                ('brent crude', 'oil_commodity', 'BNO', 'Brent'),
                ('uso', 'oil_commodity', 'USO', 'USO ticker'),
                ('e and p', 'energy_ep', 'XOP', 'E&P'),
                ('e&p', 'energy_ep', 'XOP', 'E&P'),
                ('upstream oil', 'energy_ep', 'XOP', 'Upstream'),
                ('xop', 'energy_ep', 'XOP', 'XOP ticker'),
                ('midstream', 'pipelines', 'AMLP', 'Midstream oil'),
                ('amlp', 'pipelines', 'AMLP', 'AMLP ticker'),
                ('oil refiners', 'refiners', 'CRAK', 'Oil refiners'),
                ('crak', 'refiners', 'CRAK', 'CRAK ticker'),
                ('nat gas', 'natural_gas', 'UNG', 'Nat gas'),
                ('natgas', 'natural_gas', 'UNG', 'Natgas'),
                ('ung', 'natural_gas', 'UNG', 'UNG ticker'),
                ('green energy', 'renewables', 'ICLN', 'Green energy'),
                ('green stocks', 'renewables', 'ICLN', 'Green stocks'),
                ('icln', 'renewables', 'ICLN', 'ICLN ticker'),
                ('solar energy', 'solar', 'TAN', 'Solar energy'),
                ('tan', 'solar', 'TAN', 'TAN ticker'),
                ('wind power', 'wind', 'FAN', 'Wind power'),
                ('fan', 'wind', 'FAN', 'FAN ticker'),
                ('uranium stocks', 'uranium', 'URA', 'Uranium stocks'),
                ('nuclear power', 'nuclear', 'URA', 'Nuclear power'),
                ('ura', 'uranium', 'URA', 'URA ticker'),
                # Materials / commodities / metals
                ('materials sector', 'materials', 'XLB', 'Materials'),
                ('materials stocks', 'materials', 'XLB', 'Materials stocks'),
                ('basic materials', 'materials', 'XLB', 'Basic materials'),
                ('xlb', 'materials', 'XLB', 'XLB ticker'),
                ('the gold', 'gold', 'GLD', 'Gold colloquial'),
                ('gold bullion', 'gold', 'GLD', 'Gold bullion'),
                ('gld', 'gold', 'GLD', 'GLD ticker'),
                ('gold mining', 'gold_miners', 'GDX', 'Gold mining'),
                ('gold mining stocks', 'gold_miners', 'GDX', 'Gold miners'),
                ('gdx', 'gold_miners', 'GDX', 'GDX ticker'),
                ('junior gold miners', 'gold_miners_junior', 'GDXJ', 'Junior gold miners'),
                ('gdxj', 'gold_miners_junior', 'GDXJ', 'GDXJ ticker'),
                ('silver bullion', 'silver', 'SLV', 'Silver bullion'),
                ('slv', 'silver', 'SLV', 'SLV ticker'),
                ('silver miners', 'silver_miners', 'SIL', 'Silver miners'),
                ('copper stocks', 'copper', 'COPX', 'Copper stocks'),
                ('copx', 'copper', 'COPX', 'COPX ticker'),
                ('lithium stocks', 'lithium', 'LIT', 'Lithium stocks'),
                ('batteries', 'lithium', 'LIT', 'Batteries'),
                ('lit', 'lithium', 'LIT', 'LIT ticker'),
                ('steel stocks', 'steel', 'SLX', 'Steel stocks'),
                ('slx', 'steel', 'SLX', 'SLX ticker'),
                ('metals and mining', 'mining', 'XME', 'Metals & mining'),
                ('xme', 'mining', 'XME', 'XME ticker'),
                ('commodity basket', 'commodities', 'DBC', 'Commodity basket'),
                ('dbc', 'commodities', 'DBC', 'DBC ticker'),
                ('ag', 'agriculture', 'DBA', 'Ag shorthand'),
                ('farming', 'agriculture', 'DBA', 'Farming'),
                ('farmland', 'agriculture', 'DBA', 'Farmland'),
                ('corn', 'corn', 'CORN', 'Corn ETF'),
                ('wheat', 'wheat', 'WEAT', 'Wheat ETF'),
                ('soybeans', 'soybeans', 'SOYB', 'Soybeans ETF'),
                ('dba', 'agriculture', 'DBA', 'DBA ticker'),
                ('lumber', 'timber', 'WOOD', 'Lumber'),
                ('wood', 'timber', 'WOOD', 'Wood via timber'),
                ('water stocks', 'water', 'PHO', 'Water stocks'),
                ('pho', 'water', 'PHO', 'PHO ticker'),
                # Consumer discretionary / cyclical
                ('discretionary', 'consumer_discretionary', 'XLY', 'Discretionary'),
                ('consumer cyclical', 'consumer_discretionary', 'XLY', 'Consumer cyclical'),
                ('cyclicals', 'consumer_discretionary', 'XLY', 'Cyclicals'),
                ('xly', 'consumer_discretionary', 'XLY', 'XLY ticker'),
                ('retail stocks', 'retail', 'XRT', 'Retail stocks'),
                ('retailers', 'retail', 'XRT', 'Retailers'),
                ('xrt', 'retail', 'XRT', 'XRT ticker'),
                ('travel sector', 'travel', 'AWAY', 'Travel sector'),
                ('leisure', 'travel', 'AWAY', 'Leisure'),
                ('leisure stocks', 'travel', 'AWAY', 'Leisure stocks'),
                ('away', 'travel', 'AWAY', 'AWAY ticker'),
                ('airline stocks', 'airlines', 'JETS', 'Airline stocks'),
                ('airline sector', 'airlines', 'JETS', 'Airline sector'),
                ('jets', 'airlines', 'JETS', 'JETS ticker'),
                ('cruise stocks', 'cruises', 'AWAY', 'Cruises'),
                ('hotel stocks', 'hotels', 'AWAY', 'Hotel stocks'),
                ('casinos', 'casinos', 'BJK', 'Gaming/casino ETF'),
                ('casino stocks', 'casinos', 'BJK', 'Casino stocks'),
                ('gambling', 'casinos', 'BJK', 'Gambling stocks'),
                ('restaurant stocks', 'restaurants', 'EATZ', 'Restaurants'),
                ('eatz', 'restaurants', 'EATZ', 'EATZ ticker'),
                ('homebuilder stocks', 'homebuilders', 'XHB', 'Homebuilders'),
                ('itb', 'homebuilders', 'ITB', 'iShares homebuilder ETF'),
                ('xhb', 'homebuilders', 'XHB', 'XHB ticker'),
                ('apparel', 'apparel', 'XRT', 'Apparel via retail'),
                ('luxury stocks', 'luxury', 'XLY', 'Luxury stocks'),
                # Consumer staples
                ('staples', 'consumer_staples', 'XLP', 'Staples shorthand'),
                ('defensive stocks', 'consumer_staples', 'XLP', 'Defensive'),
                ('xlp', 'consumer_staples', 'XLP', 'XLP ticker'),
                ('food stocks', 'food', 'PBJ', 'Food stocks'),
                ('beverage stocks', 'food', 'PBJ', 'Beverage stocks'),
                ('tobacco', 'tobacco', 'XLP', 'Tobacco via staples'),
                ('tobacco stocks', 'tobacco', 'XLP', 'Tobacco stocks'),
                ('pbj', 'food', 'PBJ', 'PBJ ticker'),
                # Industrials
                ('industrial sector', 'industrials', 'XLI', 'Industrial sector'),
                ('industrial stocks', 'industrials', 'XLI', 'Industrial stocks'),
                ('xli', 'industrials', 'XLI', 'XLI ticker'),
                ('aerospace and defense', 'defense', 'ITA', 'Aerospace & defense'),
                ('weapons makers', 'defense', 'ITA', 'Defense contractors'),
                ('defense contractors', 'defense', 'ITA', 'Defense contractors'),
                ('ita', 'defense', 'ITA', 'ITA ticker'),
                ('xar', 'defense', 'XAR', 'XAR alt defense'),
                ('transport stocks', 'transports', 'IYT', 'Transport stocks'),
                ('iyt', 'transports', 'IYT', 'IYT ticker'),
                ('shipping stocks', 'shipping', 'BOAT', 'Shipping stocks'),
                ('container shipping', 'shipping', 'BOAT', 'Container shipping'),
                ('dry bulk', 'shipping', 'BOAT', 'Dry bulk shipping'),
                # Communication services
                ('communications', 'communications', 'XLC', 'Comm services'),
                ('telecom stocks', 'communications', 'XLC', 'Telecom stocks'),
                ('media', 'communications', 'XLC', 'Media via comms'),
                ('media stocks', 'communications', 'XLC', 'Media stocks'),
                ('xlc', 'communications', 'XLC', 'XLC ticker'),
                # Real estate
                ('real estate stocks', 'real_estate', 'XLRE', 'RE stocks'),
                ('reit', 'real_estate', 'XLRE', 'REIT'),
                ('real estate sector', 'real_estate', 'XLRE', 'RE sector'),
                ('vnq', 'real_estate', 'VNQ', 'VNQ ticker'),
                ('xlre', 'real_estate', 'XLRE', 'XLRE ticker'),
                ('mreits', 'mortgage_reits', 'REM', 'mREITs'),
                ('rem', 'mortgage_reits', 'REM', 'REM ticker'),
                # Utilities
                ('utility sector', 'utilities', 'XLU', 'Utility sector'),
                ('utility stocks', 'utilities', 'XLU', 'Utility stocks'),
                ('utes', 'utilities', 'XLU', 'Utes shorthand'),
                ('xlu', 'utilities', 'XLU', 'XLU ticker'),
                # International / country ETFs
                ('international', 'international', 'VEA', 'Intl developed'),
                ('foreign stocks', 'international', 'VEA', 'Foreign'),
                ('ex us', 'international', 'VEA', 'Ex-US'),
                ('vea', 'international', 'VEA', 'VEA ticker'),
                ('em stocks', 'emerging_markets', 'EEM', 'EM stocks'),
                ('emerging market stocks', 'emerging_markets', 'EEM', 'EM stocks'),
                ('eem', 'emerging_markets', 'EEM', 'EEM ticker'),
                ('vwo', 'emerging_markets', 'VWO', 'Vanguard EM'),
                ('chinese market', 'china', 'FXI', 'China market'),
                ('china stocks', 'china', 'FXI', 'China'),
                ('a shares', 'china_a_shares', 'ASHR', 'China A-shares'),
                ('mchi', 'china', 'MCHI', 'iShares MSCI China'),
                ('fxi', 'china', 'FXI', 'FXI ticker'),
                ('hong kong', 'hong_kong', 'EWH', 'Hong Kong ETF'),
                ('taiwanese stocks', 'taiwan', 'EWT', 'Taiwan'),
                ('nikkei', 'japan', 'EWJ', 'Nikkei'),
                ('ewj', 'japan', 'EWJ', 'EWJ ticker'),
                ('indian market', 'india', 'INDA', 'India market'),
                ('inda', 'india', 'INDA', 'INDA ticker'),
                ('korean stocks', 'korea', 'EWY', 'Korea'),
                ('kospi', 'korea', 'EWY', 'KOSPI'),
                ('ewy', 'korea', 'EWY', 'EWY ticker'),
                ('malaysia', 'malaysia', 'EWM', 'Malaysia ETF'),
                ('thailand', 'thailand', 'THD', 'Thailand ETF'),
                ('philippines', 'philippines', 'EPHE', 'Philippines ETF'),
                ('singapore', 'singapore', 'EWS', 'Singapore ETF'),
                ('new zealand', 'new_zealand', 'ENZL', 'NZ ETF'),
                ('brazilian stocks', 'brazil', 'EWZ', 'Brazil stocks'),
                ('mexican stocks', 'mexico', 'EWW', 'Mexico'),
                ('argentina', 'argentina', 'ARGT', 'Argentina ETF'),
                ('chile', 'chile', 'ECH', 'Chile ETF'),
                ('colombia', 'colombia', 'GXG', 'Colombia ETF'),
                ('peru', 'peru', 'EPU', 'Peru ETF'),
                ('latin america', 'latin_america', 'ILF', 'LatAm ETF'),
                ('latam', 'latin_america', 'ILF', 'LatAm'),
                ('european stocks', 'europe', 'VGK', 'European'),
                ('european markets', 'europe', 'VGK', 'Europe'),
                ('eurozone', 'europe', 'EZU', 'Eurozone'),
                ('vgk', 'europe', 'VGK', 'VGK ticker'),
                ('german stocks', 'germany', 'EWG', 'Germany'),
                ('dax', 'germany', 'EWG', 'DAX'),
                ('french stocks', 'france', 'EWQ', 'France'),
                ('british stocks', 'uk', 'EWU', 'UK'),
                ('ftse', 'uk', 'EWU', 'FTSE'),
                ('italy', 'italy', 'EWI', 'Italy ETF'),
                ('spain', 'spain', 'EWP', 'Spain ETF'),
                ('netherlands', 'netherlands', 'EWN', 'Netherlands ETF'),
                ('switzerland', 'switzerland', 'EWL', 'Switzerland ETF'),
                ('sweden', 'sweden', 'EWD', 'Sweden ETF'),
                ('norway', 'norway', 'NORW', 'Norway ETF'),
                ('poland', 'poland', 'EPOL', 'Poland ETF'),
                ('russia', 'russia', 'ERUS', 'Russia ETF restricted'),
                ('turkey', 'turkey', 'TUR', 'Turkey ETF'),
                ('israel', 'israel', 'EIS', 'Israel ETF'),
                ('saudi arabia', 'saudi_arabia', 'KSA', 'Saudi ETF'),
                ('south africa', 'south_africa', 'EZA', 'South Africa ETF'),
                ('canadian stocks', 'canada', 'EWC', 'Canada'),
                ('ewc', 'canada', 'EWC', 'EWC ticker'),
                ('africa', 'africa', 'AFK', 'Africa ETF'),
                ('asia', 'asia', 'AAXJ', 'Asia ex-Japan'),
                ('asia ex japan', 'asia', 'AAXJ', 'Asia ex-Japan'),
                # Crypto and digital assets
                ('the bitcoin', 'bitcoin', 'IBIT', 'BTC colloquial'),
                ('spot bitcoin', 'bitcoin', 'IBIT', 'Spot BTC'),
                ('ibit', 'bitcoin', 'IBIT', 'IBIT ticker'),
                ('fbtc', 'bitcoin', 'FBTC', 'Fidelity BTC'),
                ('the ethereum', 'ethereum', 'ETHA', 'ETH colloquial'),
                ('etha', 'ethereum', 'ETHA', 'ETHA ticker'),
                ('cryptocurrency stocks', 'crypto_stocks', 'BITQ', 'Crypto stocks'),
                ('crypto sector', 'crypto_stocks', 'BITQ', 'Crypto sector'),
                ('bitq', 'crypto_stocks', 'BITQ', 'BITQ ticker'),
                ('crypto miners', 'crypto_miners', 'WGMI', 'Crypto miners'),
                ('mining stocks crypto', 'crypto_miners', 'WGMI', 'Crypto mining'),
                ('wgmi', 'crypto_miners', 'WGMI', 'WGMI ticker'),
                ('blok', 'blockchain', 'BLOK', 'BLOK ticker'),
                # Bonds and rates
                ('the bond market', 'bonds', 'AGG', 'Broad bond market'),
                ('bond market', 'bonds', 'AGG', 'Bond market'),
                ('twenty year bonds', 'bonds', 'TLT', '20-year'),
                ('20 year treasury', 'bonds', 'TLT', '20-year treasury'),
                ('30 year bonds', 'bonds', 'TLT', '30-year use TLT'),
                ('tlt', 'bonds', 'TLT', 'TLT ticker'),
                ('agg', 'bonds', 'AGG', 'AGG ticker'),
                ('bnd', 'bonds', 'BND', 'Vanguard total bond'),
                ('ten year', 'tenyear', 'IEF', '10-year verbal'),
                ('ten year treasury', 'tenyear', 'IEF', '10-year'),
                ('ief', 'tenyear', 'IEF', 'IEF ticker'),
                ('2 year', 'short_bonds', 'SHY', '2-year'),
                ('two year', 'short_bonds', 'SHY', '2-year verbal'),
                ('2 year treasury', 'short_bonds', 'SHY', '2-year treasury'),
                ('shy', 'short_bonds', 'SHY', 'SHY ticker'),
                ('treasury bills', 'tbills', 'BIL', 'T-bills formal'),
                ('bil', 'tbills', 'BIL', 'BIL ticker'),
                ('investment grade bonds', 'corporate_bonds', 'LQD', 'IG bonds'),
                ('ig bonds', 'corporate_bonds', 'LQD', 'IG'),
                ('lqd', 'corporate_bonds', 'LQD', 'LQD ticker'),
                ('high yield bonds', 'high_yield', 'HYG', 'High yield'),
                ('junk', 'high_yield', 'HYG', 'Junk bonds'),
                ('jnk', 'high_yield', 'JNK', 'JNK alt high yield'),
                ('municipal bonds', 'munis', 'MUB', 'Munis'),
                ('munis', 'munis', 'MUB', 'Munis shorthand'),
                ('mub', 'munis', 'MUB', 'MUB ticker'),
                ('inflation protected bonds', 'tips', 'TIP', 'TIPS'),
                ('tip', 'tips', 'TIP', 'TIP ticker'),
                ('international bonds', 'intl_bonds', 'BNDX', 'Intl bonds'),
                ('em bonds', 'em_bonds', 'EMB', 'EM bonds'),
                ('emerging market bonds', 'em_bonds', 'EMB', 'EM bonds'),
                # Volatility and hedges
                ('vol', 'volatility', 'VXX', 'Vol shorthand'),
                ('fear gauge', 'volatility', 'VXX', 'VIX alias'),
                ('vxx', 'volatility', 'VXX', 'VXX ticker'),
                ('uvxy', 'volatility', 'UVXY', 'Leveraged VIX'),
                # Factors
                ('dividend growers', 'dividend_growth', 'SCHD', 'Dividend growers'),
                ('dividend aristocrats', 'dividend_aristocrats', 'NOBL', 'Div aristocrats'),
                ('aristocrats', 'dividend_aristocrats', 'NOBL', 'Aristocrats'),
                ('schd', 'dividends', 'SCHD', 'SCHD ticker'),
                ('nobl', 'dividend_aristocrats', 'NOBL', 'NOBL ticker'),
                ('high yield stocks', 'high_dividend', 'VYM', 'High yield stocks'),
                ('vym', 'high_dividend', 'VYM', 'VYM ticker'),
                ('value factor', 'value', 'IVE', 'Value factor'),
                ('deep value', 'value', 'IVE', 'Deep value'),
                ('ive', 'value', 'IVE', 'IVE ticker'),
                ('vtv', 'value', 'VTV', 'Vanguard value'),
                ('growth factor', 'growth', 'IVW', 'Growth factor'),
                ('ivw', 'growth', 'IVW', 'IVW ticker'),
                ('vug', 'growth', 'VUG', 'Vanguard growth'),
                ('momentum stocks', 'momentum', 'MTUM', 'Momentum'),
                ('momo', 'momentum', 'MTUM', 'Momo shorthand'),
                ('mtum', 'momentum', 'MTUM', 'MTUM ticker'),
                ('quality stocks', 'quality', 'QUAL', 'Quality'),
                ('quality factor', 'quality', 'QUAL', 'Quality factor'),
                ('qual', 'quality', 'QUAL', 'QUAL ticker'),
                ('low volatility stocks', 'low_vol', 'USMV', 'Low vol stocks'),
                ('min vol', 'low_vol', 'USMV', 'Min vol'),
                ('minimum volatility', 'low_vol', 'USMV', 'Min vol'),
                ('usmv', 'low_vol', 'USMV', 'USMV ticker'),
                # Thematic
                ('sustainable investing', 'esg', 'ESGU', 'ESG formal'),
                ('esgu', 'esg', 'ESGU', 'ESGU ticker'),
                ('infra', 'infrastructure', 'PAVE', 'Infra shorthand'),
                ('pave', 'infrastructure', 'PAVE', 'PAVE ticker'),
                ('ufo', 'space', 'UFO', 'UFO ticker'),
                ('quantum stocks', 'quantum', 'QTUM', 'Quantum stocks'),
                ('qtum', 'quantum', 'QTUM', 'QTUM ticker'),
                ('disruptive innovation', 'disruptive', 'ARKK', 'Disruptive'),
                ('innovation stocks', 'disruptive', 'ARKK', 'Innovation'),
                ('cathy wood', 'disruptive', 'ARKK', 'ARKK alt spelling'),
                ('arkk', 'disruptive', 'ARKK', 'ARKK ticker'),
                ('arkf', 'fintech', 'ARKF', 'ARK fintech'),
                ('arkw', 'internet', 'ARKW', 'ARK internet'),
                ('arkq', 'robotics', 'ARKQ', 'ARK robotics'),
                ('arkx', 'space', 'ARKX', 'ARK space'),
                ('moat', 'moat', 'MOAT', 'Wide moat stocks ETF'),
                ('moat stocks', 'moat', 'MOAT', 'Moat stocks'),
                ('wide moat', 'moat', 'MOAT', 'Wide moat'),
                # Macro hedges
                ('dollar', 'dollar', 'UUP', 'US dollar ETF'),
                ('the dollar', 'dollar', 'UUP', 'Dollar'),
                ('us dollar', 'dollar', 'UUP', 'USD'),
                ('dxy', 'dollar', 'UUP', 'Dollar index'),
                ('uup', 'dollar', 'UUP', 'UUP ticker'),
                ('inflation', 'inflation', 'TIP', 'Inflation via TIPS'),
                ('inflation hedge', 'inflation', 'TIP', 'Inflation hedge'),
            ]
            for _alias, _canonical, _etf, _notes in _seed_aliases:
                conn.execute(sql_text("""
                    INSERT INTO sector_etf_aliases
                        (alias, canonical_sector, etf_ticker, notes)
                    VALUES (:a, :c, :e, :n)
                    ON CONFLICT (alias) DO NOTHING
                """), {"a": _alias, "c": _canonical, "e": _etf, "n": _notes})
            conn.commit()
        log.info("[Worker] sector_etf_aliases table + seed ready")
    except Exception as e:
        log.warning(f"[Worker] sector_etf_aliases migration: {e}")

    # predictions.prediction_category — ticker_call vs sector_call.
    # Default ticker_call preserves all existing row semantics.
    try:
        with engine.connect() as conn:
            conn.execute(sql_text(
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS "
                "prediction_category VARCHAR(20) DEFAULT 'ticker_call'"
            ))
            conn.execute(sql_text(
                "CREATE INDEX IF NOT EXISTS idx_predictions_category "
                "ON predictions(prediction_category)"
            ))
            conn.execute(sql_text(
                "UPDATE predictions SET prediction_category = 'ticker_call' "
                "WHERE prediction_category IS NULL"
            ))
            conn.commit()
        log.info("[Worker] predictions.prediction_category ready")
    except Exception as e:
        log.warning(f"[Worker] prediction_category migration: {e}")

    # scraper_runs.sector_calls_extracted — per-run counter for the
    # admin sector-calls dashboard. Stays at 0 until the feature flag
    # is flipped on.
    try:
        with engine.connect() as conn:
            conn.execute(sql_text(
                "ALTER TABLE scraper_runs ADD COLUMN IF NOT EXISTS "
                "sector_calls_extracted INTEGER NOT NULL DEFAULT 0"
            ))
            conn.commit()
        log.info("[Worker] scraper_runs.sector_calls_extracted ready")
    except Exception as e:
        log.warning(f"[Worker] scraper_runs sector_calls migration: {e}")

    # scraper_runs.options_positions_extracted — per-run counter for the
    # options-derived ticker_call path. Stays at 0 until the
    # ENABLE_OPTIONS_POSITION_EXTRACTION flag is flipped on.
    try:
        with engine.connect() as conn:
            conn.execute(sql_text(
                "ALTER TABLE scraper_runs ADD COLUMN IF NOT EXISTS "
                "options_positions_extracted INTEGER NOT NULL DEFAULT 0"
            ))
            conn.commit()
        log.info("[Worker] scraper_runs.options_positions_extracted ready")
    except Exception as e:
        log.warning(f"[Worker] scraper_runs options_positions migration: {e}")

    # predictions.event_type + event_date — earnings_call metadata + any
    # future event-tied prediction types. Partial index keeps it small.
    try:
        with engine.connect() as conn:
            conn.execute(sql_text(
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS "
                "event_type VARCHAR(32)"
            ))
            conn.execute(sql_text(
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS "
                "event_date DATE"
            ))
            conn.execute(sql_text(
                "CREATE INDEX IF NOT EXISTS idx_predictions_event "
                "ON predictions(event_type, event_date) "
                "WHERE event_type IS NOT NULL"
            ))
            conn.commit()
        log.info("[Worker] predictions.event_type + event_date ready")
    except Exception as e:
        log.warning(f"[Worker] predictions event columns migration: {e}")

    # scraper_runs.earnings_calls_extracted — per-run counter for the
    # earnings_call path. Stays at 0 until the flag is on.
    try:
        with engine.connect() as conn:
            conn.execute(sql_text(
                "ALTER TABLE scraper_runs ADD COLUMN IF NOT EXISTS "
                "earnings_calls_extracted INTEGER NOT NULL DEFAULT 0"
            ))
            conn.commit()
        log.info("[Worker] scraper_runs.earnings_calls_extracted ready")
    except Exception as e:
        log.warning(f"[Worker] scraper_runs earnings_calls migration: {e}")

    # predictions.list_id + list_rank — ranked list extraction metadata.
    # Partial index keeps the index small because most rows won't be in
    # lists. No backfill: historical predictions have no ranking data.
    try:
        with engine.connect() as conn:
            conn.execute(sql_text(
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS "
                "list_id VARCHAR(40)"
            ))
            conn.execute(sql_text(
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS "
                "list_rank INTEGER"
            ))
            conn.execute(sql_text(
                "CREATE INDEX IF NOT EXISTS idx_predictions_list_id "
                "ON predictions(list_id) WHERE list_id IS NOT NULL"
            ))
            conn.commit()
        log.info("[Worker] predictions.list_id + list_rank ready")
    except Exception as e:
        log.warning(f"[Worker] list_id/list_rank migration: {e}")

    # predictions.revision_of — self-referencing FK for target revision
    # tracking. Column add is independent from the FK constraint so an
    # old Postgres (or SQLite dev) still gets the column. Partial index
    # keeps it small.
    try:
        with engine.connect() as conn:
            conn.execute(sql_text(
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS "
                "revision_of INTEGER"
            ))
            try:
                conn.execute(sql_text("""
                    ALTER TABLE predictions
                    ADD CONSTRAINT fk_predictions_revision_of
                    FOREIGN KEY (revision_of)
                    REFERENCES predictions(id)
                    ON DELETE SET NULL
                """))
            except Exception:
                pass
            conn.execute(sql_text(
                "CREATE INDEX IF NOT EXISTS idx_predictions_revision_of "
                "ON predictions(revision_of) WHERE revision_of IS NOT NULL"
            ))
            conn.commit()
        log.info("[Worker] predictions.revision_of ready")
    except Exception as e:
        log.warning(f"[Worker] revision_of migration: {e}")

    # scraper_runs + youtube_scraper_rejections — belt-and-braces migration.
    # Base.metadata.create_all above is the primary creator (the SQLAlchemy
    # models live in models.py), but on existing DBs the indexes / column
    # adds may need ALTER guarantees. All statements use IF NOT EXISTS so
    # this block is safe to re-run on every worker boot. Both services
    # (worker + API) execute this — whichever boots first wins; the second
    # is a no-op.
    try:
        with engine.connect() as conn:
            conn.execute(sql_text("""
                CREATE TABLE IF NOT EXISTS scraper_runs (
                    id SERIAL PRIMARY KEY,
                    source VARCHAR(20) NOT NULL,
                    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    finished_at TIMESTAMP,
                    status VARCHAR(20) NOT NULL DEFAULT 'running',
                    items_fetched INTEGER NOT NULL DEFAULT 0,
                    items_processed INTEGER NOT NULL DEFAULT 0,
                    items_llm_sent INTEGER NOT NULL DEFAULT 0,
                    items_inserted INTEGER NOT NULL DEFAULT 0,
                    items_rejected INTEGER NOT NULL DEFAULT 0,
                    items_deduped INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT
                )
            """))
            conn.execute(sql_text(
                "CREATE INDEX IF NOT EXISTS idx_scraper_runs_source_started "
                "ON scraper_runs(source, started_at DESC)"
            ))
            conn.execute(sql_text("""
                CREATE TABLE IF NOT EXISTS youtube_scraper_rejections (
                    id SERIAL PRIMARY KEY,
                    video_id VARCHAR(20),
                    channel_id VARCHAR(30),
                    channel_name VARCHAR(200),
                    video_title TEXT,
                    video_published_at TIMESTAMP,
                    rejected_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    rejection_reason VARCHAR(50) NOT NULL,
                    haiku_reason TEXT,
                    haiku_raw_response JSONB,
                    transcript_snippet TEXT
                )
            """))
            conn.execute(sql_text(
                "CREATE INDEX IF NOT EXISTS idx_yt_rejections_rejected_at "
                "ON youtube_scraper_rejections(rejected_at)"
            ))
            conn.execute(sql_text(
                "CREATE INDEX IF NOT EXISTS idx_yt_rejections_reason "
                "ON youtube_scraper_rejections(rejection_reason)"
            ))
            conn.execute(sql_text(
                "CREATE INDEX IF NOT EXISTS idx_yt_rejections_channel "
                "ON youtube_scraper_rejections(channel_id)"
            ))
            conn.commit()
        log.info("[Worker] scraper_runs + youtube_scraper_rejections ensured")
    except Exception as e:
        log.warning(f"[Worker] scraper_runs/yt_rejections migration: {e}")

    # scraper_runs LLM cost/usage columns. Source-agnostic — any scraper
    # that calls an LLM can populate these. The YouTube monitor is the
    # first writer. Existing rows are left at 0; historical cost cannot
    # be reconstructed from the log.
    try:
        with engine.connect() as conn:
            for ddl in (
                "ALTER TABLE scraper_runs ADD COLUMN IF NOT EXISTS "
                "total_input_tokens BIGINT NOT NULL DEFAULT 0",
                "ALTER TABLE scraper_runs ADD COLUMN IF NOT EXISTS "
                "total_output_tokens BIGINT NOT NULL DEFAULT 0",
                "ALTER TABLE scraper_runs ADD COLUMN IF NOT EXISTS "
                "total_cache_create_tokens BIGINT NOT NULL DEFAULT 0",
                "ALTER TABLE scraper_runs ADD COLUMN IF NOT EXISTS "
                "total_cache_read_tokens BIGINT NOT NULL DEFAULT 0",
                "ALTER TABLE scraper_runs ADD COLUMN IF NOT EXISTS "
                "estimated_cost_usd NUMERIC(10,4) NOT NULL DEFAULT 0",
                "ALTER TABLE scraper_runs ADD COLUMN IF NOT EXISTS "
                "haiku_retries_count INTEGER NOT NULL DEFAULT 0",
            ):
                conn.execute(sql_text(ddl))
            conn.commit()
        log.info("[Worker] scraper_runs cost columns ensured")
    except Exception as e:
        log.warning(f"[Worker] scraper_runs cost columns migration: {e}")

    # Dormancy: add forecasters.last_prediction_at + is_dormant columns,
    # backfill on first run, then create the partial index.
    # Idempotent: subsequent runs ALTER IF NOT EXISTS and the UPDATE only
    # touches NULL rows on first run.
    try:
        with engine.connect() as conn:
            conn.execute(sql_text(
                "ALTER TABLE forecasters ADD COLUMN IF NOT EXISTS last_prediction_at TIMESTAMP"
            ))
            conn.execute(sql_text(
                "ALTER TABLE forecasters ADD COLUMN IF NOT EXISTS is_dormant BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            conn.execute(sql_text(
                "CREATE INDEX IF NOT EXISTS idx_forecasters_dormant "
                "ON forecasters(is_dormant) WHERE is_dormant = TRUE"
            ))
            conn.commit()

            # Initial backfill: only runs on the first deploy after the
            # columns are added. Once last_prediction_at is populated,
            # subsequent calls to refresh_all_forecaster_stats keep it
            # current. The WHERE clause guarantees idempotency — second
            # run finds 0 NULL rows and is a no-op.
            backfilled = conn.execute(sql_text("""
                UPDATE forecasters f
                SET last_prediction_at = (
                    SELECT MAX(prediction_date) FROM predictions p
                    WHERE p.forecaster_id = f.id
                )
                WHERE f.last_prediction_at IS NULL
            """))
            conn.execute(sql_text("""
                UPDATE forecasters
                SET is_dormant = (
                    last_prediction_at IS NULL
                    OR last_prediction_at < NOW() - INTERVAL '30 days'
                )
            """))
            conn.commit()
        log.info("[Worker] forecasters.last_prediction_at + is_dormant ensured (backfill done if first run)")
    except Exception as e:
        log.warning(f"[Worker] dormancy migration: {e}")

    # Drop the phantom `is_active` column on tracked_x_accounts if it ever
    # got added by an out-of-band SQL run. The canonical column is `active`.
    # Idempotent: DROP COLUMN IF EXISTS is a no-op when the column is absent.
    try:
        with engine.connect() as conn:
            conn.execute(sql_text(
                "ALTER TABLE tracked_x_accounts DROP COLUMN IF EXISTS is_active"
            ))
            conn.commit()
        log.info("[Worker] tracked_x_accounts.is_active phantom column dropped (no-op if absent)")
    except Exception as e:
        log.warning(f"[Worker] drop phantom is_active migration: {e}")

    # ── One-time jobs ────────────────────────────────────────────────
    # Generic flag table for one-shot maintenance scripts. Each job
    # writes its job_name into this table after a successful run, so
    # subsequent worker restarts skip it. Add a new row here when you
    # need to ship a one-time backfill / requeue / cleanup.
    try:
        with engine.connect() as conn:
            conn.execute(sql_text("""
                CREATE TABLE IF NOT EXISTS one_time_jobs (
                    job_name TEXT PRIMARY KEY,
                    ran_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            conn.commit()
        log.info("[Worker] one_time_jobs table ensured")
    except Exception as e:
        log.warning(f"[Worker] one_time_jobs table migration: {e}")

    # scraper_job_queue — cross-service work queue used by admin endpoints
    # (running on the eidolum API service) to hand off scraping work to
    # the hopeful-expression worker service. The API service lacks the
    # YouTube/Webshare env vars and should not run scraping directly.
    # Distinct from one_time_jobs (which is a flag table with job_name PK);
    # this one is a proper queue with per-row IDs + payload + status.
    try:
        with engine.connect() as conn:
            conn.execute(sql_text("""
                CREATE TABLE IF NOT EXISTS scraper_job_queue (
                    id SERIAL PRIMARY KEY,
                    job_type VARCHAR(50) NOT NULL,
                    payload JSONB,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    started_at TIMESTAMP,
                    finished_at TIMESTAMP,
                    error TEXT
                )
            """))
            conn.execute(sql_text(
                "CREATE INDEX IF NOT EXISTS idx_sjq_pending "
                "ON scraper_job_queue(status, created_at) "
                "WHERE status = 'pending'"
            ))
            conn.commit()
        log.info("[Worker] scraper_job_queue table ensured")
    except Exception as e:
        log.warning(f"[Worker] scraper_job_queue migration: {e}")

    def _run_once_requeue_billing_victims():
        """Re-classify the 377 tweets killed by the 2026-04-08 Anthropic
        billing outage. Idempotent via the one_time_jobs flag table.

        v2: now runs through Groq llama-3.3-70b-versatile (Apr 9 2026
        migration). Bumped job_name so the new pipeline fires once even
        on workers where the v1 entry already sits in one_time_jobs.
        The v1 row is also dropped here so future migrations of the same
        cohort don't accidentally short-circuit on it.
        """
        job_name = "requeue_billing_victims_april8_v2"
        try:
            with engine.connect() as conn:
                # Clear the v1 marker — the requeue is being re-run through
                # the new Groq pipeline. Keeping v1 around would not block
                # the v2 run (different job_name) but it's misleading state.
                conn.execute(sql_text(
                    "DELETE FROM one_time_jobs WHERE job_name = :old"
                ), {"old": "requeue_haiku_billing_victims_april8"})
                conn.commit()
                row = conn.execute(sql_text(
                    "SELECT 1 FROM one_time_jobs WHERE job_name = :j"
                ), {"j": job_name}).first()
                if row:
                    log.info(f"[Worker] {job_name} already ran, skipping")
                    return
        except Exception as e:
            log.warning(f"[Worker] {job_name} flag check failed: {e}")
            return

        log.info(f"[Worker] Running one-time job: {job_name}")
        try:
            from scripts.requeue_haiku_billing_victims import main as requeue_main
            summary = requeue_main()
            log.info(f"[Worker] {job_name} summary: {summary}")
        except Exception as e:
            log.error(f"[Worker] {job_name} failed: {e}", exc_info=True)
            # Do NOT mark as ran on failure — let the next deploy retry.
            return

        try:
            with engine.connect() as conn:
                conn.execute(sql_text(
                    "INSERT INTO one_time_jobs (job_name) VALUES (:j) "
                    "ON CONFLICT (job_name) DO NOTHING"
                ), {"j": job_name})
                conn.commit()
            log.info(f"[Worker] {job_name} marked complete")
        except Exception as e:
            log.warning(f"[Worker] {job_name} flag insert failed: {e}")

    _run_once_requeue_billing_victims()

    # Scheduler with separate executor for maintenance jobs.
    # default: scrapers + evaluator (must never be blocked)
    # maintenance: logos, backfills, harvests (one at a time, isolated, time-budgeted)
    executors = {
        'default': APThreadPool(max_workers=3),
        'maintenance': APThreadPool(max_workers=1),
    }
    job_defaults = {
        'coalesce': True,        # if a job missed multiple runs, just run once
        'max_instances': 1,      # never run the same job twice concurrently
        'misfire_grace_time': 300,
    }
    sched = BlockingScheduler(
        executors=executors,
        job_defaults=job_defaults,
        timezone='UTC',
    )
    t0 = datetime.utcnow() + timedelta(seconds=30)

    # ── DEFAULT executor (scrapers + evaluator + small periodic jobs) ──────
    # Locked jobs
    sched.add_job(_guarded("massive_benzinga", _massive_benzinga), "interval", hours=2, id="massive_benzinga", next_run_time=t0, executor='default')
    sched.add_job(_guarded("sweep_stuck", _sweep), "interval", hours=24, id="sweep_stuck", next_run_time=t0 + timedelta(minutes=15), executor='default')
    sched.add_job(_guarded("analyst_notifications", _analyst_notif), "interval", hours=1, id="analyst_notifications", next_run_time=t0 + timedelta(minutes=25), executor='default')

    # Independent jobs
    sched.add_job(_standalone("auto_evaluate", _evaluator), "interval", minutes=30, id="auto_evaluate", next_run_time=t0 + timedelta(minutes=5), executor='default')
    sched.add_job(_standalone("refresh_stats", _refresh_stats), "interval", hours=2, id="refresh_stats", next_run_time=t0 + timedelta(minutes=10), executor='default')
    sched.add_job(_standalone("fmp_grades", _fmp_grades), "interval", hours=24, id="fmp_grades", next_run_time=t0 + timedelta(minutes=20), executor='default')
    sched.add_job(_standalone("retry_no_data", _retry_no_data), "interval", minutes=30, id="retry_no_data", next_run_time=t0 + timedelta(minutes=5), executor='default')
    # url_backfill is a maintenance job (calls Jina/external for up to 2000 URLs per run)
    sched.add_job(_standalone("url_backfill", _url_backfill), "interval", hours=24, id="url_backfill", next_run_time=t0 + timedelta(minutes=40), executor='maintenance')
    sched.add_job(_standalone("tournament_scorer", _tournament), "interval", hours=6, id="tournament_scorer", next_run_time=t0 + timedelta(minutes=45), executor='default')
    sched.add_job(_standalone("youtube_scraper", _youtube), "interval", hours=8, id="youtube_scraper", next_run_time=t0 + timedelta(minutes=55), executor='default')
    sched.add_job(_standalone("enrich_urls", _enrich), "interval", hours=1, id="enrich_urls", next_run_time=t0 + timedelta(minutes=35), executor='default')

    # YouTube Channel Monitor — V2 transcript-based, Haiku-powered, every 12h.
    # Inserts predictions into the predictions table via insert_youtube_prediction.
    def _channel_monitor():
        try:
            from jobs.youtube_channel_monitor import run_channel_monitor
            db = BgSessionLocal()
            try:
                run_channel_monitor(db)
            finally:
                db.close()
        except Exception as e:
            log.error(f"[channel_monitor] {e}")
    sched.add_job(_standalone("channel_monitor", _channel_monitor), "interval", hours=12, id="channel_monitor", next_run_time=t0 + timedelta(minutes=90), executor='default')

    # Cross-service work queue drain. Polls scraper_job_queue every
    # 60s and runs any pending rows on the worker container (where
    # scraping env vars live). Uses _standalone so it doesn't acquire
    # the global SCRAPER_LOCK — queue jobs are short per-channel
    # fetches that shouldn't be gated by the hourly Benzinga pass.
    sched.add_job(
        _standalone("scraper_job_queue", _drain_scraper_job_queue),
        "interval", seconds=60,
        id="scraper_job_queue",
        next_run_time=t0 + timedelta(seconds=30),
        max_instances=1,
        coalesce=True,
        executor='default',
    )

    # YouTube Historical Backfill — every 4h, walks each channel's full
    # upload history oldest-first via cursor in youtube_channels.backfill_cursor.
    # Independent of the regular monitor; both share the youtube_videos
    # dedup table so neither one re-processes a video the other has done.
    def _youtube_backfill():
        try:
            from jobs.youtube_backfill import run_youtube_backfill
            db = BgSessionLocal()
            try:
                run_youtube_backfill(db)
            finally:
                db.close()
        except Exception as e:
            log.error(f"[youtube_backfill] {e}")
    sched.add_job(_standalone("youtube_backfill", _youtube_backfill), "interval", hours=4, id="youtube_backfill", next_run_time=t0 + timedelta(minutes=110), executor='default')

    # X/Twitter scraper — Apify-powered, every 8h, inserts predictions
    def _x_scraper():
        log.info("[X-SCRAPER] Scheduler fired _x_scraper job")
        try:
            from jobs.x_scraper import run_x_scraper
            log.info("[X-SCRAPER] Import OK, creating DB session")
            db = BgSessionLocal()
            try:
                run_x_scraper(db)
            finally:
                db.close()
        except Exception as e:
            log.error(f"[X-SCRAPER] Job failed: {e}", exc_info=True)
    print("[Worker] Registering X scraper job...", flush=True)
    sched.add_job(_standalone("x_scraper", _x_scraper), "interval", hours=6, id="x_scraper", next_run_time=datetime.utcnow(), misfire_grace_time=300, executor='default')

    # StockTwits scraper — Apify-powered, every 6h, offset from X scraper
    def _stocktwits_scraper():
        log.info("[STOCKTWITS] Scheduler fired _stocktwits_scraper job")
        try:
            from jobs.stocktwits_scraper import run_stocktwits_scraper
            db = BgSessionLocal()
            try:
                run_stocktwits_scraper(db)
            finally:
                db.close()
        except Exception as e:
            log.error(f"[STOCKTWITS] Job failed: {e}", exc_info=True)
    print("[Worker] Registering StockTwits scraper job...", flush=True)
    sched.add_job(_standalone("stocktwits_scraper", _stocktwits_scraper), "interval", hours=6, id="stocktwits_scraper", next_run_time=datetime.utcnow(), misfire_grace_time=300, executor='default')

    # Logo processor — fill missing logos daily (never reprocess/delete existing)
    def _process_logos():
        try:
            from jobs.process_logos import process_all_logos
            result = process_all_logos(batch_size=50, rate_limit=0.3, reprocess=False)
            log.info(f"[process_logos] Done: {result}")
        except Exception as e:
            log.error(f"[process_logos] {e}", exc_info=True)
    sched.add_job(_standalone("process_logos", _process_logos), "interval", hours=24, id="process_logos", next_run_time=t0 + timedelta(minutes=5), executor='maintenance')

    # Bulk logo fill — one-time catch-up for all missing logos, ordered by popularity
    def _bulk_fill_logos():
        try:
            from jobs.process_logos import bulk_fill_missing_logos
            result = bulk_fill_missing_logos(rate_limit=0.15)
            log.info(f"[bulk_fill_logos] Done: {result}")
        except Exception as e:
            log.error(f"[bulk_fill_logos] {e}", exc_info=True)
    sched.add_job(_standalone("bulk_fill_logos", _bulk_fill_logos), "interval", hours=24, id="bulk_fill_logos", next_run_time=t0 + timedelta(minutes=10), misfire_grace_time=600, executor='maintenance')

    # FMP Bulk Harvest — TEMPORARILY PAUSED (Apr 8 2026).
    # The harvest was logging "[FMPHarvest] {ticker} — no data from any prefix" on
    # 100% of attempts, blocking the maintenance executor. Will re-enable AFTER the
    # URL debug logging in jobs/fmp_bulk_harvest.py reveals the root cause.
    def _fmp_harvest():
        try:
            from jobs.fmp_bulk_harvest import run_fmp_bulk_harvest
            db = BgSessionLocal()
            try:
                run_fmp_bulk_harvest(db)
            finally:
                db.close()
        except Exception as e:
            log.error(f"[fmp_harvest] {e}", exc_info=True)
    log.info("[Worker] fmp_harvest is PAUSED — re-enable after URL bug is diagnosed")
    # sched.add_job(_standalone("fmp_harvest", _fmp_harvest), "interval", hours=24, id="fmp_harvest", next_run_time=datetime.utcnow() + timedelta(minutes=1), misfire_grace_time=600, executor='maintenance')

    # Polygon description backfill — fills gaps FMP missed (free, 5 calls/min)
    def _desc_backfill_polygon():
        try:
            from jobs.sector_lookup import backfill_descriptions_polygon
            backfill_descriptions_polygon()
        except Exception as e:
            log.error(f"[desc_backfill_polygon] {e}", exc_info=True)
    sched.add_job(_standalone("desc_backfill_polygon", _desc_backfill_polygon), "interval", hours=24, id="desc_backfill_polygon", next_run_time=t0 + timedelta(minutes=15), executor='maintenance')

    # Benzinga RSS — free, no API key, every 4h
    def _benzinga_rss():
        try:
            from jobs.rss_scrapers import scrape_benzinga_rss
            db = BgSessionLocal()
            try:
                scrape_benzinga_rss(db)
            finally:
                db.close()
        except Exception as e:
            log.error(f"[benzinga_rss] {e}")
    sched.add_job(_standalone("benzinga_rss", _benzinga_rss), "interval", hours=4, id="benzinga_rss", next_run_time=t0 + timedelta(minutes=50), executor='default')

    # MarketBeat RSS — free, no API key, every 4h
    def _marketbeat_rss():
        try:
            from jobs.rss_scrapers import scrape_marketbeat_rss
            db = BgSessionLocal()
            try:
                scrape_marketbeat_rss(db)
            finally:
                db.close()
        except Exception as e:
            log.error(f"[marketbeat_rss] {e}")
    sched.add_job(_standalone("marketbeat_rss", _marketbeat_rss), "interval", hours=4, id="marketbeat_rss", next_run_time=t0 + timedelta(minutes=52), executor='default')

    # yfinance recommendations — free, every 6h
    def _yfinance():
        try:
            from jobs.rss_scrapers import scrape_yfinance_recommendations
            db = BgSessionLocal()
            try:
                scrape_yfinance_recommendations(db)
            finally:
                db.close()
        except Exception as e:
            log.error(f"[yfinance] {e}")
    sched.add_job(_standalone("yfinance", _yfinance), "interval", hours=6, id="yfinance", next_run_time=t0 + timedelta(minutes=60), executor='default')

    # AlphaVantage news sentiment — free tier (25 calls/day), every 8h
    def _alphavantage():
        try:
            from jobs.rss_scrapers import scrape_alphavantage_news
            db = BgSessionLocal()
            try:
                scrape_alphavantage_news(db)
            finally:
                db.close()
        except Exception as e:
            log.error(f"[alphavantage] {e}")
    sched.add_job(_standalone("alphavantage", _alphavantage), "interval", hours=8, id="alphavantage", next_run_time=t0 + timedelta(minutes=65), executor='default')

    # Finnhub upgrades/downgrades — requires FINNHUB_KEY, every 8h
    def _finnhub_upgrades():
        try:
            from jobs.upgrade_scrapers import scrape_finnhub_upgrades
            db = BgSessionLocal()
            try:
                scrape_finnhub_upgrades(db)
            finally:
                db.close()
        except Exception as e:
            log.error(f"[finnhub_upgrades] {e}")
    sched.add_job(_standalone("finnhub_upgrades", _finnhub_upgrades), "interval", hours=8, id="finnhub_upgrades", next_run_time=t0 + timedelta(minutes=70), executor='default')

    # FMP latest grades (upgrades RSS) — requires FMP_KEY, every 4h
    def _fmp_upgrades():
        try:
            from jobs.upgrade_scrapers import scrape_fmp_upgrades
            db = BgSessionLocal()
            try:
                scrape_fmp_upgrades(db)
            finally:
                db.close()
        except Exception as e:
            log.error(f"[fmp_upgrades] {e}")
    sched.add_job(_standalone("fmp_upgrades", _fmp_upgrades), "interval", hours=4, id="fmp_upgrades", next_run_time=t0 + timedelta(minutes=54), executor='default')

    # FMP price target changes — requires FMP_KEY, every 4h
    def _fmp_price_targets():
        try:
            from jobs.upgrade_scrapers import scrape_fmp_price_targets
            db = BgSessionLocal()
            try:
                scrape_fmp_price_targets(db)
            finally:
                db.close()
        except Exception as e:
            log.error(f"[fmp_price_targets] {e}")
    sched.add_job(_standalone("fmp_price_targets", _fmp_price_targets), "interval", hours=4, id="fmp_price_targets", next_run_time=t0 + timedelta(minutes=56), executor='default')

    # FMP daily grades (all upgrades/downgrades for today+yesterday) — requires FMP_KEY, every 6h
    def _fmp_daily_grades():
        try:
            from jobs.upgrade_scrapers import scrape_fmp_daily_grades
            db = BgSessionLocal()
            try:
                scrape_fmp_daily_grades(db)
            finally:
                db.close()
        except Exception as e:
            log.error(f"[fmp_daily_grades] {e}")
    sched.add_job(_standalone("fmp_daily_grades", _fmp_daily_grades), "interval", hours=6, id="fmp_daily_grades", next_run_time=t0 + timedelta(minutes=62), executor='default')

    # FMP ratings backfill — month-by-month from 2018, runs once then done
    _fmp_backfill_done = False
    def _fmp_ratings_backfill():
        nonlocal _fmp_backfill_done
        if _fmp_backfill_done:
            return
        try:
            from jobs.fmp_scraper import backfill_fmp_ratings
            db = BgSessionLocal()
            try:
                result = backfill_fmp_ratings(db)
                log.info(f"[fmp_backfill] {result}")
                _fmp_backfill_done = True
            finally:
                db.close()
        except Exception as e:
            log.error(f"[fmp_backfill] {e}")
    sched.add_job(_standalone("fmp_ratings_backfill", _fmp_ratings_backfill), "interval", hours=24, id="fmp_ratings_backfill", next_run_time=t0 + timedelta(minutes=8), executor='maintenance')

    # FMP grades full backfill — 5000 tickers with full history, runs once
    _fmp_grades_backfill_done = False
    def _fmp_grades_backfill():
        nonlocal _fmp_grades_backfill_done
        if _fmp_grades_backfill_done:
            return
        try:
            from jobs.upgrade_scrapers import backfill_fmp_grades
            db = BgSessionLocal()
            try:
                backfill_fmp_grades(db)
                _fmp_grades_backfill_done = True
                log.info("[fmp_grades_backfill] Complete")
            finally:
                db.close()
        except Exception as e:
            log.error(f"[fmp_grades_backfill] {e}")
    sched.add_job(_standalone("fmp_grades_backfill", _fmp_grades_backfill), "interval", hours=24, id="fmp_grades_backfill", next_run_time=t0 + timedelta(minutes=12), executor='maintenance')

    # FMP Ultimate backfill — one-time massive pull of ALL global grades
    # Runs once on deploy, saves progress to config table, skips if already complete
    def _fmp_ultimate():
        try:
            from jobs.fmp_ultimate_backfill import run_fmp_ultimate_backfill
            db = BgSessionLocal()
            try:
                run_fmp_ultimate_backfill(db)
            finally:
                db.close()
        except Exception as e:
            log.error(f"[fmp_ultimate] {e}", exc_info=True)
    print("[Worker] Registering FMP Ultimate backfill (one-time)...", flush=True)
    sched.add_job(_standalone("fmp_ultimate", _fmp_ultimate), "interval", hours=24, id="fmp_ultimate", next_run_time=datetime.utcnow(), misfire_grace_time=600, executor='maintenance')

    # Cron jobs
    sched.add_job(_watchlist_queue, "interval", hours=4, id="watchlist_queue", next_run_time=t0 + timedelta(minutes=35), executor='default')
    sched.add_job(_watchlist_digest, "cron", day_of_week="mon-fri", hour=13, minute=0, id="watchlist_digest", executor='default')
    sched.add_job(_weekly_digest, "cron", day_of_week="mon", hour=13, minute=0, id="site_weekly_digest", executor='default')
    sched.add_job(_watchdog, "interval", minutes=5, id="watchdog", executor='default')

    # Benzinga historical backfill — runs as daemon thread (forward + reverse)
    # This is the biggest volume lever: 2020→today (forward) then 2019→2011 (reverse)
    try:
        from jobs.benzinga_backfill import auto_resume_backfill
        log.info("[Worker] Starting Benzinga historical backfill daemon")
        auto_resume_backfill()  # spawns its own daemon thread internally
    except Exception as e:
        log.error(f"[Worker] Benzinga backfill failed to start: {e}")

    for j in sched.get_jobs():
        log.info(f"[Worker] {j.id} → next={getattr(j, 'next_run_time', 'pending')}")
    log.info(f"[Worker] {len(sched.get_jobs())} jobs. API deploys won't affect these.")

    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("[Worker] Shutting down")


if __name__ == "__main__":
    main()

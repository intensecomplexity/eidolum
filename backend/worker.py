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

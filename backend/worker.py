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
from sqlalchemy import text as sql_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("worker")

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
    r = evaluate_batch(max_tickers=500)
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
        retry_no_data_batch(db, max_tickers=80)
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

    # Scheduler
    sched = BlockingScheduler()
    t0 = datetime.utcnow() + timedelta(seconds=30)

    # Locked jobs
    sched.add_job(_guarded("massive_benzinga", _massive_benzinga), "interval", hours=2, id="massive_benzinga", next_run_time=t0)
    sched.add_job(_guarded("sweep_stuck", _sweep), "interval", hours=24, id="sweep_stuck", next_run_time=t0 + timedelta(minutes=15))
    sched.add_job(_guarded("analyst_notifications", _analyst_notif), "interval", hours=1, id="analyst_notifications", next_run_time=t0 + timedelta(minutes=25))

    # Independent jobs
    sched.add_job(_standalone("auto_evaluate", _evaluator), "interval", minutes=30, id="auto_evaluate", next_run_time=t0 + timedelta(minutes=5))
    sched.add_job(_standalone("refresh_stats", _refresh_stats), "interval", hours=2, id="refresh_stats", next_run_time=t0 + timedelta(minutes=10))
    sched.add_job(_standalone("fmp_grades", _fmp_grades), "interval", hours=24, id="fmp_grades", next_run_time=t0 + timedelta(minutes=20))
    sched.add_job(_standalone("retry_no_data", _retry_no_data), "interval", hours=1, id="retry_no_data", next_run_time=t0 + timedelta(minutes=30))
    sched.add_job(_standalone("url_backfill", _url_backfill), "interval", hours=24, id="url_backfill", next_run_time=t0 + timedelta(minutes=40))
    sched.add_job(_standalone("tournament_scorer", _tournament), "interval", hours=6, id="tournament_scorer", next_run_time=t0 + timedelta(minutes=45))
    sched.add_job(_standalone("youtube_scraper", _youtube), "interval", hours=8, id="youtube_scraper", next_run_time=t0 + timedelta(minutes=55))
    sched.add_job(_standalone("enrich_urls", _enrich), "interval", hours=1, id="enrich_urls", next_run_time=t0 + timedelta(minutes=35))

    # YouTube Channel Monitor — Claude-powered extraction, every 12h
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
    sched.add_job(_standalone("channel_monitor", _channel_monitor), "interval", hours=12, id="channel_monitor", next_run_time=t0 + timedelta(minutes=90))

    # Cron jobs
    sched.add_job(_watchlist_queue, "interval", hours=4, id="watchlist_queue", next_run_time=t0 + timedelta(minutes=35))
    sched.add_job(_watchlist_digest, "cron", day_of_week="mon-fri", hour=13, minute=0, id="watchlist_digest")
    sched.add_job(_weekly_digest, "cron", day_of_week="mon", hour=13, minute=0, id="site_weekly_digest")
    sched.add_job(_watchdog, "interval", minutes=5, id="watchdog")

    for j in sched.get_jobs():
        log.info(f"[Worker] {j.id} → next={getattr(j, 'next_run_time', 'pending')}")
    log.info(f"[Worker] {len(sched.get_jobs())} jobs. API deploys won't affect these.")

    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("[Worker] Shutting down")


if __name__ == "__main__":
    main()

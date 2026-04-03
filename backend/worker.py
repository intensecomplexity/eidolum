"""
Eidolum Background Worker

Runs all scheduled jobs independently from the API server.
Deploy as a separate Railway service so API pushes don't restart jobs.

Start: python worker.py
Health: http://localhost:8081/health
"""
import os
import sys
import time
import signal
import threading
from datetime import datetime, timedelta
from contextlib import suppress

# Ensure backend/ is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from apscheduler.schedulers.background import BackgroundScheduler
from database import engine, BgSessionLocal, Base
from sqlalchemy import text as sql_text
from circuit_breaker import (
    db_is_healthy, mark_job_running, mark_job_done,
    acquire_job_lock, release_job_lock, watchdog_check,
    db_storage_ok,
)

_scheduler_last_run: dict[str, datetime] = {}
_shutdown = False


def _log(msg):
    print(f"[Worker] {msg}", flush=True)


# ── Shared job wrapper (same as main.py) ─────────────────────────────────────

def _guarded_job(job_name, job_fn):
    """Wrapper: circuit breaker → storage guard → global lock → run."""
    def wrapper():
        _scheduler_last_run[job_name] = datetime.utcnow()
        if not db_is_healthy(job_name):
            return
        if not db_storage_ok(job_name):
            return
        if not acquire_job_lock(job_name):
            return
        mark_job_running(job_name)
        try:
            db = BgSessionLocal()
            try:
                job_fn(db)
            except Exception as e:
                print(f"[{job_name}] Error: {e}")
            finally:
                db.close()
        finally:
            mark_job_done(job_name)
            release_job_lock(job_name)
    return wrapper


def _standalone_job(job_name, job_fn):
    """Wrapper for jobs that don't need the global lock."""
    def wrapper():
        _scheduler_last_run[job_name] = datetime.utcnow()
        if not db_is_healthy(job_name):
            return
        mark_job_running(job_name)
        try:
            job_fn()
        except Exception as e:
            print(f"[{job_name}] Error: {e}")
            import traceback; traceback.print_exc()
        finally:
            mark_job_done(job_name)
    return wrapper


# ── Job definitions (extracted from main.py lifespan) ─────────────────────────

def _job_massive_benzinga(db):
    from jobs.massive_benzinga import scrape_massive_ratings
    scrape_massive_ratings(db)


def _job_auto_evaluate():
    start = time.time()
    from jobs.historical_evaluator import evaluate_batch, refresh_all_forecaster_stats
    total_scored = 0
    batch_num = 0
    while (time.time() - start) < 480:
        result = evaluate_batch(max_tickers=500)
        scored = result.get('predictions_scored', 0)
        remaining = result.get('remaining_tickers', 0)
        total_scored += scored
        batch_num += 1
        print(f"[AutoEval] Batch {batch_num}: {scored} scored, {remaining} remaining")
        if remaining == 0 or result.get('tickers_processed', 0) == 0:
            break
        time.sleep(2)
    if total_scored > 0:
        refresh_all_forecaster_stats()
    print(f"[AutoEval] Done: {total_scored} scored in {batch_num} batches ({time.time()-start:.0f}s)")


def _job_refresh_stats():
    from jobs.historical_evaluator import refresh_all_forecaster_stats
    refresh_all_forecaster_stats()


def _job_fmp_grades():
    # Skip if no_data backlog > 1000
    db = BgSessionLocal()
    try:
        nd = db.execute(sql_text("SELECT COUNT(*) FROM predictions WHERE outcome = 'no_data'")).scalar() or 0
        if nd > 1000:
            print(f"[fmp_grades] SKIPPED — {nd:,} no_data predictions need FMP budget")
            return
    except Exception:
        pass
    finally:
        db.close()

    db = BgSessionLocal()
    try:
        from jobs.upgrade_scrapers import scrape_fmp_grades
        scrape_fmp_grades(db)
    except Exception as e:
        print(f"[fmp_grades] Error: {e}")
    finally:
        db.close()


def _job_sweep_stuck(db):
    from jobs.evaluator import sweep_stuck_predictions, retry_no_data_predictions
    sweep_stuck_predictions(db)
    db2 = BgSessionLocal()
    try:
        retry_no_data_predictions(db2)
    finally:
        db2.close()


def _job_retry_no_data():
    db = BgSessionLocal()
    try:
        from jobs.retry_no_data import retry_no_data_batch
        retry_no_data_batch(db, max_tickers=500)
    except Exception as e:
        print(f"[retry_no_data] Error: {e}")
    finally:
        db.close()


def _job_analyst_notif(db):
    from jobs.analyst_notifications import run_analyst_notifications
    run_analyst_notifications()


def _job_enrich_urls():
    print("[JinaEnrich] Job triggered")
    from jobs.enrich_urls import enrich_source_urls
    enrich_source_urls()


def _job_queue_watchlist():
    from jobs.watchlist_notifier import queue_watchlist_notifications
    queue_watchlist_notifications()


def _job_watchlist_digest():
    from jobs.watchlist_notifier import send_daily_digest
    send_daily_digest()


def _job_site_weekly_digest():
    from jobs.weekly_digest import send_site_weekly_digest
    db = BgSessionLocal()
    try:
        send_site_weekly_digest(db)
    except Exception as e:
        print(f"[SiteDigest] Error: {e}")
    finally:
        db.close()


def _job_youtube_scraper():
    from jobs.youtube_scraper import run_youtube_scraper
    db = BgSessionLocal()
    try:
        run_youtube_scraper(db)
    finally:
        db.close()


def _job_watchdog():
    watchdog_check()
    from circuit_breaker import check_site_health_and_pause
    check_site_health_and_pause()


# ── Startup initialization (migrations, seeds) ───────────────────────────────

def _run_startup_init():
    """Run critical migrations and seeds. Same as main.py _startup_init but synchronous."""
    _log("Running startup initialization...")

    # Create tables
    try:
        Base.metadata.create_all(bind=engine)
        _log("Tables created")
    except Exception as e:
        _log(f"Table creation error: {e}")
        return

    # Run phase2 migrations
    try:
        # Import dynamically to avoid circular imports
        import importlib
        main_mod = importlib.import_module("main")
        if hasattr(main_mod, "run_phase2_migrations"):
            main_mod.run_phase2_migrations()
            _log("Phase2 migrations complete")
    except Exception as e:
        _log(f"Migrations: {e}")

    _log("Startup init complete")


# ── Health check server ──────────────────────────────────────────────────────

def _start_health_server():
    """Simple HTTP health check on port 8081."""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import json

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                body = json.dumps({
                    "status": "ok",
                    "service": "eidolum-worker",
                    "jobs": {k: v.isoformat() for k, v in _scheduler_last_run.items()},
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass  # Suppress access logs

    port = int(os.environ.get("PORT", 8081))
    server = HTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _log(f"Health check server on port {port}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    _log("═" * 50)
    _log("Eidolum Background Worker starting")
    _log(f"PID: {os.getpid()}")
    _log(f"DATABASE_URL set: {bool(os.environ.get('DATABASE_URL'))}")
    _log(f"MASSIVE_API_KEY set: {bool(os.environ.get('MASSIVE_API_KEY'))}")
    _log(f"FMP_KEY set: {bool(os.environ.get('FMP_KEY'))}")
    _log(f"TIINGO_API_KEY set: {bool(os.environ.get('TIINGO_API_KEY'))}")
    _log(f"YOUTUBE_API_KEY set: {bool(os.environ.get('YOUTUBE_API_KEY'))}")
    _log(f"JINA_API_KEY set: {bool(os.environ.get('JINA_API_KEY'))}")
    _log("═" * 50)

    # Start health check server (Railway needs a port listener)
    _start_health_server()

    # Run startup initialization
    _run_startup_init()

    # Wait for tables to be ready
    time.sleep(5)

    # ── Create scheduler ──────────────────────────────────────────────────
    scheduler = BackgroundScheduler()
    first_run = datetime.utcnow() + timedelta(seconds=30)

    # Guarded jobs (acquire global SCRAPER_LOCK)
    scheduler.add_job(_guarded_job("massive_benzinga", _job_massive_benzinga),
                      "interval", hours=2, id="massive_benzinga",
                      next_run_time=first_run)

    scheduler.add_job(_guarded_job("analyst_notifications", _job_analyst_notif),
                      "interval", hours=1, id="analyst_notifications",
                      next_run_time=first_run + timedelta(minutes=25))

    scheduler.add_job(_guarded_job("sweep_stuck", _job_sweep_stuck),
                      "interval", hours=24, id="sweep_stuck",
                      next_run_time=first_run + timedelta(minutes=15))

    # Independent jobs (no global lock)
    scheduler.add_job(_standalone_job("auto_evaluate", _job_auto_evaluate),
                      "interval", minutes=30, id="auto_evaluate",
                      next_run_time=first_run + timedelta(minutes=5))

    scheduler.add_job(_standalone_job("refresh_stats", _job_refresh_stats),
                      "interval", hours=2, id="refresh_stats",
                      next_run_time=first_run + timedelta(minutes=10))

    scheduler.add_job(_standalone_job("fmp_grades", _job_fmp_grades),
                      "interval", hours=24, id="fmp_grades",
                      next_run_time=first_run + timedelta(minutes=20))

    scheduler.add_job(_standalone_job("retry_no_data", _job_retry_no_data),
                      "interval", hours=1, id="retry_no_data",
                      next_run_time=first_run + timedelta(minutes=30))

    scheduler.add_job(_standalone_job("enrich_urls", _job_enrich_urls),
                      "interval", hours=1, id="enrich_urls",
                      next_run_time=first_run + timedelta(minutes=35))

    scheduler.add_job(_standalone_job("youtube_scraper", _job_youtube_scraper),
                      "interval", hours=8, id="youtube_scraper",
                      next_run_time=first_run + timedelta(minutes=55))

    # Watchdog (no wrapper needed)
    scheduler.add_job(_job_watchdog, "interval", minutes=5, id="watchdog")

    # Cron jobs
    scheduler.add_job(_job_queue_watchlist, "interval", hours=4, id="watchlist_queue",
                      next_run_time=first_run + timedelta(minutes=40))

    scheduler.add_job(_job_watchlist_digest, "cron", day_of_week="mon-fri", hour=13, minute=0,
                      id="watchlist_digest")

    scheduler.add_job(_job_site_weekly_digest, "cron", day_of_week="mon", hour=13, minute=0,
                      id="site_weekly_digest")

    # ── Start ─────────────────────────────────────────────────────────────
    scheduler.start()

    for j in scheduler.get_jobs():
        _log(f"Job: {j.id} → next_run={j.next_run_time}")
    _log(f"{len(scheduler.get_jobs())} jobs registered")
    _log("Worker running. API deploys will NOT affect these jobs.")

    # Keep alive
    def shutdown(sig, frame):
        global _shutdown
        _log(f"Received signal {sig}, shutting down...")
        _shutdown = True
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        while not _shutdown:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        _log("Shutting down")
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()

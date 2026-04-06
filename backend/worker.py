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
    sched.add_job(_standalone("retry_no_data", _retry_no_data), "interval", minutes=30, id="retry_no_data", next_run_time=t0 + timedelta(minutes=5))
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
    sched.add_job(_standalone("x_scraper", _x_scraper), "interval", hours=6, id="x_scraper", next_run_time=datetime.utcnow(), misfire_grace_time=300)

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
    sched.add_job(_standalone("stocktwits_scraper", _stocktwits_scraper), "interval", hours=6, id="stocktwits_scraper", next_run_time=datetime.utcnow(), misfire_grace_time=300)

    # Logo processor — process new ticker logos (runs 5 min after start, then daily)
    # First run after deploy reprocesses all logos with improved bg stripping
    _logos_reprocessed = False
    def _process_logos():
        nonlocal _logos_reprocessed
        try:
            from jobs.process_logos import process_all_logos
            reprocess = not _logos_reprocessed
            result = process_all_logos(batch_size=50, rate_limit=0.3, reprocess=reprocess)
            _logos_reprocessed = True
            log.info(f"[process_logos] Done (reprocess={reprocess}): {result}")
        except Exception as e:
            log.error(f"[process_logos] {e}", exc_info=True)
    sched.add_job(_standalone("process_logos", _process_logos), "interval", hours=24, id="process_logos", next_run_time=t0 + timedelta(minutes=5))

    # Polygon description backfill — fills gaps FMP missed (free, 5 calls/min)
    def _desc_backfill_polygon():
        try:
            from jobs.sector_lookup import backfill_descriptions_polygon
            backfill_descriptions_polygon()
        except Exception as e:
            log.error(f"[desc_backfill_polygon] {e}", exc_info=True)
    sched.add_job(_standalone("desc_backfill_polygon", _desc_backfill_polygon), "interval", hours=24, id="desc_backfill_polygon", next_run_time=t0 + timedelta(minutes=15))

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
    sched.add_job(_standalone("benzinga_rss", _benzinga_rss), "interval", hours=4, id="benzinga_rss", next_run_time=t0 + timedelta(minutes=50))

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
    sched.add_job(_standalone("marketbeat_rss", _marketbeat_rss), "interval", hours=4, id="marketbeat_rss", next_run_time=t0 + timedelta(minutes=52))

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
    sched.add_job(_standalone("yfinance", _yfinance), "interval", hours=6, id="yfinance", next_run_time=t0 + timedelta(minutes=60))

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
    sched.add_job(_standalone("alphavantage", _alphavantage), "interval", hours=8, id="alphavantage", next_run_time=t0 + timedelta(minutes=65))

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
    sched.add_job(_standalone("finnhub_upgrades", _finnhub_upgrades), "interval", hours=8, id="finnhub_upgrades", next_run_time=t0 + timedelta(minutes=70))

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
    sched.add_job(_standalone("fmp_upgrades", _fmp_upgrades), "interval", hours=4, id="fmp_upgrades", next_run_time=t0 + timedelta(minutes=54))

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
    sched.add_job(_standalone("fmp_price_targets", _fmp_price_targets), "interval", hours=4, id="fmp_price_targets", next_run_time=t0 + timedelta(minutes=56))

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
    sched.add_job(_standalone("fmp_daily_grades", _fmp_daily_grades), "interval", hours=6, id="fmp_daily_grades", next_run_time=t0 + timedelta(minutes=62))

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
    sched.add_job(_standalone("fmp_ratings_backfill", _fmp_ratings_backfill), "interval", hours=24, id="fmp_ratings_backfill", next_run_time=t0 + timedelta(minutes=8))

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
    sched.add_job(_standalone("fmp_grades_backfill", _fmp_grades_backfill), "interval", hours=24, id="fmp_grades_backfill", next_run_time=t0 + timedelta(minutes=12))

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
    sched.add_job(_standalone("fmp_ultimate", _fmp_ultimate), "interval", hours=24, id="fmp_ultimate", next_run_time=datetime.utcnow(), misfire_grace_time=600)

    # Cron jobs
    sched.add_job(_watchlist_queue, "interval", hours=4, id="watchlist_queue", next_run_time=t0 + timedelta(minutes=35))
    sched.add_job(_watchlist_digest, "cron", day_of_week="mon-fri", hour=13, minute=0, id="watchlist_digest")
    sched.add_job(_weekly_digest, "cron", day_of_week="mon", hour=13, minute=0, id="site_weekly_digest")
    sched.add_job(_watchdog, "interval", minutes=5, id="watchdog")

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

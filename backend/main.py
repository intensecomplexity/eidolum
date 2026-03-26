# ⚠️ DATA SAFETY RULES — DO NOT REMOVE:
# 1. NEVER call Base.metadata.drop_all()
# 2. NEVER call db.query(X).delete() without a WHERE clause
# 3. NEVER truncate tables
# 4. NEVER use --reset or --force flags in production
# 5. ALL seed inserts must use on_conflict_do_nothing()

import os
import sys
import subprocess
import time
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from database import engine, Base, SessionLocal
from models import Forecaster, Prediction, Config
from rate_limit import limiter
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from routers import leaderboard, forecasters, assets, sync, activity, admin, platforms, follows, newsletter, saved, positions, contrarian, power_rankings, inverse, subscribers
from jobs.scraper import run_scraper
from jobs.evaluator import run_evaluator
from jobs.leaderboard_refresh import run_leaderboard_refresh
from jobs.newsletter import run_newsletter
from admin_panel import router as admin_panel_router


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response


def safety_check(db):
    """Verify data integrity before startup completes."""
    fc = db.query(Forecaster).count()
    preds = db.query(Prediction).count()

    print(f"[Eidolum Safety] Forecasters: {fc}")
    print(f"[Eidolum Safety] Predictions: {preds}")

    if fc > 0 and preds == 0:
        print("[Eidolum Safety] ⚠️ WARNING: Predictions missing! Triggering recovery seed...")
        return False  # Trigger re-seed

    return True  # All good


def init_db():
    """Create tables — single attempt, no blocking retries."""
    try:
        Base.metadata.create_all(bind=engine)
        print("[Eidolum] Database tables ready.")
    except Exception as e:
        print(f"[Eidolum] WARNING: Could not create tables: {e}")
        return

    try:
        db = SessionLocal()
        fc = db.query(Forecaster).count()
        pc = db.query(Prediction).count()
        print(f"[Eidolum] DB state: {fc} forecasters, {pc} predictions")
        db.close()
    except Exception as e:
        print(f"[Eidolum] DB check error (non-fatal): {e}")


def migrate_platform_types():
    """Fix platform field for congress/institutional forecasters. Safe to run every boot."""
    CONGRESS_NAMES = [
        "Nancy Pelosi Tracker",
        "Congress Trades Tracker",
        "Unusual Whales",
        "Quiver Quantitative",
    ]
    INSTITUTIONAL_NAMES = [
        "Goldman Sachs",
        "JPMorgan Research",
        "Morgan Stanley",
        "Jim Cramer",
        "Liz Ann Sonders",
        "Dan Ives",
        "Tom Lee",
        "Bill Ackman",
        "ARK Invest",
        "Motley Fool",
        "Hindenburg Research",
        "Citron Research",
    ]
    try:
        db = SessionLocal()
        updated = 0
        for name in CONGRESS_NAMES:
            f = db.query(Forecaster).filter(Forecaster.name == name).first()
            if f:
                if f.platform != "congress":
                    print(f"[Eidolum] Migration: {f.name} ({f.platform!r}) -> congress")
                    f.platform = "congress"
                    updated += 1
            else:
                print(f"[Eidolum] Migration: '{name}' not found in DB")
        for name in INSTITUTIONAL_NAMES:
            f = db.query(Forecaster).filter(Forecaster.name == name).first()
            if f:
                if f.platform != "institutional":
                    print(f"[Eidolum] Migration: {f.name} ({f.platform!r}) -> institutional")
                    f.platform = "institutional"
                    updated += 1
            else:
                print(f"[Eidolum] Migration: '{name}' not found in DB")
        if updated:
            db.commit()
            print(f"[Eidolum] Platform migration: {updated} forecasters updated.")
        else:
            print("[Eidolum] Platform migration: already up to date.")
        # Verify counts
        congress_n = db.query(Forecaster).filter(Forecaster.platform == "congress").count()
        institutional_n = db.query(Forecaster).filter(Forecaster.platform == "institutional").count()
        print(f"[Eidolum] Platform counts: congress={congress_n}, institutional={institutional_n}")
        db.close()
    except Exception as e:
        print(f"[Eidolum] Platform migration error (non-fatal): {e}")


def wipe_all_fake_data(db):
    """Delete predictions without real source URLs. Always runs — idempotent."""
    try:
        from sqlalchemy import text
        total = db.execute(text("SELECT COUNT(*) FROM predictions")).scalar()
        real = db.execute(text("""
            SELECT COUNT(*) FROM predictions
            WHERE source_url LIKE '%/status/%'
               OR source_url LIKE '%/watch?v=%'
               OR source_url LIKE '%/comments/%'
        """)).scalar()
        fake = total - real
        if fake == 0:
            print(f"[Eidolum] Data clean: {total} total, {real} verified, 0 fake")
            return
        result = db.execute(text("""
            DELETE FROM predictions
            WHERE source_url IS NULL
            OR (source_url NOT LIKE '%/status/%'
                AND source_url NOT LIKE '%/watch?v=%'
                AND source_url NOT LIKE '%/comments/%')
        """))
        db.commit()
        print(f"[Eidolum] Wiped {result.rowcount} fake predictions (kept {real} verified)")
    except Exception as e:
        db.rollback()
        print(f"[Eidolum] wipe_all_fake_data error: {e}")


def migrate_add_archive_columns(db):
    """Add archive_url and archived_at columns if they don't exist."""
    from sqlalchemy import text
    for col, defn in [("archive_url", "VARCHAR"), ("archived_at", "TIMESTAMP")]:
        try:
            db.execute(text(f"ALTER TABLE predictions ADD COLUMN {col} {defn}"))
            db.commit()
            print(f"[Eidolum] {col} column added")
        except Exception as e:
            db.rollback()
            if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                pass  # expected on subsequent boots
            else:
                print(f"[Eidolum] migrate {col}: {e}")


def migrate_populate_quotes(db):
    """Copy context into exact_quote where quote is missing. Safe/idempotent."""
    try:
        from sqlalchemy import text
        result = db.execute(text("""
            UPDATE predictions
            SET exact_quote = context
            WHERE exact_quote IS NULL
            AND context IS NOT NULL
        """))
        db.commit()
        print(f"[Eidolum] Populated exact_quote for {result.rowcount} predictions")
    except Exception as e:
        db.rollback()
        print(f"[Eidolum] migrate_populate_quotes error: {e}")


def migrate_clear_fake_source_urls(db):
    """Clear source URLs that aren't real post/video/tweet/article links. Safe/idempotent."""
    try:
        from sqlalchemy import text
        result = db.execute(text("""
            UPDATE predictions
            SET source_url = NULL
            WHERE source_url IS NOT NULL
            AND source_url NOT LIKE '%/watch?v=%'
            AND source_url NOT LIKE '%/status/%'
            AND source_url NOT LIKE '%/comments/%'
            AND source_url NOT LIKE '%reddit.com/r/%'
            AND source_url NOT LIKE '%stockanalysis.com%'
            AND source_url NOT LIKE '%cnbc.com%'
            AND source_url NOT LIKE '%reuters.com%'
            AND source_url NOT LIKE '%marketwatch.com%'
            AND source_url NOT LIKE '%benzinga.com%'
            AND source_url NOT LIKE '%seekingalpha.com%'
            AND source_url NOT LIKE '%barrons.com%'
            AND source_url NOT LIKE '%thestreet.com%'
            AND source_url NOT LIKE '%investors.com%'
            AND source_url NOT LIKE '%fool.com%'
            AND source_url NOT LIKE '%bloomberg.com%'
            AND source_url NOT LIKE '%wsj.com%'
            AND source_url NOT LIKE '%ft.com%'
            AND source_url NOT LIKE '%forbes.com%'
            AND source_url NOT LIKE '%yahoo.com%'
            AND source_url NOT LIKE '%web.archive.org%'
        """))
        db.commit()
        print(f"[Eidolum] Cleared {result.rowcount} fake source URLs")
    except Exception as e:
        db.rollback()
        print(f"[Eidolum] migrate_clear_fake_source_urls error: {e}")


def wipe_all_predictions(db):
    """CLEAN SLATE: Delete ALL predictions. Called once at startup to rebuild from real sources only."""
    try:
        from sqlalchemy import text
        count = db.execute(text("SELECT COUNT(*) FROM predictions")).scalar()
        if count == 0:
            print("[Cleanup] Predictions table already empty")
            return
        result = db.execute(text("DELETE FROM predictions"))
        db.commit()
        print(f"[Cleanup] WIPED {result.rowcount} predictions — clean slate for real articles only")
    except Exception as e:
        db.rollback()
        print(f"[Cleanup] wipe_all_predictions error: {e}")


def migrate_profile_urls():
    """Fix broken social media profile links. Safe to run every boot."""
    URL_FIXES = {
        "Nancy Pelosi Tracker": ("@PelosiTracker", "https://x.com/PelosiTracker"),
        "Congress Trades Tracker": ("@CongressTrading", "https://x.com/CongressTrading"),
        "Quiver Quantitative": ("@QuiverQuant", "https://x.com/QuiverQuant"),
        "Elon Musk": ("@elonmusk", "https://x.com/elonmusk"),
        "Michael Saylor": ("@saylor", "https://x.com/saylor"),
        "Patrick Boyle": (None, "https://youtube.com/@PBoyle"),
        "Mark Moss": (None, "https://youtube.com/@1MarkMoss"),
        "Humphrey Yang": (None, "https://youtube.com/@humphreytalks"),
        "JPMorgan Research": (None, "https://x.com/jpmorgan"),
        "Motley Fool": (None, "https://x.com/TheMotleyFool"),
    }
    try:
        db = SessionLocal()
        updated = 0
        for name, (handle, url) in URL_FIXES.items():
            f = db.query(Forecaster).filter(Forecaster.name == name).first()
            if not f:
                continue
            changed = False
            if url and f.channel_url != url:
                f.channel_url = url
                changed = True
            if handle and f.handle != handle:
                f.handle = handle
                changed = True
            if changed:
                updated += 1
                print(f"[Eidolum] URL fix: {f.name} -> {url}")
        if updated:
            db.commit()
            print(f"[Eidolum] URL migration: {updated} forecasters updated.")
        else:
            print("[Eidolum] URL migration: already up to date.")
        db.close()
    except Exception as e:
        print(f"[Eidolum] URL migration error (non-fatal): {e}")


def archive_missing_proofs(db):
    """Archive predictions that have source_url but no archive_url."""
    try:
        unarchived = db.query(Prediction).filter(
            Prediction.source_url.isnot(None),
            Prediction.archive_url.is_(None),
        ).limit(50).all()

        if not unarchived:
            return

        print(f"[Archive] Archiving {len(unarchived)} predictions without proof...")
        import asyncio
        from archiver.screenshot import take_screenshot

        for p in unarchived:
            loop = asyncio.new_event_loop()
            try:
                f = db.query(Forecaster).filter(Forecaster.id == p.forecaster_id).first()
                fname = f.name if f else ""
                archive_url = loop.run_until_complete(
                    take_screenshot(
                        p.source_url, p.id,
                        p.exact_quote or "", fname,
                        str(p.prediction_date)[:10] if p.prediction_date else "",
                    )
                )
                if archive_url:
                    from sqlalchemy import text as _ar
                    db.execute(
                        _ar("UPDATE predictions SET archive_url=:url, archived_at=:ts WHERE id=:id"),
                        {"url": archive_url, "ts": datetime.utcnow(), "id": p.id},
                    )
                    db.commit()
            except Exception as e:
                print(f"[Archive] Failed {p.id}: {e}")
            finally:
                loop.close()
            time.sleep(0.1)

        print("[Archive] Done archiving batch")
    except Exception as e:
        print(f"[Archive] archive_missing_proofs error: {e}")


@asynccontextmanager
async def lifespan(app):
    init_db()
    try:
        migrate_platform_types()
    except Exception as e:
        print(f"[Eidolum] Platform migration error (non-fatal): {e}")
    try:
        migrate_profile_urls()
    except Exception as e:
        print(f"[Eidolum] Profile URL migration error (non-fatal): {e}")
    # Log archive capability
    try:
        from archiver.screenshot import log_archive_status
        log_archive_status()
    except Exception:
        pass
    # STEP 1: CLEAN SLATE — delete ALL predictions before anything else
    try:
        db = SessionLocal()
        wipe_all_predictions(db)
        db.close()
    except Exception as e:
        print(f"[Eidolum] Prediction wipe error (non-fatal): {e}")
    # Remove Reddit forecasters (replaced by magazines)
    try:
        from sqlalchemy import text as _rd
        db = SessionLocal()
        reddit_count = db.execute(_rd("SELECT COUNT(*) FROM forecasters WHERE platform = 'reddit'")).scalar()
        if reddit_count > 0:
            db.execute(_rd("DELETE FROM forecasters WHERE platform = 'reddit'"))
            db.execute(_rd("DELETE FROM forecasters WHERE name LIKE '%WSB%'"))
            db.commit()
        db.close()
    except Exception as e:
        print(f"[Migration] Reddit cleanup error (non-fatal): {e}")
    # STEP 2: Seed 50 forecasters (keep existing, add missing)
    try:
        db = SessionLocal()
        from jobs.seed_magazines import seed_magazine_forecasters
        seed_magazine_forecasters(db)
        db.close()
    except Exception as e:
        print(f"[Eidolum] Magazine seed error (non-fatal): {e}")
    # Add cached stats columns to forecasters if missing
    try:
        from sqlalchemy import text as _t
        db = SessionLocal()
        for col_sql in [
            "ALTER TABLE forecasters ADD COLUMN accuracy_score FLOAT",
            "ALTER TABLE forecasters ADD COLUMN total_predictions INTEGER DEFAULT 0",
            "ALTER TABLE forecasters ADD COLUMN correct_predictions INTEGER DEFAULT 0",
            "ALTER TABLE forecasters ADD COLUMN streak INTEGER DEFAULT 0",
        ]:
            try:
                db.execute(_t(col_sql))
                db.commit()
            except Exception:
                db.rollback()
        db.close()
    except Exception as e:
        print(f"[Eidolum] Stats column migration error (non-fatal): {e}")
    # Run historical import in background thread so server starts immediately
    import threading

    def run_historical_import_background():
        import time
        time.sleep(10)
        try:
            db = SessionLocal()
            pred_count = db.query(Prediction).count()
            print(f"[Eidolum] Background import starting — {pred_count} predictions exist")
            # Scrape real news articles (Layer 1 + Layer 2 built in)
            try:
                from jobs.news_scraper import scrape_news_predictions
                scrape_news_predictions(db)
            except Exception as e:
                print(f"[Background] News scraper error: {e}")
            # Layer 3: cleanup anything that slipped through
            try:
                from jobs.prediction_validator import cleanup_invalid_predictions
                cleanup_invalid_predictions(db)
            except Exception as e:
                print(f"[Background] L3 cleanup error: {e}")
            pred_count = db.query(Prediction).count()
            print(f"[Eidolum] Background import complete — {pred_count} real predictions loaded")
            # Evaluate pending predictions
            try:
                from jobs.evaluate_predictions import evaluate_all_pending
                evaluate_all_pending(db)
            except Exception as e:
                print(f"[Background] Evaluator error: {e}")
            db.close()
        except Exception as e:
            print(f"[Eidolum] Background import error: {e}")

    thread = threading.Thread(target=run_historical_import_background, daemon=True)
    thread.start()
    print("[Eidolum] Historical import started in background thread")
    # Add archive columns if missing
    try:
        db = SessionLocal()
        migrate_add_archive_columns(db)
        db.close()
    except Exception as e:
        print(f"[Eidolum] Archive column migration error (non-fatal): {e}")
    # Safety check — scan for dangerous patterns
    try:
        from safety_check import check_safety
        violations = check_safety()
        if violations:
            print(f"[SAFETY WARNING] {len(violations)} dangerous pattern(s) found in codebase:")
            for v in violations:
                print(f"  {v['file']}: '{v['pattern']}' — {v['reason']}")
        else:
            print("[Eidolum] Safety check passed.")
    except Exception as e:
        print(f"[Eidolum] Safety check error (non-fatal): {e}")
    # Security warning
    if not os.getenv("ADMIN_SECRET"):
        print("[WARNING] ADMIN_SECRET not set — admin routes are unprotected!")
    # Start background job scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(lambda: run_scraper(SessionLocal()), "interval", hours=1, id="scraper")
    scheduler.add_job(lambda: run_evaluator(SessionLocal()), "interval", minutes=15, id="evaluator")
    scheduler.add_job(lambda: run_leaderboard_refresh(SessionLocal()), "interval", hours=1, id="leaderboard")
    scheduler.add_job(lambda: run_newsletter(SessionLocal()), "cron", hour=8, minute=0, id="newsletter")
    scheduler.start()
    print("[Eidolum] Starting — clean verified data only. Scheduler: scraper(1h), evaluator(15m), leaderboard(1h), newsletter(8am daily)")
    yield
    scheduler.shutdown()


app = FastAPI(title="Eidolum API", version="1.0.0", lifespan=lifespan)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Security headers
app.add_middleware(SecurityHeadersMiddleware)

# CORS — strict origin whitelist
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://www.eidolum.com",
        "https://eidolum.com",
        "https://eidolum.vercel.app",
        "https://api.eidolum.com",
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve archived screenshots
from fastapi.staticfiles import StaticFiles
_archive_dir = os.getenv("ARCHIVE_DIR", "/app/archive")
os.makedirs(_archive_dir, exist_ok=True)
app.mount("/archive", StaticFiles(directory=_archive_dir), name="archive")

app.include_router(leaderboard.router, prefix="/api")
app.include_router(forecasters.router, prefix="/api")
app.include_router(assets.router, prefix="/api")
app.include_router(sync.router, prefix="/api")
app.include_router(activity.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(platforms.router, prefix="/api")
app.include_router(follows.router, prefix="/api")
app.include_router(newsletter.router, prefix="/api")
app.include_router(saved.router, prefix="/api")
app.include_router(positions.router, prefix="/api")
app.include_router(contrarian.router, prefix="/api")
app.include_router(power_rankings.router, prefix="/api")
app.include_router(inverse.router, prefix="/api")
app.include_router(subscribers.router, prefix="/api")
app.include_router(admin_panel_router)  # /admin HTML + /api/admin/* endpoints


@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok", "app": "Eidolum API"}


@app.get("/api/debug")
def debug():
    """Temporary debug endpoint — remove after deployment is stable."""
    from database import DATABASE_URL as RESOLVED_URL
    raw_url = os.getenv("DATABASE_URL", "not-set")
    info = {
        "database_url_set": bool(os.getenv("DATABASE_URL")),
        "database_url_prefix": raw_url[:25] + "..." if raw_url != "not-set" else "not-set",
        "engine_url_prefix": str(engine.url)[:30] + "...",
        "engine_dialect": engine.dialect.name,
        "seed_data": os.getenv("SEED_DATA", "not-set"),
        "port": os.getenv("PORT", "not-set"),
    }
    try:
        from sqlalchemy import func
        db = SessionLocal()
        count = db.query(Forecaster).count()
        pred_count = db.query(Prediction).count()
        info["db_connected"] = True
        info["forecaster_count"] = count
        info["prediction_count"] = pred_count
        # Platform breakdown
        platform_counts = db.query(
            Forecaster.platform, func.count(Forecaster.id)
        ).group_by(Forecaster.platform).all()
        info["platform_breakdown"] = {p: c for p, c in platform_counts}
        db.close()
    except Exception as e:
        info["db_connected"] = False
        info["db_error"] = str(e)
    return info

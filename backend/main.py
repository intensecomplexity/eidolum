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
    """Create tables and optionally seed — with retry for Postgres startup delay."""
    # NEVER drop or truncate any table — ONLY create tables that don't exist yet
    for attempt in range(5):
        try:
            Base.metadata.create_all(bind=engine)
            print(f"[Eidolum] Database tables created (attempt {attempt + 1}).")
            break
        except Exception as e:
            print(f"[Eidolum] DB connect attempt {attempt + 1} failed: {e}")
            if attempt < 4:
                time.sleep(2)
            else:
                print("[Eidolum] WARNING: Could not connect to database after 5 attempts.")
                return

    # Auto-seed if SEED_DATA=true
    if os.getenv("SEED_DATA", "").lower() in ("true", "1", "yes"):
        db = SessionLocal()
        try:
            forecaster_count = db.query(Forecaster).count()
            prediction_count = db.query(Prediction).count()

            if forecaster_count == 0:
                # Fresh DB — seed everything
                print(f"[Eidolum] DB empty — running full seed...")
                subprocess.run(
                    [sys.executable, "seed.py"],
                    check=True,
                    cwd=os.path.dirname(os.path.abspath(__file__)),
                )
                print("[Eidolum] Full seed complete.")

            elif prediction_count == 0 and forecaster_count > 0:
                # Forecasters exist but predictions missing — verified reseed handles this
                print(f"[Eidolum] {forecaster_count} forecasters but 0 predictions — verified reseed will handle this.")

            else:
                print(f"[Eidolum] DB healthy: {forecaster_count} forecasters, "
                      f"{prediction_count} predictions — skipping seed.")
        except Exception as e:
            print(f"[Eidolum] Seed error (non-fatal): {e}")
        finally:
            db.close()

    # Run safety check (informational only — verified reseed handles data)
    db = SessionLocal()
    try:
        safety_check(db)
    finally:
        db.close()


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
    """Clear source URLs that aren't real post/video/tweet links. Safe/idempotent."""
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
        """))
        db.commit()
        print(f"[Eidolum] Cleared {result.rowcount} fake source URLs")
    except Exception as e:
        db.rollback()
        print(f"[Eidolum] migrate_clear_fake_source_urls error: {e}")


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


@asynccontextmanager
async def lifespan(app):
    init_db()
    migrate_platform_types()
    migrate_profile_urls()
    # Wipe fake predictions (keeps only those with real source URLs)
    try:
        db = SessionLocal()
        wipe_all_fake_data(db)
        db.close()
    except Exception as e:
        print(f"[Eidolum] Fake data wipe error (non-fatal): {e}")
    # Clear old config flag if it exists
    try:
        from sqlalchemy import text as _text
        db = SessionLocal()
        db.execute(_text("DELETE FROM config WHERE key = 'verified_reseed_done'"))
        db.commit()
        db.close()
    except Exception:
        pass  # config table may not exist
    # Add cached stats columns to forecasters if missing
    try:
        db = SessionLocal()
        from sqlalchemy import text as _t
        for col, defn in [
            ("accuracy_score", "FLOAT"),
            ("total_predictions", "INTEGER DEFAULT 0"),
            ("correct_predictions", "INTEGER DEFAULT 0"),
            ("streak", "INTEGER DEFAULT 0"),
        ]:
            try:
                db.execute(_t(f"ALTER TABLE forecasters ADD COLUMN {col} {defn}"))
            except Exception:
                pass  # column already exists
        db.commit()
        db.close()
    except Exception as e:
        print(f"[Eidolum] Stats column migration error (non-fatal): {e}")
    # Seed verified predictions (only if fewer than 5 real ones exist)
    try:
        from seed_verified import seed_verified
        seed_verified()
    except Exception as e:
        print(f"[Eidolum] Verified reseed error (non-fatal): {e}")
    # Run YouTube historical import once if fewer than 100 predictions exist
    try:
        db = SessionLocal()
        _pred_count = db.query(Prediction).count()
        db.close()
        if _pred_count < 100:
            print("[Eidolum] Running full historical import (YouTube + Twitter + Reddit)...")
            db = SessionLocal()
            from jobs.youtube_history import run_youtube_history
            from jobs.twitter_history import scrape_twitter_history
            from jobs.reddit_history import scrape_reddit_history
            run_youtube_history(db)
            scrape_twitter_history(db)
            scrape_reddit_history(db)
            db.close()
            print("[Eidolum] Historical import complete")
    except Exception as e:
        print(f"[Eidolum] YouTube history import error (non-fatal): {e}")
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
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PUT", "PATCH"],
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

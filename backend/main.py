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
from database import engine, Base, SessionLocal
from models import Forecaster, Prediction
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from routers import leaderboard, forecasters, assets, sync, activity, admin, platforms, follows, newsletter, saved, positions, contrarian, power_rankings, inverse, subscribers
from jobs.scraper import run_scraper
from jobs.evaluator import run_evaluator
from jobs.leaderboard_refresh import run_leaderboard_refresh
from jobs.newsletter import run_newsletter


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
                # Forecasters exist but predictions got wiped
                print(f"[Eidolum] {forecaster_count} forecasters but 0 predictions — reseeding predictions only...")
                subprocess.run(
                    [sys.executable, "seed.py", "--predictions-only"],
                    check=True,
                    cwd=os.path.dirname(os.path.abspath(__file__)),
                )
                print("[Eidolum] Predictions re-seeded.")

            else:
                print(f"[Eidolum] DB healthy: {forecaster_count} forecasters, "
                      f"{prediction_count} predictions — skipping seed.")
        except Exception as e:
            print(f"[Eidolum] Seed error (non-fatal): {e}")
        finally:
            db.close()

    # Run safety check regardless of SEED_DATA setting
    db = SessionLocal()
    try:
        if not safety_check(db):
            # Attempt recovery seed
            try:
                subprocess.run(
                    [sys.executable, "seed.py", "--predictions-only"],
                    check=True,
                    cwd=os.path.dirname(os.path.abspath(__file__)),
                )
                print("[Eidolum Safety] Recovery seed complete.")
            except Exception as e:
                print(f"[Eidolum Safety] Recovery seed failed: {e}")
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
    # Clean fake video IDs from seed data
    try:
        from setup_db import clean_fake_video_ids
        clean_fake_video_ids()
    except Exception as e:
        print(f"[Eidolum] Video ID cleanup error (non-fatal): {e}")
    # Populate source URLs for predictions missing them
    try:
        from setup_db import populate_source_urls
        populate_source_urls()
    except Exception as e:
        print(f"[Eidolum] Source URL population error (non-fatal): {e}")
    # Seed crypto predictions (safe — checks for existing data before inserting)
    try:
        from seed_crypto import seed_crypto
        seed_crypto()
    except Exception as e:
        print(f"[Eidolum] Crypto seed error (non-fatal): {e}")
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
    # Start background job scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(lambda: run_scraper(SessionLocal()), "interval", hours=1, id="scraper")
    scheduler.add_job(lambda: run_evaluator(SessionLocal()), "interval", minutes=15, id="evaluator")
    scheduler.add_job(lambda: run_leaderboard_refresh(SessionLocal()), "interval", hours=1, id="leaderboard")
    scheduler.add_job(lambda: run_newsletter(SessionLocal()), "cron", hour=8, minute=0, id="newsletter")
    scheduler.start()
    print("[Eidolum] Scheduler started — scraper(1h), evaluator(15m), leaderboard(1h), newsletter(8am daily)")
    yield
    scheduler.shutdown()


app = FastAPI(title="Eidolum API", version="1.0.0", lifespan=lifespan)

origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://www.eidolum.com",
    "https://eidolum.com",
    "https://eidolum.vercel.app",
    "https://eidolum-production.up.railway.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https://.*\.(vercel\.app|railway\.app)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

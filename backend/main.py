import os
import sys
import subprocess
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base, SessionLocal
from models import Forecaster
from routers import leaderboard, forecasters, assets, sync, activity, admin, platforms, follows, newsletter, saved, positions, contrarian, power_rankings, inverse


def init_db():
    """Create tables and optionally seed — with retry for Postgres startup delay."""
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

    # Auto-seed if SEED_DATA=true and DB is empty
    if os.getenv("SEED_DATA", "").lower() in ("true", "1", "yes"):
        try:
            db = SessionLocal()
            count = db.query(Forecaster).count()
            db.close()
            if count == 0:
                print("[Eidolum] Database empty — running seed.py...")
                subprocess.run(
                    [sys.executable, "seed.py"],
                    check=True,
                    cwd=os.path.dirname(os.path.abspath(__file__)),
                )
                print("[Eidolum] Seed complete.")
            else:
                print(f"[Eidolum] Database has {count} forecasters, skipping seed.")
        except Exception as e:
            print(f"[Eidolum] Seed error (non-fatal): {e}")


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
            if f and f.platform != "congress":
                f.platform = "congress"
                updated += 1
                print(f"[Eidolum] Migration: {f.name} -> congress")
        for name in INSTITUTIONAL_NAMES:
            f = db.query(Forecaster).filter(Forecaster.name == name).first()
            if f and f.platform != "institutional":
                f.platform = "institutional"
                updated += 1
                print(f"[Eidolum] Migration: {f.name} -> institutional")
        if updated:
            db.commit()
            print(f"[Eidolum] Platform migration: {updated} forecasters updated.")
        else:
            print("[Eidolum] Platform migration: already up to date.")
        db.close()
    except Exception as e:
        print(f"[Eidolum] Platform migration error (non-fatal): {e}")


@asynccontextmanager
async def lifespan(app):
    init_db()
    migrate_platform_types()
    yield


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


@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok", "app": "Eidolum API"}


@app.get("/api/debug")
def debug():
    """Temporary debug endpoint — remove after deployment is stable."""
    info = {
        "database_url_set": bool(os.getenv("DATABASE_URL")),
        "database_url_prefix": (os.getenv("DATABASE_URL", "not-set"))[:25] + "...",
        "seed_data": os.getenv("SEED_DATA", "not-set"),
        "port": os.getenv("PORT", "not-set"),
    }
    try:
        db = SessionLocal()
        count = db.query(Forecaster).count()
        db.close()
        info["db_connected"] = True
        info["forecaster_count"] = count
    except Exception as e:
        info["db_connected"] = False
        info["db_error"] = str(e)
    return info

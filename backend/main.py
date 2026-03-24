import os
import sys
import subprocess
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base, SessionLocal
from models import Forecaster
from routers import leaderboard, forecasters, assets, sync, activity, admin, platforms, follows, newsletter, saved

# Create all tables
Base.metadata.create_all(bind=engine)

# Auto-seed on first deploy if SEED_DATA=true and DB is empty
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
            print(f"[Eidolum] Database already has {count} forecasters, skipping seed.")
    except Exception as e:
        print(f"[Eidolum] Seed error (non-fatal): {e}")

app = FastAPI(title="Eidolum API", version="1.0.0")

origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://www.eidolum.com",
    "https://eidolum.com",
    "https://eidolum.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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


@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok", "app": "Eidolum API"}

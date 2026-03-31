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
from datetime import datetime, timedelta, date
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from database import engine, bg_engine, Base, SessionLocal, BgSessionLocal
from models import Forecaster, Prediction, Config
from rate_limit import limiter
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from routers import leaderboard, forecasters, assets, sync, activity, admin, platforms, follows, newsletter, saved, positions, contrarian, power_rankings, inverse, subscribers, predictions, auth, user_predictions, community, user_follows, duels, seasons_router, notifications as notifications_router, ticker_detail, activity_feed, share, daily_challenge as daily_challenge_router, reactions, watchlist as watchlist_router, controversial
from jobs.scraper import run_scraper
from jobs.evaluator import run_evaluator
from jobs.user_evaluator import evaluate_user_predictions, evaluate_duels, check_season_completion
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


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    """Kill any API request that takes longer than 8 seconds.
    Returns 504 Gateway Timeout so hanging requests don't pile up and exhaust connections."""

    TIMEOUT_SECONDS = 8

    async def dispatch(self, request: Request, call_next):
        import asyncio

        # Skip timeout for admin endpoints (they can be slow by design)
        if request.url.path.startswith("/api/admin/"):
            return await call_next(request)
        # Skip for non-API routes (static files, health checks)
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        try:
            response = await asyncio.wait_for(
                call_next(request),
                timeout=self.TIMEOUT_SECONDS,
            )
            return response
        except asyncio.TimeoutError:
            from starlette.responses import JSONResponse
            print(f"[TIMEOUT] {request.method} {request.url.path} exceeded {self.TIMEOUT_SECONDS}s")
            return JSONResponse(
                status_code=504,
                content={"error": "timeout", "message": f"Request took longer than {self.TIMEOUT_SECONDS}s"},
            )


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
    """Create tables — single attempt, skip if DB is slow."""
    try:
        # Quick connectivity test first
        from sqlalchemy import text as _t
        with engine.connect() as conn:
            conn.execute(_t("SELECT 1"))
        print("[Eidolum] DB connection OK")
    except Exception as e:
        print(f"[Eidolum] WARNING: DB not reachable, skipping init: {e}")
        return

    try:
        Base.metadata.create_all(bind=engine)
        print("[Eidolum] Database tables ready.")
    except Exception as e:
        print(f"[Eidolum] WARNING: Could not create tables: {e}")
        return

    try:
        db = SessionLocal()
        print(f"[Eidolum] DB state: connected")
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


def run_phase2_migrations():
    """Phase 2 schema: users, user_predictions, achievements, follows, duels, seasons, season_entries + indexes."""
    from sqlalchemy import text
    db = SessionLocal()

    # ── 1. users ──────────────────────────────────────────────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                display_name VARCHAR(100),
                email VARCHAR(255) UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                avatar_url TEXT,
                bio TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                streak_current INTEGER DEFAULT 0,
                streak_best INTEGER DEFAULT 0,
                paper_balance DECIMAL(20,2) DEFAULT 0
            )
        """))
        db.commit()
        print("[Phase2] users table created")
    except Exception as e:
        db.rollback()
        if "already exists" in str(e).lower():
            pass
        else:
            print(f"[Phase2] users table: {e}")

    # Add columns that may be missing from the earlier migration
    for col, defn in [
        ("avatar_url", "TEXT"),
        ("bio", "TEXT"),
        ("paper_balance", "DECIMAL(20,2) DEFAULT 0"),
    ]:
        try:
            db.execute(text(f"ALTER TABLE users ADD COLUMN {col} {defn}"))
            db.commit()
            print(f"[Phase2] users.{col} column added")
        except Exception as e:
            db.rollback()
            if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                pass
            else:
                print(f"[Phase2] users ADD {col}: {e}")

    # Ensure password_hash is NOT NULL (may have been nullable before)
    try:
        db.execute(text("ALTER TABLE users ALTER COLUMN password_hash SET NOT NULL"))
        db.commit()
    except Exception:
        db.rollback()

    # ── 2. user_predictions ───────────────────────────────────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS user_predictions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                ticker VARCHAR(10) NOT NULL,
                direction VARCHAR(10) NOT NULL CHECK (direction IN ('bullish', 'bearish')),
                price_target VARCHAR(50) NOT NULL,
                price_at_call DECIMAL(20,2),
                evaluation_window_days INTEGER NOT NULL CHECK (evaluation_window_days BETWEEN 1 AND 365),
                reasoning TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                expires_at TIMESTAMP NOT NULL,
                evaluated_at TIMESTAMP,
                outcome VARCHAR(20) DEFAULT 'pending' CHECK (outcome IN ('pending', 'correct', 'incorrect')),
                current_price DECIMAL(20,2)
            )
        """))
        db.commit()
        print("[Phase2] user_predictions table created")
    except Exception as e:
        db.rollback()
        if "already exists" in str(e).lower():
            pass
        else:
            print(f"[Phase2] user_predictions table: {e}")

    # Add expires_at column if table existed from earlier migration
    try:
        db.execute(text("ALTER TABLE user_predictions ADD COLUMN expires_at TIMESTAMP"))
        db.commit()
        print("[Phase2] user_predictions.expires_at column added")
    except Exception as e:
        db.rollback()
        if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
            pass
        else:
            print(f"[Phase2] user_predictions ADD expires_at: {e}")

    # Backfill expires_at for any existing rows that have NULL
    try:
        db.execute(text("""
            UPDATE user_predictions
            SET expires_at = created_at + (evaluation_window_days || ' days')::INTERVAL
            WHERE expires_at IS NULL AND created_at IS NOT NULL
        """))
        db.commit()
    except Exception:
        db.rollback()

    # ── 3. achievements ───────────────────────────────────────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS achievements (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                badge_id VARCHAR(50) NOT NULL,
                unlocked_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(user_id, badge_id)
            )
        """))
        db.commit()
        print("[Phase2] achievements table created")
    except Exception as e:
        db.rollback()
        if "already exists" in str(e).lower():
            pass
        else:
            print(f"[Phase2] achievements table: {e}")

    # ── 4. follows ────────────────────────────────────────────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS follows (
                id SERIAL PRIMARY KEY,
                follower_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                following_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(follower_id, following_id),
                CHECK (follower_id != following_id)
            )
        """))
        db.commit()
        print("[Phase2] follows table created")
    except Exception as e:
        db.rollback()
        if "already exists" in str(e).lower():
            pass
        else:
            print(f"[Phase2] follows table: {e}")

    # ── 5. duels ──────────────────────────────────────────────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS duels (
                id SERIAL PRIMARY KEY,
                challenger_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                opponent_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                ticker VARCHAR(10) NOT NULL,
                challenger_direction VARCHAR(10) NOT NULL CHECK (challenger_direction IN ('bullish', 'bearish')),
                opponent_direction VARCHAR(10) NOT NULL CHECK (opponent_direction IN ('bullish', 'bearish')),
                challenger_target VARCHAR(50) NOT NULL,
                opponent_target VARCHAR(50) NOT NULL,
                evaluation_window_days INTEGER NOT NULL,
                price_at_start DECIMAL(20,2),
                created_at TIMESTAMP DEFAULT NOW(),
                expires_at TIMESTAMP NOT NULL,
                status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'completed', 'declined')),
                winner_id INTEGER REFERENCES users(id),
                evaluated_at TIMESTAMP
            )
        """))
        db.commit()
        print("[Phase2] duels table created")
    except Exception as e:
        db.rollback()
        if "already exists" in str(e).lower():
            pass
        else:
            print(f"[Phase2] duels table: {e}")

    # ── 6. seasons ────────────────────────────────────────────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS seasons (
                id SERIAL PRIMARY KEY,
                name VARCHAR(50) NOT NULL,
                starts_at TIMESTAMP NOT NULL,
                ends_at TIMESTAMP NOT NULL,
                status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'completed')),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db.commit()
        print("[Phase2] seasons table created")
    except Exception as e:
        db.rollback()
        if "already exists" in str(e).lower():
            pass
        else:
            print(f"[Phase2] seasons table: {e}")

    # ── 7. season_entries ─────────────────────────────────────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS season_entries (
                id SERIAL PRIMARY KEY,
                season_id INTEGER REFERENCES seasons(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                predictions_made INTEGER DEFAULT 0,
                predictions_scored INTEGER DEFAULT 0,
                predictions_correct INTEGER DEFAULT 0,
                UNIQUE(season_id, user_id)
            )
        """))
        db.commit()
        print("[Phase2] season_entries table created")
    except Exception as e:
        db.rollback()
        if "already exists" in str(e).lower():
            pass
        else:
            print(f"[Phase2] season_entries table: {e}")

    # ── Indexes ───────────────────────────────────────────────────────────
    indexes = [
        ("idx_user_predictions_user_id",       "user_predictions(user_id)"),
        ("idx_user_predictions_outcome",       "user_predictions(outcome)"),
        ("idx_user_predictions_ticker",        "user_predictions(ticker)"),
        ("idx_user_predictions_expires_at",    "user_predictions(expires_at)"),
        ("idx_follows_follower_id",            "follows(follower_id)"),
        ("idx_follows_following_id",           "follows(following_id)"),
        ("idx_duels_challenger_id",            "duels(challenger_id)"),
        ("idx_duels_opponent_id",              "duels(opponent_id)"),
        ("idx_duels_status",                   "duels(status)"),
        ("idx_season_entries_season_id",       "season_entries(season_id)"),
        ("idx_achievements_user_id",           "achievements(user_id)"),
    ]
    for idx_name, idx_target in indexes:
        try:
            db.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_target}"))
            db.commit()
        except Exception as e:
            db.rollback()
            if "already exists" in str(e).lower():
                pass
            else:
                print(f"[Phase2] index {idx_name}: {e}")

    # ── 8. user_predictions.deleted_at column ────────────────────────────────
    try:
        db.execute(text("ALTER TABLE user_predictions ADD COLUMN deleted_at TIMESTAMP"))
        db.commit()
        print("[Phase2] user_predictions.deleted_at column added")
    except Exception as e:
        db.rollback()
        if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
            pass
        else:
            print(f"[Phase2] user_predictions ADD deleted_at: {e}")

    # ── 9. deletion_log table ─────────────────────────────────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS deletion_log (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                prediction_id INTEGER REFERENCES user_predictions(id),
                deleted_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db.commit()
        print("[Phase2] deletion_log table created")
    except Exception as e:
        db.rollback()
        if "already exists" in str(e).lower():
            pass
        else:
            print(f"[Phase2] deletion_log table: {e}")

    # ── 10. users.user_type column ───────────────────────────────────────
    try:
        db.execute(text("ALTER TABLE users ADD COLUMN user_type VARCHAR(20) DEFAULT 'player'"))
        db.commit()
        print("[Phase2] users.user_type column added")
    except Exception as e:
        db.rollback()
        if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
            pass
        else:
            print(f"[Phase2] users ADD user_type: {e}")

    # ── 11. seasons theme columns ─────────────────────────────────────────
    for col, defn in [("theme_color", "VARCHAR(7)"), ("theme_icon", "VARCHAR(50)")]:
        try:
            db.execute(text(f"ALTER TABLE seasons ADD COLUMN {col} {defn}"))
            db.commit()
            print(f"[Phase2] seasons.{col} column added")
        except Exception as e:
            db.rollback()
            if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                pass
            else:
                print(f"[Phase2] seasons ADD {col}: {e}")

    # ── 12. Rename existing Q-style seasons to themed names ───────────────
    _season_renames = {
        "Q1": ("Season of the Bull", "#22c55e", "bull"),
        "Q2": ("Season of the Hawk", "#4A9EFF", "hawk"),
        "Q3": ("Season of the Serpent", "#A855F7", "serpent"),
        "Q4": ("Season of the Wolf", "#EF4444", "wolf"),
    }
    for q_prefix, (themed_name, color, icon) in _season_renames.items():
        try:
            db.execute(text(
                "UPDATE seasons SET name = :new_name, theme_color = :color, theme_icon = :icon "
                "WHERE name LIKE :pattern AND theme_color IS NULL"
            ), {"new_name": None, "color": color, "icon": icon, "pattern": f"{q_prefix} %"})
            # Actually need to include the year in the name
            rows = db.execute(text(
                "SELECT id, name FROM seasons WHERE name LIKE :pattern"
            ), {"pattern": f"{q_prefix} %"}).fetchall()
            for row in rows:
                year = row[1].replace(f"{q_prefix} ", "")
                db.execute(text(
                    "UPDATE seasons SET name = :n, theme_color = :c, theme_icon = :i WHERE id = :id"
                ), {"n": f"{themed_name} \u2014 {year}", "c": color, "i": icon, "id": row[0]})
            db.commit()
        except Exception:
            db.rollback()

    # ── 13. users.onboarding_completed column ────────────────────────────
    try:
        db.execute(text("ALTER TABLE users ADD COLUMN onboarding_completed INTEGER DEFAULT 0"))
        db.commit()
        print("[Phase2] users.onboarding_completed column added")
    except Exception as e:
        db.rollback()
        if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
            pass
        else:
            print(f"[Phase2] users ADD onboarding_completed: {e}")

    # ── 14. notifications table ──────────────────────────────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                type VARCHAR(50) NOT NULL,
                title VARCHAR(200) NOT NULL,
                message TEXT NOT NULL,
                data TEXT,
                read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db.commit()
        print("[Phase2] notifications table created")
    except Exception as e:
        db.rollback()
        if "already exists" in str(e).lower():
            pass
        else:
            print(f"[Phase2] notifications table: {e}")

    try:
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, read, created_at DESC)"))
        db.commit()
    except Exception as e:
        db.rollback()
        if "already exists" in str(e).lower():
            pass
        else:
            print(f"[Phase2] notifications index: {e}")

    # ── 15. activity_feed_v2 table ───────────────────────────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS activity_feed_v2 (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                event_type VARCHAR(50) NOT NULL,
                ticker VARCHAR(10),
                description TEXT NOT NULL,
                data TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db.commit()
        print("[Phase2] activity_feed_v2 table created")
    except Exception as e:
        db.rollback()
        if "already exists" in str(e).lower():
            pass
        else:
            print(f"[Phase2] activity_feed_v2 table: {e}")

    try:
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_activity_feed_v2_created ON activity_feed_v2(created_at DESC)"))
        db.commit()
    except Exception as e:
        db.rollback()
        if "already exists" in str(e).lower():
            pass

    # ── 16. daily_challenges + daily_challenge_entries ───────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS daily_challenges (
                id SERIAL PRIMARY KEY,
                ticker VARCHAR(10) NOT NULL,
                ticker_name VARCHAR(100),
                price_at_open DECIMAL(20,2),
                price_at_close DECIMAL(20,2),
                correct_direction VARCHAR(10),
                challenge_date DATE NOT NULL UNIQUE,
                status VARCHAR(20) DEFAULT 'active',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db.commit()
    except Exception as e:
        db.rollback()
        if "already exists" not in str(e).lower(): print(f"[Phase2] daily_challenges: {e}")

    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS daily_challenge_entries (
                id SERIAL PRIMARY KEY,
                challenge_id INTEGER REFERENCES daily_challenges(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                direction VARCHAR(10) NOT NULL,
                submitted_at TIMESTAMP DEFAULT NOW(),
                outcome VARCHAR(20),
                UNIQUE(challenge_id, user_id)
            )
        """))
        db.commit()
    except Exception as e:
        db.rollback()
        if "already exists" not in str(e).lower(): print(f"[Phase2] daily_challenge_entries: {e}")

    # ── 17. users daily streak columns ────────────────────────────────
    for col in ["daily_streak_current INTEGER DEFAULT 0", "daily_streak_best INTEGER DEFAULT 0"]:
        try:
            db.execute(text(f"ALTER TABLE users ADD COLUMN {col}"))
            db.commit()
        except Exception:
            db.rollback()

    # ── 18. prediction_reactions table ───────────────────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS prediction_reactions (
                id SERIAL PRIMARY KEY,
                prediction_id INTEGER NOT NULL,
                prediction_source VARCHAR(20) NOT NULL CHECK (prediction_source IN ('user', 'analyst')),
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                reaction VARCHAR(20) NOT NULL CHECK (reaction IN ('agree', 'disagree', 'bold_call', 'no_way')),
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(prediction_id, prediction_source, user_id)
            )
        """))
        db.commit()
    except Exception as e:
        db.rollback()
        if "already exists" not in str(e).lower(): print(f"[Phase2] prediction_reactions: {e}")

    try:
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_reactions_pred ON prediction_reactions(prediction_id, prediction_source)"))
        db.commit()
    except Exception:
        db.rollback()

    # ── 19. watchlist table ─────────────────────────────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                ticker VARCHAR(10) NOT NULL,
                notify INTEGER DEFAULT 1,
                added_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(user_id, ticker)
            )
        """))
        db.commit()
    except Exception as e:
        db.rollback()
        if "already exists" not in str(e).lower(): print(f"[Phase2] watchlist: {e}")

    # ── 20. price alert columns ─────────────────────────────────────
    for col, defn in [
        ("last_checked_price", "DECIMAL(20,2)"),
        ("last_alert_type", "VARCHAR(20)"),
    ]:
        try:
            db.execute(text(f"ALTER TABLE user_predictions ADD COLUMN {col} {defn}"))
            db.commit()
        except Exception:
            db.rollback()

    try:
        db.execute(text("ALTER TABLE users ADD COLUMN price_alerts_enabled INTEGER DEFAULT 1"))
        db.commit()
    except Exception:
        db.rollback()

    # ── 21. user_predictions.template column ─────────────────────────
    try:
        db.execute(text("ALTER TABLE user_predictions ADD COLUMN template VARCHAR(50) DEFAULT 'custom'"))
        db.commit()
    except Exception:
        db.rollback()

    # ── 22. users.weekly_digest_enabled ──────────────────────────────
    try:
        db.execute(text("ALTER TABLE users ADD COLUMN weekly_digest_enabled INTEGER DEFAULT 1"))
        db.commit()
    except Exception:
        db.rollback()

    # ── 23. earnings_calendar table ─────────────────────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS earnings_calendar (
                id SERIAL PRIMARY KEY,
                ticker VARCHAR(10) NOT NULL,
                earnings_date DATE NOT NULL,
                earnings_time VARCHAR(20),
                fiscal_quarter VARCHAR(10),
                fiscal_year INTEGER,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(ticker, earnings_date)
            )
        """))
        db.commit()
    except Exception as e:
        db.rollback()
        if "already exists" not in str(e).lower(): print(f"[Phase2] earnings_calendar: {e}")

    # ── 24. return streak columns ───────────────────────────────────
    for col in ["return_streak_current INTEGER DEFAULT 0", "return_streak_best INTEGER DEFAULT 0", "last_active_date DATE"]:
        try:
            db.execute(text(f"ALTER TABLE users ADD COLUMN {col}"))
            db.commit()
        except Exception:
            db.rollback()

    # ── 25. Rename old seasons to epic names ─────────────────────────
    try:
        from seasons import SEASON_NAMES
        all_seasons = db.execute(text("SELECT id, starts_at, name FROM seasons")).fetchall()
        for row in all_seasons:
            sid, starts, old_name = row
            if starts:
                y = starts.year if hasattr(starts, 'year') else int(str(starts)[:4])
                m = starts.month if hasattr(starts, 'month') else int(str(starts)[5:7])
                q = (m - 1) // 3 + 1
                key = f"{y}-Q{q}"
                meta = SEASON_NAMES.get(key)
                if meta and old_name != meta["name"]:
                    db.execute(text("UPDATE seasons SET name=:n, theme_color=:c, theme_icon=:s WHERE id=:id"),
                        {"n": meta["name"], "c": meta["color"], "s": meta["subtitle"], "id": sid})
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[Phase2] Season rename: {e}")

    # ── 26. prediction_comments table ──────────────────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS prediction_comments (
                id SERIAL PRIMARY KEY,
                prediction_id INTEGER NOT NULL,
                prediction_source VARCHAR(20) NOT NULL,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                comment TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db.commit()
    except Exception as e:
        db.rollback()
        if "already exists" not in str(e).lower(): print(f"[Phase2] prediction_comments: {e}")

    try:
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_comments_pred ON prediction_comments(prediction_id, prediction_source, created_at DESC)"))
        db.commit()
    except Exception:
        db.rollback()

    # ── 27. follows.status column ───────────────────────────────────
    try:
        db.execute(text("ALTER TABLE follows ADD COLUMN status VARCHAR(20) DEFAULT 'accepted'"))
        db.commit()
    except Exception:
        db.rollback()
    # Set all existing rows to accepted
    try:
        db.execute(text("UPDATE follows SET status = 'accepted' WHERE status IS NULL"))
        db.commit()
    except Exception:
        db.rollback()

    # ── 28. online status + notification preferences ────────────────
    for col in ["last_seen_at TIMESTAMP", "notification_preferences TEXT"]:
        try:
            db.execute(text(f"ALTER TABLE users ADD COLUMN {col}"))
            db.commit()
        except Exception:
            db.rollback()

    # ── 29. analyst_subscriptions table ──────────────────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS analyst_subscriptions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                email VARCHAR(255),
                forecaster_name VARCHAR(200) NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                CONSTRAINT uq_analyst_sub_user UNIQUE (user_id, forecaster_name),
                CONSTRAINT uq_analyst_sub_email UNIQUE (email, forecaster_name)
            )
        """))
        db.commit()
        print("[Phase2] analyst_subscriptions table created")
    except Exception as e:
        db.rollback()
        if "already exists" not in str(e).lower():
            print(f"[Phase2] analyst_subscriptions: {e}")

    try:
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_analyst_sub_forecaster ON analyst_subscriptions(forecaster_name)"))
        db.commit()
    except Exception:
        db.rollback()

    # ── 30. users.auth_provider column ───────────────────────────────
    try:
        db.execute(text("ALTER TABLE users ADD COLUMN auth_provider VARCHAR(20) DEFAULT 'email'"))
        db.commit()
        print("[Phase2] users.auth_provider column added")
    except Exception:
        db.rollback()

    # ── 31. XP system columns ──────────────────────────────────────
    for col in ["xp_total INTEGER DEFAULT 0", "xp_level INTEGER DEFAULT 1", "xp_today INTEGER DEFAULT 0", "xp_last_reset DATE"]:
        try:
            db.execute(text(f"ALTER TABLE users ADD COLUMN {col}"))
            db.commit()
        except Exception:
            db.rollback()

    # ── 32. Weekly challenges tables ─────────────────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS weekly_challenges (
                id SERIAL PRIMARY KEY,
                title VARCHAR(100) NOT NULL,
                description TEXT NOT NULL,
                challenge_type VARCHAR(50) NOT NULL,
                requirements TEXT NOT NULL,
                xp_reward INTEGER DEFAULT 100,
                starts_at TIMESTAMP NOT NULL,
                ends_at TIMESTAMP NOT NULL,
                status VARCHAR(20) DEFAULT 'active',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db.commit()
    except Exception as e:
        db.rollback()
        if "already exists" not in str(e).lower():
            print(f"[Phase2] weekly_challenges: {e}")

    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS weekly_challenge_progress (
                id SERIAL PRIMARY KEY,
                challenge_id INTEGER REFERENCES weekly_challenges(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                progress INTEGER DEFAULT 0,
                completed INTEGER DEFAULT 0,
                completed_at TIMESTAMP,
                CONSTRAINT uq_weekly_progress UNIQUE (challenge_id, user_id)
            )
        """))
        db.commit()
    except Exception as e:
        db.rollback()
        if "already exists" not in str(e).lower():
            print(f"[Phase2] weekly_challenge_progress: {e}")

    # ── 33a. users.subscription_tier column ─────────────────────────
    try:
        db.execute(text("ALTER TABLE users ADD COLUMN subscription_tier VARCHAR(20) DEFAULT 'free'"))
        db.commit()
    except Exception:
        db.rollback()

    # ── 33b. users.custom_title column ─────────────────────────────
    try:
        db.execute(text("ALTER TABLE users ADD COLUMN custom_title VARCHAR(50)"))
        db.commit()
    except Exception:
        db.rollback()

    # ── 33. xp_log table ───────────────────────────────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS xp_log (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                action VARCHAR(50) NOT NULL,
                xp_gained INTEGER NOT NULL,
                description VARCHAR(200),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db.commit()
    except Exception as e:
        db.rollback()
        if "already exists" not in str(e).lower():
            print(f"[Phase2] xp_log: {e}")

    try:
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_xp_log_user_created ON xp_log(user_id, created_at DESC)"))
        db.commit()
    except Exception:
        db.rollback()

    # ── 34. users.referred_by column ────────────────────────────────
    try:
        db.execute(text("ALTER TABLE users ADD COLUMN referred_by INTEGER REFERENCES users(id)"))
        db.commit()
    except Exception:
        db.rollback()

    # ── 35. predictions.external_id column ─────────────────────────
    try:
        db.execute(text("ALTER TABLE predictions ADD COLUMN external_id VARCHAR UNIQUE"))
        db.commit()
    except Exception:
        db.rollback()
    try:
        db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_predictions_external_id ON predictions(external_id) WHERE external_id IS NOT NULL"))
        db.commit()
    except Exception:
        db.rollback()

    # ── 36. Performance indexes ────────────────────────────────────
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_pred_forecaster_id ON predictions(forecaster_id)",
        "CREATE INDEX IF NOT EXISTS idx_pred_forecaster_outcome ON predictions(forecaster_id, outcome)",
        "CREATE INDEX IF NOT EXISTS idx_pred_ticker ON predictions(ticker)",
        "CREATE INDEX IF NOT EXISTS idx_pred_evaluation_date ON predictions(evaluation_date)",
        "CREATE INDEX IF NOT EXISTS idx_pred_outcome ON predictions(outcome)",
        "CREATE INDEX IF NOT EXISTS idx_pred_date ON predictions(prediction_date)",
        "CREATE INDEX IF NOT EXISTS idx_pred_verified ON predictions(verified_by)",
        "CREATE INDEX IF NOT EXISTS idx_forecasters_total ON forecasters(total_predictions)",
        "CREATE INDEX IF NOT EXISTS idx_forecasters_accuracy ON forecasters(accuracy_score)",
    ]:
        try:
            db.execute(text(idx_sql))
            db.commit()
        except Exception:
            db.rollback()

    # ── 37. ticker_sectors cache table ─────────────────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS ticker_sectors (
                ticker VARCHAR(10) PRIMARY KEY,
                sector VARCHAR(50),
                last_updated TIMESTAMP DEFAULT NOW()
            )
        """))
        db.commit()
    except Exception as e:
        db.rollback()

    # ── 38. predictions.evaluation_summary column ──────────────────
    try:
        db.execute(text("ALTER TABLE predictions ADD COLUMN evaluation_summary TEXT"))
        db.commit()
    except Exception:
        db.rollback()

    # ── 39. forecasters.alpha column ────────────────────────────────
    try:
        db.execute(text("ALTER TABLE forecasters ADD COLUMN alpha FLOAT"))
        db.commit()
    except Exception:
        db.rollback()

    print("[Phase2] All migrations complete")
    db.close()


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


_scheduler = None  # module-level reference for diagnostic endpoints

# PROTECTION 1: Kill switch — set DISABLE_BACKGROUND_JOBS=true to skip ALL scheduled jobs
_JOBS_DISABLED = os.getenv("DISABLE_BACKGROUND_JOBS", "").lower() in ("true", "1", "yes")


# ┌──────────────────────────────────────────────────────────────────────────────┐
# │ CRITICAL: Do NOT add synchronous DB operations to lifespan().              │
# │ All DB work must go in _startup_all() background thread below.             │
# │ Adding blocking DB calls here WILL crash the site on deploy.               │
# │ The app must bind its port and start serving within seconds.               │
# │ See incident 2026-03-29: startup hung → Railway couldn't deploy new code.  │
# │ See incident 2026-03-31: connection exhaustion from concurrent bg jobs.    │
# └──────────────────────────────────────────────────────────────────────────────┘
@asynccontextmanager
async def lifespan(app):
    global _scheduler
    import threading

    # PROTECTION 8: Railway credit warning
    print("[STARTUP] ========================================")
    print("[STARTUP] Railway trial plan — monitor credits!")
    print("[STARTUP] Site goes offline when credits hit $0.")
    print("[STARTUP] Check: Railway dashboard → Usage tab")
    print("[STARTUP] ========================================")

    if _JOBS_DISABLED:
        print("[STARTUP] *** BACKGROUND JOBS DISABLED (DISABLE_BACKGROUND_JOBS=true) ***")
        print("[STARTUP] App will serve requests but no scrapers/evaluators will run.")

    def _startup_all():
        """ALL DB-touching startup work runs here — completely off the critical path.
        PROTECTION 5: Waits 30 seconds before touching the DB so the app can serve requests."""
        import time as _t2
        _t2.sleep(30)  # PROTECTION 5: 30 second delay — app must be fully ready first

        # Phase 1: Schema init + migrations
        try:
            init_db()
        except Exception as e:
            print(f"[Startup] init_db error: {e}")
        try:
            migrate_platform_types()
        except Exception:
            pass
        try:
            migrate_profile_urls()
        except Exception:
            pass
        try:
            run_phase2_migrations()
        except Exception:
            pass

        # Seed magazine forecasters
        try:
            db = BgSessionLocal()
            try:
                from jobs.seed_magazines import seed_magazine_forecasters
                seed_magazine_forecasters(db)
            finally:
                db.close()
        except Exception as e:
            print(f"[Startup] Magazine seed error: {e}")

        # Merge duplicate forecasters
        try:
            db = BgSessionLocal()
            try:
                from jobs.news_scraper import merge_duplicate_forecasters
                merge_duplicate_forecasters(db)
            finally:
                db.close()
        except Exception as e:
            print(f"[Startup] Forecaster merge error: {e}")

        # Add cached stats columns if missing
        try:
            from sqlalchemy import text as _t
            db = BgSessionLocal()
            try:
                for col_sql in [
                    "ALTER TABLE forecasters ADD COLUMN accuracy_score FLOAT",
                    "ALTER TABLE forecasters ADD COLUMN total_predictions INTEGER DEFAULT 0",
                    "ALTER TABLE forecasters ADD COLUMN correct_predictions INTEGER DEFAULT 0",
                    "ALTER TABLE forecasters ADD COLUMN streak INTEGER DEFAULT 0",
                    "ALTER TABLE forecasters ADD COLUMN avg_return FLOAT",
                    "ALTER TABLE predictions ADD COLUMN evaluated_at TIMESTAMP",
                    "ALTER TABLE ticker_sectors ADD COLUMN company_name VARCHAR(200)",
                    "ALTER TABLE ticker_sectors ADD COLUMN industry VARCHAR(100)",
                    "ALTER TABLE forecasters ADD COLUMN firm VARCHAR(200)",
                    "ALTER TABLE users ADD COLUMN twitter_url VARCHAR(255)",
                    "ALTER TABLE users ADD COLUMN linkedin_url VARCHAR(255)",
                    "ALTER TABLE users ADD COLUMN youtube_url VARCHAR(255)",
                    "ALTER TABLE users ADD COLUMN website_url VARCHAR(255)",
                    "ALTER TABLE predictions ADD COLUMN call_type VARCHAR(50)",
                ]:
                    try:
                        db.execute(_t(col_sql))
                        db.commit()
                    except Exception:
                        db.rollback()
            finally:
                db.close()
        except Exception as e:
            print(f"[Startup] Stats column error: {e}")

        # Archive columns
        try:
            db = BgSessionLocal()
            try:
                migrate_add_archive_columns(db)
            finally:
                db.close()
        except Exception as e:
            print(f"[Startup] Archive column error: {e}")

        # Season init
        try:
            from seasons import ensure_current_season as _ecs
            db = BgSessionLocal()
            try:
                _ecs(db)
            finally:
                db.close()
        except Exception as e:
            print(f"[Startup] Season init error: {e}")

        # Daily challenge
        try:
            from jobs.daily_challenge import ensure_daily_challenge_exists
            db = BgSessionLocal()
            try:
                ensure_daily_challenge_exists(db)
            finally:
                db.close()
        except Exception as e:
            print(f"[Startup] Daily challenge error: {e}")

        # Backfill call_type for existing predictions
        try:
            from sqlalchemy import text as _t
            db = BgSessionLocal()
            try:
                updated = db.execute(_t("""
                    UPDATE predictions SET call_type = CASE
                        WHEN context ILIKE '%upgrade%' THEN 'upgrade'
                        WHEN context ILIKE '%downgrade%' THEN 'downgrade'
                        WHEN context ILIKE '%initiat%coverage%' THEN 'new_coverage'
                        WHEN target_price IS NOT NULL THEN 'price_target'
                        ELSE 'rating'
                    END
                    WHERE call_type IS NULL AND outcome != 'pending_review'
                """)).rowcount
                db.commit()
                if updated:
                    print(f"[Startup] Backfilled call_type for {updated} predictions")
            finally:
                db.close()
        except Exception as e:
            print(f"[Startup] call_type backfill error: {e}")

        # VACUUM: reclaim dead rows from updates/deletes
        try:
            from sqlalchemy import text as _t
            print("[Startup] Running VACUUM (non-FULL) to reclaim dead rows...")
            raw_conn = bg_engine.raw_connection()
            try:
                raw_conn.set_isolation_level(0)  # AUTOCOMMIT required for VACUUM
                cur = raw_conn.cursor()
                cur.execute("VACUUM VERBOSE")
                cur.close()
            finally:
                raw_conn.close()
            print("[Startup] VACUUM complete")
        except Exception as e:
            print(f"[Startup] VACUUM error (non-fatal): {e}")

        # Auto-resume Benzinga backfill if not caught up
        if not _JOBS_DISABLED:
            try:
                from jobs.benzinga_backfill import auto_resume_backfill
                auto_resume_backfill()
            except Exception as e:
                print(f"[Startup] Backfill auto-resume error: {e}")

        print("[Startup] All background DB init complete")

    threading.Thread(target=_startup_all, daemon=True).start()
    print("[Startup] App starting immediately — all DB init deferred to background thread (30s delay)")

    # Security warning (no DB needed)
    if not os.getenv("ADMIN_SECRET"):
        print("[WARNING] ADMIN_SECRET not set — admin routes are unprotected!")

    # ── PROTECTION 1: Skip ALL scheduler registration if jobs are disabled ────
    if _JOBS_DISABLED:
        print("[STARTUP] Scheduler NOT started (DISABLE_BACKGROUND_JOBS=true)")
        yield
        return

    # Start background job scheduler
    from admin_panel import scheduler_last_run
    from circuit_breaker import (
        db_is_healthy, mark_job_running, mark_job_done,
        acquire_job_lock, release_job_lock, watchdog_check,
        memory_is_available, db_storage_ok,
    )

    def _guarded_job(job_name, job_fn, *, check_memory=False):
        """Wrap a background job with:
        - PROTECTION 2: Global job lock (only one job at a time)
        - PROTECTION 3: Circuit breaker (skip if DB unreachable)
        - PROTECTION 7: Memory guard (optional, for yfinance-type jobs)
        - STORAGE GUARD: Skip if DB > 4GB (volume is 5GB max)
        - Context manager for DB sessions (connections always returned)
        """
        def wrapper():
            from datetime import datetime as _dt
            scheduler_last_run[job_name] = _dt.utcnow()

            # PROTECTION 3: Circuit breaker
            if not db_is_healthy(job_name):
                return

            # STORAGE GUARD: Skip if DB approaching volume limit
            if not db_storage_ok(job_name):
                return

            # PROTECTION 7: Memory guard
            if check_memory and not memory_is_available():
                print(f"[{job_name}] Skipped: low memory")
                return

            # PROTECTION 2: Global lock — only ONE job at a time
            if not acquire_job_lock(job_name):
                return  # Another job is running, skip this cycle

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

    # ── Define all guarded jobs ───────────────────────────────────────────────
    # All first runs are deferred to 30+ seconds after startup so DB init completes first

    run_fast_scraper = _guarded_job("fast_scraper", lambda db: __import__('jobs.news_scraper', fromlist=['scrape_fast_predictions']).scrape_fast_predictions(db))
    run_hourly_scraper = _guarded_job("full_scraper", lambda db: run_scraper(db))
    run_15min_evaluator = _guarded_job("evaluator", lambda db: run_evaluator(db))

    def _user_evaluator(db):
        results = evaluate_user_predictions(db)
        print(f"[Scheduler] User evaluator completed: {len(results or [])} predictions scored")
    run_15min_user_evaluator = _guarded_job("user_evaluator", _user_evaluator)

    run_15min_duel_evaluator = _guarded_job("duel_evaluator", lambda db: evaluate_duels(db))
    run_hourly_season_check = _guarded_job("season_check", lambda db: check_season_completion(db))
    run_fmp_upgrades = _guarded_job("fmp_upgrades", lambda db: __import__('jobs.upgrade_scrapers', fromlist=['scrape_fmp_upgrades']).scrape_fmp_upgrades(db))
    run_fmp_price_targets = _guarded_job("fmp_price_targets", lambda db: __import__('jobs.upgrade_scrapers', fromlist=['scrape_fmp_price_targets']).scrape_fmp_price_targets(db))
    run_fmp_daily_grades = _guarded_job("fmp_daily_grades", lambda db: __import__('jobs.upgrade_scrapers', fromlist=['scrape_fmp_daily_grades']).scrape_fmp_daily_grades(db))
    # PROTECTION 7: yfinance gets memory guard
    run_yfinance = _guarded_job("yfinance", lambda db: __import__('jobs.rss_scrapers', fromlist=['scrape_yfinance_recommendations']).scrape_yfinance_recommendations(db), check_memory=True)
    run_benzinga_api = _guarded_job("benzinga_api", lambda db: __import__('jobs.benzinga_scraper', fromlist=['scrape_benzinga_ratings']).scrape_benzinga_ratings(db))
    run_newsapi = _guarded_job("newsapi", lambda db: __import__('jobs.news_scraper', fromlist=['scrape_newsapi']).scrape_newsapi(db))
    run_massive_benzinga = _guarded_job("massive_benzinga", lambda db: __import__('jobs.massive_benzinga', fromlist=['scrape_massive_ratings']).scrape_massive_ratings(db))

    # Newsletter — previously leaked a SessionLocal() outside _guarded_job. Fixed.
    run_newsletter_job = _guarded_job("newsletter", lambda db: run_newsletter(db))

    # Analyst notifications — now guarded
    def _analyst_notifications(db):
        from jobs.analyst_notifications import run_analyst_notifications as _ran
        _ran()
    run_analyst_notifications_job = _guarded_job("analyst_notifications", _analyst_notifications)

    run_create_daily_challenge = _guarded_job("daily_challenge_create", lambda db: __import__('jobs.daily_challenge', fromlist=['create_daily_challenge']).create_daily_challenge(db))
    run_score_daily_challenge = _guarded_job("daily_challenge_score", lambda db: __import__('jobs.daily_challenge', fromlist=['score_daily_challenge']).score_daily_challenge(db))
    run_price_alerts = _guarded_job("price_alerts", lambda db: __import__('jobs.price_alerts', fromlist=['check_price_alerts']).check_price_alerts(db))
    run_hourly_leaderboard = _guarded_job("leaderboard", lambda db: run_leaderboard_refresh(db))
    run_weekly_digest = _guarded_job("weekly_digest", lambda db: __import__('jobs.weekly_digest', fromlist=['send_weekly_digest']).send_weekly_digest(db))
    run_earnings_update = _guarded_job("earnings", lambda db: __import__('jobs.earnings', fromlist=['update_earnings_calendar']).update_earnings_calendar(db))
    run_weekly_challenge = _guarded_job("weekly_challenge", lambda db: __import__('weekly_challenges', fromlist=['create_weekly_challenge']).create_weekly_challenge(db))

    def _auto_evaluate(db):
        from jobs.historical_evaluator import evaluate_batch, refresh_all_forecaster_stats
        result = evaluate_batch(max_tickers=500)
        scored = result.get('predictions_scored', 0)
        remaining = result.get('remaining_tickers', 0)
        print(f"[AutoEval] {scored} scored, {remaining} remaining")
        if scored > 0:
            refresh_all_forecaster_stats()
    run_auto_evaluate = _guarded_job("auto_evaluate", _auto_evaluate)

    def _refresh_stats(db):
        from jobs.historical_evaluator import refresh_all_forecaster_stats
        refresh_all_forecaster_stats()
    run_refresh_stats = _guarded_job("refresh_stats", _refresh_stats)

    # ── Register all jobs with the scheduler ──────────────────────────────────
    # PROTECTION 5: No job runs before 60 seconds after startup (30s DB delay + 30s buffer)
    _first_run = datetime.utcnow() + timedelta(seconds=60)

    print("[STARTUP] Scheduler starting...")
    scheduler = AsyncIOScheduler()
    _scheduler = scheduler

    # Core scrapers
    scheduler.add_job(run_hourly_scraper, "interval", hours=1, id="scraper", next_run_time=_first_run)
    scheduler.add_job(run_fast_scraper, "interval", minutes=15, id="fast_scraper", next_run_time=_first_run + timedelta(minutes=2))
    scheduler.add_job(run_benzinga_api, "interval", hours=2, id="benzinga_api", next_run_time=_first_run + timedelta(minutes=15))
    scheduler.add_job(run_newsapi, "interval", hours=4, id="newsapi", next_run_time=_first_run + timedelta(minutes=10))

    # Massive API — Benzinga ratings
    scheduler.add_job(run_massive_benzinga, "interval", hours=2, id="massive_benzinga", next_run_time=_first_run + timedelta(minutes=20))

    # FMP structured data
    scheduler.add_job(run_fmp_upgrades, "interval", hours=2, id="fmp_upgrades", next_run_time=_first_run + timedelta(minutes=30))
    scheduler.add_job(run_fmp_price_targets, "interval", hours=2, id="fmp_price_targets", next_run_time=_first_run + timedelta(minutes=60))
    scheduler.add_job(run_fmp_daily_grades, "interval", hours=3, id="fmp_daily_grades", next_run_time=_first_run + timedelta(minutes=90))

    # yfinance (memory-guarded)
    scheduler.add_job(run_yfinance, "interval", hours=3, id="yfinance", next_run_time=_first_run + timedelta(minutes=120))

    # Evaluator + leaderboard
    scheduler.add_job(run_15min_evaluator, "interval", minutes=15, id="evaluator", next_run_time=_first_run + timedelta(minutes=3))
    scheduler.add_job(run_15min_user_evaluator, "interval", minutes=15, id="user_evaluator", next_run_time=_first_run + timedelta(minutes=4))
    scheduler.add_job(run_15min_duel_evaluator, "interval", minutes=15, id="duel_evaluator", next_run_time=_first_run + timedelta(minutes=5))
    scheduler.add_job(run_hourly_season_check, "interval", hours=1, id="season_check", next_run_time=_first_run + timedelta(minutes=45))

    # Daily challenge jobs (EST times)
    scheduler.add_job(run_create_daily_challenge, "cron", hour=14, minute=30, id="daily_challenge_create_weekday", day_of_week="mon-fri")
    scheduler.add_job(run_create_daily_challenge, "cron", hour=0, minute=5, id="daily_challenge_create_weekend", day_of_week="sat,sun")
    scheduler.add_job(run_score_daily_challenge, "cron", hour=21, minute=30, id="daily_challenge_score_weekday", day_of_week="mon-fri")
    scheduler.add_job(run_score_daily_challenge, "cron", hour=23, minute=55, id="daily_challenge_score_crypto")

    # Price alerts
    scheduler.add_job(run_price_alerts, "interval", minutes=30, id="price_alerts", next_run_time=_first_run + timedelta(minutes=6))

    # Leaderboard refresh
    scheduler.add_job(run_hourly_leaderboard, "interval", hours=1, id="leaderboard", next_run_time=_first_run + timedelta(minutes=7))

    # Newsletter (now properly guarded — was previously leaking SessionLocal)
    scheduler.add_job(run_newsletter_job, "cron", hour=8, minute=0, id="newsletter")

    # Weekly digest
    scheduler.add_job(run_weekly_digest, "cron", day_of_week="sun", hour=10, minute=0, id="weekly_digest")

    # Earnings calendar
    scheduler.add_job(run_earnings_update, "cron", hour=0, minute=15, id="earnings_update")

    # Analyst subscription notifications (now properly guarded)
    scheduler.add_job(run_analyst_notifications_job, "interval", hours=1, id="analyst_notifications", next_run_time=_first_run + timedelta(minutes=45))

    # Weekly challenge
    scheduler.add_job(run_weekly_challenge, "cron", day_of_week="mon", hour=0, minute=1, id="weekly_challenge")

    # Auto-evaluate expired predictions
    scheduler.add_job(run_auto_evaluate, "interval", hours=1, id="auto_evaluate", next_run_time=_first_run + timedelta(minutes=10))

    # Auto-refresh forecaster stats
    scheduler.add_job(run_refresh_stats, "interval", hours=2, id="refresh_stats", next_run_time=_first_run + timedelta(minutes=8))

    # ── PROTECTION 4 (site health) + PROTECTION 6 (stuck job watchdog) ────────
    def _site_health_watchdog():
        from circuit_breaker import check_site_health_and_pause
        check_site_health_and_pause()

    def _stuck_job_watchdog():
        watchdog_check()

    scheduler.add_job(_site_health_watchdog, "interval", minutes=5, id="site_health_watchdog")
    scheduler.add_job(_stuck_job_watchdog, "interval", minutes=5, id="stuck_job_watchdog")

    scheduler.start()
    job_ids = [j.id for j in scheduler.get_jobs()]
    print(f"[STARTUP] {len(job_ids)} jobs registered: {', '.join(job_ids)}")
    for j in scheduler.get_jobs():
        print(f"[STARTUP]   {j.id}: next_run={j.next_run_time}")
    print(f"[STARTUP] FINNHUB_KEY set: {bool(os.getenv('FINNHUB_KEY', '').strip())}")
    print(f"[STARTUP] Global job lock: ENABLED (only 1 bg job at a time)")
    print(f"[STARTUP] Connection pools: user=3+5(8max), bg=1+1(2max), total=10max")
    print(f"[STARTUP] First job will run in ~60s")
    yield
    scheduler.shutdown()


app = FastAPI(title="Eidolum API", version="1.0.0", lifespan=lifespan)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Request timeout — kill any API request that hangs beyond 8 seconds
app.add_middleware(RequestTimeoutMiddleware)

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
app.include_router(predictions.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(user_predictions.router, prefix="/api")
app.include_router(community.router, prefix="/api")
app.include_router(user_follows.router, prefix="/api")
app.include_router(duels.router, prefix="/api")
app.include_router(seasons_router.router, prefix="/api")
app.include_router(notifications_router.router, prefix="/api")
app.include_router(ticker_detail.router, prefix="/api")
app.include_router(activity_feed.router, prefix="/api")
app.include_router(share.router, prefix="/api")
app.include_router(daily_challenge_router.router, prefix="/api")
app.include_router(reactions.router, prefix="/api")
from routers import comments as comments_router
app.include_router(comments_router.router, prefix="/api")
from routers import prediction_detail
app.include_router(prediction_detail.router, prefix="/api")
app.include_router(watchlist_router.router, prefix="/api")
app.include_router(controversial.router, prefix="/api")
from routers import compare as compare_router
app.include_router(compare_router.router, prefix="/api")
from routers import analysts as analysts_router, heatmap
app.include_router(analysts_router.router, prefix="/api")
app.include_router(heatmap.router, prefix="/api")
from routers import earnings as earnings_router
app.include_router(earnings_router.router, prefix="/api")
from routers import weekly_challenge as weekly_challenge_router
app.include_router(weekly_challenge_router.router, prefix="/api")
from routers import xp_router
app.include_router(xp_router.router, prefix="/api")
app.include_router(admin_panel_router)  # /admin HTML + /api/admin/* endpoints


@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok", "app": "Eidolum API"}


@app.get("/api/health/infra")
def health_infra():
    """Infrastructure health check — DB connectivity, connection pools, circuit breaker.
    Returns status: "ok", "degraded", or "down"."""
    import time as _t
    from sqlalchemy import text as _text
    import circuit_breaker

    checks = {}
    status = "ok"

    # 1. Database connectivity + query time
    try:
        start = _t.time()
        db = SessionLocal()
        r = db.execute(_text("SELECT 1")).scalar()
        db_elapsed = round((_t.time() - start) * 1000, 1)
        db.close()
        checks["database"] = {"status": "ok", "query_ms": db_elapsed, "result": r}
        if db_elapsed > 2000:
            checks["database"]["status"] = "slow"
            status = "degraded"
    except Exception as e:
        checks["database"] = {"status": "down", "error": str(e)}
        status = "down"

    # 2. Connection pool stats
    try:
        pool = engine.pool
        checks["connection_pool"] = {
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "status": "ok" if pool.checkedout() < pool.size() + 3 else "high",
        }
        if pool.checkedout() >= pool.size() + pool._max_overflow:
            status = "degraded"
    except Exception as e:
        checks["connection_pool"] = {"error": str(e)}

    # 3. Background job pool stats
    try:
        bg_pool = bg_engine.pool
        checks["bg_connection_pool"] = {
            "size": bg_pool.size(),
            "checked_in": bg_pool.checkedin(),
            "checked_out": bg_pool.checkedout(),
            "overflow": bg_pool.overflow(),
        }
    except Exception:
        pass

    # 4. Circuit breaker state + running jobs
    cb_status = circuit_breaker.get_status()
    checks["circuit_breaker"] = cb_status
    if cb_status["jobs_paused"]:
        status = "degraded"

    # 5. Scheduler
    if _scheduler:
        try:
            checks["scheduler"] = {"jobs": len(_scheduler.get_jobs()), "running": True}
        except Exception:
            checks["scheduler"] = {"running": False}
    else:
        checks["scheduler"] = {"running": False}

    return {"status": status, "checks": checks}


@app.get("/api/scheduler-status")
def scheduler_status():
    """Show all scheduled jobs and their last run times."""
    from admin_panel import scheduler_last_run
    jobs = []
    if _scheduler:
        try:
            for job in _scheduler.get_jobs():
                jobs.append({
                    "id": job.id,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                })
        except Exception as e:
            jobs = [{"error": str(e)}]
    else:
        jobs = [{"error": "scheduler not initialized yet"}]
    return {
        "jobs": jobs,
        "last_runs": {k: v.isoformat() if v else None for k, v in scheduler_last_run.items()},
        "finnhub_key_set": bool(os.getenv("FINNHUB_KEY", "").strip()),
    }


@app.get("/api/admin/alpha-debug")
def alpha_debug():
    """Check exact state of alpha column in predictions table."""
    from sqlalchemy import text as _t
    db = BgSessionLocal()
    try:
        db.execute(_t("SET statement_timeout = '10000'"))
        # Count alpha states for evaluated predictions
        stats = db.execute(_t("""
            SELECT
                COUNT(*) as total_evaluated,
                COUNT(CASE WHEN alpha IS NULL THEN 1 END) as alpha_null,
                COUNT(CASE WHEN alpha IS NOT NULL THEN 1 END) as alpha_set,
                COUNT(CASE WHEN alpha = 0 THEN 1 END) as alpha_zero,
                COUNT(CASE WHEN actual_return IS NULL THEN 1 END) as return_null,
                COUNT(CASE WHEN actual_return IS NOT NULL THEN 1 END) as return_set,
                COUNT(CASE WHEN evaluation_date IS NULL THEN 1 END) as eval_date_null,
                COUNT(CASE WHEN prediction_date IS NULL THEN 1 END) as pred_date_null
            FROM predictions
            WHERE outcome IN ('correct','incorrect')
        """)).first()
        # Sample 3 evaluated predictions with their raw column values
        samples = db.execute(_t("""
            SELECT id, ticker, outcome, actual_return, alpha, sp500_return,
                   prediction_date, evaluation_date
            FROM predictions
            WHERE outcome IN ('correct','incorrect')
            ORDER BY id DESC LIMIT 5
        """)).fetchall()
        return {
            "total_evaluated": stats[0], "alpha_null": stats[1], "alpha_set": stats[2],
            "alpha_zero": stats[3], "return_null": stats[4], "return_set": stats[5],
            "eval_date_null": stats[6], "pred_date_null": stats[7],
            "samples": [
                {"id": r[0], "ticker": r[1], "outcome": r[2],
                 "actual_return": float(r[3]) if r[3] is not None else None,
                 "alpha": float(r[4]) if r[4] is not None else None,
                 "sp500_return": float(r[5]) if r[5] is not None else None,
                 "prediction_date": str(r[6]) if r[6] else None,
                 "evaluation_date": str(r[7]) if r[7] else None}
                for r in samples
            ],
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}
    finally:
        db.close()


@app.get("/api/admin/db-diagnostics")
def db_diagnostics():
    """Show prediction counts, date ranges, and breakdowns for debugging."""
    from sqlalchemy import text as _t
    db = BgSessionLocal()
    try:
        # Total counts
        total = db.execute(_t("SELECT COUNT(*) FROM predictions")).scalar()
        total_forecasters = db.execute(_t("SELECT COUNT(*) FROM forecasters")).scalar()

        # Date range
        dates = db.execute(_t("SELECT MIN(prediction_date), MAX(prediction_date) FROM predictions")).first()

        # By verified_by (source)
        by_source = db.execute(_t("SELECT verified_by, outcome, COUNT(*) as cnt FROM predictions GROUP BY verified_by, outcome ORDER BY cnt DESC")).fetchall()
        source_breakdown = [{"source": r[0], "outcome": r[1], "count": r[2]} for r in by_source]

        # Forecasters with 0 predictions
        empty_forecasters = db.execute(_t("SELECT COUNT(*) FROM forecasters WHERE id NOT IN (SELECT DISTINCT forecaster_id FROM predictions WHERE forecaster_id IS NOT NULL)")).scalar()

        # Backfill progress
        backfill_date = db.execute(_t("SELECT value FROM config WHERE key = 'backfill_last_date'")).scalar()

        # Recent predictions
        recent = db.execute(_t("SELECT id, ticker, direction, outcome, verified_by, prediction_date FROM predictions ORDER BY id DESC LIMIT 5")).fetchall()
        recent_list = [{"id": r[0], "ticker": r[1], "direction": r[2], "outcome": r[3], "source": r[4], "date": str(r[5])} for r in recent]

        return {
            "total_predictions": total,
            "total_forecasters": total_forecasters,
            "empty_forecasters": empty_forecasters,
            "earliest_prediction": str(dates[0]) if dates[0] else None,
            "latest_prediction": str(dates[1]) if dates[1] else None,
            "source_breakdown": source_breakdown,
            "backfill_last_date": backfill_date,
            "recent_predictions": recent_list,
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}
    finally:
        db.close()


@app.post("/api/admin/run-massive-benzinga")
def run_massive_benzinga_now():
    """Run the Massive Benzinga scraper immediately and return results."""
    import traceback as _tb
    db = BgSessionLocal()
    try:
        from jobs.massive_benzinga import scrape_massive_ratings
        from models import Prediction
        before = db.query(Prediction).filter(Prediction.verified_by == "massive_benzinga").count()
        scrape_massive_ratings(db)
        after = db.query(Prediction).filter(Prediction.verified_by == "massive_benzinga").count()
        return {"status": "ok", "before": before, "after": after, "new_predictions": after - before}
    except Exception as e:
        return {"status": "error", "error": str(e), "traceback": _tb.format_exc()}
    finally:
        db.close()


@app.get("/api/admin/scraper-health")
def scraper_health():
    """Health check for all background jobs."""
    from admin_panel import scheduler_last_run
    from jobs.benzinga_backfill import get_backfill_status
    from jobs.historical_evaluator import get_eval_status

    db = BgSessionLocal()
    try:
        pending_overdue = db.execute(sql_text(
            "SELECT COUNT(*) FROM predictions WHERE outcome = 'pending' AND evaluation_date IS NOT NULL AND evaluation_date < NOW()"
        )).scalar() or 0
        total_scored = db.execute(sql_text(
            "SELECT COUNT(*) FROM predictions WHERE outcome IN ('correct','incorrect')"
        )).scalar() or 0
    finally:
        db.close()

    bf = get_backfill_status()
    ev = get_eval_status()

    # Read forward/reverse progress from Config
    fwd_last = None
    rev_last = None
    fwd_done = False
    try:
        from models import Config as _Cfg
        fwd_row = db.query(_Cfg).filter(_Cfg.key == "backfill_last_date").first()
        fwd_last = fwd_row.value if fwd_row else None
        rev_row = db.query(_Cfg).filter(_Cfg.key == "backfill_reverse_last_date").first()
        rev_last = rev_row.value if rev_row else None
        done_row = db.query(_Cfg).filter(_Cfg.key == "backfill_forward_done").first()
        fwd_done = done_row.value == "true" if done_row else False
    except Exception:
        pass

    return {
        "backfill": {
            "running": bf.get("running", False),
            "phase": bf.get("phase"),
            "current_date": bf.get("current_date"),
            "days_completed": bf.get("days_completed", 0),
            "predictions_inserted": bf.get("predictions_inserted", 0),
            "last_error": bf.get("last_error"),
            "forward_last_date": fwd_last,
            "forward_done": fwd_done,
            "reverse_last_date": rev_last,
        },
        "scraper": {
            "massive_benzinga_last_run": scheduler_last_run.get("massive_benzinga", "").isoformat() if scheduler_last_run.get("massive_benzinga") else None,
            "benzinga_api_last_run": scheduler_last_run.get("benzinga_api", "").isoformat() if scheduler_last_run.get("benzinga_api") else None,
            "fmp_upgrades_last_run": scheduler_last_run.get("fmp_upgrades", "").isoformat() if scheduler_last_run.get("fmp_upgrades") else None,
        },
        "evaluator": {
            "running": ev.get("running", False),
            "predictions_scored": ev.get("predictions_scored", 0),
            "pending_overdue": pending_overdue,
            "total_scored": total_scored,
            "last_run": scheduler_last_run.get("auto_evaluate", "").isoformat() if scheduler_last_run.get("auto_evaluate") else None,
        },
    }


@app.get("/api/admin/db-size")
def db_size():
    """Show database size, table sizes, and prediction counts."""
    from sqlalchemy import text as _text
    db = BgSessionLocal()
    try:
        # Total DB size
        total = db.execute(_text(
            "SELECT pg_size_pretty(pg_database_size(current_database()))"
        )).scalar()
        total_bytes = db.execute(_text(
            "SELECT pg_database_size(current_database())"
        )).scalar()

        # Per-table sizes
        tables = db.execute(_text("""
            SELECT relname,
                   pg_size_pretty(pg_total_relation_size(relname::regclass)) AS total_size,
                   pg_total_relation_size(relname::regclass) AS size_bytes
            FROM pg_stat_user_tables
            ORDER BY pg_total_relation_size(relname::regclass) DESC
        """)).fetchall()
        table_sizes = [
            {"table": r[0], "size": r[1], "bytes": r[2]}
            for r in tables
        ]

        # Prediction count
        pred_count = db.execute(_text("SELECT COUNT(*) FROM predictions")).scalar()

        # Predictions by verified_by (source/scraper)
        by_source = db.execute(_text(
            "SELECT COALESCE(verified_by, 'unknown') AS source, COUNT(*) AS cnt "
            "FROM predictions GROUP BY verified_by ORDER BY cnt DESC"
        )).fetchall()
        source_counts = [{"source": r[0], "count": r[1]} for r in by_source]

        return {
            "total_size": total,
            "total_bytes": total_bytes,
            "total_gb": round(total_bytes / (1024**3), 2),
            "volume_limit_gb": 5.0,
            "usage_pct": round(total_bytes / (5 * 1024**3) * 100, 1),
            "tables": table_sizes,
            "total_predictions": pred_count,
            "predictions_by_source": source_counts,
        }
    finally:
        db.close()


@app.post("/api/admin/backfill-benzinga")
def start_backfill():
    """Start the day-by-day historical backfill as a background task."""
    import threading
    from jobs.benzinga_backfill import run_backfill, get_backfill_status

    status = get_backfill_status()
    if status["running"]:
        return {"status": "already_running", **status}

    threading.Thread(target=run_backfill, daemon=True).start()
    return {"status": "started", "start_date": "2024-03-29", "end_date": str(date.today())}


@app.get("/api/admin/backfill-status")
def backfill_status():
    from jobs.benzinga_backfill import get_backfill_status
    return get_backfill_status()


@app.post("/api/admin/stop-backfill")
def stop_backfill_endpoint():
    from jobs.benzinga_backfill import stop_backfill
    stop_backfill()
    return {"status": "stopping"}


@app.post("/api/admin/evaluate-historical")
def evaluate_historical():
    """Start background evaluation of all pending historical predictions.
    Processes 50 tickers at a time with 5s breaks. Trigger once and walk away."""
    import threading
    from jobs.historical_evaluator import run_evaluation_background, get_eval_status

    status = get_eval_status()
    if status["running"]:
        return {"status": "already_running", **status}

    thread = threading.Thread(target=run_evaluation_background, daemon=True)
    thread.start()
    return {"status": "started"}


@app.get("/api/admin/evaluate-status")
def evaluate_status():
    from jobs.historical_evaluator import get_eval_status
    return get_eval_status()


@app.get("/api/admin/evaluate-debug")
def evaluate_debug():
    """Show exactly what the evaluator sees — pending prediction stats."""
    from sqlalchemy import text as _t
    db = BgSessionLocal()
    try:
        # Check evaluation_date distribution
        stats = db.execute(_t("""
            SELECT
                COUNT(*) as total_pending,
                COUNT(CASE WHEN evaluation_date < NOW() THEN 1 END) as expired,
                COUNT(CASE WHEN evaluation_date >= NOW() THEN 1 END) as not_expired,
                COUNT(CASE WHEN evaluation_date IS NULL THEN 1 END) as null_eval_date,
                COUNT(CASE WHEN entry_price IS NULL THEN 1 END) as null_entry_price,
                COUNT(CASE WHEN target_price IS NULL THEN 1 END) as null_target_price,
                MIN(evaluation_date) as earliest_eval,
                MAX(evaluation_date) as latest_eval
            FROM predictions
            WHERE outcome = 'pending'
        """)).first()

        # 5 example pending predictions
        examples = db.execute(_t("""
            SELECT id, ticker, direction, target_price, entry_price,
                   evaluation_date, prediction_date, window_days
            FROM predictions
            WHERE outcome = 'pending' AND evaluation_date IS NOT NULL
            ORDER BY evaluation_date ASC
            LIMIT 5
        """)).fetchall()

        return {
            "total_pending": stats[0],
            "expired_eval_date": stats[1],
            "future_eval_date": stats[2],
            "null_eval_date": stats[3],
            "null_entry_price": stats[4],
            "null_target_price": stats[5],
            "earliest_eval_date": str(stats[6]) if stats[6] else None,
            "latest_eval_date": str(stats[7]) if stats[7] else None,
            "examples": [
                {"id": r[0], "ticker": r[1], "direction": r[2], "target_price": float(r[3]) if r[3] else None,
                 "entry_price": float(r[4]) if r[4] else None, "evaluation_date": str(r[5]) if r[5] else None,
                 "prediction_date": str(r[6]) if r[6] else None, "window_days": r[7]}
                for r in examples
            ],
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}
    finally:
        db.close()


@app.post("/api/admin/stop-evaluation")
def stop_evaluation():
    from jobs.historical_evaluator import stop_evaluation
    stop_evaluation()
    return {"status": "stopping"}


@app.post("/api/admin/refresh-forecaster-stats")
def refresh_stats():
    """Recalculate ALL forecaster stats from predictions table."""
    from jobs.historical_evaluator import refresh_all_forecaster_stats
    return refresh_all_forecaster_stats()


_re_eval_in_progress = False


@app.get("/api/admin/re-evaluate-status")
def re_evaluate_status():
    """Check if a re-evaluation is in progress."""
    return {"in_progress": _re_eval_in_progress}


@app.post("/api/admin/re-evaluate-all")
def re_evaluate_all():
    """Re-evaluate all scored predictions in batches — NEVER wipes the leaderboard.
    Resets 500 predictions at a time, re-evaluates them, then refreshes stats before
    moving to the next batch. The leaderboard always has some scored predictions."""
    import threading
    from sqlalchemy import text as _t
    global _re_eval_in_progress

    if _re_eval_in_progress:
        return {"status": "already_running"}

    # Count how many need re-evaluation
    db = BgSessionLocal()
    try:
        total_scored = db.execute(_t(
            "SELECT COUNT(*) FROM predictions WHERE outcome IN ('correct','incorrect')"
        )).scalar() or 0
    finally:
        db.close()

    _re_eval_in_progress = True

    def _run():
        global _re_eval_in_progress
        try:
            from jobs.historical_evaluator import evaluate_batch, refresh_all_forecaster_stats
            import time as _t_mod

            total_re_scored = 0
            batch_num = 0
            BATCH_SIZE = 500

            while True:
                batch_num += 1
                db = BgSessionLocal()
                try:
                    # Reset only a batch of 500 predictions to pending
                    reset_ids = db.execute(_t("""
                        SELECT id FROM predictions
                        WHERE outcome IN ('correct','incorrect')
                        ORDER BY id
                        LIMIT :batch_size
                    """), {"batch_size": BATCH_SIZE}).fetchall()

                    if not reset_ids:
                        print(f"[ReEval] No more predictions to re-evaluate")
                        break

                    ids = [r[0] for r in reset_ids]
                    db.execute(_t("""
                        UPDATE predictions
                        SET outcome='pending', actual_return=NULL, evaluated_at=NULL
                        WHERE id = ANY(:ids)
                    """), {"ids": ids})
                    db.commit()
                    print(f"[ReEval] Batch {batch_num}: reset {len(ids)} predictions to pending")
                finally:
                    db.close()

                # Re-evaluate the batch
                batch_scored = 0
                for _ in range(10):  # max 10 sub-batches per reset batch
                    result = evaluate_batch(max_tickers=500)
                    scored = result.get('predictions_scored', 0)
                    batch_scored += scored
                    if scored == 0 or result.get('remaining_tickers', 0) == 0:
                        break
                    _t_mod.sleep(3)

                total_re_scored += batch_scored
                print(f"[ReEval] Batch {batch_num}: re-scored {batch_scored}, total: {total_re_scored}")

                # Refresh stats after each batch so the leaderboard stays populated
                refresh_all_forecaster_stats()
                print(f"[ReEval] Batch {batch_num}: stats refreshed")

                _t_mod.sleep(2)

            # Final stats refresh
            refresh_all_forecaster_stats()
            print(f"[ReEval] Complete: {total_re_scored} predictions re-evaluated across {batch_num} batches")
        except Exception as e:
            print(f"[ReEval] Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            _re_eval_in_progress = False

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "total_to_reevaluate": total_scored}


@app.post("/api/admin/reformat-contexts")
def reformat_contexts():
    """Rewrite prediction context strings to human-readable format."""
    import threading
    from sqlalchemy import text as _t

    def _run():
        from jobs.context_formatter import format_context
        dbs = BgSessionLocal()
        try:
            # Get predictions with raw-format contexts (contain underscores or jargon patterns)
            rows = dbs.execute(_t("""
                SELECT id, context, ticker, direction, target_price
                FROM predictions
                WHERE context IS NOT NULL
                  AND (context LIKE '%initiates_coverage%'
                    OR context LIKE '%maintains %'
                    OR context LIKE '%upgrades %'
                    OR context LIKE '%downgrades %'
                    OR context LIKE '%reiterates %'
                    OR context LIKE '%, PT $%')
                LIMIT 20000
            """)).fetchall()
            print(f"[ReformatCtx] {len(rows)} predictions to reformat")
            updated = 0
            for r in rows:
                old_ctx = r[1] or ""
                # Parse firm and action from old format: "Firm action rating on TICKER, PT $X"
                parts = old_ctx.split(" on ")
                if len(parts) < 2:
                    continue
                before = parts[0].strip()
                # Split "Firm action rating" into components
                words = before.split()
                if len(words) < 2:
                    continue
                # Find the action word
                action_idx = None
                for i, w in enumerate(words):
                    if w.lower() in ("upgrades", "downgrades", "maintains", "reiterates", "initiates_coverage_on", "initiates"):
                        action_idx = i
                        break
                if action_idx is None:
                    continue
                firm = " ".join(words[:action_idx])
                action = words[action_idx]
                rating = " ".join(words[action_idx+1:]) if action_idx + 1 < len(words) else ""
                new_ctx = format_context(firm, action, rating, r[2], r[4])
                dbs.execute(_t("UPDATE predictions SET context=:c, exact_quote=:c WHERE id=:id"),
                            {"c": new_ctx, "id": r[0]})
                updated += 1
            dbs.commit()
            print(f"[ReformatCtx] Updated {updated} predictions")
        except Exception as e:
            dbs.rollback()
            print(f"[ReformatCtx] Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            dbs.close()

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started"}


@app.get("/api/admin/db-health")
def db_health():
    """Database health with connection pool stats and circuit breaker status."""
    import time as _t
    import circuit_breaker

    start = _t.time()
    result = {"status": "ok"}

    # Query test
    try:
        from sqlalchemy import text as _text
        db = SessionLocal()
        r = db.execute(_text("SELECT 1")).scalar()
        elapsed = round((_t.time() - start) * 1000, 1)
        db.close()
        result["query_time_ms"] = elapsed
        result["query_result"] = r
    except Exception as e:
        result["status"] = "error"
        result["query_time_ms"] = round((_t.time() - start) * 1000, 1)
        result["error"] = str(e)

    # User pool
    try:
        pool = engine.pool
        result["user_pool"] = {
            "size": pool.size(), "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(), "overflow": pool.overflow(),
        }
    except Exception:
        pass

    # Background pool
    try:
        bg_pool = bg_engine.pool
        result["bg_pool"] = {
            "size": bg_pool.size(), "checked_in": bg_pool.checkedin(),
            "checked_out": bg_pool.checkedout(), "overflow": bg_pool.overflow(),
        }
    except Exception:
        pass

    # Circuit breaker
    result["circuit_breaker"] = circuit_breaker.get_status()

    return result


@app.post("/api/admin/kill-locks")
def kill_locks():
    """Kill any long-running queries/transactions blocking the database."""
    try:
        from sqlalchemy import text as _text
        db = SessionLocal()
        # Cancel all queries running longer than 5 seconds
        db.execute(_text("""
            SELECT pg_cancel_backend(pid)
            FROM pg_stat_activity
            WHERE state = 'active'
              AND query_start < NOW() - INTERVAL '5 seconds'
              AND pid != pg_backend_pid()
        """))
        db.commit()
        db.close()
        return {"status": "killed"}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/admin/pause-jobs")
def pause_jobs():
    """Manually pause all background jobs for 15 minutes."""
    import circuit_breaker
    circuit_breaker.pause_all_jobs("manual admin request")
    return circuit_breaker.get_status()


@app.post("/api/admin/resume-jobs")
def resume_jobs():
    """Resume background jobs after a pause."""
    import circuit_breaker
    circuit_breaker.resume_all_jobs()
    return circuit_breaker.get_status()


@app.post("/api/admin/backfill-alpha")
def backfill_alpha():
    """Calculate alpha for all evaluated predictions missing it. Runs synchronously (small batch)."""
    from sqlalchemy import text as _t
    from jobs.historical_evaluator import _calc_spy_return

    dbs = BgSessionLocal()
    try:
        # Set longer timeout for this operation
        dbs.execute(_t("SET statement_timeout = '60000'"))

        rows = dbs.execute(_t("""
            SELECT id, actual_return, prediction_date, evaluation_date
            FROM predictions
            WHERE outcome IN ('correct','incorrect')
              AND alpha IS NULL
              AND actual_return IS NOT NULL
            LIMIT 10000
        """)).fetchall()

        updated = 0
        skipped = 0
        sample = []
        for r in rows:
            spy_ret = _calc_spy_return(r[2], r[3])
            if spy_ret is not None:
                alpha = round(float(r[1]) - spy_ret, 2)
                dbs.execute(_t("UPDATE predictions SET sp500_return=:s, alpha=:a WHERE id=:id"),
                            {"s": spy_ret, "a": alpha, "id": r[0]})
                updated += 1
                if len(sample) < 3:
                    sample.append({"id": r[0], "actual_return": float(r[1]), "spy_return": spy_ret, "alpha": alpha,
                                   "pred_date": str(r[2]), "eval_date": str(r[3])})
            else:
                skipped += 1
                if len(sample) < 3:
                    sample.append({"id": r[0], "actual_return": float(r[1]), "pred_date": str(r[2]),
                                   "eval_date": str(r[3]), "spy_return": None, "skipped": True})

        dbs.commit()

        # Refresh forecaster stats
        if updated > 0:
            from jobs.historical_evaluator import refresh_all_forecaster_stats
            refresh_all_forecaster_stats()

        return {
            "status": "done", "found": len(rows), "updated": updated,
            "skipped_no_spy": skipped, "sample": sample,
        }
    except Exception as e:
        dbs.rollback()
        import traceback
        return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}
    finally:
        dbs.close()


@app.post("/api/admin/backfill-sectors")
def backfill_sectors():
    """Look up and assign sectors for predictions missing sector data. 50 tickers per call."""
    import threading
    from jobs.sector_lookup import backfill_sectors_batch

    def _run():
        while True:
            result = backfill_sectors_batch(max_tickers=50)
            print(f"[SectorBackfill] {result}")
            if result.get("tickers_processed", 0) == 0:
                break
            import time
            time.sleep(2)
        print("[SectorBackfill] Complete")

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started"}


@app.get("/api/admin/sector-status")
def sector_status():
    """Show sector backfill progress."""
    from sqlalchemy import text as _t
    db = BgSessionLocal()
    try:
        total = db.execute(_t("SELECT COUNT(DISTINCT ticker) FROM predictions")).scalar() or 0
        mapped = db.execute(_t("SELECT COUNT(DISTINCT ticker) FROM predictions WHERE sector IS NOT NULL AND sector != '' AND sector != 'Other'")).scalar() or 0
        breakdown = db.execute(_t("SELECT sector, COUNT(*) FROM predictions WHERE sector IS NOT NULL AND sector != '' GROUP BY sector ORDER BY COUNT(*) DESC")).fetchall()
        return {
            "total_tickers": total,
            "tickers_mapped": mapped,
            "sectors": {r[0]: r[1] for r in breakdown},
        }
    finally:
        db.close()


@app.get("/api/admin/evaluate-test-one")
def evaluate_test_one():
    """Test evaluating a single ticker to see what happens."""
    from jobs.historical_evaluator import evaluate_batch, _fetch_history, _closest_price
    from database import SessionLocal
    from sqlalchemy import text as _t
    from datetime import datetime, timedelta
    import io, sys

    # Capture print output
    old_stdout = sys.stdout
    sys.stdout = buffer = io.StringIO()

    db = BgSessionLocal()
    try:
        # Get one popular ticker that has pending expired predictions
        row = db.execute(_t("""
            SELECT p.ticker, p.evaluation_date, p.prediction_date, p.entry_price, p.target_price, p.direction
            FROM predictions p
            WHERE p.outcome = 'pending' AND p.evaluation_date < NOW()
              AND p.ticker IN ('AAPL','TSLA','NVDA','MSFT','AMZN','META','GOOGL')
            LIMIT 1
        """)).first()
    finally:
        db.close()

    if not row:
        sys.stdout = old_stdout
        return {"error": "No pending predictions for major tickers"}

    ticker = row[0]
    eval_date = row[1]
    pred_date = row[2]

    # Test yfinance DIRECTLY (no wrapper)
    min_d = pred_date - timedelta(days=5) if pred_date else eval_date - timedelta(days=95)
    max_d = eval_date + timedelta(days=3) if eval_date else datetime.utcnow()
    s = min_d.strftime("%Y-%m-%d")
    e = max_d.strftime("%Y-%m-%d")

    # Test Finnhub candles — also test with a short 30-day range around eval_date
    prices = _fetch_history(ticker, min_d, max_d)
    short_start = eval_date - timedelta(days=15)
    short_end = eval_date + timedelta(days=3)
    prices_short = _fetch_history(ticker, short_start, short_end)

    eval_price = _closest_price(prices, eval_date) if prices else None
    pred_price = _closest_price(prices, pred_date) if prices else None

    sys.stdout = old_stdout
    logs = buffer.getvalue()

    return {
        "ticker": ticker,
        "prediction_date": str(pred_date),
        "evaluation_date": str(eval_date),
        "entry_price": float(row[3]) if row[3] else None,
        "target_price": float(row[4]) if row[4] else None,
        "direction": row[5],
        "date_range": f"{s} to {e}",
        "price_source": "finnhub_candles",
        "price_count_full": len(prices) if prices else 0,
        "price_count_short": len(prices_short) if prices_short else 0,
        "price_sample": dict(list((prices_short or prices or {}).items())[:5]) if (prices or prices_short) else None,
        "eval_date_price": eval_price,
        "pred_date_price": pred_price,
        "logs": logs,
    }
    return {"status": "stopping"}


@app.post("/api/admin/run-user-evaluator")
def run_user_evaluator_now():
    """Run the user prediction evaluator immediately and return results."""
    import traceback as _tb
    db = BgSessionLocal()
    try:
        from jobs.user_evaluator import evaluate_user_predictions
        results = evaluate_user_predictions(db)
        return {"status": "ok", "evaluated": len(results or []), "results": results or []}
    except Exception as e:
        return {"status": "error", "error": str(e), "traceback": _tb.format_exc()}
    finally:
        db.close()


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
        db = BgSessionLocal()
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


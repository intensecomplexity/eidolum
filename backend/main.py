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
from routers.admin_panel import router as admin_v2_router


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


class AdminAuthMiddleware(BaseHTTPMiddleware):
    """Block all /api/admin/* requests without valid auth.
    Accepts either ADMIN_SECRET (legacy) or JWT token from an is_admin=1 user."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/admin/"):
            admin_secret = os.getenv("ADMIN_SECRET", "")
            bearer = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
            query_secret = request.query_params.get("secret", "")
            header_secret = request.headers.get("X-Admin-Secret", "")

            # Try legacy ADMIN_SECRET first
            provided_secret = header_secret or query_secret
            if admin_secret and provided_secret == admin_secret:
                return await call_next(request)
            if admin_secret and bearer == admin_secret:
                return await call_next(request)

            # Try JWT-based admin auth
            if bearer:
                try:
                    from auth import get_current_user as _decode
                    payload = _decode(bearer)
                    uid = payload.get("user_id")
                    if uid:
                        from database import SessionLocal
                        from models import User
                        _db = SessionLocal()
                        try:
                            u = _db.query(User).filter(User.id == uid).first()
                            if u and getattr(u, 'is_admin', 0):
                                return await call_next(request)
                            print(f"[AdminAuth] JWT user {uid} is_admin={getattr(u, 'is_admin', None) if u else 'NOT FOUND'}")
                        finally:
                            _db.close()
                except Exception as e:
                    print(f"[AdminAuth] JWT check error: {e}")

            from starlette.responses import JSONResponse
            return JSONResponse({"detail": "Not found"}, status_code=404)
        return await call_next(request)


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


class PayloadSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject POST/PUT requests with payloads over 10KB for prediction endpoints."""

    MAX_BYTES = 10240  # 10KB

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT") and request.url.path.startswith("/api/"):
            # Skip admin and file upload endpoints
            if not request.url.path.startswith("/api/admin/"):
                content_length = request.headers.get("content-length")
                if content_length and int(content_length) > self.MAX_BYTES:
                    from starlette.responses import JSONResponse
                    return JSONResponse(
                        status_code=413,
                        content={"error": "Payload too large", "max_bytes": self.MAX_BYTES},
                    )
        return await call_next(request)


class RequestTrackingMiddleware(BaseHTTPMiddleware):
    """Track requests per IP for security monitoring."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/"):
            try:
                from slowapi.util import get_remote_address
                from spam_protection import track_request
                ip = get_remote_address(request)
                track_request(ip)
            except Exception:
                pass
        return await call_next(request)


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

    # ── 38b. predictions.url_quality + url_backfill_attempted columns ──
    for col in ["url_quality VARCHAR(20)", "url_backfill_attempted INTEGER DEFAULT 0"]:
        try:
            db.execute(text(f"ALTER TABLE predictions ADD COLUMN {col}"))
            db.commit()
        except Exception:
            db.rollback()

    # ── 39. forecasters.alpha column ────────────────────────────────
    try:
        db.execute(text("ALTER TABLE forecasters ADD COLUMN alpha FLOAT"))
        db.commit()
    except Exception:
        db.rollback()

    # ── 40. users.is_admin + is_banned columns ────────────────────
    for col in ["is_admin INTEGER DEFAULT 0", "is_banned INTEGER DEFAULT 0"]:
        try:
            db.execute(text(f"ALTER TABLE users ADD COLUMN {col}"))
            db.commit()
        except Exception:
            db.rollback()

    # ── 41. audit_log table ───────────────────────────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id SERIAL PRIMARY KEY,
                admin_user_id INTEGER REFERENCES users(id),
                admin_email VARCHAR(255) NOT NULL,
                action VARCHAR(100) NOT NULL,
                target_type VARCHAR(50),
                target_id INTEGER,
                details TEXT,
                ip_address VARCHAR(45),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db.commit()
    except Exception:
        db.rollback()

    # ── 42. ticker_sectors: add company_name + industry + description columns ──
    for col in [
        "company_name VARCHAR(255)",
        "industry VARCHAR(255)",
        "description VARCHAR(300)",
        "logo_url VARCHAR(500)",
        "logo_domain VARCHAR(100)",
    ]:
        try:
            db.execute(text(f"ALTER TABLE ticker_sectors ADD COLUMN {col}"))
            db.commit()
        except Exception:
            db.rollback()

    # ── 43. notification_queue table + user notification columns ──
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS notification_queue (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                ticker VARCHAR(10) NOT NULL,
                prediction_id INTEGER,
                forecaster_name VARCHAR(100),
                direction VARCHAR(20),
                target_price NUMERIC(10,2),
                context TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                sent_at TIMESTAMP
            )
        """))
        db.commit()
    except Exception:
        db.rollback()

    # ── Tournament tables ──────────────────────────────────────────────
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS tournaments (
                id SERIAL PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                status VARCHAR(20) DEFAULT 'upcoming',
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                entry_deadline TIMESTAMP,
                max_participants INTEGER DEFAULT 100,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db.commit()
    except Exception:
        db.rollback()
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS tournament_entries (
                id SERIAL PRIMARY KEY,
                tournament_id INTEGER REFERENCES tournaments(id),
                user_id INTEGER REFERENCES users(id),
                picks TEXT,
                submitted_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(tournament_id, user_id)
            )
        """))
        db.commit()
    except Exception:
        db.rollback()
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS tournament_results (
                id SERIAL PRIMARY KEY,
                tournament_id INTEGER REFERENCES tournaments(id),
                user_id INTEGER REFERENCES users(id),
                score NUMERIC(10,2) DEFAULT 0,
                rank INTEGER,
                hits INTEGER DEFAULT 0,
                nears INTEGER DEFAULT 0,
                misses INTEGER DEFAULT 0,
                prize_badge VARCHAR(50),
                UNIQUE(tournament_id, user_id)
            )
        """))
        db.commit()
    except Exception:
        db.rollback()

    for col in [
        "email_notifications INTEGER DEFAULT 1",
        "notification_frequency VARCHAR(20) DEFAULT 'daily'",
    ]:
        try:
            db.execute(text(f"ALTER TABLE users ADD COLUMN {col}"))
            db.commit()
        except Exception:
            db.rollback()

    try:
        db.execute(text("ALTER TABLE watchlist ADD COLUMN notify INTEGER DEFAULT 1"))
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


# ┌──────────────────────────────────────────────────────────────────────────────┐
# │ Fresh rebuild after DB wipe (2026-03-31).                                  │
# │ Startup: create tables → seed data → start backfill + 3 scheduled jobs.    │
# │ Only 4 jobs: backfill, evaluator, massive_benzinga scraper, stats refresh.  │
# │ Everything else disabled until the backfill catches up.                     │
# └──────────────────────────────────────────────────────────────────────────────┘
@asynccontextmanager
async def lifespan(app):
    global _scheduler
    import threading
    from admin_panel import scheduler_last_run
    from circuit_breaker import (
        db_is_healthy, mark_job_running, mark_job_done,
        acquire_job_lock, release_job_lock, watchdog_check,
        db_storage_ok,
    )

    # Opt-out kill switch: set DISABLE_BACKGROUND_JOBS=true to stop all jobs
    _disable = os.getenv("DISABLE_BACKGROUND_JOBS", "").lower() in ("true", "1", "yes")

    print("[STARTUP] ════════════════════════════════════════")
    print("[STARTUP] Eidolum API starting")
    print(f"[STARTUP] Background jobs: {'DISABLED' if _disable else 'ENABLED (default)'}")
    print(f"[STARTUP] MASSIVE_API_KEY set: {bool(os.getenv('MASSIVE_API_KEY', '').strip())}")
    _fmp = os.getenv("FMP_KEY", "").strip()
    print(f"[STARTUP] FMP_KEY set: {bool(_fmp)}{' (first 5: ' + _fmp[:5] + '...)' if _fmp else ''}")
    _tiingo = os.getenv("TIINGO_API_KEY", "").strip()
    print(f"[STARTUP] TIINGO_API_KEY set: {bool(_tiingo)}")
    print("[STARTUP] ════════════════════════════════════════")

    # Polygon API diagnostic — confirm MASSIVE_API_KEY works with Polygon
    _polygon_key = os.getenv("MASSIVE_API_KEY", "").strip()
    if _polygon_key:
        try:
            import httpx as _phx
            _pr = _phx.get(
                "https://api.polygon.io/v2/aggs/ticker/AAPL/range/1/day/2025-01-02/2025-01-10",
                params={"adjusted": "true", "sort": "asc", "apiKey": _polygon_key},
                timeout=10,
            )
            _pd = _pr.json() if _pr.status_code == 200 else {}
            _bars = _pd.get("results", [])
            print(f"[POLYGON-DIAG] AAPL 2025-01-02..10: HTTP {_pr.status_code}, {len(_bars)} bars")
            if _bars:
                from datetime import datetime as _pdt
                _b = _bars[0]
                _ds = _pdt.utcfromtimestamp(_b['t'] / 1000).strftime('%Y-%m-%d') if _b.get('t') else '?'
                print(f"[POLYGON-DIAG] First bar: date={_ds}, close=${_b.get('c', '?')}")
            elif _pr.status_code != 200:
                print(f"[POLYGON-DIAG] Error response: {str(_pr.text)[:200]}")
        except Exception as _pe:
            print(f"[POLYGON-DIAG] Failed: {_pe}")

    # NOTE: Admin promote, outcome migration, and neutral reclassification
    # all moved to _startup_init() background thread to avoid blocking healthcheck.

    if _disable:
        print("[STARTUP] Jobs disabled via DISABLE_BACKGROUND_JOBS. Only serving API requests.")
        yield
        return

    # ── Background thread: create tables + seed + start backfill ──────────────
    def _startup_init():
        import time as _t2
        from sqlalchemy import text as sql_text
        _t2.sleep(10)  # Let app bind port first

        # STEP 1: Create all tables
        try:
            Base.metadata.create_all(bind=engine)
            print("[Startup] All tables created")
        except Exception as e:
            print(f"[Startup] Table creation error: {e}")
            return  # Can't continue without tables

        # ── Log outcome distribution (no migration — accept both old and new values) ──
        try:
            with engine.connect() as _mc:
                dist_rows = _mc.execute(sql_text("SELECT outcome, COUNT(*) FROM predictions GROUP BY outcome ORDER BY COUNT(*) DESC")).fetchall()
                dist = {r[0]: r[1] for r in dist_rows}
                print(f"[Startup] Prediction outcomes: {dict(dist)}")
        except Exception as _me:
            print(f"[Startup] Outcome query error: {_me}")

        # (FMP startup diagnostic removed — was wasting API calls on every deploy)

        # ── Fix broken source URLs ────────────────────────────────────
        try:
            with engine.connect() as _url_c:
                # FMP: raw API endpoint → stockanalysis.com forecast page
                r1 = _url_c.execute(sql_text(
                    "UPDATE predictions SET source_url = 'https://stockanalysis.com/stocks/' || LOWER(ticker) || '/forecast/' "
                    "WHERE source_url LIKE '%financialmodelingprep.com/stable/%'"
                )).rowcount
                # Benzinga: generic quote pages → ratings page
                r2 = _url_c.execute(sql_text(
                    "UPDATE predictions SET source_url = 'https://www.benzinga.com/stock/' || LOWER(ticker) || '/ratings' "
                    "WHERE source_url LIKE '%benzinga.com/quote/%'"
                )).rowcount
                _url_c.commit()
                if r1 or r2:
                    print(f"[Startup] Fixed source URLs: {r1} FMP + {r2} Benzinga quote pages")
        except Exception as _ue:
            print(f"[Startup] Source URL fix error: {_ue}")

        # ── Bulk fix: generate real Benzinga URLs from external_id ────
        try:
            from jobs.enrich_urls import bulk_fix_benzinga_urls
            bulk_fix_benzinga_urls()
        except Exception as _bf:
            print(f"[Startup] Bulk URL fix error: {_bf}")

        # ── Reclassify hold/neutral predictions ────────────────────────
        # Phase 1: Context says "Neutral —" (sentiment function got it right)
        # Phase 2: Context contains neutral rating names (Hold, Equal-Weight, etc.)
        # Phase 3: Price target within 3% of entry = likely hold
        try:
            with engine.connect() as _nc:
                total_reclass = 0

                # Phase 1: "Firm: Neutral —" in context
                r1 = _nc.execute(sql_text(
                    """UPDATE predictions SET direction = 'neutral'
                    WHERE direction != 'neutral'
                    AND (context LIKE '%: Neutral%' OR exact_quote LIKE '%: Neutral%')"""
                )).rowcount
                _nc.commit()
                total_reclass += r1

                # Phase 2: Context contains neutral rating names
                # Catches "Maintains Hold rating", "Equal-Weight rating", etc.
                # even when sentiment label was wrong ("Bullish — Maintains Hold")
                r2 = _nc.execute(sql_text(
                    """UPDATE predictions SET direction = 'neutral'
                    WHERE direction != 'neutral' AND (
                        context LIKE '%Hold rating%'
                        OR context LIKE '%Neutral rating%'
                        OR context LIKE '%Market Perform rating%'
                        OR context LIKE '%Equal Weight rating%'
                        OR context LIKE '%Equal-Weight rating%'
                        OR context LIKE '%Sector Perform rating%'
                        OR context LIKE '%In-Line rating%'
                        OR context LIKE '%In Line rating%'
                        OR context LIKE '%Peer Perform rating%'
                        OR context LIKE '%Market Weight rating%'
                        OR context LIKE '%Sector Weight rating%'
                        OR context LIKE '% to Hold%'
                        OR context LIKE '% to Neutral%'
                        OR context LIKE '% to Market Perform%'
                        OR context LIKE '% to Equal Weight%'
                        OR context LIKE '% to Equal-Weight%'
                        OR context LIKE '% to Sector Perform%'
                        OR context LIKE '% to In-Line%'
                        OR context LIKE '% to Peer Perform%'
                    )"""
                )).rowcount
                _nc.commit()
                total_reclass += r2

                # Phase 3: Price target within 3% of entry = effectively hold
                r3 = _nc.execute(sql_text(
                    """UPDATE predictions SET direction = 'neutral'
                    WHERE direction != 'neutral'
                    AND target_price IS NOT NULL AND entry_price IS NOT NULL AND entry_price > 0
                    AND ABS(target_price - entry_price) / entry_price < 0.03
                    AND (context LIKE '%Maintains%' OR context LIKE '%Reaffirms%')"""
                )).rowcount
                _nc.commit()
                total_reclass += r3

                if total_reclass:
                    print(f"[Startup] Reclassified {total_reclass} to neutral (sentiment:{r1} + rating:{r2} + target:{r3})")
        except Exception as _ne:
            print(f"[Startup] Neutral reclassification error: {_ne}")

        # ── Fix bad source URLs ──────────────────────────────────────────
        try:
            _url_db = BgSessionLocal()
            total_fixed = 0

            # Benzinga: /quote/TICKER → /stock/TICKER/ratings
            r1 = _url_db.execute(sql_text(
                "UPDATE predictions SET source_url = REPLACE(source_url, '/quote/', '/stock/') || '/ratings' "
                "WHERE source_url LIKE '%benzinga.com/quote/%' AND source_url NOT LIKE '%/ratings'"
            )).rowcount
            _url_db.commit()
            total_fixed += r1

            # FMP stable/grades URLs → stockanalysis.com
            r2 = _url_db.execute(sql_text(
                "UPDATE predictions SET source_url = 'https://stockanalysis.com/stocks/' || LOWER(ticker) || '/forecast/' "
                "WHERE source_url LIKE '%financialmodelingprep.com/stable/%'"
            )).rowcount
            _url_db.commit()
            total_fixed += r2

            # Clear fake archive URLs (not real web.archive.org)
            r3 = _url_db.execute(sql_text(
                "UPDATE predictions SET archive_url = NULL "
                "WHERE archive_url IS NOT NULL AND archive_url NOT LIKE 'https://web.archive.org%' "
                "AND archive_url NOT LIKE '/archive/%'"
            )).rowcount
            _url_db.commit()
            total_fixed += r3

            if total_fixed:
                print(f"[Startup] Fixed {total_fixed} URLs (benzinga:{r1} + fmp:{r2} + fake_archive:{r3})")
            _url_db.close()
        except Exception as _ue:
            print(f"[Startup] URL migration error: {_ue}")

        # Critical indexes for ticker detail page performance
        try:
            from sqlalchemy import text as _idx_t
            _idx_db = BgSessionLocal()
            for idx in [
                "CREATE INDEX IF NOT EXISTS idx_pred_ticker ON predictions(ticker)",
                "CREATE INDEX IF NOT EXISTS idx_pred_ticker_outcome ON predictions(ticker, outcome)",
                "CREATE INDEX IF NOT EXISTS idx_pred_outcome ON predictions(outcome)",
                "CREATE INDEX IF NOT EXISTS idx_pred_forecaster_id ON predictions(forecaster_id)",
                "CREATE INDEX IF NOT EXISTS idx_pred_evaluation_date ON predictions(evaluation_date)",
            ]:
                try:
                    _idx_db.execute(_idx_t(idx))
                    _idx_db.commit()
                except Exception:
                    _idx_db.rollback()
            _idx_db.close()
            print("[Startup] Critical indexes created")
        except Exception as e:
            print(f"[Startup] Index creation error: {e}")

        # Populate forecaster slugs
        try:
            _slug_db = BgSessionLocal()
            try:
                _slug_db.execute(sql_text("ALTER TABLE forecasters ADD COLUMN IF NOT EXISTS slug VARCHAR(255) UNIQUE"))
                _slug_db.commit()
            except Exception:
                _slug_db.rollback()
            # Populate missing slugs
            no_slug = _slug_db.execute(sql_text(
                "SELECT id, name FROM forecasters WHERE slug IS NULL OR slug = ''"
            )).fetchall()
            if no_slug:
                import re as _slug_re
                seen = set()
                # Get existing slugs
                existing = _slug_db.execute(sql_text("SELECT slug FROM forecasters WHERE slug IS NOT NULL AND slug != ''")).fetchall()
                for r in existing:
                    seen.add(r[0])
                populated = 0
                for fid, fname in no_slug:
                    base = _slug_re.sub(r'[^a-z0-9]+', '-', (fname or 'unknown').lower().strip()).strip('-') or 'unknown'
                    slug = base
                    suffix = 2
                    while slug in seen:
                        slug = f"{base}-{suffix}"
                        suffix += 1
                    seen.add(slug)
                    _slug_db.execute(sql_text("UPDATE forecasters SET slug = :s WHERE id = :id"), {"s": slug, "id": fid})
                    populated += 1
                _slug_db.commit()
                if populated > 0:
                    print(f"[Startup] Populated slugs for {populated} forecasters")
            _slug_db.close()
        except Exception as e:
            print(f"[Startup] Slug migration error: {e}")

        # Ensure is_admin column exists + auto-promote super admin
        try:
            _admin_db = BgSessionLocal()
            # Add column if missing (create_all doesn't alter existing tables)
            try:
                _admin_db.execute(sql_text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin INTEGER DEFAULT 0"))
                _admin_db.commit()
            except Exception:
                _admin_db.rollback()
            # Force-set admin on every startup
            _admin_db.execute(sql_text(
                "UPDATE users SET is_admin = 1 WHERE email = 'nimrodryder@gmail.com' AND (is_admin IS NULL OR is_admin = 0)"
            ))
            _admin_db.commit()
            row = _admin_db.execute(sql_text(
                "SELECT id, is_admin FROM users WHERE email = 'nimrodryder@gmail.com'"
            )).first()
            if row:
                print(f"[Startup] Admin: user_id={row[0]}, is_admin={row[1]}")
            _admin_db.close()
        except Exception as e:
            print(f"[Startup] Admin promote error: {e}")

        # Neutral reclassification — runs every startup until neutrals exist
        try:
            from sqlalchemy import text as _rcl_t
            _rcl_db = BgSessionLocal()
            count_before = _rcl_db.execute(_rcl_t(
                "SELECT COUNT(*) FROM predictions WHERE direction = 'neutral'"
            )).scalar() or 0
            print(f"[Startup] Neutral predictions before: {count_before}")

            if count_before < 100:
                result = _rcl_db.execute(_rcl_t("""
                    UPDATE predictions SET direction = 'neutral'
                    WHERE direction != 'neutral' AND (
                        LOWER(context) LIKE '%maintains hold%'
                        OR LOWER(context) LIKE '%maintains neutral%'
                        OR LOWER(context) LIKE '%maintains equal%'
                        OR LOWER(context) LIKE '%maintains market perform%'
                        OR LOWER(context) LIKE '%maintains sector perform%'
                        OR LOWER(context) LIKE '%maintains in-line%'
                        OR LOWER(context) LIKE '%maintains peer perform%'
                        OR LOWER(context) LIKE '%reaffirms hold%'
                        OR LOWER(context) LIKE '%reaffirms neutral%'
                        OR LOWER(context) LIKE '%reaffirms equal%'
                        OR LOWER(context) LIKE '%to hold%'
                        OR LOWER(context) LIKE '%to neutral%'
                        OR LOWER(context) LIKE '%to equal-weight%'
                        OR LOWER(context) LIKE '%to equal weight%'
                        OR LOWER(context) LIKE '%to market perform%'
                        OR LOWER(context) LIKE '%to sector perform%'
                        OR LOWER(context) LIKE '%to in-line%'
                        OR LOWER(context) LIKE '%to peer perform%'
                        OR LOWER(context) LIKE '%hold rating%'
                        OR LOWER(context) LIKE '%neutral rating%'
                        OR LOWER(context) LIKE '%equal-weight rating%'
                        OR LOWER(context) LIKE '%equal weight rating%'
                        OR LOWER(context) LIKE '% hold on %'
                        OR LOWER(context) LIKE '% neutral on %'
                        OR LOWER(context) LIKE '% equal-weight on %'
                        OR LOWER(context) LIKE '% market perform on %'
                        OR LOWER(context) LIKE '%: neutral —%'
                        OR LOWER(context) LIKE '%coverage with hold%'
                        OR LOWER(context) LIKE '%coverage with neutral%'
                        OR LOWER(context) LIKE '%coverage with equal%'
                        OR LOWER(context) LIKE '%coverage with market perform%'
                    )
                """))
                _rcl_db.commit()
                count_after = _rcl_db.execute(_rcl_t(
                    "SELECT COUNT(*) FROM predictions WHERE direction = 'neutral'"
                )).scalar() or 0
                print(f"[Startup] Neutral reclassified: {count_after - count_before} new, {count_after} total")
            else:
                print(f"[Startup] Neutral predictions already exist: {count_before}")
            _rcl_db.close()
        except Exception as e:
            print(f"[Startup] Neutral reclassification error: {e}")

        # Run migrations (add columns that models.py defines but create_all might miss)
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

        # Seed magazine forecasters (alias dictionary)
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

        # Fix broken URLs: /analyst/ratings/ and /stock-articles/ → generic /stock/TICKER/ratings
        try:
            _fix_db = BgSessionLocal()
            r1 = _fix_db.execute(sql_text("""
                UPDATE predictions
                SET source_url = 'https://www.benzinga.com/stock/' || LOWER(ticker) || '/ratings'
                WHERE source_url LIKE '%%benzinga.com/analyst/ratings/%%'
            """)).rowcount
            r2 = _fix_db.execute(sql_text("""
                UPDATE predictions
                SET source_url = 'https://www.benzinga.com/stock/' || LOWER(ticker) || '/ratings',
                    url_quality = 'generic'
                WHERE source_url LIKE '%%/stock-articles/%%'
            """)).rowcount
            _fix_db.commit()
            if r1 + r2 > 0:
                print(f"[Startup] Fixed URLs: {r1} /analyst/ratings/ + {r2} /stock-articles/ → /stock/TICKER/ratings")
            _fix_db.close()
        except Exception as e:
            print(f"[Startup] URL fix error: {e}")

        # ── Source URL diagnostic ─────────────────────────────────────
        try:
            _url_db = BgSessionLocal()

            # 1. Most common URLs
            top_urls = _url_db.execute(sql_text("""
                SELECT source_url, COUNT(*) as cnt
                FROM predictions
                GROUP BY source_url
                ORDER BY cnt DESC
                LIMIT 20
            """)).fetchall()
            print("[URL-DIAG] Top 20 source URLs:")
            for r in top_urls:
                print(f"  {r[1]:>6,}x  {(r[0] or 'NULL')[:80]}")

            # 2. URL type breakdown
            breakdown = _url_db.execute(sql_text("""
                SELECT
                    COUNT(*) as total,
                    COUNT(CASE WHEN source_url IS NULL OR source_url = '' THEN 1 END) as no_url,
                    COUNT(CASE WHEN source_url LIKE '%%stockanalysis%%' THEN 1 END) as stockanalysis,
                    COUNT(CASE WHEN source_url LIKE '%%/stock/%%/ratings%%' THEN 1 END) as generic_ratings,
                    COUNT(CASE WHEN source_url LIKE '%%benzinga.com/analyst/ratings%%' THEN 1 END) as bz_analyst,
                    COUNT(CASE WHEN source_url LIKE '%%benzinga.com/news%%' OR source_url LIKE '%%benzinga.com/markets%%' THEN 1 END) as bz_article,
                    COUNT(CASE WHEN source_url LIKE '%%financialmodelingprep%%' THEN 1 END) as fmp,
                    COUNT(CASE WHEN source_url LIKE '%%/quote/%%' THEN 1 END) as quote_page
                FROM predictions
            """)).first()
            if breakdown:
                print(f"[URL-DIAG] Breakdown: total={breakdown[0]:,}, no_url={breakdown[1]:,}, "
                      f"stockanalysis={breakdown[2]:,}, generic_ratings={breakdown[3]:,}, "
                      f"bz_analyst={breakdown[4]:,}, bz_article={breakdown[5]:,}, "
                      f"fmp={breakdown[6]:,}, quote_page={breakdown[7]:,}")

            _url_db.close()
        except Exception as e:
            print(f"[URL-DIAG] Error: {e}")

        # Check no_data backlog size — if large, skip non-evaluation FMP usage
        _no_data_count = 0
        try:
            _nd_db = BgSessionLocal()
            _no_data_count = _nd_db.execute(sql_text(
                "SELECT COUNT(*) FROM predictions WHERE outcome = 'no_data'"
            )).scalar() or 0
            _nd_db.close()
            print(f"[Startup] no_data predictions: {_no_data_count:,}")
        except Exception:
            pass

        # Backfill company names (uses Finnhub, not FMP — always safe)
        try:
            from jobs.sector_lookup import backfill_company_names
            backfill_company_names()
            print("[Startup] Company name backfill complete")
        except Exception as e:
            print(f"[Startup] Company name backfill error: {e}")

        # Description backfill — SKIP if no_data backlog exists (saves FMP budget)
        if _no_data_count < 1000:
            try:
                from jobs.sector_lookup import backfill_descriptions
                backfill_descriptions()
            except Exception as e:
                print(f"[Startup] Description backfill error: {e}")
        else:
            print(f"[Startup] Skipping description backfill — {_no_data_count:,} no_data predictions need FMP budget")

        # URL quality classification (batched, idempotent)
        try:
            _uq_db = BgSessionLocal()
            batch_num = 0
            while True:
                updated = _uq_db.execute(sql_text("""
                    UPDATE predictions SET url_quality = CASE
                        WHEN source_url IS NULL OR source_url = '' THEN 'none'
                        WHEN source_url LIKE '%%benzinga.com/stock/%%/ratings%%' THEN 'generic'
                        WHEN source_url LIKE '%%stockanalysis.com%%' THEN 'generic'
                        WHEN source_url LIKE '%%/ratings' THEN 'generic'
                        WHEN source_url LIKE '%%/quote/%%' THEN 'generic'
                        WHEN source_url LIKE '%%/forecast/%%' THEN 'generic'
                        WHEN source_url LIKE '%%benzinga.com/news%%' THEN 'real_article'
                        WHEN source_url LIKE '%%benzinga.com/press%%' THEN 'real_article'
                        ELSE 'generic'
                    END
                    WHERE id IN (SELECT id FROM predictions WHERE url_quality IS NULL LIMIT 10000)
                """)).rowcount
                _uq_db.commit()
                batch_num += 1
                if updated == 0:
                    break
                print(f"[Startup] URL quality: classified {batch_num * 10000} predictions")
            # Revert bad backfill: stock-articles/analyst-ratings URLs are generic, not real
            reverted = _uq_db.execute(sql_text(
                "UPDATE predictions SET url_quality = 'generic' "
                "WHERE source_url LIKE '%%/stock-articles/%%/analyst-ratings%%' AND url_quality = 'real_article'"
            )).rowcount
            _uq_db.commit()
            if reverted:
                print(f"[Startup] URL quality: reverted {reverted} stock-articles URLs from real_article to generic")

            # Fix predictions that have genuine news URLs but wrong quality
            fixed = _uq_db.execute(sql_text(
                "UPDATE predictions SET url_quality = 'real_article' "
                "WHERE source_url LIKE '%%benzinga.com/news/%%' AND source_url NOT LIKE '%%/stock-articles/%%' "
                "AND (url_quality IS NULL OR url_quality = 'generic')"
            )).rowcount
            _uq_db.commit()
            if fixed:
                print(f"[Startup] URL quality: reclassified {fixed} benzinga.com/news URLs to real_article")

            # Log distribution
            dist = _uq_db.execute(sql_text("SELECT url_quality, COUNT(*) FROM predictions GROUP BY url_quality")).fetchall()
            print(f"[Startup] URL quality distribution: {dict((r[0] or 'NULL', r[1]) for r in dist)}")
            _uq_db.close()
        except Exception as _uqe:
            print(f"[Startup] URL quality classification error: {_uqe}")

        # STEP 2: Catch-up evaluation — clear the backlog of overdue predictions
        try:
            from sqlalchemy import text as _eval_t
            _eval_db = BgSessionLocal()
            overdue_count = _eval_db.execute(_eval_t(
                "SELECT COUNT(*) FROM predictions WHERE outcome = 'pending' AND evaluation_date IS NOT NULL AND evaluation_date < NOW()"
            )).scalar() or 0
            _eval_db.close()
            print(f"[Startup] Overdue predictions: {overdue_count}")

            if overdue_count > 100:
                print(f"[Startup] Starting evaluation catch-up for {overdue_count} overdue predictions...")
                import time as _catchup_time
                from jobs.historical_evaluator import evaluate_batch, refresh_all_forecaster_stats
                catchup_total = 0
                catchup_start = _catchup_time.time()
                max_catchup_time = 600  # 10 minutes max for startup catch-up
                while (_catchup_time.time() - catchup_start) < max_catchup_time:
                    result = evaluate_batch(max_tickers=500)
                    scored = result.get('predictions_scored', 0)
                    remaining = result.get('remaining_tickers', 0)
                    catchup_total += scored
                    if remaining == 0 or result.get('tickers_processed', 0) == 0:
                        break
                    print(f"[Startup/Eval] {catchup_total} scored so far, {remaining} remaining...")
                    _catchup_time.sleep(2)
                if catchup_total > 0:
                    refresh_all_forecaster_stats()
                elapsed = _catchup_time.time() - catchup_start
                print(f"[Startup] Evaluation catch-up done: {catchup_total} scored in {elapsed:.0f}s")
        except Exception as e:
            print(f"[Startup] Evaluation catch-up error: {e}")

        # STEP 3: Start forward backfill (2020-01-01 → today)
        try:
            from jobs.benzinga_backfill import auto_resume_backfill
            auto_resume_backfill()
        except Exception as e:
            print(f"[Startup] Backfill auto-resume error: {e}")

        print("[Startup] Init complete — backfill running in background")

    threading.Thread(target=_startup_init, daemon=True).start()

    # ── Global job lock wrapper ───────────────────────────────────────────────
    def _guarded_job(job_name, job_fn):
        """Every job: circuit breaker → storage guard → global lock → run."""
        def wrapper():
            from datetime import datetime as _dt
            scheduler_last_run[job_name] = _dt.utcnow()
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

    # ── Only 3 scheduled jobs + watchdog ──────────────────────────────────────
    # (Backfill runs as its own daemon thread, not via scheduler)

    # JOB 1: massive_benzinga 2-hour scraper (new daily data)
    run_massive_benzinga = _guarded_job("massive_benzinga", lambda db: __import__('jobs.massive_benzinga', fromlist=['scrape_massive_ratings']).scrape_massive_ratings(db))

    # JOB 2: evaluator — runs INDEPENDENTLY (no global lock!)
    # The evaluator only reads pending predictions and writes outcomes.
    # Zero data conflict with scrapers — should never be blocked by the lock.
    def _auto_evaluate_standalone():
        import time as _eval_time
        from datetime import datetime as _dt
        scheduler_last_run["auto_evaluate"] = _dt.utcnow()
        if not db_is_healthy("auto_evaluate"):
            return
        mark_job_running("auto_evaluate")
        try:
            from jobs.historical_evaluator import evaluate_batch, refresh_all_forecaster_stats
            start = _eval_time.time()
            total_scored = 0
            batch_num = 0
            while (_eval_time.time() - start) < 480:  # 8 minute max per cycle
                result = evaluate_batch(max_tickers=500)
                scored = result.get('predictions_scored', 0)
                remaining = result.get('remaining_tickers', 0)
                total_scored += scored
                batch_num += 1
                print(f"[AutoEval] Batch {batch_num}: {scored} scored, {remaining} remaining")
                if remaining == 0 or result.get('tickers_processed', 0) == 0:
                    break
                _eval_time.sleep(2)
            if total_scored > 0:
                refresh_all_forecaster_stats()
            print(f"[AutoEval] Done: {total_scored} scored in {batch_num} batches ({_eval_time.time()-start:.0f}s)")
        except Exception as e:
            print(f"[auto_evaluate] Error: {e}")
        finally:
            mark_job_done("auto_evaluate")

    # JOB 3: stats refresh — lightweight SQL only, no lock needed
    def _refresh_stats_standalone():
        from datetime import datetime as _dt
        from admin_panel import scheduler_last_run
        scheduler_last_run["refresh_stats"] = _dt.utcnow()
        if not db_is_healthy("refresh_stats"):
            return
        mark_job_running("refresh_stats")
        try:
            from jobs.historical_evaluator import refresh_all_forecaster_stats
            refresh_all_forecaster_stats()
        except Exception as e:
            print(f"[refresh_stats] Error: {e}")
        finally:
            mark_job_done("refresh_stats")

    # JOB 6: analyst subscription notifications (hourly)
    def _analyst_notif(db):
        from jobs.analyst_notifications import run_analyst_notifications
        run_analyst_notifications()
    run_analyst_notif = _guarded_job("analyst_notifications", _analyst_notif)

    # Watchdog: auto-kill stuck jobs + pause if site slow
    def _watchdog():
        watchdog_check()
        from circuit_breaker import check_site_health_and_pause
        check_site_health_and_pause()

    # ── Register with scheduler ───────────────────────────────────────────────
    _first_run = datetime.utcnow() + timedelta(seconds=90)  # 90s: wait for tables + seeds

    scheduler = AsyncIOScheduler()
    _scheduler = scheduler

    # JOB 4: FMP per-ticker grades — runs independently (no global lock)
    def _fmp_grades_standalone():
        """FMP grades — SKIPPED when no_data backlog > 1000 to save FMP budget for RetryNoData."""
        from datetime import datetime as _dt
        from admin_panel import scheduler_last_run
        scheduler_last_run["fmp_grades"] = _dt.utcnow()

        # Check no_data backlog — if large, skip grades to save FMP budget
        try:
            _chk_db = BgSessionLocal()
            _nd = _chk_db.execute(sql_text("SELECT COUNT(*) FROM predictions WHERE outcome = 'no_data'")).scalar() or 0
            _chk_db.close()
            if _nd > 1000:
                print(f"[fmp_grades] SKIPPED — {_nd:,} no_data predictions need FMP budget. Grades will resume after backlog clears.")
                return
        except Exception:
            pass

        if not db_is_healthy("fmp_grades"):
            return
        if not db_storage_ok("fmp_grades"):
            return
        mark_job_running("fmp_grades")
        try:
            db = BgSessionLocal()
            try:
                from jobs.upgrade_scrapers import scrape_fmp_grades
                scrape_fmp_grades(db)
            except Exception as e:
                print(f"[fmp_grades] Error: {e}")
            finally:
                db.close()
        finally:
            mark_job_done("fmp_grades")

    # JOB 6: daily sweep for stuck predictions (no_data cleanup)
    def _sweep_stuck(db):
        from jobs.evaluator import sweep_stuck_predictions, retry_no_data_predictions
        sweep_stuck_predictions(db)
        # Also retry no_data predictions
        from database import BgSessionLocal
        db2 = BgSessionLocal()
        try:
            retry_no_data_predictions(db2)
        finally:
            db2.close()
    run_sweep = _guarded_job("sweep_stuck", _sweep_stuck)

    # JOB 7: Retry no_data predictions using Tiingo (40 tickers/hr, 480/day limit)
    def _retry_no_data_standalone():
        from datetime import datetime as _dt
        from admin_panel import scheduler_last_run
        scheduler_last_run["retry_no_data"] = _dt.utcnow()
        if not db_is_healthy("retry_no_data"):
            return
        mark_job_running("retry_no_data")
        try:
            db = BgSessionLocal()
            try:
                from jobs.retry_no_data import retry_no_data_batch
                retry_no_data_batch(db, max_tickers=500)
            except Exception as e:
                print(f"[retry_no_data] Error: {e}")
            finally:
                db.close()
        finally:
            mark_job_done("retry_no_data")

    scheduler.add_job(run_massive_benzinga, "interval", hours=2, id="massive_benzinga", next_run_time=_first_run)
    scheduler.add_job(_fmp_grades_standalone, "interval", hours=24, id="fmp_grades", next_run_time=_first_run + timedelta(minutes=20))
    scheduler.add_job(_auto_evaluate_standalone, "interval", minutes=30, id="auto_evaluate", next_run_time=_first_run + timedelta(minutes=5))
    scheduler.add_job(_refresh_stats_standalone, "interval", hours=2, id="refresh_stats", next_run_time=_first_run + timedelta(minutes=10))
    scheduler.add_job(run_sweep, "interval", hours=24, id="sweep_stuck", next_run_time=_first_run + timedelta(minutes=15))
    scheduler.add_job(_retry_no_data_standalone, "interval", hours=1, id="retry_no_data", next_run_time=_first_run + timedelta(minutes=30))
    scheduler.add_job(run_analyst_notif, "interval", hours=1, id="analyst_notifications", next_run_time=_first_run + timedelta(minutes=25))

    # JOB: URL backfill — find real article URLs for generic predictions
    def _url_backfill_standalone():
        from datetime import datetime as _dt
        from admin_panel import scheduler_last_run
        scheduler_last_run["url_backfill"] = _dt.utcnow()
        if not db_is_healthy("url_backfill"):
            return
        mark_job_running("url_backfill")
        try:
            db = BgSessionLocal()
            try:
                from jobs.backfill_urls import backfill_real_urls
                result = backfill_real_urls(db, max_per_run=20000)
                # Update url_quality for any URLs we just fixed
                db.execute(sql_text(
                    "UPDATE predictions SET url_quality = 'real_article' "
                    "WHERE url_quality != 'real_article' AND source_url LIKE '%%benzinga.com/news%%'"
                ))
                db.commit()
            except Exception as e:
                print(f"[url_backfill] Error: {e}")
            finally:
                db.close()
        finally:
            mark_job_done("url_backfill")
    scheduler.add_job(_url_backfill_standalone, "interval", hours=24, id="url_backfill", next_run_time=_first_run + timedelta(minutes=40))
    # JOB: Tournament live scoring (only runs when active tournaments exist)
    def _tournament_score():
        try:
            db = BgSessionLocal()
            from jobs.tournament_scorer import update_live_scores
            update_live_scores(db)
            db.close()
        except Exception as e:
            print(f"[TournamentScore] Error: {e}")
    scheduler.add_job(_tournament_score, "interval", hours=6, id="tournament_scorer", next_run_time=_first_run + timedelta(minutes=45))

    # JOB: YouTube scraper — V1 log only, every 8 hours, independent (no lock)
    def _youtube_scraper():
        from datetime import datetime as _dt
        scheduler_last_run["youtube_scraper"] = _dt.utcnow()
        if not db_is_healthy("youtube_scraper"):
            return
        mark_job_running("youtube_scraper")
        try:
            from jobs.youtube_scraper import run_youtube_scraper
            db = BgSessionLocal()
            try:
                run_youtube_scraper(db)
            finally:
                db.close()
        except Exception as e:
            print(f"[YouTubeScraper] Error: {e}")
            import traceback; traceback.print_exc()
        finally:
            mark_job_done("youtube_scraper")
    scheduler.add_job(_youtube_scraper, "interval", hours=8, id="youtube_scraper", next_run_time=_first_run + timedelta(minutes=55))
    print("[YouTubeScraper] Scheduled: every 8h (LOG ONLY — no DB inserts)")

    scheduler.add_job(_watchdog, "interval", minutes=5, id="watchdog")

    # JOB: Backfill real article URLs from Benzinga API — DISABLED
    # Massive API benzinga_news_url returns generic pages, not real articles.
    # Keeping code but not scheduling.
    print("[URLBackfill] DISABLED — Massive API returns generic URLs")

    # JOB: Enrich generic URLs with real article URLs via Jina Search
    # 500 predictions/run, 0.5s delay, runs hourly = ~12,000/day
    def _enrich_urls():
        from datetime import datetime as _dt
        from admin_panel import scheduler_last_run
        scheduler_last_run["enrich_urls"] = _dt.utcnow()
        print("[JinaEnrich] Job triggered")
        if not db_is_healthy("enrich_urls"):
            print("[JinaEnrich] Skipped — DB not healthy")
            return
        mark_job_running("enrich_urls")
        try:
            from jobs.enrich_urls import enrich_source_urls
            enrich_source_urls()
        except Exception as e:
            print(f"[JinaEnrich] Error: {e}")
            import traceback; traceback.print_exc()
        finally:
            mark_job_done("enrich_urls")
    _enrich_first = _first_run + timedelta(minutes=5)
    scheduler.add_job(_enrich_urls, "interval", hours=1, id="enrich_urls", next_run_time=_enrich_first)
    print(f"[JinaEnrich] Scheduled: first run at {_enrich_first.strftime('%H:%M:%S')}, then every 1h")

    # JOB: Queue watchlist notifications (runs after scrapers, every 4 hours)
    def _queue_watchlist():
        from jobs.watchlist_notifier import queue_watchlist_notifications
        queue_watchlist_notifications()
    scheduler.add_job(_queue_watchlist, "interval", hours=4, id="watchlist_queue", next_run_time=_first_run + timedelta(minutes=35))

    # JOB: Send watchlist daily digest (8 AM EST = 13:00 UTC, weekdays)
    def _watchlist_digest():
        from jobs.watchlist_notifier import send_daily_digest
        send_daily_digest()
    scheduler.add_job(_watchlist_digest, "cron", day_of_week="mon-fri", hour=13, minute=0, id="watchlist_digest")

    # Site-wide weekly digest — Monday 8AM EST (13:00 UTC)
    def _site_weekly_digest():
        from jobs.weekly_digest import send_site_weekly_digest
        db = BgSessionLocal()
        try:
            send_site_weekly_digest(db)
        except Exception as e:
            print(f"[SiteDigest] Error: {e}")
        finally:
            db.close()
    scheduler.add_job(_site_weekly_digest, "cron", day_of_week="mon", hour=13, minute=0, id="site_weekly_digest")

    scheduler.start()
    for j in scheduler.get_jobs():
        print(f"[STARTUP] Job: {j.id} → next_run={j.next_run_time}")
    print(f"[STARTUP] {len(scheduler.get_jobs())} jobs registered")
    print(f"[STARTUP] Backfill daemon thread started in _startup_init (runs after 10s)")
    print(f"[STARTUP] Storage guard: 40GB limit")
    print(f"[STARTUP] Global job lock: only 1 job at a time")
    yield
    scheduler.shutdown()


app = FastAPI(title="Eidolum API", version="1.0.0", lifespan=lifespan)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Request tracking for security reports
app.add_middleware(RequestTrackingMiddleware)

# Payload size limit (10KB for API POST/PUT)
app.add_middleware(PayloadSizeLimitMiddleware)

# Admin auth — blocks /api/admin/* without ADMIN_SECRET
app.add_middleware(AdminAuthMiddleware)

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
from routers import activity_hub
app.include_router(activity_hub.router, prefix="/api")
app.include_router(share.router, prefix="/api")
app.include_router(daily_challenge_router.router, prefix="/api")
app.include_router(reactions.router, prefix="/api")
from routers import comments as comments_router
app.include_router(comments_router.router, prefix="/api")
from routers import ticker_discussions
app.include_router(ticker_discussions.router, prefix="/api")
from routers import prediction_detail
app.include_router(prediction_detail.router, prefix="/api")
app.include_router(watchlist_router.router, prefix="/api")
app.include_router(controversial.router, prefix="/api")
from routers import compare as compare_router
app.include_router(compare_router.router, prefix="/api")
from routers import compare_forecasters as compare_fc_router
app.include_router(compare_fc_router.router, prefix="/api")
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
app.include_router(admin_v2_router, prefix="/api")  # JWT-based admin panel
from routers.og_image import router as og_image_router
app.include_router(og_image_router, prefix="/api")
from routers.smart_money import router as smart_money_router
app.include_router(smart_money_router, prefix="/api")
from routers.tournaments import router as tournaments_router
app.include_router(tournaments_router, prefix="/api")


@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok", "app": "Eidolum API"}


from fastapi import Depends as _Depends
from sqlalchemy.orm import Session as _Session
from database import get_db as _get_db
from middleware.auth import require_admin_user as _require_admin


@app.get("/api/features")
def get_features(db: _Session = _Depends(_get_db)):
    """Return all feature flags in one call. Cached by frontend."""
    from sqlalchemy import text as _ft
    flags = {
        "tournaments": False, "daily_challenge": False,
        "duels": False, "compete": False,
    }
    try:
        rows = db.execute(_ft(
            "SELECT key, value FROM config WHERE key IN ('tournaments_enabled','daily_challenge_enabled','duels_enabled','compete_enabled')"
        )).fetchall()
        for r in rows:
            flags[r[0].replace("_enabled", "")] = r[1] == "true"
    except Exception:
        pass
    return flags


@app.post("/api/admin/toggle-duels")
def toggle_duels(admin_id: int = _Depends(_require_admin), db: _Session = _Depends(_get_db)):
    from models import Config
    row = db.query(Config).filter(Config.key == "duels_enabled").first()
    if row:
        row.value = "false" if row.value == "true" else "true"
    else:
        db.add(Config(key="duels_enabled", value="true"))
    db.commit()
    new_val = db.query(Config).filter(Config.key == "duels_enabled").first()
    return {"duels_enabled": new_val.value == "true" if new_val else False}


@app.post("/api/admin/toggle-compete")
def toggle_compete(admin_id: int = _Depends(_require_admin), db: _Session = _Depends(_get_db)):
    from models import Config
    row = db.query(Config).filter(Config.key == "compete_enabled").first()
    if row:
        row.value = "false" if row.value == "true" else "true"
    else:
        db.add(Config(key="compete_enabled", value="true"))
    db.commit()
    new_val = db.query(Config).filter(Config.key == "compete_enabled").first()
    return {"compete_enabled": new_val.value == "true" if new_val else False}


# ── SEO: sitemap.xml + robots.txt ──────────────────────────────────────────
import time as _seo_time
from fastapi.responses import Response as _RawResponse

_sitemap_cache = None
_sitemap_cache_time = 0
_SITEMAP_TTL = 86400  # 24 hours


@app.get("/sitemap.xml")
def sitemap_xml():
    global _sitemap_cache, _sitemap_cache_time
    if _sitemap_cache and (_seo_time.time() - _sitemap_cache_time) < _SITEMAP_TTL:
        return _RawResponse(content=_sitemap_cache, media_type="application/xml")

    from database import SessionLocal
    from sqlalchemy import text as _st
    db = SessionLocal()
    try:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        urls = []

        # Static pages
        for path, priority in [("/", "1.0"), ("/leaderboard", "0.9"), ("/consensus", "0.8"),
                                ("/activity", "0.7"), ("/discover", "0.7"), ("/compare", "0.6"),
                                ("/how-it-works", "0.5")]:
            urls.append(f"  <url><loc>https://www.eidolum.com{path}</loc><lastmod>{today}</lastmod><priority>{priority}</priority></url>")

        # Forecaster profiles (10+ evaluated)
        rows = db.execute(_st(
            "SELECT id FROM forecasters WHERE COALESCE(total_predictions, 0) >= 10 AND COALESCE(accuracy_score, 0) > 0 ORDER BY total_predictions DESC LIMIT 5000"
        )).fetchall()
        for r in rows:
            urls.append(f"  <url><loc>https://www.eidolum.com/forecaster/{r[0]}</loc><lastmod>{today}</lastmod><priority>0.8</priority></url>")

        # Top tickers
        ticker_rows = db.execute(_st(
            "SELECT DISTINCT ticker FROM predictions WHERE ticker IS NOT NULL ORDER BY ticker LIMIT 2000"
        )).fetchall()
        for r in ticker_rows:
            urls.append(f"  <url><loc>https://www.eidolum.com/asset/{r[0]}</loc><lastmod>{today}</lastmod><priority>0.6</priority></url>")

    except Exception:
        urls = []
    finally:
        db.close()

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(urls) + "\n</urlset>"
    _sitemap_cache = xml
    _sitemap_cache_time = _seo_time.time()
    return _RawResponse(content=xml, media_type="application/xml")


@app.get("/robots.txt")
def robots_txt():
    return _RawResponse(
        content="User-agent: *\nAllow: /\nSitemap: https://www.eidolum.com/sitemap.xml\n",
        media_type="text/plain",
    )


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
            WHERE outcome IN ('hit','near','miss','correct','incorrect')
        """)).first()
        # Sample 3 evaluated predictions with their raw column values
        samples = db.execute(_t("""
            SELECT id, ticker, outcome, actual_return, alpha, sp500_return,
                   prediction_date, evaluation_date
            FROM predictions
            WHERE outcome IN ('hit','near','miss','correct','incorrect')
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
        return {"error": str(e)}
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
        return {"error": str(e)}
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
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


@app.get("/api/admin/scraper-health")
def scraper_health():
    """Health check for all background jobs."""
    from sqlalchemy import text as sql_text
    from admin_panel import scheduler_last_run
    from jobs.benzinga_backfill import get_backfill_status
    from jobs.historical_evaluator import get_eval_status

    db = BgSessionLocal()
    try:
        pending_overdue = db.execute(sql_text(
            "SELECT COUNT(*) FROM predictions WHERE outcome = 'pending' AND evaluation_date IS NOT NULL AND evaluation_date < NOW()"
        )).scalar() or 0
        total_scored = db.execute(sql_text(
            "SELECT COUNT(*) FROM predictions WHERE outcome IN ('hit','near','miss','correct','incorrect')"
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


@app.post("/api/admin/backfill-fmp")
def start_fmp_backfill():
    """Start FMP grades backfill as a background task."""
    import threading
    from jobs.upgrade_scrapers import backfill_fmp_grades
    from database import BgSessionLocal

    def _run():
        db = BgSessionLocal()
        try:
            backfill_fmp_grades(db)
        finally:
            db.close()

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "source": "fmp_grades", "note": "full history"}


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
        return {"error": str(e)}
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
            "SELECT COUNT(*) FROM predictions WHERE outcome IN ('hit','near','miss','correct','incorrect')"
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
                        WHERE outcome IN ('hit','near','miss','correct','incorrect')
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
            WHERE outcome IN ('hit','near','miss','correct','incorrect')
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
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


# /api/debug endpoint REMOVED (2026-03-31) — exposed database info without auth


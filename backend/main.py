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
import logging
from datetime import datetime, timedelta, date
from contextlib import asynccontextmanager

# Install API-key scrubber on httpx/urllib3/root loggers BEFORE any router or
# scraper imports so the very first outbound HTTP request line is already
# protected. FMP /stable/ only accepts ?apikey= query auth, so this is the
# only thing keeping the FMP key out of plaintext logs on the API process.
from log_filter import install_key_scrubber
install_key_scrubber()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from database import engine, bg_engine, Base, SessionLocal, BgSessionLocal
from models import Forecaster, Prediction, Config
from rate_limit import limiter
# Background jobs moved to worker.py (separate Railway service)
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
    import threading

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

        # ── Create processed_logos table ──────────────────────────────
        try:
            with engine.connect() as _pl_c:
                _pl_c.execute(sql_text("""
                    CREATE TABLE IF NOT EXISTS processed_logos (
                        ticker VARCHAR(20) PRIMARY KEY,
                        image_data BYTEA NOT NULL,
                        processed_at TIMESTAMP DEFAULT NOW()
                    )
                """))
                _pl_c.commit()
                print("[Startup] processed_logos table ready")
        except Exception as e:
            print(f"[Startup] processed_logos table error: {e}")

        # ── youtube_channels pruning columns + counter backfill ────────
        # Mirrors the migration in worker.py so the API service can boot
        # the new admin endpoints (list pruned + reactivate) even if the
        # API container starts before the worker. Idempotent.
        try:
            with engine.connect() as _yc_c:
                for _yc_ddl in (
                    "ALTER TABLE youtube_channels ADD COLUMN IF NOT EXISTS "
                    "videos_processed_count INTEGER NOT NULL DEFAULT 0",
                    "ALTER TABLE youtube_channels ADD COLUMN IF NOT EXISTS "
                    "predictions_extracted_count INTEGER NOT NULL DEFAULT 0",
                    "ALTER TABLE youtube_channels ADD COLUMN IF NOT EXISTS "
                    "deactivated_at TIMESTAMP",
                    "ALTER TABLE youtube_channels ADD COLUMN IF NOT EXISTS "
                    "deactivation_reason VARCHAR(50)",
                ):
                    _yc_c.execute(sql_text(_yc_ddl))
                # Counter backfill (only seeds rows still at 0)
                _yc_c.execute(sql_text("""
                    UPDATE youtube_channels c
                    SET videos_processed_count = COALESCE((
                        SELECT COUNT(*) FROM youtube_videos v
                        WHERE v.channel_name = c.channel_name
                          AND v.transcript_status IN ('ok_inserted', 'ok_no_predictions')
                    ), 0)
                    WHERE videos_processed_count = 0
                """))
                _yc_c.execute(sql_text("""
                    UPDATE youtube_channels c
                    SET predictions_extracted_count = COALESCE((
                        SELECT COUNT(*) FROM youtube_videos v
                        WHERE v.channel_name = c.channel_name
                          AND v.predictions_extracted > 0
                    ), 0)
                    WHERE predictions_extracted_count = 0
                """))
                _yc_c.commit()
                print("[Startup] youtube_channels pruning columns + backfill ready")
        except Exception as _yce:
            print(f"[Startup] youtube_channels pruning migration error: {_yce}")

        # ── youtube_channel_meta (admin-facing metadata, FK'd to forecasters) ──
        # Backs the /admin/youtube-channels admin page. Mirrors the shape of
        # tracked_x_accounts so the YouTube admin page is symmetric with the
        # X one. Idempotent: CREATE TABLE IF NOT EXISTS + INSERT ... ON
        # CONFLICT DO NOTHING so it's safe to re-run on every boot.
        try:
            with engine.connect() as _ym_c:
                _ym_c.execute(sql_text("""
                    CREATE TABLE IF NOT EXISTS youtube_channel_meta (
                        id SERIAL PRIMARY KEY,
                        forecaster_id INTEGER NOT NULL REFERENCES forecasters(id) ON DELETE CASCADE,
                        channel_id VARCHAR(30) NOT NULL,
                        tier INTEGER NOT NULL DEFAULT 4,
                        notes TEXT,
                        active BOOLEAN NOT NULL DEFAULT TRUE,
                        added_date TIMESTAMP NOT NULL DEFAULT NOW(),
                        last_scraped_at TIMESTAMP,
                        last_scrape_videos_found INTEGER DEFAULT 0,
                        last_scrape_predictions_extracted INTEGER DEFAULT 0,
                        total_videos_scraped INTEGER DEFAULT 0,
                        total_predictions_extracted INTEGER DEFAULT 0,
                        videos_processed_count INTEGER DEFAULT 0,
                        predictions_extracted_count INTEGER DEFAULT 0,
                        deactivated_at TIMESTAMP,
                        deactivation_reason VARCHAR(50),
                        CONSTRAINT uq_yt_meta_forecaster UNIQUE (forecaster_id),
                        CONSTRAINT uq_yt_meta_channel_id UNIQUE (channel_id),
                        CONSTRAINT ck_yt_meta_tier CHECK (tier BETWEEN 1 AND 4)
                    )
                """))
                _ym_c.execute(sql_text(
                    "CREATE INDEX IF NOT EXISTS idx_yt_meta_active "
                    "ON youtube_channel_meta(active)"
                ))
                _ym_c.execute(sql_text(
                    "CREATE INDEX IF NOT EXISTS idx_yt_meta_tier "
                    "ON youtube_channel_meta(tier)"
                ))
                # Backfill: every forecaster with platform='youtube' and a
                # resolved channel_id gets a default meta row. Forecasters
                # without a channel_id are skipped — they'll be added when
                # the scraper resolves their channel_id on the next run.
                _ym_c.execute(sql_text("""
                    INSERT INTO youtube_channel_meta
                        (forecaster_id, channel_id, tier, active, added_date)
                    SELECT f.id, f.channel_id, 4, TRUE, NOW()
                    FROM forecasters f
                    WHERE f.platform = 'youtube'
                      AND f.channel_id IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM youtube_channel_meta m
                          WHERE m.forecaster_id = f.id
                      )
                """))
                _ym_c.commit()
                print("[Startup] youtube_channel_meta table + backfill ready")
        except Exception as _yme:
            print(f"[Startup] youtube_channel_meta migration error: {_yme}")

        # ── sector_etf_aliases (sector → ETF mapping for YouTube sector calls)
        # Seeded with the canonical mappings below. Admin can add more
        # aliases via /admin/sector-aliases without a deploy. Idempotent:
        # ON CONFLICT (alias) DO NOTHING.
        try:
            with engine.connect() as _sa_c:
                _sa_c.execute(sql_text("""
                    CREATE TABLE IF NOT EXISTS sector_etf_aliases (
                        id SERIAL PRIMARY KEY,
                        alias VARCHAR(100) NOT NULL UNIQUE,
                        canonical_sector VARCHAR(50) NOT NULL,
                        etf_ticker VARCHAR(10) NOT NULL,
                        notes TEXT
                    )
                """))
                _sa_c.execute(sql_text(
                    "CREATE INDEX IF NOT EXISTS idx_sector_aliases_canonical "
                    "ON sector_etf_aliases(canonical_sector)"
                ))
                _seed_aliases = [
                    ('technology', 'technology', 'XLK', 'Tech sector ETF'),
                    ('tech', 'technology', 'XLK', 'Tech sector alias'),
                    ('big tech', 'technology', 'QQQ', 'Big tech via Nasdaq-100'),
                    ('semiconductors', 'semiconductors', 'SOXX', 'Semi sector ETF'),
                    ('semis', 'semiconductors', 'SOXX', 'Semi alias'),
                    ('chip stocks', 'semiconductors', 'SOXX', 'Semi alias'),
                    ('chips', 'semiconductors', 'SOXX', 'Semi alias'),
                    ('energy', 'energy', 'XLE', 'Energy sector ETF'),
                    ('oil', 'energy', 'XLE', 'Oil alias for energy'),
                    ('oil stocks', 'energy', 'XLE', 'Energy alias'),
                    ('financials', 'financials', 'XLF', 'Financial sector ETF'),
                    ('banks', 'financials', 'KBE', 'Bank sector ETF'),
                    ('big banks', 'financials', 'KBE', 'Bank alias'),
                    ('healthcare', 'healthcare', 'XLV', 'Healthcare sector ETF'),
                    ('health care', 'healthcare', 'XLV', 'Healthcare alias'),
                    ('biotech', 'biotech', 'XBI', 'Biotech ETF'),
                    ('biotechnology', 'biotech', 'XBI', 'Biotech alias'),
                    ('pharma', 'pharma', 'IHE', 'Pharma ETF'),
                    ('pharmaceuticals', 'pharma', 'IHE', 'Pharma alias'),
                    ('industrials', 'industrials', 'XLI', 'Industrial sector ETF'),
                    ('consumer discretionary', 'consumer_discretionary', 'XLY', 'Consumer disc ETF'),
                    ('retail', 'consumer_discretionary', 'XRT', 'Retail ETF'),
                    ('consumer staples', 'consumer_staples', 'XLP', 'Consumer staples ETF'),
                    ('utilities', 'utilities', 'XLU', 'Utility sector ETF'),
                    ('real estate', 'real_estate', 'XLRE', 'REIT sector ETF'),
                    ('reits', 'real_estate', 'XLRE', 'REIT alias'),
                    ('communication services', 'communications', 'XLC', 'Comm services ETF'),
                    ('telecom', 'communications', 'XLC', 'Telecom alias'),
                    ('materials', 'materials', 'XLB', 'Materials sector ETF'),
                    ('gold', 'gold', 'GLD', 'Gold ETF'),
                    ('gold miners', 'gold_miners', 'GDX', 'Gold miners ETF'),
                    ('silver', 'silver', 'SLV', 'Silver ETF'),
                    ('crypto', 'crypto', 'BITO', 'Crypto futures ETF, maps to BTC via BITO'),
                    ('bitcoin', 'bitcoin', 'BITO', 'BTC via BITO ETF'),
                    ('bonds', 'bonds', 'TLT', '20+ year treasury bonds'),
                    ('long bonds', 'bonds', 'TLT', 'Bonds alias'),
                    ('short bonds', 'short_bonds', 'SHY', '1-3 year treasuries'),
                    ('emerging markets', 'emerging_markets', 'EEM', 'EM ETF'),
                    ('china', 'china', 'FXI', 'China large cap ETF'),
                    ('chinese stocks', 'china', 'FXI', 'China alias'),
                    ('europe', 'europe', 'VGK', 'European stocks ETF'),
                    ('small caps', 'small_caps', 'IWM', 'Russell 2000'),
                    ('russell 2000', 'small_caps', 'IWM', 'Small caps index'),
                    ('large caps', 'large_caps', 'SPY', 'S&P 500 proxy'),
                    ('s&p 500', 'sp500', 'SPY', 'S&P 500 index'),
                    ('sp500', 'sp500', 'SPY', 'S&P 500 alias'),
                    ('nasdaq', 'nasdaq', 'QQQ', 'Nasdaq-100 proxy'),
                    # ── Expanded aliases (sub-sectors, thematic, intl, crypto, factors) ──
                    # Broad market (expanded)
                    ('the market', 'sp500', 'SPY', 'Generic market mention'),
                    ('stocks', 'sp500', 'SPY', 'Generic stocks mention'),
                    ('equities', 'sp500', 'SPY', 'Formal equities term'),
                    ('us stocks', 'sp500', 'SPY', 'US equity mention'),
                    ('us equities', 'sp500', 'SPY', 'US equity mention'),
                    ('the spy', 'sp500', 'SPY', 'Trader shorthand for S&P 500'),
                    ('s and p', 'sp500', 'SPY', 'Verbal S&P alias'),
                    ('s&p', 'sp500', 'SPY', 'S&P abbreviation'),
                    ('standard and poors', 'sp500', 'SPY', 'Full name'),
                    ('dow', 'dow', 'DIA', 'Dow Jones Industrial Average'),
                    ('dow jones', 'dow', 'DIA', 'Dow alias'),
                    ('industrial average', 'dow', 'DIA', 'Dow alias'),
                    ('the dow', 'dow', 'DIA', 'Dow alias'),
                    ('qqq', 'nasdaq', 'QQQ', 'Nasdaq 100 ETF ticker'),
                    ('nasdaq 100', 'nasdaq', 'QQQ', 'Nasdaq 100'),
                    ('tech heavy', 'nasdaq', 'QQQ', 'Nasdaq as tech-heavy proxy'),
                    ('total market', 'total_market', 'VTI', 'Vanguard total market'),
                    ('all us stocks', 'total_market', 'VTI', 'Total market proxy'),
                    ('mid caps', 'mid_caps', 'IJH', 'Mid-cap index'),
                    ('mid cap stocks', 'mid_caps', 'IJH', 'Mid-cap alias'),
                    ('micro caps', 'micro_caps', 'IWC', 'Micro-cap ETF'),
                    # Technology sub-sectors
                    ('cloud computing', 'cloud', 'SKYY', 'Cloud computing ETF'),
                    ('cloud stocks', 'cloud', 'SKYY', 'Cloud alias'),
                    ('saas', 'saas', 'CLOU', 'SaaS cloud ETF'),
                    ('software', 'software', 'IGV', 'Software ETF'),
                    ('software stocks', 'software', 'IGV', 'Software alias'),
                    ('cybersecurity', 'cybersecurity', 'HACK', 'Cybersecurity ETF'),
                    ('cyber security', 'cybersecurity', 'HACK', 'Cybersecurity alias'),
                    ('cyber', 'cybersecurity', 'HACK', 'Cybersecurity shorthand'),
                    ('ai stocks', 'ai', 'BOTZ', 'AI and robotics ETF'),
                    ('artificial intelligence', 'ai', 'BOTZ', 'AI alias'),
                    ('ai', 'ai', 'BOTZ', 'AI shorthand'),
                    ('robotics', 'robotics', 'ROBO', 'Robotics ETF'),
                    ('robots', 'robotics', 'ROBO', 'Robotics alias'),
                    ('fintech', 'fintech', 'FINX', 'Fintech ETF'),
                    ('fin tech', 'fintech', 'FINX', 'Fintech alias'),
                    ('payments', 'fintech', 'IPAY', 'Payments ETF'),
                    ('internet', 'internet', 'FDN', 'Internet ETF'),
                    ('internet stocks', 'internet', 'FDN', 'Internet alias'),
                    ('social media', 'social_media', 'SOCL', 'Social media ETF'),
                    ('cloud infrastructure', 'cloud', 'WCLD', 'Pure cloud software ETF'),
                    ('data centers', 'data_centers', 'SRVR', 'Data center REIT ETF'),
                    ('5g', '5g', 'FIVG', '5G network ETF'),
                    ('ev', 'ev', 'DRIV', 'Electric vehicle ETF'),
                    ('electric vehicles', 'ev', 'DRIV', 'EV alias'),
                    ('ev stocks', 'ev', 'DRIV', 'EV alias'),
                    ('autonomous vehicles', 'autonomous', 'DRIV', 'Autonomous vehicles proxy'),
                    ('self driving', 'autonomous', 'DRIV', 'Self driving alias'),
                    ('metaverse', 'metaverse', 'META', 'Meta as metaverse proxy — weak mapping, prefer ticker'),
                    ('gaming', 'gaming', 'ESPO', 'Video games ETF'),
                    ('video games', 'gaming', 'ESPO', 'Gaming alias'),
                    ('esports', 'gaming', 'ESPO', 'Esports ETF'),
                    # Semiconductor sub-sectors
                    ('chip makers', 'semiconductors', 'SOXX', 'Semi alias'),
                    ('semiconductor stocks', 'semiconductors', 'SOXX', 'Semi full name'),
                    ('fabless', 'semiconductors', 'SOXX', 'Fabless chip design'),
                    ('foundries', 'semiconductors', 'SOXX', 'Chip foundries'),
                    ('memory chips', 'semiconductors', 'SOXX', 'Memory semi sub-sector'),
                    ('analog chips', 'semiconductors', 'SOXX', 'Analog semi sub-sector'),
                    ('sox', 'semiconductors', 'SOXX', 'SOX index alias'),
                    # Financials expanded
                    ('regional banks', 'regional_banks', 'KRE', 'Regional banks ETF'),
                    ('small banks', 'regional_banks', 'KRE', 'Regional banks alias'),
                    ('insurance', 'insurance', 'KIE', 'Insurance ETF'),
                    ('insurance stocks', 'insurance', 'KIE', 'Insurance alias'),
                    ('asset managers', 'asset_managers', 'XLF', 'Asset managers in financial sector'),
                    ('brokers', 'brokers', 'IAI', 'Broker dealers ETF'),
                    ('broker dealers', 'brokers', 'IAI', 'Brokers alias'),
                    ('capital markets', 'capital_markets', 'KCE', 'Capital markets ETF'),
                    ('private equity', 'private_equity', 'PSP', 'Listed private equity ETF'),
                    ('pe', 'private_equity', 'PSP', 'PE shorthand'),
                    # Healthcare sub-sectors
                    ('medical devices', 'medical_devices', 'IHI', 'Medical devices ETF'),
                    ('med tech', 'medical_devices', 'IHI', 'Medtech alias'),
                    ('medtech', 'medical_devices', 'IHI', 'Medtech alias'),
                    ('genomics', 'genomics', 'ARKG', 'Genomics ETF'),
                    ('gene therapy', 'genomics', 'ARKG', 'Gene therapy'),
                    ('cannabis', 'cannabis', 'MSOS', 'US cannabis ETF'),
                    ('weed stocks', 'cannabis', 'MSOS', 'Cannabis alias'),
                    ('marijuana', 'cannabis', 'MSOS', 'Cannabis alias'),
                    ('hospitals', 'hospitals', 'IHF', 'Healthcare providers'),
                    # Energy sub-sectors
                    ('renewables', 'renewables', 'ICLN', 'Clean energy ETF'),
                    ('renewable energy', 'renewables', 'ICLN', 'Renewables alias'),
                    ('clean energy', 'renewables', 'ICLN', 'Clean energy alias'),
                    ('solar', 'solar', 'TAN', 'Solar ETF'),
                    ('solar stocks', 'solar', 'TAN', 'Solar alias'),
                    ('wind', 'wind', 'FAN', 'Wind energy ETF'),
                    ('wind energy', 'wind', 'FAN', 'Wind alias'),
                    ('uranium', 'uranium', 'URA', 'Uranium ETF'),
                    ('nuclear', 'nuclear', 'URA', 'Nuclear via uranium'),
                    ('nuclear energy', 'nuclear', 'URA', 'Nuclear alias'),
                    ('natural gas', 'natural_gas', 'UNG', 'Natural gas ETF'),
                    ('gas stocks', 'natural_gas', 'XOP', 'Oil & gas E&P as gas proxy'),
                    ('oil and gas', 'energy', 'XLE', 'Oil & gas'),
                    ('crude', 'oil', 'USO', 'Crude oil ETF'),
                    ('crude oil', 'oil', 'USO', 'Crude oil'),
                    ('brent', 'oil', 'BNO', 'Brent crude ETF'),
                    ('wti', 'oil', 'USO', 'WTI crude proxy'),
                    ('exploration and production', 'energy_e_and_p', 'XOP', 'E&P ETF'),
                    ('pipelines', 'pipelines', 'AMLP', 'MLP pipeline ETF'),
                    ('mlps', 'pipelines', 'AMLP', 'MLP alias'),
                    ('refiners', 'refiners', 'CRAK', 'Oil refiners ETF'),
                    # Materials and commodities
                    ('copper', 'copper', 'COPX', 'Copper miners ETF'),
                    ('copper miners', 'copper', 'COPX', 'Copper miners'),
                    ('lithium', 'lithium', 'LIT', 'Lithium and battery ETF'),
                    ('battery stocks', 'lithium', 'LIT', 'Battery/lithium alias'),
                    ('steel', 'steel', 'SLX', 'Steel ETF'),
                    ('aluminum', 'aluminum', 'XME', 'Metals & mining as aluminum proxy'),
                    ('mining', 'mining', 'XME', 'Metals & mining ETF'),
                    ('miners', 'mining', 'XME', 'Miners alias'),
                    ('metals', 'materials', 'XLB', 'Metals/materials'),
                    ('commodities', 'commodities', 'DBC', 'Broad commodities ETF'),
                    ('broad commodities', 'commodities', 'DBC', 'Commodities alias'),
                    ('agriculture', 'agriculture', 'DBA', 'Agriculture commodities ETF'),
                    ('ag stocks', 'agriculture', 'DBA', 'Agriculture alias'),
                    ('farm', 'agriculture', 'DBA', 'Farming alias'),
                    ('timber', 'timber', 'WOOD', 'Timber ETF'),
                    ('water', 'water', 'PHO', 'Water ETF'),
                    # Consumer and retail
                    ('e commerce', 'ecommerce', 'XRT', 'Retail ETF as e-commerce proxy'),
                    ('ecommerce', 'ecommerce', 'XRT', 'Ecommerce alias'),
                    ('online retail', 'ecommerce', 'XRT', 'Online retail'),
                    ('luxury', 'luxury', 'XLY', 'Luxury via consumer discretionary'),
                    ('travel', 'travel', 'AWAY', 'Travel ETF'),
                    ('travel stocks', 'travel', 'AWAY', 'Travel alias'),
                    ('airlines', 'airlines', 'JETS', 'Airlines ETF'),
                    ('cruise lines', 'travel', 'AWAY', 'Cruise via travel'),
                    ('hotels', 'hotels', 'AWAY', 'Hotels via travel'),
                    ('restaurants', 'restaurants', 'EATZ', 'Restaurant ETF'),
                    ('food', 'food', 'PBJ', 'Food & beverage ETF'),
                    ('beverages', 'food', 'PBJ', 'Beverages via food'),
                    ('homebuilders', 'homebuilders', 'XHB', 'Homebuilders ETF'),
                    ('home builders', 'homebuilders', 'XHB', 'Homebuilders alias'),
                    ('housing', 'homebuilders', 'XHB', 'Housing proxy'),
                    ('housing stocks', 'homebuilders', 'XHB', 'Housing alias'),
                    # Real estate sub-sectors
                    ('commercial real estate', 'real_estate', 'VNQ', 'Commercial REITs'),
                    ('cre', 'real_estate', 'VNQ', 'CRE shorthand'),
                    ('residential reits', 'residential_reits', 'REZ', 'Residential REITs ETF'),
                    ('mortgage reits', 'mortgage_reits', 'REM', 'Mortgage REITs ETF'),
                    ('m reits', 'mortgage_reits', 'REM', 'mREITs alias'),
                    # Industrials and defense
                    ('defense', 'defense', 'ITA', 'Aerospace & defense ETF'),
                    ('defense stocks', 'defense', 'ITA', 'Defense alias'),
                    ('aerospace', 'defense', 'ITA', 'Aerospace via defense'),
                    ('weapons', 'defense', 'ITA', 'Defense alias'),
                    ('transports', 'transports', 'IYT', 'Transportation ETF'),
                    ('transportation', 'transports', 'IYT', 'Transports alias'),
                    ('trucking', 'transports', 'IYT', 'Trucking via transports'),
                    ('shipping', 'shipping', 'BOAT', 'Shipping ETF'),
                    ('rails', 'rails', 'IYT', 'Rails via transports'),
                    ('railroads', 'rails', 'IYT', 'Railroads alias'),
                    # Thematic
                    ('esg', 'esg', 'ESGU', 'ESG ETF'),
                    ('sustainable', 'esg', 'ESGU', 'ESG alias'),
                    ('infrastructure', 'infrastructure', 'PAVE', 'US infrastructure ETF'),
                    ('infrastructure stocks', 'infrastructure', 'PAVE', 'Infrastructure alias'),
                    ('space', 'space', 'UFO', 'Space ETF'),
                    ('space stocks', 'space', 'UFO', 'Space alias'),
                    ('space exploration', 'space', 'UFO', 'Space alias'),
                    ('quantum computing', 'quantum', 'QTUM', 'Quantum computing ETF'),
                    ('quantum', 'quantum', 'QTUM', 'Quantum alias'),
                    ('blockchain', 'blockchain', 'BLOK', 'Blockchain ETF'),
                    ('web3', 'blockchain', 'BLOK', 'Web3 via blockchain'),
                    ('disruptive', 'disruptive', 'ARKK', 'Disruptive innovation ETF'),
                    ('innovation', 'disruptive', 'ARKK', 'Innovation alias'),
                    ('cathie wood', 'disruptive', 'ARKK', 'ARKK nickname'),
                    ('ark', 'disruptive', 'ARKK', 'ARK shorthand'),
                    # International and country-specific
                    ('international stocks', 'international', 'VEA', 'Developed intl ETF'),
                    ('developed markets', 'international', 'VEA', 'Developed intl alias'),
                    ('japan', 'japan', 'EWJ', 'Japan ETF'),
                    ('japanese stocks', 'japan', 'EWJ', 'Japan alias'),
                    ('india', 'india', 'INDA', 'India ETF'),
                    ('indian stocks', 'india', 'INDA', 'India alias'),
                    ('brazil', 'brazil', 'EWZ', 'Brazil ETF'),
                    ('mexico', 'mexico', 'EWW', 'Mexico ETF'),
                    ('taiwan', 'taiwan', 'EWT', 'Taiwan ETF'),
                    ('south korea', 'korea', 'EWY', 'South Korea ETF'),
                    ('korea', 'korea', 'EWY', 'Korea alias'),
                    ('vietnam', 'vietnam', 'VNM', 'Vietnam ETF'),
                    ('indonesia', 'indonesia', 'EIDO', 'Indonesia ETF'),
                    ('germany', 'germany', 'EWG', 'Germany ETF'),
                    ('uk', 'uk', 'EWU', 'UK ETF'),
                    ('united kingdom', 'uk', 'EWU', 'UK alias'),
                    ('france', 'france', 'EWQ', 'France ETF'),
                    ('canada', 'canada', 'EWC', 'Canada ETF'),
                    ('australia', 'australia', 'EWA', 'Australia ETF'),
                    ('frontier markets', 'frontier', 'FM', 'Frontier markets ETF'),
                    ('em', 'emerging_markets', 'EEM', 'EM shorthand'),
                    ('emerging', 'emerging_markets', 'EEM', 'Emerging alias'),
                    # Crypto and digital assets
                    ('ethereum', 'ethereum', 'ETHE', 'Grayscale Ethereum trust, closest ETH proxy'),
                    ('eth', 'ethereum', 'ETHE', 'ETH alias'),
                    ('btc', 'bitcoin', 'IBIT', 'Spot Bitcoin ETF (iShares)'),
                    ('bitcoin etf', 'bitcoin', 'IBIT', 'Spot Bitcoin ETF'),
                    ('crypto stocks', 'crypto_stocks', 'BITQ', 'Crypto-exposed equities ETF'),
                    ('blockchain stocks', 'blockchain', 'BLOK', 'Blockchain alias'),
                    ('miners crypto', 'crypto_miners', 'WGMI', 'Crypto miners ETF'),
                    ('bitcoin miners', 'crypto_miners', 'WGMI', 'BTC miners alias'),
                    # Bonds and rates
                    ('treasuries', 'bonds', 'TLT', 'Long treasuries'),
                    ('treasury bonds', 'bonds', 'TLT', 'Treasuries'),
                    ('long term bonds', 'bonds', 'TLT', 'Long bonds'),
                    ('20 year bonds', 'bonds', 'TLT', '20-year treasury ETF'),
                    ('10 year', 'tenyr', 'IEF', '10-year treasury ETF'),
                    ('10 year treasury', 'tenyr', 'IEF', '10-year alias'),
                    ('short term bonds', 'short_bonds', 'SHY', 'Short treasuries'),
                    ('tbills', 'tbills', 'BIL', 'T-bills ETF'),
                    ('t bills', 'tbills', 'BIL', 'T-bills alias'),
                    ('corporate bonds', 'corporate_bonds', 'LQD', 'Investment grade corporate'),
                    ('investment grade', 'corporate_bonds', 'LQD', 'IG alias'),
                    ('high yield', 'high_yield', 'HYG', 'Junk bonds ETF'),
                    ('junk bonds', 'high_yield', 'HYG', 'Junk alias'),
                    ('hyg', 'high_yield', 'HYG', 'HYG ticker'),
                    ('muni bonds', 'munis', 'MUB', 'Municipal bonds ETF'),
                    ('municipals', 'munis', 'MUB', 'Munis alias'),
                    ('tips', 'tips', 'TIP', 'Treasury inflation protected'),
                    ('inflation protected', 'tips', 'TIP', 'TIPS alias'),
                    # Volatility and hedges
                    ('vix', 'volatility', 'VXX', 'VIX futures ETF'),
                    ('volatility', 'volatility', 'VXX', 'Volatility alias'),
                    ('fear index', 'volatility', 'VXX', 'VIX alias'),
                    ('hedges', 'volatility', 'VXX', 'Generic hedge'),
                    # Dividend and factor
                    ('dividend stocks', 'dividends', 'SCHD', 'Dividend ETF'),
                    ('dividends', 'dividends', 'SCHD', 'Dividends alias'),
                    ('dividend growth', 'dividend_growth', 'SCHD', 'Dividend growth alias'),
                    ('high dividend', 'high_dividend', 'VYM', 'High dividend ETF'),
                    ('yield stocks', 'high_dividend', 'VYM', 'Yield alias'),
                    ('value', 'value', 'IVE', 'Value ETF'),
                    ('value stocks', 'value', 'IVE', 'Value alias'),
                    ('growth', 'growth', 'IVW', 'Growth ETF'),
                    ('growth stocks', 'growth', 'IVW', 'Growth alias'),
                    ('momentum', 'momentum', 'MTUM', 'Momentum factor ETF'),
                    ('quality', 'quality', 'QUAL', 'Quality factor ETF'),
                    ('low vol', 'low_vol', 'USMV', 'Low volatility ETF'),
                    ('low volatility', 'low_vol', 'USMV', 'Low vol alias'),
                    # ── v2 expansion: broader coverage of sub-sectors, countries,
                    # commodities, factors, crypto, bonds, volatility. Every alias
                    # is lowercase; every etf_ticker is a real US-listed ETF.
                    # Overlaps with earlier rows hit ON CONFLICT DO NOTHING and
                    # preserve the original mapping — intended behavior.
                    # Broad US market indices
                    ('stock market', 'sp500', 'SPY', 'Generic'),
                    ('american stocks', 'sp500', 'SPY', 'US colloquial'),
                    ('spx', 'sp500', 'SPY', 'S&P index abbrev'),
                    ('sp 500', 'sp500', 'SPY', 'Alt spelling'),
                    ('voo', 'sp500', 'SPY', 'Vanguard S&P alias'),
                    ('ivv', 'sp500', 'SPY', 'iShares S&P alias'),
                    ('blue chips', 'dow', 'DIA', 'Blue chip stocks'),
                    ('blue chip stocks', 'dow', 'DIA', 'Blue chip alias'),
                    ('triple q', 'nasdaq', 'QQQ', 'QQQ verbal'),
                    ('the nasdaq', 'nasdaq', 'QQQ', 'Nasdaq alias'),
                    ('tech index', 'nasdaq', 'QQQ', 'Tech index'),
                    ('whole market', 'total_market', 'VTI', 'Total market'),
                    ('vti', 'total_market', 'VTI', 'VTI ticker'),
                    ('russell two thousand', 'small_caps', 'IWM', 'Russell verbal'),
                    ('iwm', 'small_caps', 'IWM', 'IWM ticker'),
                    ('small cap', 'small_caps', 'IWM', 'Small cap'),
                    ('small cap stocks', 'small_caps', 'IWM', 'Small caps'),
                    ('mid cap', 'mid_caps', 'IJH', 'Mid-cap'),
                    ('ijh', 'mid_caps', 'IJH', 'IJH ticker'),
                    ('micro cap', 'micro_caps', 'IWC', 'Micro-cap'),
                    ('micro cap stocks', 'micro_caps', 'IWC', 'Micro caps'),
                    ('mega caps', 'mega_caps', 'MGC', 'Mega-cap'),
                    ('mega cap stocks', 'mega_caps', 'MGC', 'Mega caps'),
                    ('large cap stocks', 'large_caps', 'SPY', 'Large caps'),
                    # Technology broad + mag 7
                    ('tech sector', 'technology', 'XLK', 'Tech sector'),
                    ('tech stocks', 'technology', 'XLK', 'Tech stocks'),
                    ('technology sector', 'technology', 'XLK', 'Tech formal'),
                    ('xlk', 'technology', 'XLK', 'XLK ticker'),
                    ('faang', 'big_tech', 'QQQ', 'FAANG'),
                    ('faang stocks', 'big_tech', 'QQQ', 'FAANG'),
                    ('mag 7', 'big_tech', 'QQQ', 'Magnificent 7'),
                    ('mag seven', 'big_tech', 'QQQ', 'Mag 7 alt'),
                    ('magnificent 7', 'big_tech', 'QQQ', 'Mag 7 full'),
                    ('magnificent seven', 'big_tech', 'QQQ', 'Mag 7 formal'),
                    # Technology sub-sectors
                    ('cloud', 'cloud', 'SKYY', 'Cloud'),
                    ('the cloud', 'cloud', 'SKYY', 'Cloud colloquial'),
                    ('skyy', 'cloud', 'SKYY', 'SKYY ticker'),
                    ('saas stocks', 'saas', 'CLOU', 'SaaS alias'),
                    ('software as a service', 'saas', 'CLOU', 'SaaS formal'),
                    ('clou', 'saas', 'CLOU', 'CLOU ticker'),
                    ('enterprise software', 'software', 'IGV', 'Enterprise SW'),
                    ('igv', 'software', 'IGV', 'IGV ticker'),
                    ('cyber stocks', 'cybersecurity', 'HACK', 'Cyber'),
                    ('security stocks', 'cybersecurity', 'HACK', 'Security'),
                    ('infosec', 'cybersecurity', 'HACK', 'Infosec'),
                    ('hack', 'cybersecurity', 'HACK', 'HACK ticker'),
                    ('cibr', 'cybersecurity', 'CIBR', 'CIBR ticker'),
                    ('ai theme', 'ai', 'BOTZ', 'AI theme'),
                    ('ai play', 'ai', 'BOTZ', 'AI colloquial'),
                    ('ai boom', 'ai', 'BOTZ', 'AI boom'),
                    ('ai revolution', 'ai', 'BOTZ', 'AI revolution'),
                    ('machine learning', 'ai', 'BOTZ', 'ML'),
                    ('botz', 'ai', 'BOTZ', 'BOTZ ticker'),
                    ('robotics stocks', 'robotics', 'ROBO', 'Robotics'),
                    ('robo', 'robotics', 'ROBO', 'ROBO ticker'),
                    ('fintech stocks', 'fintech', 'FINX', 'Fintech'),
                    ('finx', 'fintech', 'FINX', 'FINX ticker'),
                    ('payment stocks', 'payments', 'IPAY', 'Payments'),
                    ('digital payments', 'payments', 'IPAY', 'Digital payments'),
                    ('ipay', 'payments', 'IPAY', 'IPAY ticker'),
                    ('web stocks', 'internet', 'FDN', 'Web stocks'),
                    ('fdn', 'internet', 'FDN', 'FDN ticker'),
                    ('social media stocks', 'social_media', 'SOCL', 'Social media'),
                    ('socl', 'social_media', 'SOCL', 'SOCL ticker'),
                    ('data center stocks', 'data_centers', 'SRVR', 'Data centers'),
                    ('srvr', 'data_centers', 'SRVR', 'SRVR ticker'),
                    ('five g', '5g', 'FIVG', '5G verbal'),
                    ('5g stocks', '5g', 'FIVG', '5G stocks'),
                    ('fivg', '5g', 'FIVG', 'FIVG ticker'),
                    ('evs', 'ev', 'DRIV', 'EVs'),
                    ('electric vehicle stocks', 'ev', 'DRIV', 'EV stocks'),
                    ('autonomous driving', 'autonomous', 'DRIV', 'Autonomous'),
                    ('self driving cars', 'autonomous', 'DRIV', 'Self driving cars'),
                    ('driv', 'ev', 'DRIV', 'DRIV ticker'),
                    ('video game stocks', 'gaming', 'ESPO', 'Gaming'),
                    ('gaming stocks', 'gaming', 'ESPO', 'Gaming'),
                    ('espo', 'gaming', 'ESPO', 'ESPO ticker'),
                    # Semiconductors
                    ('chipmakers', 'semiconductors', 'SOXX', 'Chipmakers'),
                    ('chip sector', 'semiconductors', 'SOXX', 'Chip sector'),
                    ('semi sector', 'semiconductors', 'SOXX', 'Semi sector'),
                    ('soxx', 'semiconductors', 'SOXX', 'SOXX ticker'),
                    ('smh', 'semiconductors', 'SMH', 'VanEck semi ETF'),
                    ('chip foundries', 'semiconductors', 'SOXX', 'Foundries'),
                    ('gpu stocks', 'semiconductors', 'SOXX', 'GPU stocks'),
                    # Financials
                    ('financial sector', 'financials', 'XLF', 'Financials'),
                    ('financial stocks', 'financials', 'XLF', 'Financial stocks'),
                    ('xlf', 'financials', 'XLF', 'XLF ticker'),
                    ('bank stocks', 'banks', 'KBE', 'Bank stocks'),
                    ('banking', 'banks', 'KBE', 'Banking'),
                    ('banking sector', 'banks', 'KBE', 'Banking sector'),
                    ('money center banks', 'banks', 'KBE', 'Money center banks'),
                    ('kbe', 'banks', 'KBE', 'KBE ticker'),
                    ('kbwb', 'banks', 'KBWB', 'KBW bank ETF'),
                    ('community banks', 'regional_banks', 'KRE', 'Community banks'),
                    ('regional bank stocks', 'regional_banks', 'KRE', 'Regional bank stocks'),
                    ('kre', 'regional_banks', 'KRE', 'KRE ticker'),
                    ('insurers', 'insurance', 'KIE', 'Insurers'),
                    ('insurance sector', 'insurance', 'KIE', 'Insurance sector'),
                    ('kie', 'insurance', 'KIE', 'KIE ticker'),
                    ('broker stocks', 'brokers', 'IAI', 'Broker stocks'),
                    ('iai', 'brokers', 'IAI', 'IAI ticker'),
                    ('kce', 'capital_markets', 'KCE', 'KCE ticker'),
                    ('pe firms', 'private_equity', 'PSP', 'PE firms'),
                    ('psp', 'private_equity', 'PSP', 'PSP ticker'),
                    # Healthcare
                    ('healthcare sector', 'healthcare', 'XLV', 'Healthcare'),
                    ('healthcare stocks', 'healthcare', 'XLV', 'Healthcare stocks'),
                    ('health stocks', 'healthcare', 'XLV', 'Health stocks'),
                    ('xlv', 'healthcare', 'XLV', 'XLV ticker'),
                    ('biotech stocks', 'biotech', 'XBI', 'Biotech stocks'),
                    ('biotech sector', 'biotech', 'XBI', 'Biotech sector'),
                    ('xbi', 'biotech', 'XBI', 'XBI ticker'),
                    ('ibb', 'biotech', 'IBB', 'IBB alt biotech'),
                    ('drug stocks', 'pharma', 'IHE', 'Drug stocks'),
                    ('pharma stocks', 'pharma', 'IHE', 'Pharma stocks'),
                    ('big pharma', 'pharma', 'IHE', 'Big pharma'),
                    ('ihe', 'pharma', 'IHE', 'IHE ticker'),
                    ('medical device stocks', 'medical_devices', 'IHI', 'Med device stocks'),
                    ('ihi', 'medical_devices', 'IHI', 'IHI ticker'),
                    ('crispr stocks', 'genomics', 'ARKG', 'CRISPR stocks'),
                    ('arkg', 'genomics', 'ARKG', 'ARKG ticker'),
                    ('weed', 'cannabis', 'MSOS', 'Weed'),
                    ('marijuana stocks', 'cannabis', 'MSOS', 'Marijuana stocks'),
                    ('pot stocks', 'cannabis', 'MSOS', 'Pot stocks'),
                    ('msos', 'cannabis', 'MSOS', 'MSOS ticker'),
                    ('hospital stocks', 'hospitals', 'IHF', 'Hospital stocks'),
                    ('health insurers', 'hospitals', 'IHF', 'Health insurers'),
                    ('managed care', 'hospitals', 'IHF', 'Managed care'),
                    ('ihf', 'hospitals', 'IHF', 'IHF ticker'),
                    # Energy
                    ('energy sector', 'energy', 'XLE', 'Energy sector'),
                    ('energy stocks', 'energy', 'XLE', 'Energy stocks'),
                    ('oil & gas', 'energy', 'XLE', 'O&G'),
                    ('fossil fuels', 'energy', 'XLE', 'Fossil fuels'),
                    ('xle', 'energy', 'XLE', 'XLE ticker'),
                    ('wti crude', 'oil_commodity', 'USO', 'WTI crude'),
                    ('brent crude', 'oil_commodity', 'BNO', 'Brent'),
                    ('uso', 'oil_commodity', 'USO', 'USO ticker'),
                    ('e and p', 'energy_ep', 'XOP', 'E&P'),
                    ('e&p', 'energy_ep', 'XOP', 'E&P'),
                    ('upstream oil', 'energy_ep', 'XOP', 'Upstream'),
                    ('xop', 'energy_ep', 'XOP', 'XOP ticker'),
                    ('midstream', 'pipelines', 'AMLP', 'Midstream oil'),
                    ('amlp', 'pipelines', 'AMLP', 'AMLP ticker'),
                    ('oil refiners', 'refiners', 'CRAK', 'Oil refiners'),
                    ('crak', 'refiners', 'CRAK', 'CRAK ticker'),
                    ('nat gas', 'natural_gas', 'UNG', 'Nat gas'),
                    ('natgas', 'natural_gas', 'UNG', 'Natgas'),
                    ('ung', 'natural_gas', 'UNG', 'UNG ticker'),
                    ('green energy', 'renewables', 'ICLN', 'Green energy'),
                    ('green stocks', 'renewables', 'ICLN', 'Green stocks'),
                    ('icln', 'renewables', 'ICLN', 'ICLN ticker'),
                    ('solar energy', 'solar', 'TAN', 'Solar energy'),
                    ('tan', 'solar', 'TAN', 'TAN ticker'),
                    ('wind power', 'wind', 'FAN', 'Wind power'),
                    ('fan', 'wind', 'FAN', 'FAN ticker'),
                    ('uranium stocks', 'uranium', 'URA', 'Uranium stocks'),
                    ('nuclear power', 'nuclear', 'URA', 'Nuclear power'),
                    ('ura', 'uranium', 'URA', 'URA ticker'),
                    # Materials / commodities / metals
                    ('materials sector', 'materials', 'XLB', 'Materials'),
                    ('materials stocks', 'materials', 'XLB', 'Materials stocks'),
                    ('basic materials', 'materials', 'XLB', 'Basic materials'),
                    ('xlb', 'materials', 'XLB', 'XLB ticker'),
                    ('the gold', 'gold', 'GLD', 'Gold colloquial'),
                    ('gold bullion', 'gold', 'GLD', 'Gold bullion'),
                    ('gld', 'gold', 'GLD', 'GLD ticker'),
                    ('gold mining', 'gold_miners', 'GDX', 'Gold mining'),
                    ('gold mining stocks', 'gold_miners', 'GDX', 'Gold miners'),
                    ('gdx', 'gold_miners', 'GDX', 'GDX ticker'),
                    ('junior gold miners', 'gold_miners_junior', 'GDXJ', 'Junior gold miners'),
                    ('gdxj', 'gold_miners_junior', 'GDXJ', 'GDXJ ticker'),
                    ('silver bullion', 'silver', 'SLV', 'Silver bullion'),
                    ('slv', 'silver', 'SLV', 'SLV ticker'),
                    ('silver miners', 'silver_miners', 'SIL', 'Silver miners'),
                    ('copper stocks', 'copper', 'COPX', 'Copper stocks'),
                    ('copx', 'copper', 'COPX', 'COPX ticker'),
                    ('lithium stocks', 'lithium', 'LIT', 'Lithium stocks'),
                    ('batteries', 'lithium', 'LIT', 'Batteries'),
                    ('lit', 'lithium', 'LIT', 'LIT ticker'),
                    ('steel stocks', 'steel', 'SLX', 'Steel stocks'),
                    ('slx', 'steel', 'SLX', 'SLX ticker'),
                    ('metals and mining', 'mining', 'XME', 'Metals & mining'),
                    ('xme', 'mining', 'XME', 'XME ticker'),
                    ('commodity basket', 'commodities', 'DBC', 'Commodity basket'),
                    ('dbc', 'commodities', 'DBC', 'DBC ticker'),
                    ('ag', 'agriculture', 'DBA', 'Ag shorthand'),
                    ('farming', 'agriculture', 'DBA', 'Farming'),
                    ('farmland', 'agriculture', 'DBA', 'Farmland'),
                    ('corn', 'corn', 'CORN', 'Corn ETF'),
                    ('wheat', 'wheat', 'WEAT', 'Wheat ETF'),
                    ('soybeans', 'soybeans', 'SOYB', 'Soybeans ETF'),
                    ('dba', 'agriculture', 'DBA', 'DBA ticker'),
                    ('lumber', 'timber', 'WOOD', 'Lumber'),
                    ('wood', 'timber', 'WOOD', 'Wood via timber'),
                    ('water stocks', 'water', 'PHO', 'Water stocks'),
                    ('pho', 'water', 'PHO', 'PHO ticker'),
                    # Consumer discretionary / cyclical
                    ('discretionary', 'consumer_discretionary', 'XLY', 'Discretionary'),
                    ('consumer cyclical', 'consumer_discretionary', 'XLY', 'Consumer cyclical'),
                    ('cyclicals', 'consumer_discretionary', 'XLY', 'Cyclicals'),
                    ('xly', 'consumer_discretionary', 'XLY', 'XLY ticker'),
                    ('retail stocks', 'retail', 'XRT', 'Retail stocks'),
                    ('retailers', 'retail', 'XRT', 'Retailers'),
                    ('xrt', 'retail', 'XRT', 'XRT ticker'),
                    ('travel sector', 'travel', 'AWAY', 'Travel sector'),
                    ('leisure', 'travel', 'AWAY', 'Leisure'),
                    ('leisure stocks', 'travel', 'AWAY', 'Leisure stocks'),
                    ('away', 'travel', 'AWAY', 'AWAY ticker'),
                    ('airline stocks', 'airlines', 'JETS', 'Airline stocks'),
                    ('airline sector', 'airlines', 'JETS', 'Airline sector'),
                    ('jets', 'airlines', 'JETS', 'JETS ticker'),
                    ('cruise stocks', 'cruises', 'AWAY', 'Cruises'),
                    ('hotel stocks', 'hotels', 'AWAY', 'Hotel stocks'),
                    ('casinos', 'casinos', 'BJK', 'Gaming/casino ETF'),
                    ('casino stocks', 'casinos', 'BJK', 'Casino stocks'),
                    ('gambling', 'casinos', 'BJK', 'Gambling stocks'),
                    ('restaurant stocks', 'restaurants', 'EATZ', 'Restaurants'),
                    ('eatz', 'restaurants', 'EATZ', 'EATZ ticker'),
                    ('homebuilder stocks', 'homebuilders', 'XHB', 'Homebuilders'),
                    ('itb', 'homebuilders', 'ITB', 'iShares homebuilder ETF'),
                    ('xhb', 'homebuilders', 'XHB', 'XHB ticker'),
                    ('apparel', 'apparel', 'XRT', 'Apparel via retail'),
                    ('luxury stocks', 'luxury', 'XLY', 'Luxury stocks'),
                    # Consumer staples
                    ('staples', 'consumer_staples', 'XLP', 'Staples shorthand'),
                    ('defensive stocks', 'consumer_staples', 'XLP', 'Defensive'),
                    ('xlp', 'consumer_staples', 'XLP', 'XLP ticker'),
                    ('food stocks', 'food', 'PBJ', 'Food stocks'),
                    ('beverage stocks', 'food', 'PBJ', 'Beverage stocks'),
                    ('tobacco', 'tobacco', 'XLP', 'Tobacco via staples'),
                    ('tobacco stocks', 'tobacco', 'XLP', 'Tobacco stocks'),
                    ('pbj', 'food', 'PBJ', 'PBJ ticker'),
                    # Industrials
                    ('industrial sector', 'industrials', 'XLI', 'Industrial sector'),
                    ('industrial stocks', 'industrials', 'XLI', 'Industrial stocks'),
                    ('xli', 'industrials', 'XLI', 'XLI ticker'),
                    ('aerospace and defense', 'defense', 'ITA', 'Aerospace & defense'),
                    ('weapons makers', 'defense', 'ITA', 'Defense contractors'),
                    ('defense contractors', 'defense', 'ITA', 'Defense contractors'),
                    ('ita', 'defense', 'ITA', 'ITA ticker'),
                    ('xar', 'defense', 'XAR', 'XAR alt defense'),
                    ('transport stocks', 'transports', 'IYT', 'Transport stocks'),
                    ('iyt', 'transports', 'IYT', 'IYT ticker'),
                    ('shipping stocks', 'shipping', 'BOAT', 'Shipping stocks'),
                    ('container shipping', 'shipping', 'BOAT', 'Container shipping'),
                    ('dry bulk', 'shipping', 'BOAT', 'Dry bulk shipping'),
                    # Communication services
                    ('communications', 'communications', 'XLC', 'Comm services'),
                    ('telecom stocks', 'communications', 'XLC', 'Telecom stocks'),
                    ('media', 'communications', 'XLC', 'Media via comms'),
                    ('media stocks', 'communications', 'XLC', 'Media stocks'),
                    ('xlc', 'communications', 'XLC', 'XLC ticker'),
                    # Real estate
                    ('real estate stocks', 'real_estate', 'XLRE', 'RE stocks'),
                    ('reit', 'real_estate', 'XLRE', 'REIT'),
                    ('real estate sector', 'real_estate', 'XLRE', 'RE sector'),
                    ('vnq', 'real_estate', 'VNQ', 'VNQ ticker'),
                    ('xlre', 'real_estate', 'XLRE', 'XLRE ticker'),
                    ('mreits', 'mortgage_reits', 'REM', 'mREITs'),
                    ('rem', 'mortgage_reits', 'REM', 'REM ticker'),
                    # Utilities
                    ('utility sector', 'utilities', 'XLU', 'Utility sector'),
                    ('utility stocks', 'utilities', 'XLU', 'Utility stocks'),
                    ('utes', 'utilities', 'XLU', 'Utes shorthand'),
                    ('xlu', 'utilities', 'XLU', 'XLU ticker'),
                    # International / country ETFs
                    ('international', 'international', 'VEA', 'Intl developed'),
                    ('foreign stocks', 'international', 'VEA', 'Foreign'),
                    ('ex us', 'international', 'VEA', 'Ex-US'),
                    ('vea', 'international', 'VEA', 'VEA ticker'),
                    ('em stocks', 'emerging_markets', 'EEM', 'EM stocks'),
                    ('emerging market stocks', 'emerging_markets', 'EEM', 'EM stocks'),
                    ('eem', 'emerging_markets', 'EEM', 'EEM ticker'),
                    ('vwo', 'emerging_markets', 'VWO', 'Vanguard EM'),
                    ('chinese market', 'china', 'FXI', 'China market'),
                    ('china stocks', 'china', 'FXI', 'China'),
                    ('a shares', 'china_a_shares', 'ASHR', 'China A-shares'),
                    ('mchi', 'china', 'MCHI', 'iShares MSCI China'),
                    ('fxi', 'china', 'FXI', 'FXI ticker'),
                    ('hong kong', 'hong_kong', 'EWH', 'Hong Kong ETF'),
                    ('taiwanese stocks', 'taiwan', 'EWT', 'Taiwan'),
                    ('nikkei', 'japan', 'EWJ', 'Nikkei'),
                    ('ewj', 'japan', 'EWJ', 'EWJ ticker'),
                    ('indian market', 'india', 'INDA', 'India market'),
                    ('inda', 'india', 'INDA', 'INDA ticker'),
                    ('korean stocks', 'korea', 'EWY', 'Korea'),
                    ('kospi', 'korea', 'EWY', 'KOSPI'),
                    ('ewy', 'korea', 'EWY', 'EWY ticker'),
                    ('malaysia', 'malaysia', 'EWM', 'Malaysia ETF'),
                    ('thailand', 'thailand', 'THD', 'Thailand ETF'),
                    ('philippines', 'philippines', 'EPHE', 'Philippines ETF'),
                    ('singapore', 'singapore', 'EWS', 'Singapore ETF'),
                    ('new zealand', 'new_zealand', 'ENZL', 'NZ ETF'),
                    ('brazilian stocks', 'brazil', 'EWZ', 'Brazil stocks'),
                    ('mexican stocks', 'mexico', 'EWW', 'Mexico'),
                    ('argentina', 'argentina', 'ARGT', 'Argentina ETF'),
                    ('chile', 'chile', 'ECH', 'Chile ETF'),
                    ('colombia', 'colombia', 'GXG', 'Colombia ETF'),
                    ('peru', 'peru', 'EPU', 'Peru ETF'),
                    ('latin america', 'latin_america', 'ILF', 'LatAm ETF'),
                    ('latam', 'latin_america', 'ILF', 'LatAm'),
                    ('european stocks', 'europe', 'VGK', 'European'),
                    ('european markets', 'europe', 'VGK', 'Europe'),
                    ('eurozone', 'europe', 'EZU', 'Eurozone'),
                    ('vgk', 'europe', 'VGK', 'VGK ticker'),
                    ('german stocks', 'germany', 'EWG', 'Germany'),
                    ('dax', 'germany', 'EWG', 'DAX'),
                    ('french stocks', 'france', 'EWQ', 'France'),
                    ('british stocks', 'uk', 'EWU', 'UK'),
                    ('ftse', 'uk', 'EWU', 'FTSE'),
                    ('italy', 'italy', 'EWI', 'Italy ETF'),
                    ('spain', 'spain', 'EWP', 'Spain ETF'),
                    ('netherlands', 'netherlands', 'EWN', 'Netherlands ETF'),
                    ('switzerland', 'switzerland', 'EWL', 'Switzerland ETF'),
                    ('sweden', 'sweden', 'EWD', 'Sweden ETF'),
                    ('norway', 'norway', 'NORW', 'Norway ETF'),
                    ('poland', 'poland', 'EPOL', 'Poland ETF'),
                    ('russia', 'russia', 'ERUS', 'Russia ETF restricted'),
                    ('turkey', 'turkey', 'TUR', 'Turkey ETF'),
                    ('israel', 'israel', 'EIS', 'Israel ETF'),
                    ('saudi arabia', 'saudi_arabia', 'KSA', 'Saudi ETF'),
                    ('south africa', 'south_africa', 'EZA', 'South Africa ETF'),
                    ('canadian stocks', 'canada', 'EWC', 'Canada'),
                    ('ewc', 'canada', 'EWC', 'EWC ticker'),
                    ('africa', 'africa', 'AFK', 'Africa ETF'),
                    ('asia', 'asia', 'AAXJ', 'Asia ex-Japan'),
                    ('asia ex japan', 'asia', 'AAXJ', 'Asia ex-Japan'),
                    # Crypto and digital assets
                    ('the bitcoin', 'bitcoin', 'IBIT', 'BTC colloquial'),
                    ('spot bitcoin', 'bitcoin', 'IBIT', 'Spot BTC'),
                    ('ibit', 'bitcoin', 'IBIT', 'IBIT ticker'),
                    ('fbtc', 'bitcoin', 'FBTC', 'Fidelity BTC'),
                    ('the ethereum', 'ethereum', 'ETHA', 'ETH colloquial'),
                    ('etha', 'ethereum', 'ETHA', 'ETHA ticker'),
                    ('cryptocurrency stocks', 'crypto_stocks', 'BITQ', 'Crypto stocks'),
                    ('crypto sector', 'crypto_stocks', 'BITQ', 'Crypto sector'),
                    ('bitq', 'crypto_stocks', 'BITQ', 'BITQ ticker'),
                    ('crypto miners', 'crypto_miners', 'WGMI', 'Crypto miners'),
                    ('mining stocks crypto', 'crypto_miners', 'WGMI', 'Crypto mining'),
                    ('wgmi', 'crypto_miners', 'WGMI', 'WGMI ticker'),
                    ('blok', 'blockchain', 'BLOK', 'BLOK ticker'),
                    # Bonds and rates
                    ('the bond market', 'bonds', 'AGG', 'Broad bond market'),
                    ('bond market', 'bonds', 'AGG', 'Bond market'),
                    ('twenty year bonds', 'bonds', 'TLT', '20-year'),
                    ('20 year treasury', 'bonds', 'TLT', '20-year treasury'),
                    ('30 year bonds', 'bonds', 'TLT', '30-year use TLT'),
                    ('tlt', 'bonds', 'TLT', 'TLT ticker'),
                    ('agg', 'bonds', 'AGG', 'AGG ticker'),
                    ('bnd', 'bonds', 'BND', 'Vanguard total bond'),
                    ('ten year', 'tenyear', 'IEF', '10-year verbal'),
                    ('ten year treasury', 'tenyear', 'IEF', '10-year'),
                    ('ief', 'tenyear', 'IEF', 'IEF ticker'),
                    ('2 year', 'short_bonds', 'SHY', '2-year'),
                    ('two year', 'short_bonds', 'SHY', '2-year verbal'),
                    ('2 year treasury', 'short_bonds', 'SHY', '2-year treasury'),
                    ('shy', 'short_bonds', 'SHY', 'SHY ticker'),
                    ('treasury bills', 'tbills', 'BIL', 'T-bills formal'),
                    ('bil', 'tbills', 'BIL', 'BIL ticker'),
                    ('investment grade bonds', 'corporate_bonds', 'LQD', 'IG bonds'),
                    ('ig bonds', 'corporate_bonds', 'LQD', 'IG'),
                    ('lqd', 'corporate_bonds', 'LQD', 'LQD ticker'),
                    ('high yield bonds', 'high_yield', 'HYG', 'High yield'),
                    ('junk', 'high_yield', 'HYG', 'Junk bonds'),
                    ('jnk', 'high_yield', 'JNK', 'JNK alt high yield'),
                    ('municipal bonds', 'munis', 'MUB', 'Munis'),
                    ('munis', 'munis', 'MUB', 'Munis shorthand'),
                    ('mub', 'munis', 'MUB', 'MUB ticker'),
                    ('inflation protected bonds', 'tips', 'TIP', 'TIPS'),
                    ('tip', 'tips', 'TIP', 'TIP ticker'),
                    ('international bonds', 'intl_bonds', 'BNDX', 'Intl bonds'),
                    ('em bonds', 'em_bonds', 'EMB', 'EM bonds'),
                    ('emerging market bonds', 'em_bonds', 'EMB', 'EM bonds'),
                    # Volatility and hedges
                    ('vol', 'volatility', 'VXX', 'Vol shorthand'),
                    ('fear gauge', 'volatility', 'VXX', 'VIX alias'),
                    ('vxx', 'volatility', 'VXX', 'VXX ticker'),
                    ('uvxy', 'volatility', 'UVXY', 'Leveraged VIX'),
                    # Factors
                    ('dividend growers', 'dividend_growth', 'SCHD', 'Dividend growers'),
                    ('dividend aristocrats', 'dividend_aristocrats', 'NOBL', 'Div aristocrats'),
                    ('aristocrats', 'dividend_aristocrats', 'NOBL', 'Aristocrats'),
                    ('schd', 'dividends', 'SCHD', 'SCHD ticker'),
                    ('nobl', 'dividend_aristocrats', 'NOBL', 'NOBL ticker'),
                    ('high yield stocks', 'high_dividend', 'VYM', 'High yield stocks'),
                    ('vym', 'high_dividend', 'VYM', 'VYM ticker'),
                    ('value factor', 'value', 'IVE', 'Value factor'),
                    ('deep value', 'value', 'IVE', 'Deep value'),
                    ('ive', 'value', 'IVE', 'IVE ticker'),
                    ('vtv', 'value', 'VTV', 'Vanguard value'),
                    ('growth factor', 'growth', 'IVW', 'Growth factor'),
                    ('ivw', 'growth', 'IVW', 'IVW ticker'),
                    ('vug', 'growth', 'VUG', 'Vanguard growth'),
                    ('momentum stocks', 'momentum', 'MTUM', 'Momentum'),
                    ('momo', 'momentum', 'MTUM', 'Momo shorthand'),
                    ('mtum', 'momentum', 'MTUM', 'MTUM ticker'),
                    ('quality stocks', 'quality', 'QUAL', 'Quality'),
                    ('quality factor', 'quality', 'QUAL', 'Quality factor'),
                    ('qual', 'quality', 'QUAL', 'QUAL ticker'),
                    ('low volatility stocks', 'low_vol', 'USMV', 'Low vol stocks'),
                    ('min vol', 'low_vol', 'USMV', 'Min vol'),
                    ('minimum volatility', 'low_vol', 'USMV', 'Min vol'),
                    ('usmv', 'low_vol', 'USMV', 'USMV ticker'),
                    # Thematic
                    ('sustainable investing', 'esg', 'ESGU', 'ESG formal'),
                    ('esgu', 'esg', 'ESGU', 'ESGU ticker'),
                    ('infra', 'infrastructure', 'PAVE', 'Infra shorthand'),
                    ('pave', 'infrastructure', 'PAVE', 'PAVE ticker'),
                    ('ufo', 'space', 'UFO', 'UFO ticker'),
                    ('quantum stocks', 'quantum', 'QTUM', 'Quantum stocks'),
                    ('qtum', 'quantum', 'QTUM', 'QTUM ticker'),
                    ('disruptive innovation', 'disruptive', 'ARKK', 'Disruptive'),
                    ('innovation stocks', 'disruptive', 'ARKK', 'Innovation'),
                    ('cathy wood', 'disruptive', 'ARKK', 'ARKK alt spelling'),
                    ('arkk', 'disruptive', 'ARKK', 'ARKK ticker'),
                    ('arkf', 'fintech', 'ARKF', 'ARK fintech'),
                    ('arkw', 'internet', 'ARKW', 'ARK internet'),
                    ('arkq', 'robotics', 'ARKQ', 'ARK robotics'),
                    ('arkx', 'space', 'ARKX', 'ARK space'),
                    ('moat', 'moat', 'MOAT', 'Wide moat stocks ETF'),
                    ('moat stocks', 'moat', 'MOAT', 'Moat stocks'),
                    ('wide moat', 'moat', 'MOAT', 'Wide moat'),
                    # Macro hedges
                    ('dollar', 'dollar', 'UUP', 'US dollar ETF'),
                    ('the dollar', 'dollar', 'UUP', 'Dollar'),
                    ('us dollar', 'dollar', 'UUP', 'USD'),
                    ('dxy', 'dollar', 'UUP', 'Dollar index'),
                    ('uup', 'dollar', 'UUP', 'UUP ticker'),
                    ('inflation', 'inflation', 'TIP', 'Inflation via TIPS'),
                    ('inflation hedge', 'inflation', 'TIP', 'Inflation hedge'),
                ]
                for _alias, _canonical, _etf, _notes in _seed_aliases:
                    _sa_c.execute(sql_text("""
                        INSERT INTO sector_etf_aliases
                            (alias, canonical_sector, etf_ticker, notes)
                        VALUES (:a, :c, :e, :n)
                        ON CONFLICT (alias) DO NOTHING
                    """), {"a": _alias, "c": _canonical, "e": _etf, "n": _notes})
                _sa_c.commit()
                print("[Startup] sector_etf_aliases table + seed ready")
        except Exception as _sae:
            print(f"[Startup] sector_etf_aliases migration error: {_sae}")

        # ── predictions.prediction_category (ticker_call | sector_call) ──
        # Default ticker_call preserves all existing row semantics — every
        # prediction already in the table is a ticker call. New sector_call
        # rows are only inserted by the YouTube classifier's gated sector
        # extraction path (feature flag default 0%).
        try:
            with engine.connect() as _pc_c:
                _pc_c.execute(sql_text(
                    "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS "
                    "prediction_category VARCHAR(20) DEFAULT 'ticker_call'"
                ))
                _pc_c.execute(sql_text(
                    "CREATE INDEX IF NOT EXISTS idx_predictions_category "
                    "ON predictions(prediction_category)"
                ))
                # Backfill NULLs to 'ticker_call' for any row inserted before
                # the column default landed (defensive — DEFAULT covers new
                # rows but not historical inserts on some Postgres versions).
                _pc_c.execute(sql_text(
                    "UPDATE predictions SET prediction_category = 'ticker_call' "
                    "WHERE prediction_category IS NULL"
                ))
                _pc_c.commit()
                print("[Startup] predictions.prediction_category ready")
        except Exception as _pce:
            print(f"[Startup] prediction_category migration error: {_pce}")

        # ── scraper_runs.sector_calls_extracted ─────────────────────────
        # Per-run counter for the admin sector-calls dashboard. Incremented
        # by the YouTube monitor when the sector-aware prompt extracts a
        # sector_call that survives ETF mapping + insertion. Always runs,
        # but stays at 0 until the feature flag is flipped on.
        try:
            with engine.connect() as _sr2_c:
                _sr2_c.execute(sql_text(
                    "ALTER TABLE scraper_runs ADD COLUMN IF NOT EXISTS "
                    "sector_calls_extracted INTEGER NOT NULL DEFAULT 0"
                ))
                _sr2_c.commit()
                print("[Startup] scraper_runs.sector_calls_extracted ready")
        except Exception as _sre:
            print(f"[Startup] scraper_runs sector_calls migration error: {_sre}")

        # ── predictions.list_id + list_rank (ranked list extraction) ────
        # Stores speaker-declared rank position within a ranked list
        # ("my top 5 stocks: NVDA, AMD, TSM, AAPL, MSFT"). Both columns
        # move together — either both set or both NULL. Partial index on
        # list_id is intentional: most rows will never be in a list, so
        # WHERE list_id IS NOT NULL keeps the index small. No backfill:
        # historical predictions have no ranking metadata.
        try:
            with engine.connect() as _ll_c:
                _ll_c.execute(sql_text(
                    "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS "
                    "list_id VARCHAR(40)"
                ))
                _ll_c.execute(sql_text(
                    "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS "
                    "list_rank INTEGER"
                ))
                _ll_c.execute(sql_text(
                    "CREATE INDEX IF NOT EXISTS idx_predictions_list_id "
                    "ON predictions(list_id) WHERE list_id IS NOT NULL"
                ))
                _ll_c.commit()
                print("[Startup] predictions.list_id + list_rank ready")
        except Exception as _lle:
            print(f"[Startup] list_id/list_rank migration error: {_lle}")

        # ── predictions.revision_of (target revision tracking) ──────────
        # Self-referencing FK linking a revised prediction to its
        # immediate predecessor by the same forecaster on the same
        # ticker. Flat chain — the insertion logic always points at the
        # most recent prior (even if that prior is itself a revision)
        # without walking up. ON DELETE SET NULL so removing an early
        # prediction just severs the link, never cascades. Partial
        # index keeps the index small: only revised rows get indexed.
        # No backfill: historical predictions have no revision metadata.
        try:
            with engine.connect() as _rv_c:
                _rv_c.execute(sql_text(
                    "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS "
                    "revision_of INTEGER"
                ))
                # Attempt to add the FK constraint separately so failure
                # on an old Postgres (or SQLite dev) doesn't block the
                # column add. Idempotent: catch and ignore if the
                # constraint is already present.
                try:
                    _rv_c.execute(sql_text("""
                        ALTER TABLE predictions
                        ADD CONSTRAINT fk_predictions_revision_of
                        FOREIGN KEY (revision_of)
                        REFERENCES predictions(id)
                        ON DELETE SET NULL
                    """))
                except Exception:
                    pass
                _rv_c.execute(sql_text(
                    "CREATE INDEX IF NOT EXISTS idx_predictions_revision_of "
                    "ON predictions(revision_of) WHERE revision_of IS NOT NULL"
                ))
                _rv_c.commit()
                print("[Startup] predictions.revision_of ready")
        except Exception as _rve:
            print(f"[Startup] revision_of migration error: {_rve}")

        # ── ENABLE_YOUTUBE_SECTOR_CALLS flag seed ─────────────────────────
        # Seed at 0 (feature OFF) on first boot. Idempotent: only inserts
        # if the row doesn't already exist. Admin flips via
        # POST /api/admin/sector-calls/traffic.
        try:
            with engine.connect() as _fl_c:
                _fl_c.execute(sql_text("""
                    INSERT INTO config (key, value)
                    VALUES ('ENABLE_YOUTUBE_SECTOR_CALLS', '0')
                    ON CONFLICT (key) DO NOTHING
                """))
                _fl_c.commit()
                print("[Startup] ENABLE_YOUTUBE_SECTOR_CALLS flag seeded")
        except Exception as _fle:
            print(f"[Startup] ENABLE_YOUTUBE_SECTOR_CALLS seed error: {_fle}")

        # ── ENABLE_RANKED_LIST_EXTRACTION flag seed ───────────────────
        # Default 'false' (feature OFF). Admin flips via the toggle
        # endpoint. Must stay at false until eval on a test corpus.
        try:
            with engine.connect() as _rl_c:
                _rl_c.execute(sql_text("""
                    INSERT INTO config (key, value)
                    VALUES ('ENABLE_RANKED_LIST_EXTRACTION', 'false')
                    ON CONFLICT (key) DO NOTHING
                """))
                _rl_c.commit()
                print("[Startup] ENABLE_RANKED_LIST_EXTRACTION flag seeded")
        except Exception as _rle:
            print(f"[Startup] ENABLE_RANKED_LIST_EXTRACTION seed error: {_rle}")

        # ── ENABLE_TARGET_REVISIONS flag seed ───────────────────────────
        # Default 'false'. Admin flips via POST /api/admin/toggle-target-
        # revisions once they've eval'd the prompt change on a corpus.
        try:
            with engine.connect() as _tr_c:
                _tr_c.execute(sql_text("""
                    INSERT INTO config (key, value)
                    VALUES ('ENABLE_TARGET_REVISIONS', 'false')
                    ON CONFLICT (key) DO NOTHING
                """))
                _tr_c.commit()
                print("[Startup] ENABLE_TARGET_REVISIONS flag seeded")
        except Exception as _tre:
            print(f"[Startup] ENABLE_TARGET_REVISIONS seed error: {_tre}")

        # ── youtube_channel_meta totals backfill ────────────────────────
        # Historical backfill for the admin card counters. Three columns:
        #   - total_predictions_extracted (display)
        #   - predictions_extracted_count (auto-prune yield counter)
        #   - videos_processed_count      (auto-prune throughput counter)
        # Each UPDATE has an idempotency guard (= 0) so it only touches
        # rows the monitor hasn't already started writing to. Runs every
        # boot; no-ops once populated.
        try:
            with engine.connect() as _yb_c:
                # total_predictions_extracted — counts 'youtube_haiku_v1'
                # inserts only (the display metric on the admin card).
                _yb_c.execute(sql_text("""
                    UPDATE youtube_channel_meta m
                    SET total_predictions_extracted = sub.cnt
                    FROM (
                        SELECT f.id AS forecaster_id, COUNT(*) AS cnt
                        FROM predictions p
                        JOIN forecasters f ON f.id = p.forecaster_id
                        WHERE p.source_type = 'youtube'
                          AND p.verified_by = 'youtube_haiku_v1'
                        GROUP BY f.id
                    ) sub
                    WHERE m.forecaster_id = sub.forecaster_id
                      AND m.total_predictions_extracted = 0
                """))
                # predictions_extracted_count — auto-prune yield counter.
                # Counts ANY source_type='youtube' prediction so V1 rows
                # (predating youtube_haiku_v1) still credit the channel.
                _yb_c.execute(sql_text("""
                    UPDATE youtube_channel_meta m
                    SET predictions_extracted_count = sub.cnt
                    FROM (
                        SELECT f.id AS forecaster_id, COUNT(*) AS cnt
                        FROM predictions p
                        JOIN forecasters f ON f.id = p.forecaster_id
                        WHERE p.source_type = 'youtube'
                        GROUP BY f.id
                    ) sub
                    WHERE m.forecaster_id = sub.forecaster_id
                      AND m.predictions_extracted_count = 0
                """))
                # videos_processed_count — reached-Haiku throughput.
                # UNION of post-Haiku rejections with inserted predictions,
                # keyed by channel_id on both sides, distinct on video_id.
                # source_platform_id format is 'yt_<video_id>_<ticker>';
                # SPLIT_PART pulls the video_id cleanly without the
                # nested-replace hack the task spec suggests.
                _yb_c.execute(sql_text("""
                    UPDATE youtube_channel_meta m
                    SET videos_processed_count = sub.cnt
                    FROM (
                        SELECT channel_id, COUNT(DISTINCT video_id) AS cnt
                        FROM (
                            SELECT channel_id, video_id
                            FROM youtube_scraper_rejections
                            WHERE rejection_reason IN (
                                'haiku_no_predictions',
                                'invalid_ticker',
                                'neutral_or_no_direction'
                            )
                            UNION
                            SELECT f.channel_id AS channel_id,
                                   SPLIT_PART(p.source_platform_id, '_', 2) AS video_id
                            FROM predictions p
                            JOIN forecasters f ON f.id = p.forecaster_id
                            WHERE p.source_type = 'youtube'
                              AND p.source_platform_id LIKE 'yt\\_%' ESCAPE '\\'
                              AND f.channel_id IS NOT NULL
                        ) combined
                        WHERE channel_id IS NOT NULL
                        GROUP BY channel_id
                    ) sub
                    WHERE m.channel_id = sub.channel_id
                      AND m.videos_processed_count = 0
                """))
                _yb_c.commit()
                print("[Startup] youtube_channel_meta totals backfilled")
        except Exception as _ybe:
            print(f"[Startup] youtube_channel_meta totals backfill error: {_ybe}")

        # ── scraper_job_queue (cross-service work queue) ───────────────
        # Mirrors the migration in worker.py so the API service can INSERT
        # queued jobs even if the worker container boots later. Idempotent.
        try:
            with engine.connect() as _sjq_c:
                _sjq_c.execute(sql_text("""
                    CREATE TABLE IF NOT EXISTS scraper_job_queue (
                        id SERIAL PRIMARY KEY,
                        job_type VARCHAR(50) NOT NULL,
                        payload JSONB,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        started_at TIMESTAMP,
                        finished_at TIMESTAMP,
                        error TEXT
                    )
                """))
                _sjq_c.execute(sql_text(
                    "CREATE INDEX IF NOT EXISTS idx_sjq_pending "
                    "ON scraper_job_queue(status, created_at) "
                    "WHERE status = 'pending'"
                ))
                _sjq_c.commit()
                print("[Startup] scraper_job_queue ready")
        except Exception as _sjqe:
            print(f"[Startup] scraper_job_queue migration error: {_sjqe}")

        # ── youtube_channel_meta.last_scraped_at backfill ──────────────
        # Two-pass strategy mirroring the spec. Pass 1 copies from
        # forecasters.last_synced_at, which holds historical per-channel
        # fetch timestamps from the pre-meta era. Pass 2 backs it up
        # with MAX(predictions.created_at) for channels whose forecaster
        # row still has last_synced_at=NULL (older V1 rows). Both passes
        # have an IS NULL idempotency guard so they only touch rows the
        # monitor hasn't already written.
        try:
            with engine.connect() as _ls_c:
                # Pass 1: forecasters.last_synced_at
                _ls_c.execute(sql_text("""
                    UPDATE youtube_channel_meta m
                    SET last_scraped_at = f.last_synced_at
                    FROM forecasters f
                    WHERE m.forecaster_id = f.id
                      AND f.platform = 'youtube'
                      AND f.last_synced_at IS NOT NULL
                      AND m.last_scraped_at IS NULL
                """))
                # Pass 2: fallback from prediction created_at
                _ls_c.execute(sql_text("""
                    UPDATE youtube_channel_meta m
                    SET last_scraped_at = sub.latest
                    FROM (
                        SELECT f.id AS forecaster_id,
                               MAX(p.created_at) AS latest
                        FROM predictions p
                        JOIN forecasters f ON f.id = p.forecaster_id
                        WHERE p.source_type = 'youtube'
                        GROUP BY f.id
                    ) sub
                    WHERE m.forecaster_id = sub.forecaster_id
                      AND m.last_scraped_at IS NULL
                """))
                _ls_c.commit()
                print("[Startup] youtube_channel_meta.last_scraped_at backfilled")
        except Exception as _lse:
            print(f"[Startup] youtube_channel_meta.last_scraped_at backfill error: {_lse}")

        # ── scraper_runs + youtube_scraper_rejections (mirrors worker.py) ──
        # Both API and worker run this. SQLAlchemy create_all above already
        # creates the tables when the model is fresh, but the IF NOT EXISTS
        # block here is the belt-and-braces guarantee for indexes on
        # existing DBs. Idempotent: safe to re-run on every boot.
        try:
            with engine.connect() as _sr_c:
                _sr_c.execute(sql_text("""
                    CREATE TABLE IF NOT EXISTS scraper_runs (
                        id SERIAL PRIMARY KEY,
                        source VARCHAR(20) NOT NULL,
                        started_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        finished_at TIMESTAMP,
                        status VARCHAR(20) NOT NULL DEFAULT 'running',
                        items_fetched INTEGER NOT NULL DEFAULT 0,
                        items_processed INTEGER NOT NULL DEFAULT 0,
                        items_llm_sent INTEGER NOT NULL DEFAULT 0,
                        items_inserted INTEGER NOT NULL DEFAULT 0,
                        items_rejected INTEGER NOT NULL DEFAULT 0,
                        items_deduped INTEGER NOT NULL DEFAULT 0,
                        error_message TEXT
                    )
                """))
                _sr_c.execute(sql_text(
                    "CREATE INDEX IF NOT EXISTS idx_scraper_runs_source_started "
                    "ON scraper_runs(source, started_at DESC)"
                ))
                _sr_c.execute(sql_text("""
                    CREATE TABLE IF NOT EXISTS youtube_scraper_rejections (
                        id SERIAL PRIMARY KEY,
                        video_id VARCHAR(20),
                        channel_id VARCHAR(30),
                        channel_name VARCHAR(200),
                        video_title TEXT,
                        video_published_at TIMESTAMP,
                        rejected_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        rejection_reason VARCHAR(50) NOT NULL,
                        haiku_reason TEXT,
                        haiku_raw_response JSONB,
                        transcript_snippet TEXT
                    )
                """))
                _sr_c.execute(sql_text(
                    "CREATE INDEX IF NOT EXISTS idx_yt_rejections_rejected_at "
                    "ON youtube_scraper_rejections(rejected_at)"
                ))
                _sr_c.execute(sql_text(
                    "CREATE INDEX IF NOT EXISTS idx_yt_rejections_reason "
                    "ON youtube_scraper_rejections(rejection_reason)"
                ))
                _sr_c.execute(sql_text(
                    "CREATE INDEX IF NOT EXISTS idx_yt_rejections_channel "
                    "ON youtube_scraper_rejections(channel_id)"
                ))
                _sr_c.commit()
                print("[Startup] scraper_runs + youtube_scraper_rejections ready")
        except Exception as _sre:
            print(f"[Startup] scraper_runs/yt_rejections error: {_sre}")

        # ── scraper_runs LLM cost/usage columns (mirrors worker.py) ────
        try:
            with engine.connect() as _sc_c:
                for _sc_ddl in (
                    "ALTER TABLE scraper_runs ADD COLUMN IF NOT EXISTS "
                    "total_input_tokens BIGINT NOT NULL DEFAULT 0",
                    "ALTER TABLE scraper_runs ADD COLUMN IF NOT EXISTS "
                    "total_output_tokens BIGINT NOT NULL DEFAULT 0",
                    "ALTER TABLE scraper_runs ADD COLUMN IF NOT EXISTS "
                    "total_cache_create_tokens BIGINT NOT NULL DEFAULT 0",
                    "ALTER TABLE scraper_runs ADD COLUMN IF NOT EXISTS "
                    "total_cache_read_tokens BIGINT NOT NULL DEFAULT 0",
                    "ALTER TABLE scraper_runs ADD COLUMN IF NOT EXISTS "
                    "estimated_cost_usd NUMERIC(10,4) NOT NULL DEFAULT 0",
                    "ALTER TABLE scraper_runs ADD COLUMN IF NOT EXISTS "
                    "haiku_retries_count INTEGER NOT NULL DEFAULT 0",
                ):
                    _sc_c.execute(sql_text(_sc_ddl))
                _sc_c.commit()
                print("[Startup] scraper_runs cost columns ready")
        except Exception as _sce:
            print(f"[Startup] scraper_runs cost columns error: {_sce}")

        # ── Clean up company descriptions — first sentence only, no "..." ──
        try:
            with engine.connect() as _desc_c:
                # Get long descriptions (> 150 chars or containing "...")
                long_descs = _desc_c.execute(sql_text(
                    "SELECT ticker, description FROM ticker_sectors "
                    "WHERE description IS NOT NULL AND (LENGTH(description) > 150 OR description LIKE '%...')"
                )).fetchall()
                cleaned = 0
                for row in long_descs:
                    old = row[1]
                    # Take first sentence (split on ". " and take the first part)
                    first_sentence = old.split('. ')[0]
                    # Remove trailing "..." if present
                    if first_sentence.endswith('...'):
                        first_sentence = first_sentence[:-3].strip()
                    # If still too long, truncate at last word boundary before 150 chars
                    if len(first_sentence) > 150:
                        cut = first_sentence[:150]
                        last_space = cut.rfind(' ')
                        if last_space > 80:
                            first_sentence = cut[:last_space]
                        else:
                            first_sentence = cut
                    # Add period if it doesn't end with one
                    if first_sentence and not first_sentence.endswith('.'):
                        first_sentence = first_sentence + '.'
                    if first_sentence != old:
                        _desc_c.execute(sql_text(
                            "UPDATE ticker_sectors SET description = :desc WHERE ticker = :t"
                        ), {"desc": first_sentence, "t": row[0]})
                        cleaned += 1
                _desc_c.commit()
                if cleaned:
                    print(f"[Startup] Cleaned {cleaned} company descriptions (first sentence only)")
        except Exception as _de:
            print(f"[Startup] Description cleanup error: {_de}")

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

        # ── Backfill logo_url: update existing + insert missing ticker_sectors rows ──
        try:
            _logo_db = BgSessionLocal()

            # Step 1: Update existing rows with NULL/empty/clearbit logo_url
            filled = _logo_db.execute(sql_text("""
                UPDATE ticker_sectors
                SET logo_url = 'https://financialmodelingprep.com/image-stock/' || UPPER(ticker) || '.png'
                WHERE logo_url IS NULL OR logo_url = '' OR logo_url LIKE '%%clearbit%%'
            """)).rowcount
            _logo_db.commit()

            # Step 2: Create ticker_sectors rows for tickers that have predictions but no row
            inserted = _logo_db.execute(sql_text("""
                INSERT INTO ticker_sectors (ticker, sector, logo_url)
                SELECT DISTINCT p.ticker, 'Other',
                       'https://financialmodelingprep.com/image-stock/' || UPPER(p.ticker) || '.png'
                FROM predictions p
                WHERE NOT EXISTS (SELECT 1 FROM ticker_sectors ts WHERE ts.ticker = p.ticker)
                  AND p.ticker IS NOT NULL AND p.ticker != ''
                ON CONFLICT (ticker) DO NOTHING
            """)).rowcount
            _logo_db.commit()

            if filled or inserted:
                print(f"[Startup] Logo backfill: {filled} updated, {inserted} new rows inserted")
            _logo_db.close()
        except Exception as e:
            print(f"[Startup] Logo backfill error: {e}")

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

        # Description backfill — try FMP first (50 tickers), then Polygon (50 more, free)
        if _no_data_count < 1000:
            try:
                from jobs.sector_lookup import backfill_descriptions
                backfill_descriptions()
            except Exception as e:
                print(f"[Startup] FMP description backfill error: {e}")
        else:
            print(f"[Startup] Skipping FMP description backfill — {_no_data_count:,} no_data predictions need FMP budget")
        # Polygon description backfill moved to worker.py — too slow for API startup (50 tickers * 12s = 10 min)
        print("[Startup] Polygon description backfill runs in worker (not API startup)")

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

    # ── Background jobs moved to worker.py (separate Railway service) ──────
    # All scheduled jobs now run in the worker process.
    # API deploys no longer restart background jobs.
    print("[STARTUP] Background jobs run in worker.py (separate service)")
    print("[STARTUP] This API process has NO scheduled jobs")

    yield


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
try:
    os.makedirs(_archive_dir, exist_ok=True)
except PermissionError:
    _archive_dir = "/tmp/archive"
    os.makedirs(_archive_dir, exist_ok=True)
    print(f"[WARNING] Cannot write to /app/archive, using {_archive_dir}")
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
from routers.firms import router as firms_router
app.include_router(firms_router, prefix="/api")
from routers.logo_serve import router as logo_serve_router
app.include_router(logo_serve_router, prefix="/api")
from routers.company_data import router as company_data_router
app.include_router(company_data_router, prefix="/api")


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
        "duels": False, "compete": False, "compare_analysts": False,
        "evaluate_x_predictions": False,
        # Integer 0-100. 0 = YouTube sector-call extraction OFF. The
        # frontend admin overview tab reads this to render the current
        # slider value.
        "youtube_sector_traffic_pct": 0,
        # Boolean: ranked list extraction appends the ranked-list
        # instructions to the Haiku system prompt. Default false.
        "ranked_list_extraction": False,
        # Boolean: target revision detection appends the revisions
        # instructions and links revised predictions via revision_of.
        # Default false.
        "target_revisions": False,
    }
    try:
        rows = db.execute(_ft(
            "SELECT key, value FROM config WHERE key IN ('tournaments_enabled','daily_challenge_enabled','duels_enabled','compete_enabled','compare_analysts_enabled','EVALUATE_X_PREDICTIONS','ENABLE_YOUTUBE_SECTOR_CALLS','ENABLE_RANKED_LIST_EXTRACTION','ENABLE_TARGET_REVISIONS')"
        )).fetchall()
        for r in rows:
            if r[0] == "EVALUATE_X_PREDICTIONS":
                flags["evaluate_x_predictions"] = str(r[1]).strip().lower() == "true"
            elif r[0] == "ENABLE_YOUTUBE_SECTOR_CALLS":
                try:
                    pct = int(str(r[1]).strip())
                except (ValueError, TypeError):
                    pct = 0
                flags["youtube_sector_traffic_pct"] = max(0, min(100, pct))
            elif r[0] == "ENABLE_RANKED_LIST_EXTRACTION":
                flags["ranked_list_extraction"] = str(r[1]).strip().lower() == "true"
            elif r[0] == "ENABLE_TARGET_REVISIONS":
                flags["target_revisions"] = str(r[1]).strip().lower() == "true"
            else:
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


@app.post("/api/admin/toggle-compare-analysts")
def toggle_compare_analysts(admin_id: int = _Depends(_require_admin), db: _Session = _Depends(_get_db)):
    from models import Config
    row = db.query(Config).filter(Config.key == "compare_analysts_enabled").first()
    if row:
        row.value = "false" if row.value == "true" else "true"
    else:
        db.add(Config(key="compare_analysts_enabled", value="true"))
    db.commit()
    new_val = db.query(Config).filter(Config.key == "compare_analysts_enabled").first()
    return {"compare_analysts_enabled": new_val.value == "true" if new_val else False}


@app.post("/api/admin/toggle-evaluate-x")
def toggle_evaluate_x(admin_id: int = _Depends(_require_admin), db: _Session = _Depends(_get_db)):
    from models import Config
    row = db.query(Config).filter(Config.key == "EVALUATE_X_PREDICTIONS").first()
    if row:
        row.value = "false" if str(row.value).strip().lower() == "true" else "true"
    else:
        db.add(Config(key="EVALUATE_X_PREDICTIONS", value="true"))
    db.commit()
    new_val = db.query(Config).filter(Config.key == "EVALUATE_X_PREDICTIONS").first()
    return {
        "evaluate_x_predictions": (
            str(new_val.value).strip().lower() == "true" if new_val else False
        )
    }


@app.post("/api/admin/toggle-ranked-list-extraction")
def toggle_ranked_list_extraction(
    admin_id: int = _Depends(_require_admin),
    db: _Session = _Depends(_get_db),
):
    """Flip ENABLE_RANKED_LIST_EXTRACTION between 'true' and 'false'.
    Invalidates the feature_flags cache so the new value takes effect
    on the next classify_video call instead of waiting 60s for the TTL."""
    from models import Config
    row = db.query(Config).filter(Config.key == "ENABLE_RANKED_LIST_EXTRACTION").first()
    if row:
        row.value = "false" if str(row.value).strip().lower() == "true" else "true"
    else:
        db.add(Config(key="ENABLE_RANKED_LIST_EXTRACTION", value="true"))
    db.commit()
    try:
        from feature_flags import invalidate_ranked_list_flag_cache
        invalidate_ranked_list_flag_cache()
    except Exception:
        pass
    new_val = db.query(Config).filter(Config.key == "ENABLE_RANKED_LIST_EXTRACTION").first()
    return {
        "ranked_list_extraction": (
            str(new_val.value).strip().lower() == "true" if new_val else False
        )
    }


@app.post("/api/admin/toggle-target-revisions")
def toggle_target_revisions(
    admin_id: int = _Depends(_require_admin),
    db: _Session = _Depends(_get_db),
):
    """Flip ENABLE_TARGET_REVISIONS between 'true' and 'false'.
    Invalidates the feature_flags cache so changes take effect on the
    next classify_video call instead of waiting 60s for the TTL."""
    from models import Config
    row = db.query(Config).filter(Config.key == "ENABLE_TARGET_REVISIONS").first()
    if row:
        row.value = "false" if str(row.value).strip().lower() == "true" else "true"
    else:
        db.add(Config(key="ENABLE_TARGET_REVISIONS", value="true"))
    db.commit()
    try:
        from feature_flags import invalidate_target_revisions_flag_cache
        invalidate_target_revisions_flag_cache()
    except Exception:
        pass
    new_val = db.query(Config).filter(Config.key == "ENABLE_TARGET_REVISIONS").first()
    return {
        "target_revisions": (
            str(new_val.value).strip().lower() == "true" if new_val else False
        )
    }


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

        # Firm pages
        firm_rows = db.execute(_st(
            "SELECT DISTINCT firm FROM forecasters WHERE firm IS NOT NULL AND firm != '' "
            "GROUP BY firm HAVING COUNT(*) >= 2 OR SUM(COALESCE(total_predictions, 0)) >= 10 "
            "ORDER BY SUM(COALESCE(total_predictions, 0)) DESC LIMIT 200"
        )).fetchall()
        import re as _slug_re
        for r in firm_rows:
            slug = _slug_re.sub(r'[^a-z0-9]+', '-', r[0].lower().strip()).strip('-')
            urls.append(f"  <url><loc>https://www.eidolum.com/firm/{slug}</loc><lastmod>{today}</lastmod><priority>0.7</priority></url>")

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


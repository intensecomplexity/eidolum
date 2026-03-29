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
from datetime import datetime, timedelta
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


@asynccontextmanager
async def lifespan(app):
    global _scheduler
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
    # One-time data cleanup: remove garbage forecasters, duplicates, benzinga_web junk
    try:
        db = SessionLocal()
        from sqlalchemy import text as _text
        # Delete predictions from garbage forecasters (name > 50 chars)
        r1 = db.execute(_text("DELETE FROM predictions WHERE forecaster_id IN (SELECT id FROM forecasters WHERE LENGTH(name) > 50)"))
        # Delete the garbage forecasters themselves
        r2 = db.execute(_text("DELETE FROM forecasters WHERE LENGTH(name) > 50"))
        # Delete cross-scraper duplicates (keep oldest per ticker+forecaster+direction+date)
        r3 = db.execute(_text("""
            DELETE FROM predictions WHERE id IN (
                SELECT p2.id FROM predictions p1
                JOIN predictions p2 ON p1.ticker = p2.ticker
                    AND p1.forecaster_id = p2.forecaster_id
                    AND p1.direction = p2.direction
                    AND DATE(p1.prediction_date) = DATE(p2.prediction_date)
                    AND p1.id < p2.id
            )
        """))
        db.commit()
        total_cleaned = (r1.rowcount or 0) + (r3.rowcount or 0)
        if total_cleaned > 0:
            print(f"[Startup Cleanup] Removed {r1.rowcount} garbage predictions, {r2.rowcount} garbage forecasters, {r3.rowcount} duplicates")
        db.close()
    except Exception as e:
        print(f"[Startup Cleanup] Error (non-fatal): {e}")

    # Predictions persist between deploys — Layer 3 cleanup handles invalid ones hourly
    # Seed forecasters (keep existing, add missing)
    try:
        db = SessionLocal()
        from jobs.seed_magazines import seed_magazine_forecasters
        seed_magazine_forecasters(db)
        db.close()
    except Exception as e:
        print(f"[Eidolum] Magazine seed error (non-fatal): {e}")
    # Merge duplicate forecasters (same firm, different names)
    try:
        db = SessionLocal()
        from jobs.news_scraper import merge_duplicate_forecasters
        merge_duplicate_forecasters(db)
        db.close()
    except Exception as e:
        print(f"[Eidolum] Forecaster merge error (non-fatal): {e}")
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
            active_scrapers = []
            # Finnhub news (primary)
            try:
                from jobs.news_scraper import scrape_news_predictions
                scrape_news_predictions(db)
                active_scrapers.append("news_scraper")
            except Exception as e:
                print(f"[Background] News scraper error: {e}")
            # Benzinga API
            try:
                from jobs.benzinga_scraper import scrape_benzinga_ratings
                scrape_benzinga_ratings(db)
                active_scrapers.append("benzinga_api")
            except Exception as e:
                print(f"[Background] Benzinga error: {e}")
            # FMP upgrades
            try:
                from jobs.upgrade_scrapers import scrape_fmp_upgrades
                scrape_fmp_upgrades(db)
                active_scrapers.append("fmp_upgrades")
            except Exception as e:
                print(f"[Background] FMP upgrades error: {e}")
            # FMP price targets
            try:
                from jobs.upgrade_scrapers import scrape_fmp_price_targets
                scrape_fmp_price_targets(db)
                active_scrapers.append("fmp_price_targets")
            except Exception as e:
                print(f"[Background] FMP price targets error: {e}")
            # FMP daily grades
            try:
                from jobs.upgrade_scrapers import scrape_fmp_daily_grades
                scrape_fmp_daily_grades(db)
                active_scrapers.append("fmp_daily_grades")
            except Exception as e:
                print(f"[Background] FMP daily grades error: {e}")
            # Benzinga web scraper — DISABLED (produces garbage data)
            # try:
            #     from jobs.benzinga_web_scraper import scrape_benzinga_web
            #     scrape_benzinga_web(db)
            #     active_scrapers.append("benzinga_web")
            # except Exception as e:
            #     print(f"[Background] Benzinga web error: {e}")
            # NewsAPI
            try:
                from jobs.news_scraper import scrape_newsapi
                scrape_newsapi(db)
                active_scrapers.append("newsapi")
            except Exception as e:
                print(f"[Background] NewsAPI error: {e}")
            # yfinance recommendations
            try:
                from jobs.rss_scrapers import scrape_yfinance_recommendations
                scrape_yfinance_recommendations(db)
                active_scrapers.append("yfinance")
            except Exception as e:
                print(f"[Background] yfinance error: {e}")
            # Layer 3 cleanup
            try:
                from jobs.prediction_validator import cleanup_invalid_predictions
                cleanup_invalid_predictions(db)
            except Exception as e:
                print(f"[Background] L3 cleanup error: {e}")
            pred_count = db.query(Prediction).count()
            print(f"[Eidolum] Background import complete — {pred_count} predictions. Active: {', '.join(active_scrapers)}")
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
    # Phase 2 schema: users, predictions, achievements, follows, duels, seasons
    try:
        run_phase2_migrations()
    except Exception as e:
        print(f"[Eidolum] Phase 2 migration error (non-fatal): {e}")
    # Ensure a season exists for the current quarter
    try:
        from seasons import ensure_current_season as _ecs
        _db = SessionLocal()
        _ecs(_db)
        _db.close()
    except Exception as e:
        print(f"[Eidolum] Season init error (non-fatal): {e}")
    # Ensure daily challenge exists on startup
    try:
        from jobs.daily_challenge import ensure_daily_challenge_exists
        _db = SessionLocal()
        ensure_daily_challenge_exists(_db)
        _db.close()
    except Exception as e:
        print(f"[Eidolum] Daily challenge startup error (non-fatal): {e}")
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
    from admin_panel import scheduler_last_run

    def run_fast_scraper():
        from datetime import datetime as _dt
        print(f"[Scheduler] Running fast scraper at {_dt.utcnow()}")
        scheduler_last_run["fast_scraper"] = _dt.utcnow()
        from jobs.news_scraper import scrape_fast_predictions
        db = SessionLocal()
        try:
            scrape_fast_predictions(db)
        except Exception as e:
            print(f"[FastScraper] Error: {e}")
        finally:
            db.close()

    def run_hourly_scraper():
        from datetime import datetime as _dt
        print(f"[Scheduler] Running full scraper at {_dt.utcnow()}")
        scheduler_last_run["full_scraper"] = _dt.utcnow()
        db = SessionLocal()
        try:
            run_scraper(db)
        finally:
            db.close()

    def run_15min_evaluator():
        from datetime import datetime as _dt
        print(f"[Scheduler] Running evaluator at {_dt.utcnow()}")
        scheduler_last_run["evaluator"] = _dt.utcnow()
        db = SessionLocal()
        try:
            run_evaluator(db)
        finally:
            db.close()

    def run_15min_user_evaluator():
        from datetime import datetime as _dt
        print(f"[Scheduler] Running user evaluator at {_dt.utcnow()}")
        scheduler_last_run["user_evaluator"] = _dt.utcnow()
        db = SessionLocal()
        try:
            results = evaluate_user_predictions(db)
            print(f"[Scheduler] User evaluator completed: {len(results or [])} predictions scored")
        except Exception as e:
            print(f"[Scheduler] USER EVALUATOR FAILED: {e}")
            import traceback
            traceback.print_exc()
        finally:
            db.close()

    def run_15min_duel_evaluator():
        from datetime import datetime as _dt
        print(f"[Scheduler] Running duel evaluator at {_dt.utcnow()}")
        scheduler_last_run["duel_evaluator"] = _dt.utcnow()
        db = SessionLocal()
        try:
            evaluate_duels(db)
        finally:
            db.close()

    def run_hourly_season_check():
        from datetime import datetime as _dt
        print(f"[Scheduler] Running season check at {_dt.utcnow()}")
        scheduler_last_run["season_check"] = _dt.utcnow()
        db = SessionLocal()
        try:
            check_season_completion(db)
        finally:
            db.close()

    def run_fmp_upgrades():
        from datetime import datetime as _dt
        print(f"[Scheduler] Running FMP upgrades at {_dt.utcnow()}")
        scheduler_last_run["fmp_upgrades"] = _dt.utcnow()
        db = SessionLocal()
        try:
            from jobs.upgrade_scrapers import scrape_fmp_upgrades
            scrape_fmp_upgrades(db)
        except Exception as e:
            print(f"[FMP] Error: {e}")
        finally:
            db.close()

    def run_fmp_price_targets():
        from datetime import datetime as _dt
        print(f"[Scheduler] Running FMP price targets at {_dt.utcnow()}")
        scheduler_last_run["fmp_price_targets"] = _dt.utcnow()
        db = SessionLocal()
        try:
            from jobs.upgrade_scrapers import scrape_fmp_price_targets
            scrape_fmp_price_targets(db)
        except Exception as e:
            print(f"[FMP-PT] Error: {e}")
        finally:
            db.close()

    def run_fmp_daily_grades():
        from datetime import datetime as _dt
        print(f"[Scheduler] Running FMP daily grades at {_dt.utcnow()}")
        scheduler_last_run["fmp_daily_grades"] = _dt.utcnow()
        db = SessionLocal()
        try:
            from jobs.upgrade_scrapers import scrape_fmp_daily_grades
            scrape_fmp_daily_grades(db)
        except Exception as e:
            print(f"[FMP-Daily] Error: {e}")
        finally:
            db.close()

    def run_yfinance():
        from datetime import datetime as _dt
        print(f"[Scheduler] Running yfinance at {_dt.utcnow()}")
        scheduler_last_run["yfinance"] = _dt.utcnow()
        db = SessionLocal()
        try:
            from jobs.rss_scrapers import scrape_yfinance_recommendations
            scrape_yfinance_recommendations(db)
        except Exception as e:
            print(f"[yfinance] Error: {e}")
        finally:
            db.close()

    def run_benzinga_api():
        from datetime import datetime as _dt
        print(f"[Scheduler] Running Benzinga API at {_dt.utcnow()}")
        scheduler_last_run["benzinga_api"] = _dt.utcnow()
        db = SessionLocal()
        try:
            from jobs.benzinga_scraper import scrape_benzinga_ratings
            scrape_benzinga_ratings(db)
        except Exception as e:
            print(f"[Benzinga] Error: {e}")
        finally:
            db.close()

    def run_benzinga_web():
        from datetime import datetime as _dt
        print(f"[Scheduler] Running Benzinga Web at {_dt.utcnow()}")
        scheduler_last_run["benzinga_web"] = _dt.utcnow()
        db = SessionLocal()
        try:
            from jobs.benzinga_web_scraper import scrape_benzinga_web
            scrape_benzinga_web(db)
        except Exception as e:
            print(f"[BenzingaWeb] Error: {e}")
        finally:
            db.close()

    def run_newsapi():
        from datetime import datetime as _dt
        print(f"[Scheduler] Running NewsAPI at {_dt.utcnow()}")
        scheduler_last_run["newsapi"] = _dt.utcnow()
        db = SessionLocal()
        try:
            from jobs.news_scraper import scrape_newsapi
            scrape_newsapi(db)
        except Exception as e:
            print(f"[NewsAPI] Error: {e}")
        finally:
            db.close()

    print("[STARTUP] Scheduler starting...")
    scheduler = AsyncIOScheduler()
    _scheduler = scheduler
    # Core scrapers
    scheduler.add_job(run_hourly_scraper, "interval", hours=1, id="scraper")
    scheduler.add_job(run_fast_scraper, "interval", minutes=15, id="fast_scraper")
    scheduler.add_job(run_benzinga_api, "interval", hours=2, id="benzinga_api", next_run_time=datetime.utcnow() + timedelta(minutes=15))
    scheduler.add_job(run_newsapi, "interval", hours=4, id="newsapi", next_run_time=datetime.utcnow() + timedelta(minutes=10))
    # DISABLED: benzinga_web produces garbage data (bad firm names, duplicates of API data)
    # scheduler.add_job(run_benzinga_web, "interval", hours=2, id="benzinga_web", next_run_time=datetime.utcnow() + timedelta(minutes=25))

    # Massive API — Benzinga ratings
    def run_massive_benzinga():
        from datetime import datetime as _dt
        print(f"[Scheduler] Running Massive Benzinga at {_dt.utcnow()}")
        db = SessionLocal()
        try:
            from jobs.massive_benzinga import scrape_massive_ratings
            scrape_massive_ratings(db)
        except Exception as e:
            print(f"[MassiveBZ] Scheduler error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            db.close()

    scheduler.add_job(run_massive_benzinga, "interval", hours=2, id="massive_benzinga", next_run_time=datetime.utcnow() + timedelta(minutes=20))

    # FMP structured data
    scheduler.add_job(run_fmp_upgrades, "interval", hours=2, id="fmp_upgrades", next_run_time=datetime.utcnow() + timedelta(minutes=30))
    scheduler.add_job(run_fmp_price_targets, "interval", hours=2, id="fmp_price_targets", next_run_time=datetime.utcnow() + timedelta(minutes=60))
    scheduler.add_job(run_fmp_daily_grades, "interval", hours=3, id="fmp_daily_grades", next_run_time=datetime.utcnow() + timedelta(minutes=90))
    # yfinance
    scheduler.add_job(run_yfinance, "interval", hours=3, id="yfinance", next_run_time=datetime.utcnow() + timedelta(minutes=120))
    # Evaluator + leaderboard
    scheduler.add_job(run_15min_evaluator, "interval", minutes=15, id="evaluator")
    scheduler.add_job(run_15min_user_evaluator, "interval", minutes=15, id="user_evaluator", next_run_time=datetime.utcnow() + timedelta(seconds=30))
    scheduler.add_job(run_15min_duel_evaluator, "interval", minutes=15, id="duel_evaluator")
    scheduler.add_job(run_hourly_season_check, "interval", hours=1, id="season_check")

    # Daily challenge jobs (EST times)
    def run_create_daily_challenge():
        from datetime import datetime as _dt
        print(f"[Scheduler] Creating daily challenge at {_dt.utcnow()}")
        scheduler_last_run["daily_challenge_create"] = _dt.utcnow()
        db = SessionLocal()
        try:
            from jobs.daily_challenge import create_daily_challenge
            create_daily_challenge(db)
        except Exception as e:
            print(f"[DailyChallenge] Create error: {e}")
        finally:
            db.close()

    def run_score_daily_challenge():
        from datetime import datetime as _dt
        print(f"[Scheduler] Scoring daily challenge at {_dt.utcnow()}")
        scheduler_last_run["daily_challenge_score"] = _dt.utcnow()
        db = SessionLocal()
        try:
            from jobs.daily_challenge import score_daily_challenge
            score_daily_challenge(db)
        except Exception as e:
            print(f"[DailyChallenge] Score error: {e}")
        finally:
            db.close()

    # Weekday: create at 14:30 UTC (9:30 AM EST)
    scheduler.add_job(run_create_daily_challenge, "cron", hour=14, minute=30, id="daily_challenge_create_weekday", day_of_week="mon-fri")
    # Weekend: create crypto challenge at 00:05 UTC
    scheduler.add_job(run_create_daily_challenge, "cron", hour=0, minute=5, id="daily_challenge_create_weekend", day_of_week="sat,sun")
    # Weekday stock scoring: 21:30 UTC (4:30 PM EST)
    scheduler.add_job(run_score_daily_challenge, "cron", hour=21, minute=30, id="daily_challenge_score_weekday", day_of_week="mon-fri")
    # Crypto scoring (weekdays + weekends): 23:55 UTC
    scheduler.add_job(run_score_daily_challenge, "cron", hour=23, minute=55, id="daily_challenge_score_crypto")

    # Price alerts — every 30 min during market hours
    def run_price_alerts():
        from datetime import datetime as _dt
        print(f"[Scheduler] Running price alerts at {_dt.utcnow()}")
        scheduler_last_run["price_alerts"] = _dt.utcnow()
        db = SessionLocal()
        try:
            from jobs.price_alerts import check_price_alerts
            check_price_alerts(db)
        except Exception as e:
            print(f"[PriceAlerts] Error: {e}")
        finally:
            db.close()

    scheduler.add_job(run_price_alerts, "interval", minutes=30, id="price_alerts")

    def run_hourly_leaderboard():
        from datetime import datetime as _dt
        scheduler_last_run["leaderboard"] = _dt.utcnow()
        db = SessionLocal()
        try:
            run_leaderboard_refresh(db)
        finally:
            db.close()

    scheduler.add_job(run_hourly_leaderboard, "interval", hours=1, id="leaderboard")
    scheduler.add_job(lambda: run_newsletter(SessionLocal()), "cron", hour=8, minute=0, id="newsletter")

    # Weekly digest — Sundays at 10:00 UTC
    def run_weekly_digest():
        from datetime import datetime as _dt
        print(f"[Scheduler] Running weekly digest at {_dt.utcnow()}")
        scheduler_last_run["weekly_digest"] = _dt.utcnow()
        db = SessionLocal()
        try:
            from jobs.weekly_digest import send_weekly_digest
            send_weekly_digest(db)
        except Exception as e:
            print(f"[WeeklyDigest] Error: {e}")
        finally:
            db.close()

    scheduler.add_job(run_weekly_digest, "cron", day_of_week="sun", hour=10, minute=0, id="weekly_digest")

    # Earnings calendar — daily at midnight UTC
    def run_earnings_update():
        from datetime import datetime as _dt
        print(f"[Scheduler] Updating earnings at {_dt.utcnow()}")
        scheduler_last_run["earnings"] = _dt.utcnow()
        db = SessionLocal()
        try:
            from jobs.earnings import update_earnings_calendar
            update_earnings_calendar(db)
        except Exception as e:
            print(f"[Earnings] Error: {e}")
        finally:
            db.close()

    scheduler.add_job(run_earnings_update, "cron", hour=0, minute=15, id="earnings_update")

    # Analyst subscription notifications — every hour
    from jobs.analyst_notifications import run_analyst_notifications
    scheduler.add_job(run_analyst_notifications, "interval", hours=1, id="analyst_notifications", next_run_time=datetime.utcnow() + timedelta(minutes=45))

    # Weekly challenge — create every Monday at 00:01 UTC
    def run_weekly_challenge():
        db = SessionLocal()
        try:
            from weekly_challenges import create_weekly_challenge
            create_weekly_challenge(db)
        except Exception as e:
            print(f"[WeeklyChallenge] Error: {e}")
        finally:
            db.close()

    scheduler.add_job(run_weekly_challenge, "cron", day_of_week="mon", hour=0, minute=1, id="weekly_challenge")

    scheduler.start()
    job_ids = [j.id for j in scheduler.get_jobs()]
    print(f"[STARTUP] {len(job_ids)} jobs registered: {', '.join(job_ids)}")
    for j in scheduler.get_jobs():
        print(f"[STARTUP]   {j.id}: next_run={j.next_run_time}")
    print(f"[STARTUP] FINNHUB_KEY set: {bool(os.getenv('FINNHUB_KEY', '').strip())}")
    print(f"[STARTUP] User evaluator will run in ~30s")
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


@app.post("/api/admin/run-massive-benzinga")
def run_massive_benzinga_now():
    """Run the Massive Benzinga scraper immediately and return results."""
    import traceback as _tb
    db = SessionLocal()
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


@app.post("/api/admin/run-user-evaluator")
def run_user_evaluator_now():
    """Run the user prediction evaluator immediately and return results."""
    import traceback as _tb
    db = SessionLocal()
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

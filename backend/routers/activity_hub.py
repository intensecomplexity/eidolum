"""
Activity hub endpoints — powers the unified Activity page.
Four feeds: recent predictions, recently scored, expiring, and friend activity.
"""
import datetime
from fastapi import APIRouter, Depends, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
from typing import Optional

from database import get_db
from rate_limit import limiter
from auth import get_current_user as _decode_token

router = APIRouter()
_optional_bearer = HTTPBearer(auto_error=False)


# ── GET /api/activity/recent-predictions ────────────────────────────────────


@router.get("/activity/recent-predictions")
@limiter.limit("60/minute")
def recent_predictions(request: Request, db: Session = Depends(get_db)):
    """Most recent analyst predictions submitted."""
    rows = db.execute(sql_text("""
        SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
               p.prediction_date, p.window_days, p.context, p.exact_quote,
               p.created_at,
               f.id AS fid, f.name AS fname, f.accuracy_score,
               ts.company_name
        FROM predictions p
        JOIN forecasters f ON f.id = p.forecaster_id
        LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker
        ORDER BY p.created_at DESC
        LIMIT 20
    """)).fetchall()

    return [
        {
            "id": r[0], "ticker": r[1], "direction": r[2],
            "target_price": float(r[3]) if r[3] else None,
            "entry_price": float(r[4]) if r[4] else None,
            "prediction_date": r[5].isoformat() if r[5] else None,
            "window_days": r[6],
            "context": (r[7] or r[8] or "")[:200],
            "created_at": r[9].isoformat() if r[9] else None,
            "forecaster_id": r[10], "forecaster_name": r[11],
            "accuracy": round(float(r[12]), 1) if r[12] else None,
            "company_name": r[13],
            "type": "prediction",
        }
        for r in rows
    ]


# ── GET /api/activity/recently-scored ───────────────────────────────────────


@router.get("/activity/recently-scored")
@limiter.limit("60/minute")
def recently_scored(request: Request, db: Session = Depends(get_db)):
    """Recently evaluated predictions (only those predicted in the last 6 months)."""
    rows = db.execute(sql_text("""
        SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
               p.outcome, p.actual_return, p.evaluation_date, p.prediction_date,
               p.context, p.exact_quote,
               f.id AS fid, f.name AS fname, f.accuracy_score,
               ts.company_name
        FROM predictions p
        JOIN forecasters f ON f.id = p.forecaster_id
        LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker
        WHERE p.outcome IN ('hit', 'near', 'miss', 'correct', 'incorrect')
          AND p.prediction_date > NOW() - INTERVAL '6 months'
        ORDER BY p.evaluation_date DESC NULLS LAST
        LIMIT 20
    """)).fetchall()

    return [
        {
            "id": r[0], "ticker": r[1], "direction": r[2],
            "target_price": float(r[3]) if r[3] else None,
            "entry_price": float(r[4]) if r[4] else None,
            "outcome": r[5],
            "actual_return": round(float(r[6]), 1) if r[6] is not None else None,
            "evaluation_date": r[7].isoformat() if r[7] else None,
            "prediction_date": r[8].isoformat() if r[8] else None,
            "context": (r[9] or r[10] or "")[:200],
            "forecaster_id": r[11], "forecaster_name": r[12],
            "accuracy": round(float(r[13]), 1) if r[13] else None,
            "company_name": r[14],
            "type": "scored",
        }
        for r in rows
    ]


# ── GET /api/activity/expiring ──────────────────────────────────────────────


@router.get("/activity/expiring")
@limiter.limit("60/minute")
def expiring_predictions(request: Request, db: Session = Depends(get_db)):
    """Analyst predictions expiring soonest."""
    rows = db.execute(sql_text("""
        SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
               p.evaluation_date, p.prediction_date, p.window_days,
               p.context, p.exact_quote,
               f.id AS fid, f.name AS fname, f.accuracy_score,
               ts.company_name
        FROM predictions p
        JOIN forecasters f ON f.id = p.forecaster_id
        LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker
        WHERE p.outcome = 'pending'
          AND p.evaluation_date IS NOT NULL
          AND p.evaluation_date > NOW()
        ORDER BY p.evaluation_date ASC
        LIMIT 20
    """)).fetchall()

    now = datetime.datetime.utcnow()
    return [
        {
            "id": r[0], "ticker": r[1], "direction": r[2],
            "target_price": float(r[3]) if r[3] else None,
            "entry_price": float(r[4]) if r[4] else None,
            "evaluation_date": r[5].isoformat() if r[5] else None,
            "prediction_date": r[6].isoformat() if r[6] else None,
            "window_days": r[7],
            "context": (r[8] or r[9] or "")[:200],
            "days_remaining": max(0, (r[5] - now).days) if r[5] else None,
            "forecaster_id": r[10], "forecaster_name": r[11],
            "accuracy": round(float(r[12]), 1) if r[12] else None,
            "company_name": r[13],
            "type": "expiring",
        }
        for r in rows
    ]


# ── GET /api/activity/friends ───────────────────────────────────────────────


@router.get("/activity/friends")
@limiter.limit("60/minute")
def friend_activity(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    db: Session = Depends(get_db),
):
    """Recent predictions from users that the current user follows."""
    current_user_id = None
    if credentials and credentials.credentials:
        try:
            data = _decode_token(credentials.credentials)
            current_user_id = data.get("user_id")
        except Exception:
            pass

    if not current_user_id:
        return []

    # Get followed user IDs
    from models import Follow
    following_ids = [
        f.following_id
        for f in db.query(Follow.following_id).filter(Follow.follower_id == current_user_id).all()
    ]

    if not following_ids:
        return []

    rows = db.execute(sql_text("""
        SELECT up.id, up.ticker, up.direction, up.price_target, up.price_at_call,
               up.outcome, up.created_at, up.expires_at, up.evaluated_at,
               up.evaluation_window_days,
               u.id AS uid, u.username, u.user_type,
               ts.company_name
        FROM user_predictions up
        JOIN users u ON u.id = up.user_id
        LEFT JOIN ticker_sectors ts ON ts.ticker = up.ticker
        WHERE up.user_id = ANY(:friend_ids)
          AND up.deleted_at IS NULL
        ORDER BY up.created_at DESC
        LIMIT 20
    """), {"friend_ids": following_ids}).fetchall()

    now = datetime.datetime.utcnow()
    return [
        {
            "id": r[0], "ticker": r[1], "direction": r[2],
            "target_price": float(r[3]) if r[3] else None,
            "entry_price": float(r[4]) if r[4] else None,
            "outcome": r[5],
            "created_at": r[6].isoformat() if r[6] else None,
            "expires_at": r[7].isoformat() if r[7] else None,
            "evaluated_at": r[8].isoformat() if r[8] else None,
            "window_days": r[9],
            "user_id": r[10], "username": r[11],
            "user_type": r[12] or "player",
            "company_name": r[13],
            "type": "friend",
        }
        for r in rows
    ]

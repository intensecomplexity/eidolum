import json
from fastapi import APIRouter, Depends, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from models import ActivityEvent, User, Follow
from rate_limit import limiter
from auth import get_current_user as _decode_token

router = APIRouter()
_optional_bearer = HTTPBearer(auto_error=False)

# Only show prediction-related events in the public feed
FEED_EVENT_TYPES = ("prediction_submitted", "prediction_scored")


def _rank_name(scored: int) -> str:
    if scored >= 250: return "Legendary"
    if scored >= 100: return "Oracle"
    if scored >= 50: return "Strategist"
    if scored >= 25: return "Analyst"
    if scored >= 10: return "Novice"
    return "Unranked"


def _event_dict(e: ActivityEvent, user: User | None) -> dict:
    return {
        "id": e.id,
        "event_type": e.event_type,
        "description": e.description,
        "ticker": e.ticker,
        "data": json.loads(e.data) if e.data else None,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "user_id": e.user_id,
        "username": user.username if user else None,
        "user_type": (user.user_type or "player") if user else "player",
    }


@router.get("/feed/global")
@limiter.limit("60/minute")
def global_feed(
    request: Request,
    before: Optional[int] = Query(None),
    ticker: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(ActivityEvent).filter(ActivityEvent.event_type.in_(FEED_EVENT_TYPES))

    if before:
        query = query.filter(ActivityEvent.id < before)
    if ticker:
        query = query.filter(ActivityEvent.ticker == ticker.upper())

    events = query.order_by(ActivityEvent.created_at.desc()).limit(50).all()

    user_ids = set(e.user_id for e in events)
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}

    return [_event_dict(e, users.get(e.user_id)) for e in events]


@router.get("/feed/following")
@limiter.limit("60/minute")
def following_feed(
    request: Request,
    before: Optional[int] = Query(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    db: Session = Depends(get_db),
):
    current_user_id = None
    if credentials and credentials.credentials:
        try:
            data = _decode_token(credentials.credentials)
            current_user_id = data.get("user_id")
        except Exception:
            pass

    following_ids = []
    if current_user_id:
        following_ids = [
            f.following_id
            for f in db.query(Follow.following_id).filter(Follow.follower_id == current_user_id).all()
        ]

    query = db.query(ActivityEvent).filter(ActivityEvent.event_type.in_(FEED_EVENT_TYPES))

    if following_ids:
        query = query.filter(ActivityEvent.user_id.in_(following_ids))

    if before:
        query = query.filter(ActivityEvent.id < before)

    events = query.order_by(ActivityEvent.created_at.desc()).limit(50).all()

    user_ids = set(e.user_id for e in events)
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}

    return [_event_dict(e, users.get(e.user_id)) for e in events]

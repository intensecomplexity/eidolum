"""
Online status tracker — updates last_seen_at for authenticated users.
Uses a lightweight cache to avoid DB writes on every request.
Only updates if last update was more than 2 minutes ago.
A user is "online" if last_seen_at is within the last 5 minutes.
"""
import time
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import User

_last_updated: dict[int, float] = {}
_UPDATE_INTERVAL = 120  # seconds (2 minutes)
ONLINE_THRESHOLD = 300  # seconds (5 minutes)


def update_last_seen(user_id: int, db: Session):
    """Update last_seen_at if not recently updated."""
    now = time.time()
    last = _last_updated.get(user_id, 0)
    if now - last < _UPDATE_INTERVAL:
        return

    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.last_seen_at = datetime.utcnow()
            db.commit()
    except Exception:
        db.rollback()

    _last_updated[user_id] = now


def is_online(user) -> bool:
    """Check if a user is online (last_seen_at within 5 minutes)."""
    if not user or not user.last_seen_at:
        return False
    return (datetime.utcnow() - user.last_seen_at).total_seconds() < ONLINE_THRESHOLD


def last_seen_text(user) -> str:
    """Return human-readable last seen text."""
    if not user or not user.last_seen_at:
        return ""
    if is_online(user):
        return "Online now"
    diff = (datetime.utcnow() - user.last_seen_at).total_seconds()
    if diff < 3600:
        return f"Last seen {int(diff / 60)}m ago"
    if diff < 86400:
        return f"Last seen {int(diff / 3600)}h ago"
    return f"Last seen {int(diff / 86400)}d ago"

"""
Notification helper — creates notification records.
Import and call create_notification() from anywhere in the backend.
"""
import json
from sqlalchemy.orm import Session
from models import Notification


def create_notification(
    user_id: int,
    type: str,
    title: str,
    message: str,
    data: dict | None = None,
    db: Session = None,
):
    """Insert a notification row. Caller must commit the session."""
    notif = Notification(
        user_id=user_id,
        type=type,
        title=title,
        message=message,
        data=json.dumps(data) if data else None,
    )
    if db:
        db.add(notif)
    return notif

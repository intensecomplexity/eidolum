"""
Activity feed helper — logs public events.
"""
import json
from sqlalchemy.orm import Session
from models import ActivityEvent


def log_activity(
    user_id: int,
    event_type: str,
    description: str,
    ticker: str | None = None,
    data: dict | None = None,
    db: Session = None,
):
    event = ActivityEvent(
        user_id=user_id,
        event_type=event_type,
        ticker=ticker,
        description=description,
        data=json.dumps(data) if data else None,
    )
    if db:
        db.add(event)
    return event

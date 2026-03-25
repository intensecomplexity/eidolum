from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from database import get_db
from models import ActivityFeedItem
from rate_limit import limiter

router = APIRouter()


@router.get("/activity-feed")
@limiter.limit("60/minute")
def get_activity_feed(
    request: Request,
    db: Session = Depends(get_db),
    limit: int = Query(30, le=100),
):
    items = (
        db.query(ActivityFeedItem)
        .order_by(ActivityFeedItem.timestamp.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": item.id,
            "event_type": item.event_type,
            "forecaster_id": item.forecaster_id,
            "ticker": item.ticker,
            "direction": item.direction,
            "outcome": item.outcome,
            "actual_return": item.actual_return,
            "message": item.message,
            "rank_from": item.rank_from,
            "rank_to": item.rank_to,
            "timestamp": item.timestamp.isoformat(),
        }
        for item in items
    ]

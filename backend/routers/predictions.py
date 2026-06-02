from datetime import datetime
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from models import Prediction, Forecaster
from utils import append_youtube_timestamp
from services.prediction_visibility import yt_visible_filter
from routers._prediction_filters import hedged_filter_clause, reported_speech_filter_clause
from rate_limit import limiter

router = APIRouter()

# User-facing visibility policy: hide NULL-timestamp YouTube rows
# (2026-04-18 policy). not_excluded_filter and non_qwen_filter were
# previously folded in here but are training-data filters, not user
# filters — removing them recovers 348K legitimate Wall St rating
# rows on user-facing feeds.
_VISIBLE = text(yt_visible_filter('predictions'))

# T2 hedged/hypothetical filter (2026-06-02 sweep completion). No-op when
# HIDE_HEDGED_PREDICTIONS is off, so the .filter() call is unconditional.
_HEDGED = hedged_filter_clause(Prediction.conviction_level)
# Reported-speech filter (2026-06-02 audit). No-op when
# HIDE_REPORTED_SPEECH is off. Chained alongside _HEDGED at each call site.
_NOT_REPORTED = reported_speech_filter_clause(Prediction.is_reported_speech)


@router.get("/predictions/today")
@limiter.limit("60/minute")
def get_today_predictions(request: Request, db: Session = Depends(get_db)):
    """Get today's newest predictions for the Live Activity feed."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    predictions = (
        db.query(Prediction)
        .filter(Prediction.prediction_date >= today_start)
        .filter(_VISIBLE)
        .filter(_HEDGED)
        .filter(_NOT_REPORTED)
        .order_by(Prediction.prediction_date.desc())
        .limit(5)
        .all()
    )

    # If no predictions today, show the 5 most recent overall
    if not predictions:
        predictions = (
            db.query(Prediction)
            .filter(_VISIBLE)
            .filter(_HEDGED)
            .filter(_NOT_REPORTED)
            .order_by(Prediction.prediction_date.desc())
            .limit(5)
            .all()
        )

    results = []
    for p in predictions:
        forecaster = db.query(Forecaster).filter(Forecaster.id == p.forecaster_id).first()
        results.append({
            "id": p.id,
            "ticker": p.ticker,
            "direction": p.direction,
            "context": p.context,
            "source_url": append_youtube_timestamp(p.source_url, p.source_type, p.source_timestamp_seconds, p.video_timestamp_sec),
            "archive_url": p.archive_url,
            "prediction_date": p.prediction_date.isoformat() if p.prediction_date else None,
            "forecaster_name": forecaster.name if forecaster else "Unknown",
            "forecaster_id": p.forecaster_id,
            "outcome": p.outcome,
            "source_type": p.source_type,
            "verified_by": p.verified_by,
        })

    return results


@router.get("/predictions/recent")
@limiter.limit("60/minute")
def get_recent_predictions(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    ticker: str = Query(None),
    direction: str = Query(None),
    db: Session = Depends(get_db),
):
    """Get all recent predictions, paginated, newest first."""
    query = db.query(Prediction).filter(_VISIBLE).filter(_HEDGED).filter(_NOT_REPORTED)

    if ticker:
        query = query.filter(Prediction.ticker == ticker.upper())
    if direction and direction in ("bullish", "bearish"):
        query = query.filter(Prediction.direction == direction)

    total = query.count()
    offset = (page - 1) * per_page

    predictions = (
        query
        .order_by(Prediction.prediction_date.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )

    results = []
    for p in predictions:
        forecaster = db.query(Forecaster).filter(Forecaster.id == p.forecaster_id).first()
        results.append({
            "id": p.id,
            "ticker": p.ticker,
            "direction": p.direction,
            "context": p.context,
            "source_url": append_youtube_timestamp(p.source_url, p.source_type, p.source_timestamp_seconds, p.video_timestamp_sec),
            "archive_url": p.archive_url,
            "prediction_date": p.prediction_date.isoformat() if p.prediction_date else None,
            "forecaster_name": forecaster.name if forecaster else "Unknown",
            "forecaster_id": p.forecaster_id,
            "outcome": p.outcome,
            "target_price": p.target_price,
            "window_days": p.window_days,
            "source_type": p.source_type,
            "verified_by": p.verified_by,
        })

    return {
        "predictions": results,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }

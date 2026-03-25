import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import get_db
from models import Forecaster, Prediction, format_timestamp, get_youtube_timestamp_url, DisclosedPosition
from utils import compute_forecaster_stats, compute_streak
from rate_limit import limiter

router = APIRouter()


@router.get("/forecasters")
@limiter.limit("60/minute")
def list_forecasters(request: Request, db: Session = Depends(get_db)):
    forecasters = db.query(Forecaster).order_by(Forecaster.name).all()
    return [
        {
            "id": f.id,
            "name": f.name,
            "handle": f.handle,
            "channel_url": f.channel_url,
            "subscriber_count": f.subscriber_count,
            "profile_image_url": f.profile_image_url,
        }
        for f in forecasters
    ]


@router.get("/forecaster/{forecaster_id}")
@limiter.limit("30/minute")
def get_forecaster(request: Request, forecaster_id: int, db: Session = Depends(get_db)):
    f = db.query(Forecaster).filter(Forecaster.id == forecaster_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Forecaster not found")

    stats = compute_forecaster_stats(f, db)
    streak = compute_streak(f.id, db)
    predictions = (
        db.query(Prediction)
        .filter(Prediction.forecaster_id == f.id)
        .filter(Prediction.outcome != "pending_review")
        .order_by(Prediction.prediction_date.desc())
        .all()
    )

    # Build cumulative accuracy over time
    sorted_preds = sorted(
        [p for p in predictions if p.outcome != "pending"],
        key=lambda p: p.prediction_date,
    )
    accuracy_over_time = []
    correct = 0
    total = 0
    for p in sorted_preds:
        total += 1
        if p.outcome == "correct":
            correct += 1
        accuracy_over_time.append({
            "date": p.prediction_date.strftime("%Y-%m-%d"),
            "cumulative_accuracy": round(correct / total * 100, 1),
            "ticker": p.ticker,
            "direction": p.direction,
            "outcome": p.outcome,
        })

    return {
        "id": f.id,
        "name": f.name,
        "handle": f.handle,
        "platform": f.platform or "youtube",
        "channel_url": f.channel_url,
        "subscriber_count": f.subscriber_count,
        "profile_image_url": f.profile_image_url,
        "bio": f.bio,
        "streak": streak,
        **stats,
        "predictions": [
            {
                "id": p.id,
                "ticker": p.ticker,
                "direction": p.direction,
                "target_price": p.target_price,
                "entry_price": p.entry_price,
                "prediction_date": p.prediction_date.isoformat(),
                "evaluation_date": (
                    p.evaluation_date.isoformat() if p.evaluation_date
                    else (p.prediction_date + datetime.timedelta(days=p.window_days)).isoformat()
                ),
                "window_days": p.window_days,
                "time_horizon": getattr(p, "time_horizon", None) or (
                    "short" if p.window_days <= 30
                    else "long" if p.window_days >= 365
                    else "medium"
                ),
                "outcome": p.outcome,
                "actual_return": p.actual_return,
                "sp500_return": p.sp500_return,
                "alpha": p.alpha,
                "sector": p.sector,
                "context": p.context,
                "exact_quote": p.exact_quote,
                "source_url": p.source_url,
                "archive_url": p.archive_url,
                "source_type": p.source_type,
                "source_title": p.source_title,
                "source_platform_id": p.source_platform_id,
                "video_timestamp_sec": p.video_timestamp_sec,
                "verified_by": p.verified_by,
                "timestamp_display": format_timestamp(p.video_timestamp_sec),
                "timestamp_url": get_youtube_timestamp_url(p.source_platform_id, p.video_timestamp_sec),
                "has_conflict": bool(p.has_conflict),
                "conflict_note": p.conflict_note,
                "has_source": bool(
                    p.source_url and (
                        '/status/' in p.source_url
                        or '/watch?v=' in p.source_url
                        or '/comments/' in p.source_url
                    )
                ),
            }
            for p in predictions
        ],
        "accuracy_over_time": accuracy_over_time,
        "disclosed_positions": [
            {
                "ticker": pos.ticker,
                "position_type": pos.position_type,
                "disclosed_at": pos.disclosed_at.isoformat() if pos.disclosed_at else None,
                "source_url": pos.source_url,
                "notes": pos.notes,
            }
            for pos in db.query(DisclosedPosition).filter(
                DisclosedPosition.forecaster_id == f.id
            ).all()
        ],
        "conflict_stats": {
            "total": len(predictions),
            "conflicts": sum(1 for p in predictions if p.has_conflict),
            "rate": round(sum(1 for p in predictions if p.has_conflict) / len(predictions) * 100, 1) if predictions else 0,
        },
    }

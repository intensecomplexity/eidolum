import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Forecaster, Prediction, format_timestamp, get_youtube_timestamp_url
from utils import compute_forecaster_stats, compute_streak

router = APIRouter()


@router.get("/forecasters")
def list_forecasters(db: Session = Depends(get_db)):
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
def get_forecaster(forecaster_id: int, db: Session = Depends(get_db)):
    f = db.query(Forecaster).filter(Forecaster.id == forecaster_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Forecaster not found")

    stats = compute_forecaster_stats(f, db)
    streak = compute_streak(f.id, db)
    predictions = (
        db.query(Prediction)
        .filter(Prediction.forecaster_id == f.id)
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
                "source_type": p.source_type,
                "source_title": p.source_title,
                "source_platform_id": p.source_platform_id,
                "video_timestamp_sec": p.video_timestamp_sec,
                "verified_by": p.verified_by,
                "timestamp_display": format_timestamp(p.video_timestamp_sec),
                "timestamp_url": get_youtube_timestamp_url(p.source_platform_id, p.video_timestamp_sec),
            }
            for p in predictions
        ],
        "accuracy_over_time": accuracy_over_time,
    }

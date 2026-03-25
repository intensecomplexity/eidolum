from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from database import get_db
from models import Prediction, Forecaster, format_timestamp, get_youtube_timestamp_url
from utils import compute_forecaster_stats

router = APIRouter()


@router.get("/asset/{ticker}/consensus")
def get_asset_consensus(
    ticker: str,
    db: Session = Depends(get_db),
    days: int = Query(90, description="Look-back window in days"),
):
    ticker = ticker.upper()
    predictions = (
        db.query(Prediction)
        .filter(Prediction.ticker == ticker)
        .order_by(Prediction.prediction_date.desc())
        .all()
    )

    if not predictions:
        return {
            "ticker": ticker,
            "total_predictions": 0,
            "bullish_count": 0,
            "bearish_count": 0,
            "bullish_pct": 0.0,
            "recent_predictions": [],
            "top_accurate_forecasters": [],
        }

    bull = [p for p in predictions if p.direction == "bullish"]
    bear = [p for p in predictions if p.direction == "bearish"]
    total = len(predictions)

    # Enrich with forecaster info
    recent = []
    for p in predictions[:20]:
        f = db.query(Forecaster).filter(Forecaster.id == p.forecaster_id).first()
        if not f:
            continue
        stats = compute_forecaster_stats(f, db)
        recent.append({
            "prediction_id": p.id,
            "ticker": p.ticker,
            "direction": p.direction,
            "target_price": p.target_price,
            "entry_price": p.entry_price,
            "prediction_date": p.prediction_date.isoformat(),
            "outcome": p.outcome,
            "actual_return": p.actual_return,
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
            "forecaster": {
                "id": f.id,
                "name": f.name,
                "handle": f.handle,
                "channel_url": f.channel_url,
                "accuracy_rate": stats["accuracy_rate"],
            },
        })

    # Top forecasters on this ticker by accuracy
    forecaster_stats = {}
    for p in predictions:
        if p.outcome == "pending":
            continue
        fid = p.forecaster_id
        if fid not in forecaster_stats:
            forecaster_stats[fid] = {"correct": 0, "total": 0}
        forecaster_stats[fid]["total"] += 1
        if p.outcome == "correct":
            forecaster_stats[fid]["correct"] += 1

    top = []
    for fid, s in forecaster_stats.items():
        if s["total"] < 1:
            continue
        f = db.query(Forecaster).filter(Forecaster.id == fid).first()
        if not f:
            continue
        top.append({
            "id": f.id,
            "name": f.name,
            "handle": f.handle,
            "ticker_accuracy": round(s["correct"] / s["total"] * 100, 1),
            "ticker_predictions": s["total"],
        })

    top.sort(key=lambda x: x["ticker_accuracy"], reverse=True)

    return {
        "ticker": ticker,
        "total_predictions": total,
        "bullish_count": len(bull),
        "bearish_count": len(bear),
        "bullish_pct": round(len(bull) / total * 100, 1) if total else 0.0,
        "recent_predictions": recent,
        "top_accurate_forecasters": top[:5],
    }

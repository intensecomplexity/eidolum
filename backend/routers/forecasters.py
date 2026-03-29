import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from database import get_db
from models import Forecaster, Prediction, format_timestamp, get_youtube_timestamp_url
from rate_limit import limiter

router = APIRouter()


@router.get("/forecasters")
@limiter.limit("60/minute")
def list_forecasters(request: Request, limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    forecasters = db.query(Forecaster).filter(Forecaster.total_predictions > 0).order_by(Forecaster.name).limit(limit).all()
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


from fastapi import Query as Q


@router.get("/forecasters/all")
@limiter.limit("60/minute")
def list_all_forecasters(
    request: Request,
    letter: str = Q(None),
    search: str = Q(None),
    db: Session = Depends(get_db),
):
    """List all forecasters A-Z with stats. Optional letter/search filter."""
    query = db.query(Forecaster)
    if letter and len(letter) == 1:
        query = query.filter(Forecaster.name.ilike(f"{letter}%"))
    if search:
        query = query.filter(Forecaster.name.ilike(f"%{search}%"))
    forecasters = query.order_by(Forecaster.name).all()

    results = []
    for f in forecasters:
        total = db.query(Prediction).filter(Prediction.forecaster_id == f.id).count()
        scored = db.query(Prediction).filter(
            Prediction.forecaster_id == f.id,
            Prediction.outcome.in_(["correct", "incorrect"]),
        ).count()
        correct = db.query(Prediction).filter(
            Prediction.forecaster_id == f.id,
            Prediction.outcome == "correct",
        ).count()
        accuracy = round(correct / scored * 100, 1) if scored > 0 else None

        results.append({
            "id": f.id,
            "name": f.name,
            "handle": f.handle,
            "platform": f.platform or "institutional",
            "profile_image_url": f.profile_image_url,
            "total_predictions": total,
            "scored_predictions": scored,
            "accuracy": accuracy,
            "is_ranked": scored >= 10,
        })

    return results


import time as _time

_forecaster_cache: dict[int, tuple] = {}  # id → (data, timestamp)
FORECASTER_CACHE_TTL = 300  # 5 minutes


@router.get("/forecaster/{forecaster_id}")
@limiter.limit("30/minute")
def get_forecaster(
    request: Request,
    forecaster_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    filter: str = Query(None),  # all, evaluated, pending, correct, incorrect
    db: Session = Depends(get_db),
):
    # Check cache for base stats (sector_strengths always computed fresh)
    cached = _forecaster_cache.get(forecaster_id)
    if cached and (_time.time() - cached[1]) < FORECASTER_CACHE_TTL:
        result = dict(cached[0])
        result["predictions"] = _get_predictions_page(forecaster_id, page, limit, filter, db)
        result["sector_strengths"] = _get_sector_strengths(forecaster_id, db)
        return result

    f = db.query(Forecaster).filter(Forecaster.id == forecaster_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Forecaster not found")

    # Use pre-computed stats from Forecaster table (fast)
    total = f.total_predictions or 0
    correct_count = f.correct_predictions or 0
    accuracy = f.accuracy_score or 0

    sector_strengths = _get_sector_strengths(forecaster_id, db)

    # Accuracy over time — single SQL query, last 50 scored predictions
    accuracy_over_time = []
    try:
        aot_rows = db.execute(sql_text("""
            SELECT prediction_date, ticker, direction, outcome
            FROM predictions
            WHERE forecaster_id = :fid AND outcome IN ('correct','incorrect')
            ORDER BY prediction_date ASC
            LIMIT 50
        """), {"fid": forecaster_id}).fetchall()
        cum_correct = 0
        cum_total = 0
        for r in aot_rows:
            cum_total += 1
            if r[3] == "correct":
                cum_correct += 1
            accuracy_over_time.append({
                "date": r[0].strftime("%Y-%m-%d") if r[0] else "",
                "cumulative_accuracy": round(cum_correct / cum_total * 100, 1),
                "ticker": r[1], "direction": r[2], "outcome": r[3],
            })
    except Exception:
        pass

    result = {
        "id": f.id,
        "name": f.name,
        "handle": f.handle,
        "platform": f.platform or "youtube",
        "channel_url": f.channel_url,
        "subscriber_count": f.subscriber_count,
        "profile_image_url": f.profile_image_url,
        "bio": f.bio,
        "streak": {"type": "none", "count": 0},
        "sector_strengths": sector_strengths,
        "accuracy_rate": accuracy,
        "total_predictions": total,
        "evaluated_predictions": total,
        "correct_predictions": correct_count,
        "alpha": float(f.alpha or 0),
        "accuracy_over_time": accuracy_over_time,
        "prediction_counts": _get_prediction_counts(forecaster_id, db),
        "predictions": _get_predictions_page(forecaster_id, page, limit, filter, db),
        "disclosed_positions": [],
        "conflict_stats": {"total": total, "conflicts": 0, "rate": 0},
    }

    # Cache the stats (without predictions — those are paginated)
    cache_data = {k: v for k, v in result.items() if k != "predictions"}
    _forecaster_cache[forecaster_id] = (cache_data, _time.time())

    return result


def _get_sector_strengths(forecaster_id: int, db) -> list:
    """Compute sector accuracy breakdown for a forecaster."""
    try:
        from sqlalchemy import text as sql_text
        rows = db.execute(sql_text("""
            SELECT sector, COUNT(*) as total,
                   SUM(CASE WHEN outcome='correct' THEN 1 ELSE 0 END) as correct
            FROM predictions
            WHERE forecaster_id = :fid AND outcome IN ('correct','incorrect')
              AND sector IS NOT NULL AND sector != ''
            GROUP BY sector ORDER BY total DESC
        """), {"fid": forecaster_id}).fetchall()
        result = [
            {"sector": r[0], "accuracy": round(r[2] / r[1] * 100, 1) if r[1] > 0 else 0, "count": r[1]}
            for r in rows if r[0] != "Other" or len(rows) == 1
        ]
        return result
    except Exception as e:
        print(f"[ForecasterDetail] Sector query error: {e}")
        return []


def _get_prediction_counts(forecaster_id: int, db) -> dict:
    """Get prediction counts by outcome for filter tabs."""
    from sqlalchemy import text as sql_text
    try:
        rows = db.execute(sql_text("""
            SELECT outcome, COUNT(*) FROM predictions
            WHERE forecaster_id = :fid GROUP BY outcome
        """), {"fid": forecaster_id}).fetchall()
        counts = {r[0]: r[1] for r in rows}
        return {
            "all": sum(counts.values()),
            "evaluated": counts.get("correct", 0) + counts.get("incorrect", 0),
            "pending": counts.get("pending", 0),
            "correct": counts.get("correct", 0),
            "incorrect": counts.get("incorrect", 0),
        }
    except Exception:
        return {"all": 0, "evaluated": 0, "pending": 0, "correct": 0, "incorrect": 0}


def _get_predictions_page(forecaster_id: int, page: int, limit: int, filter_type: str, db) -> list:
    """Get paginated predictions with filter and smart sort."""
    from sqlalchemy import text as sql_text
    offset = (page - 1) * limit

    # Build WHERE clause based on filter
    where_extra = ""
    if filter_type == "evaluated":
        where_extra = "AND outcome IN ('correct','incorrect')"
    elif filter_type == "pending":
        where_extra = "AND outcome = 'pending'"
    elif filter_type == "correct":
        where_extra = "AND outcome = 'correct'"
    elif filter_type == "incorrect":
        where_extra = "AND outcome = 'incorrect'"

    # Sort: evaluated first (by eval date DESC), then pending (by eval date ASC)
    order = """
        CASE WHEN outcome IN ('correct','incorrect') THEN 0 ELSE 1 END,
        CASE WHEN outcome IN ('correct','incorrect') THEN evaluation_date END DESC,
        CASE WHEN outcome = 'pending' THEN evaluation_date END ASC
    """

    rows = db.execute(sql_text(f"""
        SELECT id, ticker, direction, target_price, entry_price,
               prediction_date, evaluation_date, window_days,
               outcome, actual_return, evaluation_summary,
               sector, context, exact_quote, source_url, archive_url,
               source_type, source_platform_id, video_timestamp_sec,
               verified_by, has_conflict, conflict_note
        FROM predictions
        WHERE forecaster_id = :fid {where_extra}
        ORDER BY {order}
        LIMIT :lim OFFSET :off
    """), {"fid": forecaster_id, "lim": limit, "off": offset}).fetchall()

    results = []
    for p in rows:
        pred_date = p[5]
        eval_date = p[6]
        window = p[7] or 90
        if not eval_date and pred_date:
            eval_date = pred_date + datetime.timedelta(days=window)
        horizon = "short" if window <= 30 else ("long" if window >= 365 else "medium")
        results.append({
            "id": p[0], "ticker": p[1], "direction": p[2],
            "target_price": p[3], "entry_price": p[4],
            "prediction_date": pred_date.isoformat() if pred_date else None,
            "evaluation_date": eval_date.isoformat() if eval_date else None,
            "window_days": window, "time_horizon": horizon,
            "outcome": p[8], "actual_return": p[9],
            "evaluation_summary": p[10],
            "sector": p[11], "context": p[12], "exact_quote": p[13],
            "source_url": p[14], "archive_url": p[15],
            "source_type": p[16], "source_platform_id": p[17],
            "video_timestamp_sec": p[18], "verified_by": p[19],
            "has_conflict": bool(p[20]), "conflict_note": p[21],
            "has_source": bool(p[14] and ('/status/' in (p[14] or '') or '/watch?v=' in (p[14] or '') or '/comments/' in (p[14] or ''))),
            "timestamp_display": format_timestamp(p[18]),
            "timestamp_url": get_youtube_timestamp_url(p[17], p[18]),
        })
    return results

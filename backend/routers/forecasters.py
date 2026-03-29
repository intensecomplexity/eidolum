import datetime
import time as _time
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
from database import get_db
from models import Forecaster, Prediction, format_timestamp, get_youtube_timestamp_url
from rate_limit import limiter

router = APIRouter()

_forecaster_cache: dict[int, tuple] = {}
FORECASTER_CACHE_TTL = 300


@router.get("/forecasters")
@limiter.limit("60/minute")
def list_forecasters(request: Request, limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    forecasters = db.query(Forecaster).filter(Forecaster.total_predictions > 0).order_by(Forecaster.name).limit(limit).all()
    return [{"id": f.id, "name": f.name, "handle": f.handle, "channel_url": f.channel_url,
             "subscriber_count": f.subscriber_count, "profile_image_url": f.profile_image_url} for f in forecasters]


@router.get("/forecaster/{forecaster_id}")
@limiter.limit("30/minute")
def get_forecaster(
    request: Request,
    forecaster_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    filter: str = Query(None),
    sector: str = Query(None),
    db: Session = Depends(get_db),
):
    # Fast path: return cached stats + fresh predictions (1 DB query)
    cached = _forecaster_cache.get(forecaster_id)
    if cached and (_time.time() - cached[1]) < FORECASTER_CACHE_TTL:
        result = dict(cached[0])
        result["predictions"] = _get_preds(forecaster_id, page, limit, filter, sector, db)
        return result

    # Uncached: 1 query for forecaster + 1 for predictions
    f = db.query(Forecaster).filter(Forecaster.id == forecaster_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Forecaster not found")

    result = {
        "id": f.id, "name": f.name, "handle": f.handle,
        "platform": f.platform or "youtube", "channel_url": f.channel_url,
        "subscriber_count": f.subscriber_count, "profile_image_url": f.profile_image_url,
        "bio": f.bio,
        "streak": {"type": "none", "count": 0},
        "accuracy_rate": float(f.accuracy_score or 0),
        "total_predictions": f.total_predictions or 0,
        "evaluated_predictions": f.total_predictions or 0,
        "correct_predictions": f.correct_predictions or 0,
        "alpha": float(f.alpha or 0),
        "sector_strengths": [],
        "accuracy_over_time": [],
        "prediction_counts": {"all": 0, "evaluated": 0, "pending": 0, "correct": 0, "incorrect": 0},
        "predictions": _get_preds(forecaster_id, page, limit, filter, sector, db),
        "disclosed_positions": [],
        "conflict_stats": {"total": 0, "conflicts": 0, "rate": 0},
    }

    # Cache the base stats (without predictions)
    cache_data = {k: v for k, v in result.items() if k != "predictions"}
    _forecaster_cache[forecaster_id] = (cache_data, _time.time())

    return result


@router.get("/forecaster/{forecaster_id}/sectors")
@limiter.limit("30/minute")
def get_forecaster_sectors(request: Request, forecaster_id: int, db: Session = Depends(get_db)):
    """Lazy-loaded sector strengths and prediction counts."""
    try:
        sector_rows = db.execute(sql_text("""
            SELECT sector, COUNT(*) as total,
                   SUM(CASE WHEN outcome='correct' THEN 1 ELSE 0 END) as correct
            FROM predictions
            WHERE forecaster_id = :fid AND outcome IN ('correct','incorrect')
              AND sector IS NOT NULL AND sector != ''
            GROUP BY sector ORDER BY total DESC
        """), {"fid": forecaster_id}).fetchall()
        sectors = [{"sector": r[0], "accuracy": round(r[2] / r[1] * 100, 1) if r[1] > 0 else 0, "count": r[1]}
                   for r in sector_rows if r[0] != "Other" or len(sector_rows) == 1]
    except Exception:
        sectors = []

    try:
        count_rows = db.execute(sql_text("""
            SELECT outcome, COUNT(*) FROM predictions
            WHERE forecaster_id = :fid GROUP BY outcome
        """), {"fid": forecaster_id}).fetchall()
        counts = {r[0]: r[1] for r in count_rows}
    except Exception:
        counts = {}

    return {
        "sector_strengths": sectors,
        "prediction_counts": {
            "all": sum(counts.values()),
            "evaluated": counts.get("correct", 0) + counts.get("incorrect", 0),
            "pending": counts.get("pending", 0),
            "correct": counts.get("correct", 0),
            "incorrect": counts.get("incorrect", 0),
        },
    }


@router.get("/forecaster/{forecaster_id}/accuracy-chart")
@limiter.limit("30/minute")
def get_accuracy_chart(request: Request, forecaster_id: int, db: Session = Depends(get_db)):
    """Lazy-loaded accuracy over time chart data."""
    try:
        rows = db.execute(sql_text("""
            SELECT prediction_date, ticker, direction, outcome
            FROM predictions
            WHERE forecaster_id = :fid AND outcome IN ('correct','incorrect')
            ORDER BY prediction_date ASC LIMIT 50
        """), {"fid": forecaster_id}).fetchall()
        cum_c = cum_t = 0
        data = []
        for r in rows:
            cum_t += 1
            if r[3] == "correct":
                cum_c += 1
            data.append({"date": r[0].strftime("%Y-%m-%d") if r[0] else "", "cumulative_accuracy": round(cum_c / cum_t * 100, 1),
                         "ticker": r[1], "direction": r[2], "outcome": r[3]})
        return data
    except Exception:
        return []


def _get_preds(fid, page, limit, filter_type, sector, db):
    """Single fast query for paginated predictions."""
    offset = (page - 1) * limit
    where = ""
    params = {"fid": fid, "lim": limit, "off": offset}
    if filter_type == "evaluated":
        where += " AND outcome IN ('correct','incorrect')"
    elif filter_type == "pending":
        where += " AND outcome = 'pending'"
    elif filter_type == "correct":
        where += " AND outcome = 'correct'"
    elif filter_type == "incorrect":
        where += " AND outcome = 'incorrect'"
    if sector:
        where += " AND sector = :sec"
        params["sec"] = sector

    try:
        rows = db.execute(sql_text(f"""
            SELECT id, ticker, direction, target_price, entry_price,
                   prediction_date, evaluation_date, window_days,
                   outcome, actual_return, evaluation_summary,
                   sector, context, exact_quote, source_url, archive_url,
                   source_type, source_platform_id, video_timestamp_sec,
                   verified_by, has_conflict, conflict_note
            FROM predictions
            WHERE forecaster_id = :fid {where}
            ORDER BY CASE WHEN outcome IN ('correct','incorrect') THEN 0 ELSE 1 END,
                     prediction_date DESC
            LIMIT :lim OFFSET :off
        """), params).fetchall()
    except Exception:
        return []

    results = []
    for p in rows:
        pd = p[5]
        ed = p[6]
        w = p[7] or 90
        if not ed and pd:
            ed = pd + datetime.timedelta(days=w)
        results.append({
            "id": p[0], "ticker": p[1], "direction": p[2],
            "target_price": p[3], "entry_price": p[4],
            "prediction_date": pd.isoformat() if pd else None,
            "evaluation_date": ed.isoformat() if ed else None,
            "window_days": w,
            "time_horizon": "short" if w <= 30 else ("long" if w >= 365 else "medium"),
            "outcome": p[8], "actual_return": p[9], "evaluation_summary": p[10],
            "sector": p[11], "context": p[12], "exact_quote": p[13],
            "source_url": p[14], "archive_url": p[15],
            "source_type": p[16], "source_platform_id": p[17],
            "video_timestamp_sec": p[18], "verified_by": p[19],
            "has_conflict": bool(p[20]), "conflict_note": p[21],
            "has_source": bool(p[14] and ('/status/' in (p[14] or '') or '/watch?v=' in (p[14] or ''))),
            "timestamp_display": format_timestamp(p[18]),
            "timestamp_url": get_youtube_timestamp_url(p[17], p[18]),
        })
    return results

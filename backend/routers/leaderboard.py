import datetime
import time as _time
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, text as sql_text
from database import get_db
from models import Forecaster, Prediction
from rate_limit import limiter

router = APIRouter()

# Leaderboard cache — refreshed every 10 minutes
_leaderboard_cache: list = []
_cache_time: float = 0
CACHE_TTL = 600


def _refresh_leaderboard(db: Session) -> list:
    """Compute the full leaderboard using a single SQL query."""
    try:
        # Set a statement timeout to prevent hanging
        db.execute(sql_text("SET statement_timeout = '5000'"))  # 5 seconds max
    except Exception:
        pass  # SQLite doesn't support this

    rows = db.execute(sql_text("""
        SELECT
            f.id, f.name, f.handle, f.platform, f.channel_url,
            f.subscriber_count, f.profile_image_url, f.streak,
            f.total_predictions, f.correct_predictions, f.accuracy_score
        FROM forecasters f
        WHERE COALESCE(f.total_predictions, 0) >= 10
          AND COALESCE(f.accuracy_score, 0) > 0
        ORDER BY f.accuracy_score DESC, f.total_predictions DESC
        LIMIT 100
    """)).fetchall()

    results = []
    for i, r in enumerate(rows):
        results.append({
            "id": r[0], "name": r[1], "handle": r[2],
            "platform": r[3] or "youtube", "channel_url": r[4],
            "subscriber_count": r[5], "profile_image_url": r[6],
            "streak": r[7] or 0,
            "accuracy_rate": float(r[10] or 0),
            "total_predictions": r[8] or 0,
            "evaluated_predictions": r[8] or 0,
            "correct_predictions": r[9] or 0,
            "scored_count": r[8] or 0,
            "alpha": 0, "rank": i + 1, "rank_movement": 0,
            "has_disclosed_positions": False,
            "conflict_count": 0, "conflict_rate": 0,
            "verified_predictions": r[8] or 0,
        })
    return results


@router.get("/leaderboard")
@limiter.limit("60/minute")
def get_leaderboard(
    request: Request,
    db: Session = Depends(get_db),
    sector: str = Query(None),
    period_days: int = Query(None),
    direction: str = Query(None),
    tab: str = Query(None),
    filter: str = Query(None),
):
    global _leaderboard_cache, _cache_time

    # For filtered views, compute on demand (rare, acceptable latency)
    if tab == "week" or sector or direction:
        from utils import compute_forecaster_stats
        forecasters = db.query(Forecaster).filter(Forecaster.total_predictions >= 10).all()
        effective_period = 7 if tab == "week" else period_days
        results = []
        for f in forecasters:
            stats = compute_forecaster_stats(f, db, sector=sector, period_days=effective_period, direction=direction)
            if stats.get("evaluated_predictions", 0) < 10:
                continue
            results.append({
                "id": f.id, "name": f.name, "handle": f.handle,
                "platform": f.platform or "youtube", "channel_url": f.channel_url,
                "subscriber_count": f.subscriber_count, "profile_image_url": f.profile_image_url,
                "streak": 0, "rank_movement": 0, "has_disclosed_positions": False,
                "conflict_count": 0, "conflict_rate": 0, "verified_predictions": 0,
                **stats,
            })
        results.sort(key=lambda x: (x["accuracy_rate"], x.get("alpha", 0)), reverse=True)
        for i, r in enumerate(results):
            r["rank"] = i + 1
            r["scored_count"] = r.get("evaluated_predictions", 0)
        return results

    # Default all-time: use cache
    if _leaderboard_cache and (_time.time() - _cache_time) < CACHE_TTL:
        return _leaderboard_cache

    _leaderboard_cache = _refresh_leaderboard(db)
    _cache_time = _time.time()
    return _leaderboard_cache


@router.get("/pending-predictions")
@limiter.limit("60/minute")
def get_pending_predictions(request: Request, db: Session = Depends(get_db)):
    now = datetime.datetime.utcnow()
    rows = db.execute(sql_text("""
        SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
               p.prediction_date, p.evaluation_date, p.window_days, p.current_return,
               p.context, p.sector, f.id, f.name, f.handle, f.platform
        FROM predictions p
        JOIN forecasters f ON f.id = p.forecaster_id
        WHERE p.outcome = 'pending'
        ORDER BY p.prediction_date DESC
        LIMIT 100
    """)).fetchall()

    results = []
    for r in rows:
        pred_date = r[5]
        window = r[7] or 30
        resolution_date = pred_date + datetime.timedelta(days=window) if pred_date else None
        days_elapsed = (now - pred_date).days if pred_date else 0
        days_remaining = max(0, window - days_elapsed)
        results.append({
            "id": r[0], "ticker": r[1], "direction": r[2], "target_price": r[3], "entry_price": r[4],
            "prediction_date": r[5].isoformat() if r[5] else None,
            "evaluation_date": r[6].isoformat() if r[6] else (resolution_date.isoformat() if resolution_date else None),
            "resolution_date": resolution_date.isoformat() if resolution_date else None,
            "window_days": window,
            "days_elapsed": days_elapsed, "days_remaining": days_remaining,
            "progress_pct": min(100, round(days_elapsed / window * 100, 1)) if window else 0,
            "current_return": r[8], "context": r[9], "sector": r[10],
            "forecaster": {"id": r[11], "name": r[12], "handle": r[13], "platform": r[14] or "youtube"},
        })
    return results


_stats_cache = None
_stats_cache_time: float = 0

@router.get("/homepage-stats")
@limiter.limit("60/minute")
def get_homepage_stats(request: Request, db: Session = Depends(get_db)):
    global _stats_cache, _stats_cache_time
    if _stats_cache and (_time.time() - _stats_cache_time) < 300:
        return _stats_cache

    try:
        total_fc = db.execute(sql_text("SELECT COUNT(*) FROM forecasters WHERE COALESCE(total_predictions,0) > 0")).scalar() or 0
        scored = db.execute(sql_text("SELECT COUNT(*) FROM predictions WHERE outcome IN ('correct','incorrect')")).scalar() or 0
        correct_count = db.execute(sql_text("SELECT COUNT(*) FROM predictions WHERE outcome = 'correct'")).scalar() or 0
    except Exception:
        total_fc = scored = correct_count = 0

    avg_acc = round(correct_count / scored * 100, 1) if scored > 0 else 0
    _stats_cache = {
        "forecasters_tracked": total_fc,
        "verified_predictions": scored,
        "total_predictions": scored,
        "avg_accuracy": avg_acc,
        "months_of_data": 24,
        "conflict_flags": 0,
        "transparency_tracked": 0,
    }
    _stats_cache_time = _time.time()
    return _stats_cache


@router.get("/trending-tickers")
@limiter.limit("60/minute")
def get_trending_tickers(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(sql_text("""
        SELECT ticker, direction, COUNT(*) as cnt
        FROM predictions WHERE outcome != 'pending'
        GROUP BY ticker, direction
    """)).fetchall()

    ticker_map = {}
    for r in rows:
        t = r[0]
        if t not in ticker_map:
            ticker_map[t] = {"bullish": 0, "bearish": 0}
        ticker_map[t][r[1]] = r[2]

    NAMES = {
        "NVDA": "NVIDIA", "AAPL": "Apple", "TSLA": "Tesla", "META": "Meta",
        "MSFT": "Microsoft", "AMD": "AMD", "AMZN": "Amazon", "GOOGL": "Alphabet",
    }

    tickers = []
    for t, counts in ticker_map.items():
        total = counts["bullish"] + counts["bearish"]
        if total < 5:
            continue
        bull_pct = round(counts["bullish"] / total * 100)
        consensus = "STRONG BULL" if bull_pct >= 75 else "BULLISH" if bull_pct >= 55 else "STRONG BEAR" if bull_pct <= 25 else "BEARISH" if bull_pct <= 45 else "MIXED"
        tickers.append({"ticker": t, "name": NAMES.get(t, t), "total": total, "bullish": counts["bullish"], "bearish": counts["bearish"], "bull_pct": bull_pct, "consensus": consensus})

    tickers.sort(key=lambda x: x["total"], reverse=True)
    return tickers[:10]


@router.get("/controversial")
@limiter.limit("60/minute")
def get_controversial(request: Request, db: Session = Depends(get_db)):
    return []  # Simplified — compute asynchronously if needed


@router.get("/hot-streaks")
@limiter.limit("60/minute")
def get_hot_streaks(request: Request, db: Session = Depends(get_db)):
    return []  # Simplified — compute asynchronously if needed


@router.get("/forecaster/{forecaster_id}/latest-quote")
@limiter.limit("60/minute")
def get_latest_quote(request: Request, forecaster_id: int, db: Session = Depends(get_db)):
    pred = db.query(Prediction).filter(
        Prediction.forecaster_id == forecaster_id,
        Prediction.exact_quote.isnot(None),
    ).order_by(Prediction.prediction_date.desc()).first()
    if not pred:
        return None
    return {
        "ticker": pred.ticker, "direction": pred.direction,
        "exact_quote": pred.exact_quote[:120] + "..." if len(pred.exact_quote or "") > 120 else pred.exact_quote,
        "prediction_date": pred.prediction_date.isoformat(),
        "source_type": pred.source_type,
    }


@router.get("/prediction-of-the-day")
@limiter.limit("60/minute")
def get_prediction_of_the_day(request: Request, db: Session = Depends(get_db)):
    return None  # Simplified — compute asynchronously if needed


@router.get("/report-cards")
@limiter.limit("60/minute")
def get_report_cards(request: Request, db: Session = Depends(get_db), month: int = Query(None), year: int = Query(None)):
    return {"month": "", "month_num": 0, "year": 0, "report_cards": []}  # Simplified


@router.get("/rare-signals")
@limiter.limit("60/minute")
def get_rare_signals(request: Request, db: Session = Depends(get_db)):
    return []  # Simplified

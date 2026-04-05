import datetime
import re
import time as _time
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
from database import get_db
from models import Forecaster, Prediction, format_timestamp, get_youtube_timestamp_url
from rate_limit import limiter
from firm_urls import get_firm_url

router = APIRouter()

_forecaster_cache: dict[int, tuple] = {}
FORECASTER_CACHE_TTL = 300


def slugify(name: str) -> str:
    """Convert forecaster name to URL slug: 'Dan Ives' → 'dan-ives'"""
    s = name.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    s = s.strip('-')
    return s or 'unknown'


def _build_accuracy_trend(forecaster_id: int, db: Session, sector: str = None) -> list:
    """Build prediction-by-prediction cumulative accuracy trend.
    Uses three-tier scoring: hit/correct=1.0, near=0.5, miss/incorrect=0.
    Optionally filter by sector."""
    try:
        where = "WHERE forecaster_id = :fid AND outcome IN ('hit','near','miss','correct','incorrect') AND actual_return IS NOT NULL"
        params = {"fid": forecaster_id}
        if sector and sector != "All":
            where += " AND sector = :sector"
            params["sector"] = sector
        rows = db.execute(sql_text(f"""
            SELECT outcome
            FROM predictions
            {where}
            ORDER BY COALESCE(evaluated_at, evaluation_date, prediction_date) ASC
        """), params).fetchall()
    except Exception:
        return []

    if len(rows) < 5:
        return []

    trend = []
    hits = 0
    nears = 0
    for i, r in enumerate(rows):
        if r[0] in ("hit", "correct"):
            hits += 1
        elif r[0] == "near":
            nears += 1
        total = i + 1
        acc = round((hits + nears * 0.5) / total * 100, 1)
        if total <= 10 or total % max(1, len(rows) // 50) == 0 or total == len(rows):
            trend.append({
                "prediction_number": total,
                "cumulative_accuracy": acc,
                "correct": hits,
                "total": total,
            })

    return trend


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

    # Quick stats: earliest prediction date + sector count
    try:
        extra = db.execute(sql_text("""
            SELECT MIN(prediction_date),
                   COUNT(DISTINCT CASE WHEN sector IS NOT NULL AND sector != '' AND sector != 'Other' THEN sector END),
                   COUNT(*)
            FROM predictions WHERE forecaster_id = :fid
        """), {"fid": forecaster_id}).first()
        first_pred_date = extra[0].isoformat() if extra and extra[0] else None
        sector_count = extra[1] if extra else 0
        total_all = extra[2] if extra else 0
    except Exception:
        first_pred_date = None
        sector_count = 0
        total_all = f.total_predictions or 0

    # Prediction counts by outcome + direction (single query)
    pred_counts = {"all": 0, "evaluated": 0, "pending": 0, "hits": 0, "nears": 0, "misses": 0, "correct": 0, "incorrect": 0, "bullish": 0, "bearish": 0, "neutral": 0}
    try:
        count_rows = db.execute(sql_text("""
            SELECT outcome, direction, COUNT(*) FROM predictions
            WHERE forecaster_id = :fid GROUP BY outcome, direction
        """), {"fid": forecaster_id}).fetchall()
        for r in count_rows:
            outcome, direction, cnt = r[0], r[1], r[2]
            pred_counts["all"] += cnt
            if outcome in ("hit", "correct"):
                pred_counts["hits"] += cnt
                pred_counts["correct"] += cnt
                pred_counts["evaluated"] += cnt
            elif outcome == "near":
                pred_counts["nears"] += cnt
                pred_counts["evaluated"] += cnt
            elif outcome in ("miss", "incorrect"):
                pred_counts["misses"] += cnt
                pred_counts["incorrect"] += cnt
                pred_counts["evaluated"] += cnt
            elif outcome == "pending":
                pred_counts["pending"] += cnt
            if direction == "bullish":
                pred_counts["bullish"] += cnt
            elif direction == "bearish":
                pred_counts["bearish"] += cnt
            elif direction == "neutral":
                pred_counts["neutral"] += cnt
    except Exception as e:
        print(f"[Forecaster] Count query error for {forecaster_id}: {e}")

    # Calculate accuracy from actual prediction outcomes (not stale cached value)
    if pred_counts["evaluated"] > 0:
        live_accuracy = round((pred_counts["hits"] + pred_counts["nears"] * 0.5) / pred_counts["evaluated"] * 100, 1)
    else:
        live_accuracy = 0

    result = {
        "id": f.id, "name": f.name, "handle": f.handle,
        "slug": getattr(f, 'slug', None) or slugify(f.name),
        "platform": f.platform or "youtube", "channel_url": f.channel_url,
        "subscriber_count": f.subscriber_count, "profile_image_url": f.profile_image_url,
        "bio": f.bio,
        "firm": getattr(f, 'firm', None),
        "firm_url": get_firm_url(getattr(f, 'firm', None)),
        "streak": {"type": "none", "count": 0},
        "accuracy_rate": live_accuracy,
        "total_predictions": pred_counts["evaluated"],
        "evaluated_predictions": pred_counts["evaluated"],
        "correct_predictions": pred_counts["hits"],
        "alpha": float(f.alpha or 0),
        "avg_return": float(f.avg_return or 0),
        "first_prediction_date": first_pred_date,
        "sector_count": sector_count,
        "total_all_predictions": total_all,
        "sector_strengths": [],
        "accuracy_over_time": _build_accuracy_trend(forecaster_id, db, sector),
        "prediction_counts": pred_counts,
        "predictions": _get_preds(forecaster_id, page, limit, filter, sector, db),
        "disclosed_positions": [],
        "conflict_stats": {"total": 0, "conflicts": 0, "rate": 0},
    }

    # Cache the base stats (without predictions)
    cache_data = {k: v for k, v in result.items() if k != "predictions"}
    _forecaster_cache[forecaster_id] = (cache_data, _time.time())

    return result


@router.get("/forecaster/by-slug/{slug}")
@limiter.limit("30/minute")
def get_forecaster_by_slug(
    request: Request,
    slug: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    filter: str = Query(None),
    sector: str = Query(None),
    db: Session = Depends(get_db),
):
    """Look up forecaster by URL slug (e.g. 'dan-ives')."""
    f = db.query(Forecaster).filter(Forecaster.slug == slug).first()
    if not f:
        raise HTTPException(status_code=404, detail="Forecaster not found")
    # Delegate to the main endpoint
    return get_forecaster(request, f.id, page, limit, filter, sector, db)


@router.get("/forecaster/{forecaster_id}/sectors")
@limiter.limit("30/minute")
def get_forecaster_sectors(request: Request, forecaster_id: int, db: Session = Depends(get_db)):
    """Lazy-loaded sector strengths and prediction counts."""
    try:
        # Show sector breakdown for ALL predictions (not just scored)
        sector_rows = db.execute(sql_text("""
            SELECT COALESCE(p.sector, ts.sector) as sec,
                   COUNT(*) as total,
                   SUM(CASE WHEN p.outcome IN ('hit','correct') THEN 1 ELSE 0 END) as hits,
                   SUM(CASE WHEN p.outcome = 'near' THEN 1 ELSE 0 END) as nears,
                   SUM(CASE WHEN p.outcome IN ('hit','near','miss','correct','incorrect') THEN 1 ELSE 0 END) as scored
            FROM predictions p
            LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker
            WHERE p.forecaster_id = :fid
              AND COALESCE(p.sector, ts.sector) IS NOT NULL
              AND COALESCE(p.sector, ts.sector) != ''
            GROUP BY sec ORDER BY total DESC
        """), {"fid": forecaster_id}).fetchall()
        sectors = []
        for r in sector_rows:
            if r[0] == "Other" and len(sector_rows) > 1:
                continue
            scored = r[4] or 0
            acc = round((r[2] + r[3] * 0.5) / scored * 100, 1) if scored > 0 else 0
            sectors.append({"sector": r[0], "accuracy": acc, "count": r[1], "scored": scored})
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

    # Direction breakdown
    dir_counts = {"bullish": 0, "bearish": 0, "neutral": 0}
    try:
        dir_rows = db.execute(sql_text("""
            SELECT direction, COUNT(*) FROM predictions
            WHERE forecaster_id = :fid AND direction IS NOT NULL
            GROUP BY direction
        """), {"fid": forecaster_id}).fetchall()
        for r in dir_rows:
            if r[0] in dir_counts:
                dir_counts[r[0]] = r[1]
    except Exception:
        pass

    return {
        "sector_strengths": sectors,
        "prediction_counts": {
            "all": sum(counts.values()),
            "evaluated": counts.get("hit", 0) + counts.get("near", 0) + counts.get("miss", 0) + counts.get("correct", 0) + counts.get("incorrect", 0),
            "pending": counts.get("pending", 0),
            "hits": counts.get("hit", 0) + counts.get("correct", 0),
            "nears": counts.get("near", 0),
            "misses": counts.get("miss", 0) + counts.get("incorrect", 0),
            "correct": counts.get("hit", 0) + counts.get("correct", 0),
            "incorrect": counts.get("miss", 0) + counts.get("incorrect", 0),
            "bullish": dir_counts["bullish"],
            "bearish": dir_counts["bearish"],
            "neutral": dir_counts["neutral"],
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
            WHERE forecaster_id = :fid AND outcome IN ('hit','near','miss','correct','incorrect')
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
        where += " AND outcome IN ('hit','near','miss','correct','incorrect')"
    elif filter_type == "pending":
        where += " AND outcome = 'pending'"
    elif filter_type == "correct" or filter_type == "hit":
        where += " AND outcome IN ('hit','correct')"
    elif filter_type == "incorrect" or filter_type == "miss":
        where += " AND outcome IN ('miss','incorrect')"
    if sector:
        where += " AND sector = :sec"
        params["sec"] = sector

    try:
        rows = db.execute(sql_text(f"""
            SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
                   p.prediction_date, p.evaluation_date, p.window_days,
                   p.outcome, p.actual_return, p.evaluation_summary,
                   p.sector, p.context, p.exact_quote, p.source_url, p.archive_url,
                   p.source_type, p.source_platform_id, p.video_timestamp_sec,
                   p.verified_by, p.has_conflict, p.conflict_note,
                   ts.logo_domain, ts.logo_url, ts.company_name,
                   p.url_quality
            FROM predictions p
            LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker
            WHERE p.forecaster_id = :fid {where}
            ORDER BY CASE WHEN p.outcome IN ('hit','near','miss','correct','incorrect') THEN 0 ELSE 1 END,
                     p.prediction_date DESC
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
            "logo_domain": p[22], "logo_url": p[23], "company_name": p[24],
            "url_quality": p[25],
        })
    return results


# ── GET /api/forecaster/{forecaster_id}/simulator ────────────────────────────

_sim_cache: dict[int, tuple] = {}
_SIM_TTL = 3600  # 1 hour


@router.get("/forecaster/{forecaster_id}/simulator")
@limiter.limit("30/minute")
def get_portfolio_simulator(
    request: Request,
    forecaster_id: int,
    db: Session = Depends(get_db),
):
    cached = _sim_cache.get(forecaster_id)
    if cached and (_time.time() - cached[1]) < _SIM_TTL:
        return cached[0]

    f = db.query(Forecaster).filter(Forecaster.id == forecaster_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Forecaster not found")

    # Get all scored predictions ordered by date
    rows = db.execute(sql_text("""
        SELECT ticker, direction, prediction_date, evaluation_date,
               entry_price, target_price, actual_return, outcome, window_days
        FROM predictions
        WHERE forecaster_id = :fid
          AND outcome IN ('correct', 'incorrect', 'hit', 'near', 'miss')
          AND actual_return IS NOT NULL
          AND prediction_date IS NOT NULL
        ORDER BY prediction_date ASC
    """), {"fid": forecaster_id}).fetchall()

    if len(rows) < 5:
        result = {"forecaster_id": forecaster_id, "forecaster_name": f.name,
                  "insufficient_data": True, "total_predictions": len(rows)}
        _sim_cache[forecaster_id] = (result, _time.time())
        return result

    # Return caps by evaluation window — prevents corrupted data
    # (evaluator used today's price instead of historical for some old predictions)
    def _max_return(window_days):
        if not window_days or window_days <= 0:
            window_days = 90
        if window_days <= 30:
            return 50.0    # Max ±50% in 30 days
        if window_days <= 90:
            return 100.0   # Max ±100% in 90 days
        if window_days <= 180:
            return 150.0   # Max ±150% in 6 months
        return 200.0       # Max ±200% in 1 year

    # Simulate portfolio: $1,000 per trade, compounding portfolio value
    starting = 10000
    per_trade = 1000
    portfolio = starting
    timeline = []
    trades = []
    best_call = None
    worst_call = None
    first_date = None
    last_date = None

    for r in rows:
        ticker, direction, pred_date, eval_date, entry, target, ret, outcome, window = r
        if ret is None:
            continue

        ret_pct = float(ret)

        # Cap returns at reasonable bounds for the evaluation window
        cap = _max_return(window)
        ret_pct = max(-cap, min(cap, ret_pct))

        pnl = per_trade * (ret_pct / 100)
        portfolio += pnl

        date_str = eval_date.strftime("%Y-%m-%d") if eval_date else (pred_date.strftime("%Y-%m-%d") if pred_date else None)
        pred_str = pred_date.strftime("%Y-%m-%d") if pred_date else None
        if not first_date and pred_str:
            first_date = pred_str
        if pred_str:
            last_date = pred_str

        trade = {
            "date": date_str,
            "pred_date": pred_str,
            "ticker": ticker,
            "direction": direction,
            "entry": float(entry) if entry else None,
            "target": float(target) if target else None,
            "return_pct": round(ret_pct, 1),
            "pnl": round(pnl, 2),
            "portfolio_value": round(portfolio, 2),
            "outcome": outcome,
            "window_days": window,
        }
        trades.append(trade)
        timeline.append({
            "date": date_str,
            "value": round(portfolio, 2),
            "prediction": f"{ticker} {'+' if ret_pct >= 0 else ''}{ret_pct:.1f}%",
        })

        if best_call is None or ret_pct > best_call["return_pct"]:
            best_call = {"ticker": ticker, "return_pct": round(ret_pct, 1), "date": date_str}
        if worst_call is None or ret_pct < worst_call["return_pct"]:
            worst_call = {"ticker": ticker, "return_pct": round(ret_pct, 1), "date": date_str}

    total_return = round((portfolio - starting) / starting * 100, 1)

    # Build time period string
    period_str = None
    if first_date and last_date:
        from datetime import datetime as _dt
        try:
            fd = _dt.strptime(first_date, "%Y-%m-%d")
            ld = _dt.strptime(last_date, "%Y-%m-%d")
            period_str = f"{fd.strftime('%b %Y')} — {ld.strftime('%b %Y')}"
        except Exception:
            pass

    # Alpha vs S&P (use forecaster's stored alpha if available)
    alpha = round(float(f.alpha or 0), 1) if f.alpha else 0

    result = {
        "forecaster_id": forecaster_id,
        "forecaster_name": f.name,
        "insufficient_data": False,
        "starting_capital": starting,
        "per_trade": per_trade,
        "current_value": round(portfolio, 2),
        "total_return_pct": total_return,
        "total_predictions": len(trades),
        "time_period": period_str,
        "alpha": alpha,
        "best_call": best_call,
        "worst_call": worst_call,
        "portfolio_over_time": timeline,
        "trades": trades,
    }

    _sim_cache[forecaster_id] = (result, _time.time())
    return result

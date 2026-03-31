import time as _time
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
from database import get_db
from models import Prediction, Forecaster, format_timestamp, get_youtube_timestamp_url
from utils import compute_forecaster_stats
from rate_limit import limiter

router = APIRouter()

# ── Ticker detail cache ──────────────────────────────────────────────────────
_ticker_cache: dict[str, tuple] = {}
_TICKER_TTL = 300  # 5 minutes


@router.get("/ticker/{ticker}/detail")
@limiter.limit("60/minute")
def get_ticker_detail(request: Request, ticker: str, db: Session = Depends(get_db)):
    """Full ticker detail page data: current consensus, historical track record, predictions."""
    ticker = ticker.upper().strip()

    cached = _ticker_cache.get(ticker)
    if cached and (_time.time() - cached[1]) < _TICKER_TTL:
        return cached[0]

    from datetime import datetime

    # ── Sector + company name ─────────────────────────────────────────────
    sector = None
    company_name = None
    industry = None
    try:
        ts_row = db.execute(sql_text(
            "SELECT sector, company_name, industry FROM ticker_sectors WHERE ticker = :t"
        ), {"t": ticker}).first()
        if ts_row:
            sector = ts_row[0]
            company_name = ts_row[1]
            industry = ts_row[2]
    except Exception:
        pass
    if not sector:
        sector = db.execute(sql_text(
            "SELECT sector FROM predictions WHERE ticker = :t AND sector IS NOT NULL AND sector != 'Other' LIMIT 1"
        ), {"t": ticker}).scalar()
    if not company_name:
        from ticker_lookup import TICKER_INFO
        company_name = TICKER_INFO.get(ticker)

    # ── Pending predictions with forecaster details ───────────────────────
    pending_rows = db.execute(sql_text("""
        SELECT p.id, p.direction, p.target_price, p.entry_price,
               p.prediction_date, p.evaluation_date, p.window_days,
               p.context, p.exact_quote, p.source_url,
               f.id, f.name, f.handle, f.accuracy_score, f.firm
        FROM predictions p
        JOIN forecasters f ON f.id = p.forecaster_id
        WHERE p.ticker = :t AND p.outcome = 'pending'
        ORDER BY p.evaluation_date ASC NULLS LAST
        LIMIT 50
    """), {"t": ticker}).fetchall()

    pending = []
    bulls = []
    bears = []
    for r in pending_rows:
        eval_date = r[5]
        pred_date = r[4]
        days_rem = None
        if eval_date:
            days_rem = max(0, (eval_date - datetime.utcnow()).days)
        acc = round(float(r[13]), 1) if r[13] else 0
        target = float(r[2]) if r[2] else None
        pred = {
            "id": r[0], "direction": r[1], "target_price": target,
            "entry_price": float(r[3]) if r[3] else None,
            "prediction_date": pred_date.isoformat() if pred_date else None,
            "evaluation_date": eval_date.isoformat() if eval_date else None,
            "window_days": r[6], "context": r[7], "exact_quote": r[8],
            "source_url": r[9], "days_remaining": days_rem, "ticker": ticker,
            "outcome": "pending",
            "forecaster": {"id": r[10], "name": r[11], "handle": r[12],
                           "accuracy_rate": acc, "firm": r[14] or None},
        }
        pending.append(pred)

        entry = {"forecaster_id": r[10], "name": r[11], "firm": r[14] or None,
                 "accuracy": acc, "target": target}
        if r[1] == "bullish":
            bulls.append(entry)
        else:
            bears.append(entry)

    # Sort by accuracy descending within each group
    bulls.sort(key=lambda x: x["accuracy"], reverse=True)
    bears.sort(key=lambda x: x["accuracy"], reverse=True)

    pending_total = len(pending)
    pending_bullish = len(bulls)
    pending_bearish = len(bears)

    current_consensus = {
        "total": pending_total,
        "bullish_count": pending_bullish,
        "bearish_count": pending_bearish,
        "bullish_pct": round(pending_bullish / pending_total * 100, 1) if pending_total > 0 else 0,
        "bearish_pct": round(pending_bearish / pending_total * 100, 1) if pending_total > 0 else 0,
        "bulls": bulls,
        "bears": bears,
    }

    # ── Historical (evaluated predictions) ────────────────────────────────
    hist_row = db.execute(sql_text("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN outcome='correct' THEN 1 ELSE 0 END) as correct,
            SUM(CASE WHEN direction='bullish' THEN 1 ELSE 0 END) as bull_total,
            SUM(CASE WHEN direction='bullish' AND outcome='correct' THEN 1 ELSE 0 END) as bull_correct,
            SUM(CASE WHEN direction='bearish' THEN 1 ELSE 0 END) as bear_total,
            SUM(CASE WHEN direction='bearish' AND outcome='correct' THEN 1 ELSE 0 END) as bear_correct,
            AVG(CASE WHEN target_price IS NOT NULL THEN target_price END) as avg_target
        FROM predictions
        WHERE ticker = :t AND outcome IN ('correct', 'incorrect')
    """), {"t": ticker}).first()

    hist_total = hist_row[0] or 0
    hist_correct = hist_row[1] or 0
    hist_bull_total = hist_row[2] or 0
    hist_bull_correct = hist_row[3] or 0
    hist_bear_total = hist_row[4] or 0
    hist_bear_correct = hist_row[5] or 0
    hist_avg_target = round(float(hist_row[6]), 2) if hist_row[6] else None

    historical = {
        "total_evaluated": hist_total,
        "correct": hist_correct,
        "accuracy": round(hist_correct / hist_total * 100, 1) if hist_total > 0 else 0,
        "bullish_total": hist_bull_total,
        "bullish_correct": hist_bull_correct,
        "bullish_accuracy": round(hist_bull_correct / hist_bull_total * 100, 1) if hist_bull_total > 0 else 0,
        "bearish_total": hist_bear_total,
        "bearish_correct": hist_bear_correct,
        "bearish_accuracy": round(hist_bear_correct / hist_bear_total * 100, 1) if hist_bear_total > 0 else 0,
        "avg_target": hist_avg_target,
    }

    # ── Total count across all predictions ────────────────────────────────
    total_all = db.execute(sql_text(
        "SELECT COUNT(*) FROM predictions WHERE ticker = :t"
    ), {"t": ticker}).scalar() or 0

    # ── Recent evaluated (last 15) ────────────────────────────────────────
    scored_rows = db.execute(sql_text("""
        SELECT p.id, p.direction, p.target_price, p.entry_price,
               p.prediction_date, p.evaluation_date, p.outcome, p.actual_return,
               p.context, p.exact_quote,
               f.id, f.name, f.handle, f.accuracy_score, f.firm
        FROM predictions p
        JOIN forecasters f ON f.id = p.forecaster_id
        WHERE p.ticker = :t AND p.outcome IN ('correct','incorrect')
        ORDER BY p.evaluation_date DESC NULLS LAST
        LIMIT 15
    """), {"t": ticker}).fetchall()

    recent_scored = []
    for r in scored_rows:
        recent_scored.append({
            "id": r[0], "direction": r[1], "target_price": float(r[2]) if r[2] else None,
            "entry_price": float(r[3]) if r[3] else None,
            "prediction_date": r[4].isoformat() if r[4] else None,
            "evaluation_date": r[5].isoformat() if r[5] else None,
            "outcome": r[6], "actual_return": float(r[7]) if r[7] is not None else None,
            "context": r[8], "exact_quote": r[9], "ticker": ticker,
            "forecaster": {"id": r[10], "name": r[11], "handle": r[12],
                           "accuracy_rate": float(r[13]) if r[13] else 0,
                           "firm": r[14] or None},
        })

    # ── Top forecaster on this ticker ─────────────────────────────────────
    top_fc = None
    try:
        top_row = db.execute(sql_text("""
            SELECT f.id, f.name,
                   SUM(CASE WHEN p.outcome='correct' THEN 1 ELSE 0 END) as c,
                   COUNT(*) as t
            FROM predictions p JOIN forecasters f ON f.id = p.forecaster_id
            WHERE p.ticker = :t AND p.outcome IN ('correct','incorrect')
            GROUP BY f.id, f.name HAVING COUNT(*) >= 2
            ORDER BY ROUND(SUM(CASE WHEN p.outcome='correct' THEN 1 ELSE 0 END)::numeric / COUNT(*) * 100, 1) DESC
            LIMIT 1
        """), {"t": ticker}).first()
        if top_row:
            top_fc = {"id": top_row[0], "name": top_row[1],
                      "accuracy": round(top_row[2] / top_row[3] * 100, 1) if top_row[3] > 0 else 0,
                      "predictions": top_row[3]}
    except Exception:
        pass

    result = {
        "ticker": ticker,
        "company_name": company_name,
        "industry": industry,
        "sector": sector,
        "total_predictions": total_all,
        "current_consensus": current_consensus,
        "historical": historical,
        "stats": {
            "evaluated": hist_total, "correct": hist_correct,
            "historical_accuracy": historical["accuracy"],
            "avg_target_price": hist_avg_target,
            "top_forecaster": top_fc,
        },
        "pending_predictions": pending,
        "recent_evaluated": recent_scored,
    }

    _ticker_cache[ticker] = (result, _time.time())
    return result


@router.get("/asset/{ticker}/consensus")
@limiter.limit("60/minute")
def get_asset_consensus(
    request: Request,
    ticker: str,
    db: Session = Depends(get_db),
    days: int = Query(90, description="Look-back window in days"),
):
    ticker = ticker.upper()
    predictions = (
        db.query(Prediction)
        .filter(Prediction.ticker == ticker)
        .filter(Prediction.outcome != "pending")
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

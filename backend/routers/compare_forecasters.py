"""Compare two forecasters side-by-side."""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from database import get_db
from models import Forecaster, Prediction
from rate_limit import limiter

router = APIRouter()


def _forecaster_stats(fid: int, db: Session) -> dict | None:
    f = db.query(Forecaster).filter(Forecaster.id == fid).first()
    if not f:
        return None

    rows = db.execute(sql_text("""
        SELECT outcome, actual_return, direction, sector
        FROM predictions
        WHERE forecaster_id = :fid AND outcome IN ('hit','near','miss','correct','incorrect')
    """), {"fid": fid}).fetchall()

    hit = sum(1 for r in rows if r[0] in ('hit', 'correct'))
    near = sum(1 for r in rows if r[0] == 'near')
    miss = sum(1 for r in rows if r[0] in ('miss', 'incorrect'))
    total = hit + near + miss
    accuracy = round((hit + near * 0.5) / total * 100, 1) if total > 0 else 0

    returns = [float(r[1]) for r in rows if r[1] is not None]
    avg_return = round(sum(returns) / len(returns), 1) if returns else 0

    # Sector breakdown
    sector_stats = {}
    for r in rows:
        s = r[3] or 'Other'
        if s not in sector_stats:
            sector_stats[s] = {'hit': 0, 'total': 0}
        sector_stats[s]['total'] += 1
        if r[0] in ('hit', 'correct'):
            sector_stats[s]['hit'] += 1

    sectors = {}
    best_sector = None
    best_acc = -1
    for s, v in sector_stats.items():
        if v['total'] >= 2:
            acc = round(v['hit'] / v['total'] * 100, 1)
            sectors[s] = acc
            if acc > best_acc:
                best_acc = acc
                best_sector = s

    # Top tickers
    ticker_counts = {}
    for r in rows:
        # direction is in r[2], but we don't have ticker here
        pass
    top_tickers_rows = db.execute(sql_text("""
        SELECT ticker, COUNT(*) as c FROM predictions
        WHERE forecaster_id = :fid AND outcome IN ('hit','near','miss','correct','incorrect')
        GROUP BY ticker ORDER BY c DESC LIMIT 5
    """), {"fid": fid}).fetchall()
    top_tickers = [r[0] for r in top_tickers_rows]

    # Streak
    streak_val = f.streak or 0

    # Simulated portfolio value
    portfolio = 10000
    for r in rows:
        if r[1] is not None:
            portfolio += 1000 * (float(r[1]) / 100)

    return {
        "id": f.id,
        "name": f.name,
        "firm": getattr(f, 'firm', None),
        "platform": f.platform or "institutional",
        "accuracy": accuracy,
        "total_scored": total,
        "hit_count": hit,
        "near_count": near,
        "miss_count": miss,
        "avg_return": avg_return,
        "alpha": round(float(f.alpha or 0), 1),
        "best_sector": best_sector,
        "best_sector_accuracy": best_acc if best_acc >= 0 else None,
        "sector_accuracy": sectors,
        "streak": abs(streak_val),
        "streak_type": "win" if streak_val > 0 else "loss" if streak_val < 0 else "none",
        "simulated_10k": round(portfolio, 0),
        "top_tickers": top_tickers,
    }


@router.get("/compare/forecasters")
@limiter.limit("30/minute")
def compare_forecasters(
    request: Request,
    a: int = Query(...),
    b: int = Query(...),
    db: Session = Depends(get_db),
):
    sa = _forecaster_stats(a, db)
    sb = _forecaster_stats(b, db)
    if not sa or not sb:
        return {"error": "One or both forecasters not found"}

    # Head-to-head: tickers both predicted on
    h2h = db.execute(sql_text("""
        SELECT a.ticker, a.direction, a.outcome, a.actual_return,
               b.direction, b.outcome, b.actual_return
        FROM predictions a
        JOIN predictions b ON a.ticker = b.ticker
            AND a.prediction_date = b.prediction_date
        WHERE a.forecaster_id = :a AND b.forecaster_id = :b
          AND a.outcome IN ('hit','near','miss','correct','incorrect')
          AND b.outcome IN ('hit','near','miss','correct','incorrect')
        LIMIT 20
    """), {"a": a, "b": b}).fetchall()

    head_to_head = [{
        "ticker": r[0],
        "a_direction": r[1], "a_outcome": r[2], "a_return": round(float(r[3]), 1) if r[3] else None,
        "b_direction": r[4], "b_outcome": r[5], "b_return": round(float(r[6]), 1) if r[6] else None,
    } for r in h2h]

    return {"a": sa, "b": sb, "head_to_head": head_to_head}

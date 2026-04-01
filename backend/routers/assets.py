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


def _empty_ticker_result(ticker: str, company_name: str = None) -> dict:
    """Return a valid but empty result for tickers with no predictions."""
    return {
        "ticker": ticker,
        "company_name": company_name,
        "industry": None,
        "sector": None,
        "total_predictions": 0,
        "current_consensus": {
            "total": 0, "bullish_count": 0, "bearish_count": 0,
            "bullish_pct": 0, "bearish_pct": 0, "bulls": [], "bears": [],
        },
        "historical": {
            "total_evaluated": 0, "correct": 0, "accuracy": 0,
            "bullish_total": 0, "bullish_correct": 0, "bullish_accuracy": 0,
            "bearish_total": 0, "bearish_correct": 0, "bearish_accuracy": 0,
            "avg_target": None,
        },
        "stats": {"evaluated": 0, "correct": 0, "historical_accuracy": 0,
                  "avg_target_price": None, "top_forecaster": None},
        "pending_predictions": [],
        "recent_evaluated": [],
    }


@router.get("/ticker/{ticker}/detail")
@limiter.limit("60/minute")
def get_ticker_detail(request: Request, ticker: str, db: Session = Depends(get_db)):
    """Full ticker detail page data: current consensus, historical track record, predictions.
    Pure DB queries only — no external API calls. Wrapped in try/except for resilience."""
    ticker = ticker.upper().strip()
    if not ticker or len(ticker) > 10:
        return _empty_ticker_result(ticker)

    cached = _ticker_cache.get(ticker)
    if cached and (_time.time() - cached[1]) < _TICKER_TTL:
        return cached[0]

    try:
        return _build_ticker_detail(ticker, db)
    except Exception as e:
        print(f"[TickerDetail] Error for {ticker}: {e}")
        from ticker_lookup import TICKER_INFO
        return _empty_ticker_result(ticker, TICKER_INFO.get(ticker))


def _build_ticker_detail(ticker: str, db) -> dict:
    from datetime import datetime

    # No manual statement_timeout — rely on the 8s RequestTimeoutMiddleware

    # Quick check: does this ticker have ANY predictions?
    exists = db.execute(sql_text(
        "SELECT 1 FROM predictions WHERE ticker = :t LIMIT 1"
    ), {"t": ticker}).first()

    if not exists:
        from ticker_lookup import TICKER_INFO
        result = _empty_ticker_result(ticker, TICKER_INFO.get(ticker))
        _ticker_cache[ticker] = (result, _time.time())
        return result

    # ── Sector + company name + industry (from DB, with on-the-fly lookup) ──
    sector = None
    company_name = None
    industry = None
    description = None
    try:
        ts_row = db.execute(sql_text(
            "SELECT sector, company_name, industry, description FROM ticker_sectors WHERE ticker = :t"
        ), {"t": ticker}).first()
        if ts_row:
            sector = ts_row[0]
            company_name = ts_row[1]
            industry = ts_row[2]
            description = ts_row[3]
    except Exception:
        db.rollback()

    # If ticker_sectors has no entry or no company_name, look up via Finnhub and cache
    if not company_name:
        try:
            from jobs.sector_lookup import get_sector, _cache_to_db, FINNHUB_KEY, KNOWN_SECTORS
            import httpx as _httpx
            if FINNHUB_KEY:
                r = _httpx.get(
                    "https://finnhub.io/api/v1/stock/profile2",
                    params={"symbol": ticker, "token": FINNHUB_KEY},
                    timeout=5,
                )
                data = r.json()
                _cn = data.get("name", "")
                _ind = data.get("finnhubIndustry", "")
                if _cn:
                    company_name = _cn
                    industry = _ind
                    if not sector:
                        from jobs.sector_lookup import _normalize_sector
                        sector = _normalize_sector(_ind) if _ind else KNOWN_SECTORS.get(ticker, "Other")
                    _cache_to_db(ticker, sector or "Other", db, company_name=_cn, industry=_ind)
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    # Fallback: use static TICKER_INFO for company name
    if not company_name:
        from ticker_lookup import TICKER_INFO
        company_name = TICKER_INFO.get(ticker)

    if not sector:
        try:
            sector = db.execute(sql_text(
                "SELECT sector FROM predictions WHERE ticker = :t AND sector IS NOT NULL AND sector != 'Other' LIMIT 1"
            ), {"t": ticker}).scalar()
        except Exception:
            db.rollback()

    # ── Combined counts query (one round-trip instead of multiple) ──────
    try:
        counts_row = db.execute(sql_text("""
            SELECT
                COUNT(*) as total_all,
                SUM(CASE WHEN outcome = 'pending' THEN 1 ELSE 0 END) as pending_count,
                SUM(CASE WHEN outcome IN ('hit','near','miss','correct','incorrect') THEN 1 ELSE 0 END) as eval_count,
                SUM(CASE WHEN outcome IN ('hit','correct') THEN 1 ELSE 0 END) as hit_count,
                SUM(CASE WHEN outcome IN ('hit','near','miss','correct','incorrect') AND direction='bullish' THEN 1 ELSE 0 END) as bull_eval,
                SUM(CASE WHEN outcome IN ('hit','correct') AND direction='bullish' THEN 1 ELSE 0 END) as bull_hit,
                SUM(CASE WHEN outcome IN ('hit','near','miss','correct','incorrect') AND direction='bearish' THEN 1 ELSE 0 END) as bear_eval,
                SUM(CASE WHEN outcome IN ('hit','correct') AND direction='bearish' THEN 1 ELSE 0 END) as bear_hit,
                AVG(CASE WHEN target_price IS NOT NULL THEN target_price END) as avg_target,
                SUM(CASE WHEN outcome = 'near' THEN 1 ELSE 0 END) as near_count,
                SUM(CASE WHEN outcome = 'near' AND direction='bullish' THEN 1 ELSE 0 END) as bull_near,
                SUM(CASE WHEN outcome = 'near' AND direction='bearish' THEN 1 ELSE 0 END) as bear_near,
                SUM(CASE WHEN direction='bullish' THEN 1 ELSE 0 END) as all_bullish,
                SUM(CASE WHEN direction='bearish' THEN 1 ELSE 0 END) as all_bearish,
                SUM(CASE WHEN direction='neutral' THEN 1 ELSE 0 END) as all_neutral
            FROM predictions WHERE ticker = :t
        """), {"t": ticker}).first()
    except Exception as e:
        print(f"[TickerDetail] Counts query failed for {ticker}: {e}")
        db.rollback()
        counts_row = None

    total_all = (counts_row[0] or 0) if counts_row else 0
    hist_total = (counts_row[2] or 0) if counts_row else 0
    hist_hits = (counts_row[3] or 0) if counts_row else 0
    hist_bull_total = (counts_row[4] or 0) if counts_row else 0
    hist_bull_hits = (counts_row[5] or 0) if counts_row else 0
    hist_bear_total = (counts_row[6] or 0) if counts_row else 0
    hist_bear_hits = (counts_row[7] or 0) if counts_row else 0
    hist_avg_target = round(float(counts_row[8]), 2) if counts_row and counts_row[8] else None
    hist_nears = (counts_row[9] or 0) if counts_row else 0
    hist_bull_nears = (counts_row[10] or 0) if counts_row else 0
    hist_bear_nears = (counts_row[11] or 0) if counts_row else 0
    all_bullish = (counts_row[12] or 0) if counts_row else 0
    all_bearish = (counts_row[13] or 0) if counts_row else 0
    all_neutral = (counts_row[14] or 0) if counts_row else 0

    def _tt(h, n, t):
        return round((h + n * 0.5) / t * 100, 1) if t > 0 else 0

    historical = {
        "total_evaluated": hist_total,
        "hits": hist_hits,
        "nears": hist_nears,
        "accuracy": _tt(hist_hits, hist_nears, hist_total),
        "bullish_total": hist_bull_total,
        "bullish_accuracy": _tt(hist_bull_hits, hist_bull_nears, hist_bull_total),
        "bearish_total": hist_bear_total,
        "bearish_accuracy": _tt(hist_bear_hits, hist_bear_nears, hist_bear_total),
        "avg_target": hist_avg_target,
    }

    # ── Pending predictions with forecaster details ───────────────────────
    pending = []
    bulls = []
    bears = []
    try:
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

        now = datetime.utcnow()
        for r in pending_rows:
            eval_date = r[5]
            pred_date = r[4]
            days_rem = max(0, (eval_date - now).days) if eval_date else None
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
    except Exception as e:
        print(f"[TickerDetail] Pending query failed for {ticker}: {e}")
        db.rollback()

    bulls.sort(key=lambda x: x["accuracy"], reverse=True)
    bears.sort(key=lambda x: x["accuracy"], reverse=True)

    pending_total = len(pending)
    pending_neutrals = len([p for p in pending if p.get("direction") == "neutral"])
    # Use ALL predictions for consensus when pending count is too low
    consensus_bull = len(bulls) if pending_total >= 3 else all_bullish
    consensus_bear = len(bears) if pending_total >= 3 else all_bearish
    consensus_neutral = pending_neutrals if pending_total >= 3 else all_neutral
    consensus_total = (pending_total if pending_total >= 3 else total_all) or 1
    current_consensus = {
        "total": consensus_total,
        "bullish_count": consensus_bull,
        "bearish_count": consensus_bear,
        "neutral_count": consensus_neutral,
        "bullish_pct": round(consensus_bull / consensus_total * 100, 1) if consensus_total > 0 else 0,
        "bearish_pct": round(consensus_bear / consensus_total * 100, 1) if consensus_total > 0 else 0,
        "neutral_pct": round(consensus_neutral / consensus_total * 100, 1) if consensus_total > 0 else 0,
        "bulls": bulls,
        "bears": bears,
    }

    # ── Recent evaluated (last 15) ────────────────────────────────────────
    recent_scored = []
    try:
        scored_rows = db.execute(sql_text("""
            SELECT p.id, p.direction, p.target_price, p.entry_price,
                   p.prediction_date, p.evaluation_date, p.outcome, p.actual_return,
                   p.context, p.exact_quote,
                   f.id, f.name, f.handle, f.accuracy_score, f.firm
            FROM predictions p
            JOIN forecasters f ON f.id = p.forecaster_id
            WHERE p.ticker = :t AND p.outcome IN ('hit','near','miss','correct','incorrect')
            ORDER BY p.evaluation_date DESC NULLS LAST
            LIMIT 15
        """), {"t": ticker}).fetchall()

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
    except Exception as e:
        print(f"[TickerDetail] Scored query failed for {ticker}: {e}")
        db.rollback()

    # ── Top forecaster on this ticker (simplified, no ::numeric cast) ────
    top_fc = None
    try:
        top_row = db.execute(sql_text("""
            SELECT f.id, f.name,
                   SUM(CASE WHEN p.outcome='correct' THEN 1 ELSE 0 END) as c,
                   COUNT(*) as t
            FROM predictions p JOIN forecasters f ON f.id = p.forecaster_id
            WHERE p.ticker = :t AND p.outcome IN ('hit','near','miss','correct','incorrect')
            GROUP BY f.id, f.name HAVING COUNT(*) >= 2
            ORDER BY SUM(CASE WHEN p.outcome='correct' THEN 1 ELSE 0 END) * 1.0 / COUNT(*) DESC
            LIMIT 1
        """), {"t": ticker}).first()
        if top_row:
            top_fc = {"id": top_row[0], "name": top_row[1],
                      "accuracy": round(top_row[2] / top_row[3] * 100, 1) if top_row[3] > 0 else 0,
                      "predictions": top_row[3]}
    except Exception:
        pass

    from ticker_domains import get_domain as _gd
    logo_domain = _gd(ticker)

    result = {
        "ticker": ticker,
        "company_name": company_name,
        "logo_domain": logo_domain,
        "description": description,
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

    # Get company info
    _sector = None
    _company = None
    _logo_url = None
    _description = None
    try:
        _ts = db.execute(sql_text(
            "SELECT sector, company_name, logo_url, description FROM ticker_sectors WHERE ticker = :t"
        ), {"t": ticker}).first()
        if _ts:
            _sector = _ts[0]
            _company = _ts[1]
            _logo_url = _ts[2]
            _description = _ts[3]
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
    if not _company:
        from ticker_lookup import TICKER_INFO
        _company = TICKER_INFO.get(ticker)

    all_predictions = (
        db.query(Prediction)
        .filter(Prediction.ticker == ticker)
        .order_by(Prediction.prediction_date.desc())
        .all()
    )

    if not all_predictions:
        return {
            "ticker": ticker,
            "company_name": _company,
            "logo_url": _logo_url,
            "description": _description,
            "sector": _sector,
            "total_predictions": 0,
            "total_all_predictions": 0,
            "bullish_count": 0,
            "bearish_count": 0,
            "neutral_count": 0,
            "bullish_pct": 0.0,
            "bearish_pct": 0.0,
            "neutral_pct": 0.0,
            "pending_count": 0,
            "recent_predictions": [],
            "top_accurate_forecasters": [],
            "pending_predictions": [],
            "bulls": [],
            "bears": [],
        }

    scored_outcomes = {"hit", "near", "miss", "correct", "incorrect"}
    predictions = [p for p in all_predictions if p.outcome in scored_outcomes]
    pending_preds = [p for p in all_predictions if p.outcome == "pending"]
    bull = [p for p in all_predictions if p.direction == "bullish"]
    bear = [p for p in all_predictions if p.direction == "bearish"]
    neutral = [p for p in all_predictions if p.direction == "neutral"]
    total = len(all_predictions)

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
        fid = p.forecaster_id
        if fid not in forecaster_stats:
            forecaster_stats[fid] = {"correct": 0, "total": 0}
        forecaster_stats[fid]["total"] += 1
        if p.outcome in ("correct", "hit"):
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

    # Build pending predictions with forecaster details for bull/bear lists
    pending_list = []
    bulls_list = []
    bears_list = []
    fid_cache = {}
    for p in pending_preds[:50]:
        if p.forecaster_id not in fid_cache:
            f = db.query(Forecaster).filter(Forecaster.id == p.forecaster_id).first()
            fid_cache[p.forecaster_id] = f
        f = fid_cache.get(p.forecaster_id)
        if not f:
            continue
        acc = float(f.accuracy_score) if f.accuracy_score else 0
        entry = {
            "forecaster_id": f.id, "name": f.name, "firm": getattr(f, 'firm', None),
            "accuracy": round(acc, 1), "target": float(p.target_price) if p.target_price else None,
        }
        if p.direction == "bullish":
            bulls_list.append(entry)
        elif p.direction == "bearish":
            bears_list.append(entry)
        pending_list.append({
            "id": p.id, "direction": p.direction, "target_price": float(p.target_price) if p.target_price else None,
            "entry_price": float(p.entry_price) if p.entry_price else None,
            "prediction_date": p.prediction_date.isoformat() if p.prediction_date else None,
            "evaluation_date": p.evaluation_date.isoformat() if p.evaluation_date else None,
            "window_days": p.window_days, "context": p.context, "exact_quote": p.exact_quote,
            "source_url": p.source_url, "outcome": "pending", "ticker": ticker,
            "forecaster": {"id": f.id, "name": f.name, "handle": f.handle,
                           "accuracy_rate": round(acc, 1), "firm": getattr(f, 'firm', None)},
        })

    bulls_list.sort(key=lambda x: x["accuracy"], reverse=True)
    bears_list.sort(key=lambda x: x["accuracy"], reverse=True)

    return {
        "ticker": ticker,
        "company_name": _company,
        "logo_url": _logo_url,
        "description": _description,
        "sector": _sector,
        "total_predictions": total,
        "total_all_predictions": len(all_predictions),
        "bullish_count": len(bull),
        "bearish_count": len(bear),
        "neutral_count": len(neutral),
        "bullish_pct": round(len(bull) / total * 100, 1) if total else 0.0,
        "bearish_pct": round(len(bear) / total * 100, 1) if total else 0.0,
        "neutral_pct": round(len(neutral) / total * 100, 1) if total else 0.0,
        "pending_count": len(pending_preds),
        "recent_predictions": recent,
        "top_accurate_forecasters": top[:5],
        "pending_predictions": pending_list,
        "bulls": bulls_list,
        "bears": bears_list,
    }

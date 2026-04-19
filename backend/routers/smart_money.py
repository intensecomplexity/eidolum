"""
'Follow the Smart Money' — shows what top-accuracy analysts are currently betting on.
Only includes analysts with accuracy >= 60% AND >= 35 scored predictions.
"""
import time as _time
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from database import get_db
from rate_limit import limiter
from services.prediction_visibility import (
    yt_visible_filter, non_qwen_filter, not_excluded_filter,
)

_YT_VIS_P = yt_visible_filter("p")
_NON_QWEN_P = non_qwen_filter("p")
_NOT_EXCL_P = not_excluded_filter("p")

router = APIRouter()

_cache = {}
_cache_time = 0
_CACHE_TTL = 3600  # 1 hour


@router.get("/smart-money")
@limiter.limit("30/minute")
def get_smart_money(
    request: Request,
    db: Session = Depends(get_db),
    sector: str = Query(None),
    min_analysts: int = Query(2, ge=1, le=20),
    sort: str = Query("analysts_count"),
):
    global _cache, _cache_time

    cache_key = f"{sector}|{min_analysts}|{sort}"
    cached = _cache.get(cache_key)
    if cached and (_time.time() - _cache_time) < _CACHE_TTL:
        return cached

    # Get top analyst IDs (accuracy >= 60%, 35+ scored)
    top_analysts = db.execute(sql_text("""
        SELECT id, name, accuracy_score, firm
        FROM forecasters
        WHERE COALESCE(total_predictions, 0) >= 35
          AND COALESCE(accuracy_score, 0) >= 60
    """)).fetchall()

    if not top_analysts:
        result = {"bullish": [], "bearish": [], "top_analyst_count": 0}
        _cache[cache_key] = result
        _cache_time = _time.time()
        return result

    top_ids = [r[0] for r in top_analysts]
    analyst_info = {r[0]: {"name": r[1], "accuracy": round(float(r[2]), 1), "firm": r[3]} for r in top_analysts}

    # Get pending predictions from top analysts. Exclude stale "pending"
    # rows published more than 18 months ago — those are predictions
    # whose evaluation window has effectively already run. They should
    # not feed the "who's currently betting on X" aggregate.
    where = "AND p.direction IN ('bullish', 'bearish', 'neutral')"
    where += " AND (p.prediction_date IS NULL OR p.prediction_date >= NOW() - INTERVAL '18 months')"
    params = {"ids": top_ids}
    if sector:
        where += " AND ts.sector = :sector"
        params["sector"] = sector

    rows = db.execute(sql_text(f"""
        SELECT p.ticker, p.direction, p.forecaster_id, p.target_price, p.entry_price,
               ts.company_name, ts.logo_url, ts.logo_domain, ts.sector
        FROM predictions p
        LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker
        WHERE p.outcome = 'pending'
          AND p.forecaster_id = ANY(:ids)
          AND {_YT_VIS_P}
          AND {_NON_QWEN_P}
          AND {_NOT_EXCL_P}
          {where}
    """), params).fetchall()

    # Group by ticker + direction
    from collections import defaultdict
    ticker_data = defaultdict(lambda: {"bullish": [], "bearish": [], "neutral": [],
                                        "targets": [], "entries": [],
                                        "company_name": None, "logo_url": None,
                                        "logo_domain": None, "sector": None})

    for r in rows:
        ticker = r[0]
        direction = r[1]
        fid = r[2]
        td = ticker_data[ticker]
        td[direction].append(fid)
        if r[3]:
            td["targets"].append(float(r[3]))
        if r[4]:
            td["entries"].append(float(r[4]))
        if r[5]:
            td["company_name"] = r[5]
        if r[6]:
            td["logo_url"] = r[6]
        if r[7]:
            td["logo_domain"] = r[7]
        if r[8]:
            td["sector"] = r[8]

    # Build bullish list
    bullish_list = []
    bearish_list = []

    # Resolve the real live price for each unique ticker so upside_pct
    # reflects today's reality. Falling back to entries[-1] would re-use
    # a stale entry price from an old prediction and is exactly why
    # SNOW/MSFT were appearing on Bullish Bets with negative upside.
    try:
        from routers.ticker_detail import _fetch_price_data
    except Exception:
        _fetch_price_data = None  # type: ignore
    live_prices: dict = {}
    if _fetch_price_data is not None:
        for ticker in ticker_data.keys():
            try:
                data = _fetch_price_data(ticker)
                lp = data.get("current_price") if data else None
                if lp and lp > 0:
                    live_prices[ticker] = float(lp)
            except Exception:
                pass

    for ticker, td in ticker_data.items():
        bull_ids = list(set(td["bullish"]))
        bear_ids = list(set(td["bearish"]))
        neut_ids = list(set(td["neutral"]))
        total_top = len(bull_ids) + len(bear_ids) + len(neut_ids)

        avg_target = round(sum(td["targets"]) / len(td["targets"]), 2) if td["targets"] else None
        current = live_prices.get(ticker)
        if current is None and td["entries"]:
            current = td["entries"][-1]
        upside = round((avg_target - current) / current * 100, 1) if avg_target and current and current > 0 else None

        base = {
            "ticker": ticker,
            "company_name": td["company_name"],
            "logo_url": td["logo_url"],
            "logo_domain": td["logo_domain"],
            "sector": td["sector"],
            "avg_target": avg_target,
            "current_price": current,
            "upside_pct": upside,
            "total_top_analysts": total_top,
            "bullish_count": len(bull_ids),
            "bearish_count": len(bear_ids),
            "neutral_count": len(neut_ids),
            "conviction_pct": round(len(bull_ids) / total_top * 100) if total_top > 0 else 0,
        }

        # Direction-consistent filter: only surface a bullish card when
        # the aggregate target is still ABOVE the live price (otherwise
        # it's not a bullish bet anymore — the stock already ran past).
        # Same check in reverse for bearish. When we have no live price,
        # we can't make this call so we keep the card and let the
        # frontend render it without an upside.
        target_bullish_ok = (avg_target is None or current is None or avg_target > current)
        target_bearish_ok = (avg_target is None or current is None or avg_target < current)

        if len(bull_ids) >= min_analysts and target_bullish_ok:
            bullish_list.append({
                **base,
                "analyst_count": len(bull_ids),
                "analysts": [{"id": fid, "name": analyst_info[fid]["name"],
                              "accuracy": analyst_info[fid]["accuracy"],
                              "firm": analyst_info[fid]["firm"]} for fid in bull_ids[:10]],
            })

        if len(bear_ids) >= min_analysts and target_bearish_ok:
            bearish_list.append({
                **base,
                "analyst_count": len(bear_ids),
                "conviction_pct": round(len(bear_ids) / total_top * 100) if total_top > 0 else 0,
                "analysts": [{"id": fid, "name": analyst_info[fid]["name"],
                              "accuracy": analyst_info[fid]["accuracy"],
                              "firm": analyst_info[fid]["firm"]} for fid in bear_ids[:10]],
            })

    # Sort
    if sort == "upside":
        bullish_list.sort(key=lambda x: x.get("upside_pct") or 0, reverse=True)
        bearish_list.sort(key=lambda x: abs(x.get("upside_pct") or 0), reverse=True)
    elif sort == "sector":
        bullish_list.sort(key=lambda x: x.get("sector") or "")
        bearish_list.sort(key=lambda x: x.get("sector") or "")
    else:
        bullish_list.sort(key=lambda x: x["analyst_count"], reverse=True)
        bearish_list.sort(key=lambda x: x["analyst_count"], reverse=True)

    result = {
        "bullish": bullish_list,
        "bearish": bearish_list,
        "top_analyst_count": len(top_ids),
    }
    _cache[cache_key] = result
    _cache_time = _time.time()
    return result

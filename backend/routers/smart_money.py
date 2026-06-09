"""
'Follow the Smart Money' — shows what top-accuracy analysts are currently betting on.
Only includes analysts with accuracy >= 60% AND >= 35 scored predictions.
"""
import time as _time
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from database import get_db
from rate_limit import limiter
from services.prediction_visibility import yt_visible_filter
from services.ticker_display import (
    resolve_ticker_display_name, resolve_ticker_display_sector,
)
from routers._prediction_filters import hedged_filter_sql

_YT_VIS_P = yt_visible_filter("p")
_HEDGED_P = hedged_filter_sql("p")

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

    # ── Step 1: SQL pre-filter ─────────────────────────────────────────
    # Before this fix we pulled every pending prediction from the 151
    # top analysts (~3,300 rows / 1,077 distinct tickers) and then ran
    # the per-ticker live-price loop over all 1,077. Most tickers had
    # only one analyst behind them and failed the min_analysts filter
    # AFTER paying the price-fetch cost — wasted work that pushed total
    # latency past the 8s frontend timeout. By moving the
    # `COUNT(DISTINCT forecaster_id) >= min_analysts` check into SQL
    # we cut the fan-out by ~3.5x (e.g. 1,077 → 305 tickers at
    # min_analysts=2) before any HTTP work begins.
    sector_join = ""
    sector_where = ""
    prefilter_params: dict = {"ids": top_ids, "min_analysts": min_analysts}
    if sector:
        sector_join = "JOIN ticker_sectors ts ON ts.ticker = p.ticker"
        sector_where = "AND ts.sector = :sector"
        prefilter_params["sector"] = sector

    survivors = db.execute(sql_text(f"""
        SELECT p.ticker, p.direction
        FROM predictions p
        {sector_join}
        WHERE p.outcome = 'pending'
          AND p.forecaster_id = ANY(:ids)
          AND p.direction IN ('bullish', 'bearish', 'neutral')
          AND (p.prediction_date IS NULL
               OR p.prediction_date >= NOW() - INTERVAL '18 months')
          AND {_YT_VIS_P}{_HEDGED_P}
          {sector_where}
        GROUP BY p.ticker, p.direction
        HAVING COUNT(DISTINCT p.forecaster_id) >= :min_analysts
    """), prefilter_params).fetchall()

    survivor_tickers = sorted({r[0] for r in survivors})
    if not survivor_tickers:
        result = {"bullish": [], "bearish": [], "top_analyst_count": len(top_ids)}
        _cache[cache_key] = result
        _cache_time = _time.time()
        return result

    # ── Step 2: detail query restricted to survivor tickers ────────────
    # Pull per-row fields (target_price, entry_price, ticker_sectors)
    # for the surviving ticker set. The same WHERE conditions as the
    # pre-filter apply so the row sets agree.
    rows = db.execute(sql_text(f"""
        SELECT p.ticker, p.direction, p.forecaster_id, p.target_price, p.entry_price,
               ts.company_name, ts.logo_url, ts.logo_domain, ts.sector
        FROM predictions p
        LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker
        WHERE p.outcome = 'pending'
          AND p.forecaster_id = ANY(:ids)
          AND p.direction IN ('bullish', 'bearish', 'neutral')
          AND (p.prediction_date IS NULL
               OR p.prediction_date >= NOW() - INTERVAL '18 months')
          AND p.ticker = ANY(:tickers)
          AND {_YT_VIS_P}{_HEDGED_P}
    """), {"ids": top_ids, "tickers": survivor_tickers}).fetchall()

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

    # Resolve a current price for each unique ticker so upside_pct
    # reflects reality. Falling back to entries[-1] would re-use a stale
    # entry price from an old prediction and is exactly why SNOW/MSFT
    # were appearing on Bullish Bets with negative upside.
    #
    # Prices come from the LOCAL price_bars asset (20M+ EOD rows, kept
    # current by the daily incremental cron) in ONE batched indexed
    # query — the previous per-ticker external HTTP fanout (ThreadPool
    # over 300+ tickers) cost ~8.4s on a fully cold worker and 504'd at
    # the gateway. EOD close is acceptable for this surface: it ranks
    # calls, it isn't a trading terminal.
    all_tickers = list(ticker_data.keys())
    live_prices: dict = {}
    stale_closes: dict = {}
    try:
        bar_rows = db.execute(sql_text("""
            SELECT DISTINCT ON (ticker) ticker, close, bar_date
            FROM price_bars
            WHERE ticker = ANY(:tickers)
            ORDER BY ticker, bar_date DESC
        """), {"tickers": all_tickers}).fetchall()
        import datetime as _dt
        fresh_floor = _dt.date.today() - _dt.timedelta(days=5)
        for br in bar_rows:
            if br[1] is None or float(br[1]) <= 0:
                continue
            if br[2] >= fresh_floor:
                live_prices[br[0]] = float(br[1])
            else:
                # Last KNOWN close — real historical data, used only if the
                # live refresh below doesn't beat the deadline.
                stale_closes[br[0]] = float(br[1])
    except Exception:
        pass

    # Live-fetch fallback ONLY for tickers with no local bar in the last
    # 5 days. The daily incremental cron refreshes 200 tickers/day, so
    # long-tail names age out — each successful live fetch is persisted
    # back into price_bars (write-through, source='live'), making the
    # miss set self-healing AND shared across workers. The pool is
    # DEADLINED at 2.5s: permanently-dead tickers walk the full provider
    # cascade and must never hold the response hostage (the old unbounded
    # fanout is what 504'd cold workers). Stragglers fall back to their
    # last known close.
    missing = [t for t in all_tickers if t not in live_prices]
    if missing:
        try:
            from routers.ticker_detail import _fetch_price_data
        except Exception:
            _fetch_price_data = None  # type: ignore
        if _fetch_price_data is not None:
            from concurrent.futures import as_completed
            def _fetch_one(t):
                try:
                    d = _fetch_price_data(t)
                    lp = d.get("current_price") if d else None
                    return t, (float(lp) if lp and lp > 0 else None)
                except Exception:
                    return t, None
            fetched = []
            pool = ThreadPoolExecutor(max_workers=10)
            futures = [pool.submit(_fetch_one, t) for t in missing]
            try:
                for fut in as_completed(futures, timeout=2.5):
                    ticker, price = fut.result()
                    if price is not None:
                        live_prices[ticker] = price
                        fetched.append((ticker, price))
            except Exception:
                pass  # deadline hit — stragglers use stale_closes below
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
            if fetched:
                try:
                    import datetime as _dt
                    from services.price_store import persist_bar
                    today = _dt.date.today()
                    for ticker, price in fetched:
                        persist_bar(ticker, today, price, source="live")
                except Exception:
                    pass

    # Anything still unresolved uses its last known close (better than the
    # old behavior of silently reusing a years-old entry_price).
    for t, c in stale_closes.items():
        live_prices.setdefault(t, c)

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
            "company_name": resolve_ticker_display_name(ticker, td["company_name"]),
            "logo_url": td["logo_url"],
            "logo_domain": td["logo_domain"],
            "sector": resolve_ticker_display_sector(ticker, td["sector"]),
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

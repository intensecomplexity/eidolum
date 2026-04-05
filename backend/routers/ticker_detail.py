import os
import time
import httpx
from datetime import datetime, timezone
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import User, UserPrediction
from rate_limit import limiter
from ticker_lookup import TICKER_INFO

router = APIRouter()

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")
POLYGON_KEY = os.getenv("MASSIVE_API_KEY", "").strip()

# ── Price cache (5 min TTL) ────────────────────────────────────────��─────────

_price_cache: dict[str, dict] = {}
_PRICE_TTL = 300  # seconds


def _fetch_price_data(symbol: str) -> dict | None:
    now = time.time()
    cached = _price_cache.get(symbol)
    if cached and now - cached["_ts"] < _PRICE_TTL:
        return cached

    # Check if crypto first
    from crypto_prices import is_crypto, get_crypto_price_data
    if is_crypto(symbol):
        result = get_crypto_price_data(symbol)
        if result:
            _price_cache[symbol] = result
            return result

    result = None

    # 1. Finnhub — real-time quote (best quality when available)
    if FINNHUB_KEY:
        try:
            r = httpx.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": symbol, "token": FINNHUB_KEY},
                timeout=10,
            )
            data = r.json()
            c = data.get("c")
            pc = data.get("pc")  # previous close
            if c and c > 0:
                change = round(c - pc, 2) if pc else 0
                pct = round((change / pc) * 100, 2) if pc and pc > 0 else 0
                result = {
                    "ticker": symbol,
                    "name": TICKER_INFO.get(symbol, symbol),
                    "current_price": round(c, 2),
                    "price_change_24h": change,
                    "price_change_percent": pct,
                    "_ts": now,
                }
        except Exception:
            pass

    # 2. Polygon — previous day close (broad coverage, no daily limit)
    if not result and POLYGON_KEY:
        try:
            r = httpx.get(
                f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev",
                params={"apiKey": POLYGON_KEY},
                timeout=10,
            )
            data = r.json()
            results = data.get("results", [])
            if results:
                bar = results[0]
                close = bar.get("c")
                open_price = bar.get("o")
                if close and close > 0:
                    change = round(close - open_price, 2) if open_price else 0
                    pct = round((change / open_price) * 100, 2) if open_price and open_price > 0 else 0
                    result = {
                        "ticker": symbol,
                        "name": TICKER_INFO.get(symbol, symbol),
                        "current_price": round(close, 2),
                        "price_change_24h": change,
                        "price_change_percent": pct,
                        "_ts": now,
                    }
        except Exception:
            pass

    # 3. Evaluator fallback (Tiingo/FMP)
    if not result:
        try:
            from jobs.evaluator import get_current_price
            price = get_current_price(symbol)
            if price:
                result = {
                    "ticker": symbol,
                    "name": TICKER_INFO.get(symbol, symbol),
                    "current_price": round(price, 2),
                    "price_change_24h": 0,
                    "price_change_percent": 0,
                    "_ts": now,
                }
        except Exception:
            pass

    if result:
        _price_cache[symbol] = result

    return result


def _prediction_dict(p, username=None, user_type=None):
    now = datetime.utcnow()
    remaining = None
    if p.expires_at:
        remaining = max(0, (p.expires_at - now).days)
    return {
        "id": p.id,
        "user_id": p.user_id,
        "username": username,
        "user_type": user_type or "player",
        "ticker": p.ticker,
        "direction": p.direction,
        "price_target": p.price_target,
        "price_at_call": float(p.price_at_call) if p.price_at_call else None,
        "evaluation_window_days": p.evaluation_window_days,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "expires_at": p.expires_at.isoformat() if p.expires_at else None,
        "evaluated_at": p.evaluated_at.isoformat() if p.evaluated_at else None,
        "outcome": p.outcome,
        "current_price": float(p.current_price) if p.current_price else None,
        "days_remaining": remaining,
    }


# ── GET /api/tickers/{symbol}/price ───────────────────────────────────────────


@router.get("/tickers/{symbol}/price")
@limiter.limit("60/minute")
def get_ticker_price(request: Request, symbol: str):
    symbol = symbol.upper().strip()

    data = _fetch_price_data(symbol)
    if not data:
        return {
            "ticker": symbol,
            "name": TICKER_INFO.get(symbol, symbol),
            "current_price": None,
            "price_change_24h": None,
            "price_change_percent": None,
        }

    return {k: v for k, v in data.items() if not k.startswith("_")}


# ── GET /api/ticker/{ticker}/price ───────────────────────────────────────────


@router.get("/ticker/{ticker}/price")
@limiter.limit("60/minute")
def get_ticker_price_simple(request: Request, ticker: str):
    """Return current price in simplified format for the submission form."""
    ticker = ticker.upper().strip()
    if ticker not in TICKER_INFO:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")

    data = _fetch_price_data(ticker)
    price = data.get("current_price") if data else None
    ts = datetime.fromtimestamp(data["_ts"], tz=timezone.utc).isoformat() if data and data.get("_ts") else None

    return {
        "ticker": ticker,
        "price": price,
        "updated_at": ts,
    }


# ── GET /api/tickers/{symbol}/predictions ─────────────────────────────────────


@router.get("/tickers/{symbol}/predictions")
@limiter.limit("60/minute")
def get_ticker_predictions(
    request: Request,
    symbol: str,
    status: str = Query("pending"),
    db: Session = Depends(get_db),
):
    symbol = symbol.upper().strip()

    query = (
        db.query(UserPrediction, User.username, User.user_type)
        .join(User, User.id == UserPrediction.user_id)
        .filter(
            UserPrediction.ticker == symbol,
            UserPrediction.deleted_at.is_(None),
        )
    )

    if status == "pending":
        query = query.filter(UserPrediction.outcome == "pending")
        query = query.order_by(UserPrediction.expires_at.asc())
    elif status == "scored":
        query = query.filter(UserPrediction.outcome.in_(["hit","near","miss","correct","incorrect"]))
        query = query.order_by(UserPrediction.evaluated_at.desc())
    else:
        query = query.order_by(UserPrediction.created_at.desc())

    rows = query.limit(100).all()

    return [_prediction_dict(p, username, utype) for p, username, utype in rows]


# ── GET /api/tickers/{symbol}/top-callers ─────────────────────────────────────


@router.get("/tickers/{symbol}/top-callers")
@limiter.limit("60/minute")
def get_ticker_top_callers(
    request: Request,
    symbol: str,
    db: Session = Depends(get_db),
):
    symbol = symbol.upper().strip()

    scored = (
        db.query(UserPrediction)
        .filter(
            UserPrediction.ticker == symbol,
            UserPrediction.outcome.in_(["hit","near","miss","correct","incorrect"]),
            UserPrediction.deleted_at.is_(None),
        )
        .all()
    )

    user_stats: dict[int, dict] = defaultdict(lambda: {"correct": 0, "total": 0})
    for p in scored:
        user_stats[p.user_id]["total"] += 1
        if p.outcome == "correct":
            user_stats[p.user_id]["correct"] += 1

    results = []
    for uid, stats in user_stats.items():
        if stats["total"] < 3:
            continue
        user = db.query(User).filter(User.id == uid).first()
        if not user:
            continue
        accuracy = round(stats["correct"] / stats["total"] * 100, 1)
        results.append({
            "user_id": uid,
            "username": user.username,
            "display_name": user.display_name,
            "user_type": user.user_type or "player",
            "accuracy": accuracy,
            "total_calls": stats["total"],
            "correct_calls": stats["correct"],
        })

    results.sort(key=lambda x: (x["accuracy"], x["total_calls"]), reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return results[:20]


# ── GET /api/tickers/{symbol}/stats ───────────────────────────────────────────


@router.get("/tickers/{symbol}/stats")
@limiter.limit("60/minute")
def get_ticker_stats(
    request: Request,
    symbol: str,
    db: Session = Depends(get_db),
):
    symbol = symbol.upper().strip()

    all_preds = (
        db.query(UserPrediction)
        .filter(UserPrediction.ticker == symbol, UserPrediction.deleted_at.is_(None))
        .all()
    )

    total = len(all_preds)
    pending = sum(1 for p in all_preds if p.outcome == "pending")
    scored = [p for p in all_preds if p.outcome in ("correct", "incorrect")]
    correct = sum(1 for p in scored if p.outcome == "correct")
    accuracy = round(correct / len(scored) * 100, 1) if scored else 0

    bullish = sum(1 for p in all_preds if p.direction == "bullish" and p.outcome == "pending")
    bearish = sum(1 for p in all_preds if p.direction == "bearish" and p.outcome == "pending")

    return {
        "ticker": symbol,
        "name": TICKER_INFO.get(symbol, symbol),
        "total_predictions": total,
        "pending_predictions": pending,
        "scored_predictions": len(scored),
        "correct_predictions": correct,
        "community_accuracy": accuracy,
        "bullish_pending": bullish,
        "bearish_pending": bearish,
    }


# ── GET /api/ticker/{ticker}/chart — price history + prediction markers ──────

_chart_cache: dict[str, tuple] = {}
_CHART_TTL_MARKET = 300   # 5 minutes during market hours
_CHART_TTL_CLOSED = 3600  # 1 hour outside market hours

PERIOD_DAYS = {"1w": 7, "1m": 30, "3m": 90, "6m": 180, "1y": 365, "all": 3650}

FMP_KEY = os.getenv("FMP_KEY", "")


def _is_market_hours():
    """Check if US stock market is currently open (rough check)."""
    from datetime import timezone
    now_utc = datetime.now(timezone.utc)
    # ET = UTC-4 (EDT) or UTC-5 (EST). Use UTC-4 as approximation.
    et_hour = (now_utc.hour - 4) % 24
    weekday = now_utc.weekday()
    return weekday < 5 and 9 <= et_hour < 16


@router.get("/ticker/{ticker}/chart")
@limiter.limit("30/minute")
def get_ticker_chart(
    request: Request,
    ticker: str,
    period: str = Query("3m"),
    db: Session = Depends(get_db),
):
    ticker = ticker.upper().strip()
    cache_key = f"{ticker}_{period}"
    ttl = _CHART_TTL_MARKET if _is_market_hours() else _CHART_TTL_CLOSED

    cached = _chart_cache.get(cache_key)
    if cached and (time.time() - cached[1]) < ttl:
        return cached[0]

    days = PERIOD_DAYS.get(period, 90)
    prices = []

    POLYGON_KEY = os.getenv("MASSIVE_API_KEY", "").strip()
    from datetime import timedelta as _td
    end_date = datetime.utcnow().strftime("%Y-%m-%d")
    start_date = (datetime.utcnow() - _td(days=days)).strftime("%Y-%m-%d")

    # 1. Try Polygon (free, 5 calls/min, 2 years of data)
    if POLYGON_KEY and not prices:
        try:
            r = httpx.get(
                f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start_date}/{end_date}",
                params={"adjusted": "true", "sort": "asc", "limit": "5000", "apiKey": POLYGON_KEY},
                timeout=15,
            )
            if r.status_code == 200:
                for bar in (r.json().get("results") or []):
                    ts_ms = bar.get("t")
                    close = bar.get("c")
                    if ts_ms and close and float(close) > 0:
                        prices.append({
                            "date": datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d"),
                            "close": round(float(close), 2),
                            "volume": int(bar.get("v", 0)),
                        })
        except Exception as e:
            print(f"[Chart] Polygon error for {ticker}: {e}")

    # 2. Fallback to FMP /api/v3/ (paid, full history)
    if not prices and FMP_KEY:
        try:
            r = httpx.get(
                f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}",
                params={"apikey": FMP_KEY, "serietype": "line"},
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                historical = data.get("historical", []) if isinstance(data, dict) else []
                for item in historical:
                    d = item.get("date", "")
                    if d >= start_date:
                        prices.append({"date": d, "close": round(float(item.get("close", 0)), 2), "volume": 0})
                prices.sort(key=lambda x: x["date"])
        except Exception as e:
            print(f"[Chart] FMP error for {ticker}: {e}")

    # Fetch prediction markers from DB
    from models import Prediction, Forecaster
    from sqlalchemy import text as _t

    predictions = []
    try:
        # Get date range from price data
        if prices:
            start_date = prices[0]["date"]
        else:
            start_date = "2020-01-01"

        rows = db.execute(_t("""
            SELECT p.prediction_date, p.entry_price, p.target_price,
                   p.direction, p.outcome, p.actual_return,
                   f.name as forecaster_name
            FROM predictions p
            JOIN forecasters f ON f.id = p.forecaster_id
            WHERE p.ticker = :t AND p.prediction_date >= :start
            ORDER BY p.prediction_date ASC
            LIMIT 100
        """), {"t": ticker, "start": start_date}).fetchall()

        for r in rows:
            pred_date = r[0]
            predictions.append({
                "date": pred_date.strftime("%Y-%m-%d") if pred_date else None,
                "price_at_prediction": float(r[1]) if r[1] else None,
                "target": float(r[2]) if r[2] else None,
                "direction": r[3],
                "outcome": r[4],
                "forecaster": r[6],
                "return_pct": round(float(r[5]), 1) if r[5] is not None else None,
            })
    except Exception as e:
        print(f"[Chart] prediction query error for {ticker}: {e}")

    result = {"ticker": ticker, "period": period, "prices": prices, "predictions": predictions}
    _chart_cache[cache_key] = (result, time.time())
    return result

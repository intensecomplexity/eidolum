import os
import time
import httpx
from datetime import datetime
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

# ── Price cache (5 min TTL) ──────────────────────────────────────────────────

_price_cache: dict[str, dict] = {}
_PRICE_TTL = 300  # seconds


def _fetch_price_data(symbol: str) -> dict | None:
    now = time.time()
    cached = _price_cache.get(symbol)
    if cached and now - cached["_ts"] < _PRICE_TTL:
        return cached

    result = None
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
    if symbol not in TICKER_INFO:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {symbol}")

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
        query = query.filter(UserPrediction.outcome.in_(["correct", "incorrect"]))
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
            UserPrediction.outcome.in_(["correct", "incorrect"]),
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

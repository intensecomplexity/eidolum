"""
Sector/ticker sentiment heatmap endpoints.
"""
import os
import time
import httpx
from collections import defaultdict
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import User, UserPrediction
from rate_limit import limiter
from ticker_lookup import TICKER_INFO
from badge_engine import SECTOR_MAP, get_sector

router = APIRouter()

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")
_price_cache: dict[str, dict] = {}
_PRICE_TTL = 600  # 10 min


def _get_7d_change(ticker: str) -> float | None:
    cached = _price_cache.get(ticker)
    if cached and time.time() - cached.get("_ts", 0) < _PRICE_TTL:
        return cached.get("change_7d")

    if not FINNHUB_KEY:
        return None
    try:
        r = httpx.get("https://finnhub.io/api/v1/quote", params={"symbol": ticker, "token": FINNHUB_KEY}, timeout=10)
        d = r.json()
        c, pc = d.get("c"), d.get("pc")
        if c and pc and pc > 0:
            change = round((c - pc) / pc * 100, 1)
            _price_cache[ticker] = {"change_7d": change, "_ts": time.time()}
            return change
    except Exception:
        pass
    return None


# Invert sector map: sector -> [tickers]
SECTOR_TICKERS: dict[str, list[str]] = defaultdict(list)
for _t, _s in SECTOR_MAP.items():
    SECTOR_TICKERS[_s].append(_t)
# Add "Other" for tickers not in map
for _t in TICKER_INFO:
    if _t not in SECTOR_MAP:
        SECTOR_TICKERS["Other"].append(_t)


# ── GET /api/heatmap/sectors ──────────────────────────────────────────────────


@router.get("/heatmap/sectors")
@limiter.limit("30/minute")
def sector_heatmap(request: Request, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)

    pending = (
        db.query(UserPrediction)
        .filter(UserPrediction.outcome == "pending", UserPrediction.deleted_at.is_(None))
        .all()
    )

    # Also get predictions from ~7 days ago for sentiment change
    recent_scored = (
        db.query(UserPrediction)
        .filter(
            UserPrediction.deleted_at.is_(None),
            UserPrediction.created_at >= week_ago,
            UserPrediction.created_at < now - timedelta(days=1),
        )
        .all()
    )

    results = []
    for sector, tickers in SECTOR_TICKERS.items():
        sector_preds = [p for p in pending if p.ticker in tickers]
        total = len(sector_preds)
        if total == 0:
            continue

        bull = sum(1 for p in sector_preds if p.direction == "bullish")
        bull_pct = round(bull / total * 100, 1)

        # Accuracy on this sector
        scored = (
            db.query(UserPrediction)
            .filter(
                UserPrediction.ticker.in_(tickers),
                UserPrediction.outcome.in_(["correct", "incorrect"]),
                UserPrediction.deleted_at.is_(None),
            )
            .all()
        )
        correct = sum(1 for p in scored if p.outcome == "correct")
        avg_acc = round(correct / len(scored) * 100, 1) if scored else 0

        # Top caller
        user_stats: dict[int, dict] = defaultdict(lambda: {"correct": 0, "total": 0})
        for p in scored:
            user_stats[p.user_id]["total"] += 1
            if p.outcome == "correct":
                user_stats[p.user_id]["correct"] += 1

        top_caller = None
        top_acc = 0
        for uid, stats in user_stats.items():
            if stats["total"] >= 3:
                acc = round(stats["correct"] / stats["total"] * 100, 1)
                if acc > top_acc:
                    top_acc = acc
                    u = db.query(User).filter(User.id == uid).first()
                    if u:
                        top_caller = {"username": u.username, "accuracy": acc}

        # Hot ticker in sector
        ticker_counts = defaultdict(lambda: {"bull": 0, "total": 0})
        for p in sector_preds:
            ticker_counts[p.ticker]["total"] += 1
            if p.direction == "bullish":
                ticker_counts[p.ticker]["bull"] += 1

        hot = max(ticker_counts.items(), key=lambda x: x[1]["total"])
        hot_ticker = {
            "ticker": hot[0],
            "bullish_pct": round(hot[1]["bull"] / hot[1]["total"] * 100, 1) if hot[1]["total"] > 0 else 50,
            "active_predictions": hot[1]["total"],
        }

        # Sentiment change (rough: compare current pending vs week-old predictions)
        old_sector = [p for p in recent_scored if p.ticker in tickers]
        old_bull_pct = round(sum(1 for p in old_sector if p.direction == "bullish") / len(old_sector) * 100, 1) if old_sector else bull_pct
        sentiment_change = round(bull_pct - old_bull_pct, 1)

        results.append({
            "sector": sector,
            "tickers": tickers,
            "total_active_predictions": total,
            "bullish_pct": bull_pct,
            "bearish_pct": round(100 - bull_pct, 1),
            "avg_accuracy_on_sector": avg_acc,
            "top_caller": top_caller,
            "hot_ticker": hot_ticker,
            "sentiment_change_7d": sentiment_change,
        })

    results.sort(key=lambda x: x["total_active_predictions"], reverse=True)
    return results


# ── GET /api/heatmap/tickers ──────────────────────────────────────────────────


@router.get("/heatmap/tickers")
@limiter.limit("30/minute")
def ticker_heatmap(request: Request, db: Session = Depends(get_db)):
    pending = (
        db.query(UserPrediction)
        .filter(UserPrediction.outcome == "pending", UserPrediction.deleted_at.is_(None))
        .all()
    )

    ticker_data: dict[str, dict] = defaultdict(lambda: {"bull": 0, "total": 0})
    for p in pending:
        ticker_data[p.ticker]["total"] += 1
        if p.direction == "bullish":
            ticker_data[p.ticker]["bull"] += 1

    results = []
    for ticker, data in ticker_data.items():
        if data["total"] < 3:
            continue

        bull_pct = round(data["bull"] / data["total"] * 100, 1)
        price_change = _get_7d_change(ticker)

        # Alignment
        sentiment = "neutral"
        if price_change is not None:
            if bull_pct >= 60 and price_change > 0:
                sentiment = "aligned"
            elif bull_pct >= 60 and price_change < 0:
                sentiment = "divergent"
            elif bull_pct <= 40 and price_change < 0:
                sentiment = "aligned"
            elif bull_pct <= 40 and price_change > 0:
                sentiment = "divergent"

        results.append({
            "ticker": ticker,
            "name": TICKER_INFO.get(ticker, ticker),
            "sector": get_sector(ticker),
            "bullish_pct": bull_pct,
            "bearish_pct": round(100 - bull_pct, 1),
            "total_predictions": data["total"],
            "price_change_7d": price_change,
            "sentiment_vs_price": sentiment,
        })

    results.sort(key=lambda x: x["total_predictions"], reverse=True)
    return results

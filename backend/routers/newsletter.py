import datetime
import os
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db
from models import NewsletterSubscriber, Prediction, Forecaster
from utils import compute_forecaster_stats
from rate_limit import limiter
from middleware.auth import require_admin

router = APIRouter()

class SubscribeRequest(BaseModel):
    email: str

@router.post("/newsletter/subscribe")
@limiter.limit("5/minute")
def subscribe(request: Request, req: SubscribeRequest, db: Session = Depends(get_db)):
    existing = db.query(NewsletterSubscriber).filter(
        NewsletterSubscriber.email == req.email
    ).first()
    if existing:
        if existing.unsubscribed_at:
            existing.unsubscribed_at = None
            db.commit()
            return {"status": "resubscribed"}
        return {"status": "already_subscribed"}
    db.add(NewsletterSubscriber(email=req.email))
    db.commit()
    return {"status": "subscribed"}

@router.post("/newsletter/unsubscribe")
@limiter.limit("10/minute")
def unsubscribe(request: Request, req: SubscribeRequest, db: Session = Depends(get_db)):
    sub = db.query(NewsletterSubscriber).filter(
        NewsletterSubscriber.email == req.email
    ).first()
    if sub:
        sub.unsubscribed_at = datetime.datetime.utcnow()
        db.commit()
    return {"status": "unsubscribed"}

@router.get("/newsletter/generate")
@limiter.limit("10/minute")
def generate_newsletter(request: Request, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """Generate this week's newsletter content."""
    now = datetime.datetime.utcnow()
    week_ago = now - datetime.timedelta(days=7)
    week_label = now.strftime("Week of %B %d")

    # 1. Biggest resolved calls this week
    resolved = db.query(Prediction).filter(
        Prediction.evaluation_date >= week_ago,
        Prediction.outcome.notin_(["pending"]),
        Prediction.actual_return.isnot(None)
    ).all()
    resolved.sort(key=lambda p: abs(p.actual_return or 0), reverse=True)
    top_calls = []
    for p in resolved[:3]:
        f = db.query(Forecaster).filter(Forecaster.id == p.forecaster_id).first()
        if f:
            top_calls.append({
                "forecaster": f.name,
                "ticker": p.ticker,
                "direction": p.direction,
                "outcome": p.outcome,
                "actual_return": p.actual_return,
            })

    # 2. Leaderboard changes
    forecasters = db.query(Forecaster).all()
    ranked = []
    for f in forecasters:
        stats = compute_forecaster_stats(f, db)
        ranked.append({"id": f.id, "name": f.name, "rank_last_week": f.rank_last_week, **stats})
    ranked.sort(key=lambda x: (x["accuracy_rate"], x["alpha"]), reverse=True)
    for i, r in enumerate(ranked):
        r["current_rank"] = i + 1
    movers = [r for r in ranked if r["rank_last_week"] and r["rank_last_week"] != r["current_rank"]]
    movers.sort(key=lambda x: abs(x["rank_last_week"] - x["current_rank"]), reverse=True)

    # 3. Platform winner
    platform_stats = {}
    for f in forecasters:
        plat = f.platform or "youtube"
        if plat not in platform_stats:
            platform_stats[plat] = {"correct": 0, "total": 0}
        preds = db.query(Prediction).filter(
            Prediction.forecaster_id == f.id,
            Prediction.evaluation_date >= week_ago,
            Prediction.outcome.notin_(["pending"])
        ).all()
        for p in preds:
            platform_stats[plat]["total"] += 1
            if p.outcome == "correct":
                platform_stats[plat]["correct"] += 1
    platform_winner = None
    best_acc = 0
    for plat, s in platform_stats.items():
        if s["total"] >= 3:
            acc = round(s["correct"] / s["total"] * 100, 1)
            if acc > best_acc:
                best_acc = acc
                platform_winner = {"platform": plat, "accuracy": acc, "predictions": s["total"]}

    # 4. Most controversial
    predictions = db.query(Prediction).filter(Prediction.prediction_date >= week_ago).all()
    ticker_sides = {}
    for p in predictions:
        if p.ticker not in ticker_sides:
            ticker_sides[p.ticker] = {"bullish": 0, "bearish": 0}
        ticker_sides[p.ticker][p.direction] += 1
    controversial = None
    max_total = 0
    for t, sides in ticker_sides.items():
        if sides["bullish"] >= 2 and sides["bearish"] >= 2:
            total = sides["bullish"] + sides["bearish"]
            if total > max_total:
                max_total = total
                controversial = {"ticker": t, "bulls": sides["bullish"], "bears": sides["bearish"]}

    # 5. Predictions resolving next week
    next_week = now + datetime.timedelta(days=7)
    pending = db.query(Prediction).filter(Prediction.outcome == "pending").all()
    resolving_soon = []
    for p in pending:
        resolution = p.prediction_date + datetime.timedelta(days=p.window_days)
        if now <= resolution <= next_week:
            f = db.query(Forecaster).filter(Forecaster.id == p.forecaster_id).first()
            if f:
                resolving_soon.append({
                    "forecaster": f.name,
                    "ticker": p.ticker,
                    "direction": p.direction,
                    "resolution_date": resolution.isoformat(),
                })

    return {
        "subject": f"Eidolum Weekly — {week_label}",
        "week_label": week_label,
        "top_calls": top_calls[:3],
        "leaderboard_movers": [{"name": m["name"], "from": m["rank_last_week"], "to": m["current_rank"]} for m in movers[:5]],
        "platform_winner": platform_winner,
        "controversial": controversial,
        "resolving_soon": resolving_soon[:5],
    }

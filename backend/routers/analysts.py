"""
Analyst/forecaster pages — dedicated profiles for scraped Wall Street analysts and firms.
"""
from collections import defaultdict
from typing import Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import Forecaster, Prediction, AnalystSubscription, User
from rate_limit import limiter
from auth import get_current_user as _decode_token

_optional_bearer = HTTPBearer(auto_error=False)

router = APIRouter()


def _accuracy(correct: int, total: int) -> float:
    return round(correct / total * 100, 1) if total > 0 else 0


# ── GET /api/analysts ─────────────────────────────────────────────────────────


@router.get("/analysts")
@limiter.limit("60/minute")
def list_analysts(request: Request, q: str = Query(""), db: Session = Depends(get_db)):
    query = db.query(Forecaster)

    if q.strip():
        pattern = f"%{q.strip().lower()}%"
        query = query.filter(func.lower(Forecaster.name).like(pattern))

    forecasters = query.order_by(Forecaster.total_predictions.desc().nullslast()).all()

    results = []
    for f in forecasters:
        total = f.total_predictions or 0
        correct = f.correct_predictions or 0
        scored = total  # cached stats are for scored predictions
        if total == 0:
            # Compute from predictions table
            scored = db.query(func.count(Prediction.id)).filter(
                Prediction.forecaster_id == f.id,
                Prediction.outcome.in_(["correct", "incorrect"]),
            ).scalar() or 0
            correct = db.query(func.count(Prediction.id)).filter(
                Prediction.forecaster_id == f.id,
                Prediction.outcome == "correct",
            ).scalar() or 0
            total = db.query(func.count(Prediction.id)).filter(Prediction.forecaster_id == f.id).scalar() or 0

        last_pred = db.query(func.max(Prediction.prediction_date)).filter(Prediction.forecaster_id == f.id).scalar()

        results.append({
            "id": f.id,
            "name": f.name,
            "handle": f.handle,
            "platform": f.platform,
            "total_predictions": total,
            "scored_predictions": scored,
            "correct_predictions": correct,
            "accuracy": _accuracy(correct, scored),
            "most_recent": last_pred.isoformat() if last_pred else None,
        })

    return results


# ── GET /api/analysts/rankings ────────────────────────────────────────────────


@router.get("/analysts/rankings")
@limiter.limit("60/minute")
def analyst_rankings(request: Request, db: Session = Depends(get_db)):
    forecasters = db.query(Forecaster).all()

    results = []
    for f in forecasters:
        scored = db.query(func.count(Prediction.id)).filter(
            Prediction.forecaster_id == f.id,
            Prediction.outcome.in_(["correct", "incorrect"]),
        ).scalar() or 0
        if scored < 10:
            continue
        correct = db.query(func.count(Prediction.id)).filter(
            Prediction.forecaster_id == f.id,
            Prediction.outcome == "correct",
        ).scalar() or 0

        results.append({
            "id": f.id,
            "name": f.name,
            "platform": f.platform,
            "scored_predictions": scored,
            "correct_predictions": correct,
            "accuracy": _accuracy(correct, scored),
            "streak": f.streak or 0,
        })

    results.sort(key=lambda x: (x["accuracy"], x["scored_predictions"]), reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return results[:50]


# ── GET /api/analysts/{name} ──────────────────────────────────────────────────


@router.get("/analysts/{name}")
@limiter.limit("60/minute")
def analyst_profile(request: Request, name: str, db: Session = Depends(get_db)):
    f = db.query(Forecaster).filter(func.lower(Forecaster.name) == name.lower()).first()
    if not f:
        # Try handle
        f = db.query(Forecaster).filter(func.lower(Forecaster.handle) == name.lower()).first()
    if not f:
        raise HTTPException(status_code=404, detail="Analyst not found")

    all_preds = db.query(Prediction).filter(Prediction.forecaster_id == f.id).all()
    scored = [p for p in all_preds if p.outcome in ("correct", "incorrect")]
    correct = [p for p in scored if p.outcome == "correct"]
    pending = [p for p in all_preds if p.outcome == "pending"]

    # Sector breakdown
    sector_stats = defaultdict(lambda: {"correct": 0, "total": 0})
    for p in scored:
        s = p.sector or "Other"
        sector_stats[s]["total"] += 1
        if p.outcome == "correct":
            sector_stats[s]["correct"] += 1

    sector_breakdown = sorted([
        {"sector": s, "accuracy": _accuracy(v["correct"], v["total"]), "total": v["total"]}
        for s, v in sector_stats.items() if v["total"] >= 1
    ], key=lambda x: x["total"], reverse=True)

    # Ticker breakdown
    ticker_stats = defaultdict(lambda: {"correct": 0, "total": 0})
    for p in scored:
        ticker_stats[p.ticker]["total"] += 1
        if p.outcome == "correct":
            ticker_stats[p.ticker]["correct"] += 1

    ticker_breakdown = sorted([
        {"ticker": t, "accuracy": _accuracy(v["correct"], v["total"]), "total": v["total"]}
        for t, v in ticker_stats.items() if v["total"] >= 1
    ], key=lambda x: x["total"], reverse=True)

    # Most called tickers
    ticker_counts = defaultdict(int)
    for p in all_preds:
        ticker_counts[p.ticker] += 1
    most_called = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    # Best/worst sector
    best_sector = max(sector_breakdown, key=lambda x: x["accuracy"]) if sector_breakdown else None
    worst_sector = min(sector_breakdown, key=lambda x: x["accuracy"]) if sector_breakdown else None

    # Recent predictions
    recent = sorted(all_preds, key=lambda p: p.prediction_date or p.created_at, reverse=True)[:20]

    return {
        "id": f.id,
        "name": f.name,
        "handle": f.handle,
        "platform": f.platform,
        "bio": f.bio,
        "channel_url": f.channel_url,
        "user_type": "analyst",
        "total_predictions": len(all_preds),
        "scored_predictions": len(scored),
        "correct_predictions": len(correct),
        "accuracy": _accuracy(len(correct), len(scored)),
        "active_predictions": len(pending),
        "streak": f.streak or 0,
        "sector_breakdown": sector_breakdown,
        "ticker_breakdown": ticker_breakdown[:15],
        "most_called_tickers": [{"ticker": t, "count": c} for t, c in most_called],
        "best_sector": best_sector,
        "worst_sector": worst_sector,
        "recent_predictions": [
            {
                "id": p.id,
                "ticker": p.ticker,
                "direction": p.direction,
                "target_price": p.target_price,
                "entry_price": p.entry_price,
                "outcome": p.outcome,
                "actual_return": p.actual_return,
                "prediction_date": p.prediction_date.isoformat() if p.prediction_date else None,
                "evaluation_date": p.evaluation_date.isoformat() if p.evaluation_date else None,
                "source_url": p.source_url,
            }
            for p in recent
        ],
    }


# ── GET /api/analysts/{name}/accuracy-history ─────────────────────────────────


@router.get("/analysts/{name}/accuracy-history")
@limiter.limit("60/minute")
def analyst_accuracy_history(request: Request, name: str, db: Session = Depends(get_db)):
    f = db.query(Forecaster).filter(func.lower(Forecaster.name) == name.lower()).first()
    if not f:
        f = db.query(Forecaster).filter(func.lower(Forecaster.handle) == name.lower()).first()
    if not f:
        raise HTTPException(status_code=404, detail="Analyst not found")

    scored = (
        db.query(Prediction)
        .filter(
            Prediction.forecaster_id == f.id,
            Prediction.outcome.in_(["correct", "incorrect"]),
            Prediction.evaluation_date.isnot(None),
        )
        .order_by(Prediction.evaluation_date.asc())
        .all()
    )

    months = defaultdict(lambda: {"scored": 0, "correct": 0})
    for p in scored:
        key = p.evaluation_date.strftime("%Y-%m")
        months[key]["scored"] += 1
        if p.outcome == "correct":
            months[key]["correct"] += 1

    import datetime as _dt
    now = _dt.datetime.utcnow()
    result = []
    cum_s = cum_c = 0
    for i in range(11, -1, -1):
        d = now - _dt.timedelta(days=i * 30)
        key = d.strftime("%Y-%m")
        data = months.get(key, {"scored": 0, "correct": 0})
        cum_s += data["scored"]
        cum_c += data["correct"]
        result.append({
            "month": key,
            "scored": data["scored"],
            "correct": data["correct"],
            "accuracy": round(data["correct"] / data["scored"] * 100, 1) if data["scored"] > 0 else None,
            "rolling_accuracy": round(cum_c / cum_s * 100, 1) if cum_s > 0 else None,
        })

    return result


# ── GET /api/analysts/{name}/predictions ──────────────────────────────────────


@router.get("/analysts/{name}/predictions")
@limiter.limit("60/minute")
def analyst_predictions(
    request: Request,
    name: str,
    outcome: str = Query(None),
    ticker: str = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    f = db.query(Forecaster).filter(func.lower(Forecaster.name) == name.lower()).first()
    if not f:
        f = db.query(Forecaster).filter(func.lower(Forecaster.handle) == name.lower()).first()
    if not f:
        raise HTTPException(status_code=404, detail="Analyst not found")

    query = db.query(Prediction).filter(Prediction.forecaster_id == f.id)

    if outcome and outcome in ("correct", "incorrect", "pending"):
        query = query.filter(Prediction.outcome == outcome)
    if ticker:
        query = query.filter(Prediction.ticker == ticker.upper())

    total = query.count()
    preds = query.order_by(Prediction.prediction_date.desc().nullslast()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "predictions": [
            {
                "id": p.id,
                "ticker": p.ticker,
                "direction": p.direction,
                "target_price": p.target_price,
                "entry_price": p.entry_price,
                "outcome": p.outcome,
                "actual_return": p.actual_return,
                "sector": p.sector,
                "prediction_date": p.prediction_date.isoformat() if p.prediction_date else None,
                "evaluation_date": p.evaluation_date.isoformat() if p.evaluation_date else None,
                "source_url": p.source_url,
                "exact_quote": p.exact_quote,
            }
            for p in preds
        ],
    }


def _get_user_id(credentials) -> Optional[int]:
    """Extract user_id from optional bearer token, or return None."""
    if not credentials or not credentials.credentials:
        return None
    try:
        return _decode_token(credentials.credentials).get("user_id")
    except Exception:
        return None


# ── GET /api/analysts/{name}/subscription-status ─────────────────────────────


@router.get("/analysts/{name}/subscription-status")
@limiter.limit("60/minute")
def subscription_status(
    request: Request,
    name: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    db: Session = Depends(get_db),
):
    uid = _get_user_id(credentials)
    if not uid:
        return {"subscribed": False}

    sub = db.query(AnalystSubscription).filter(
        AnalystSubscription.user_id == uid,
        func.lower(AnalystSubscription.forecaster_name) == name.lower(),
    ).first()
    return {"subscribed": sub is not None}


# ── POST /api/analysts/{name}/subscribe ──────────────────────────────────────


@router.post("/analysts/{name}/subscribe")
@limiter.limit("30/minute")
def subscribe_analyst(
    request: Request,
    name: str,
    email: Optional[str] = Body(None, embed=True),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    db: Session = Depends(get_db),
):
    # Verify analyst exists
    f = db.query(Forecaster).filter(func.lower(Forecaster.name) == name.lower()).first()
    if not f:
        f = db.query(Forecaster).filter(func.lower(Forecaster.handle) == name.lower()).first()
    if not f:
        raise HTTPException(status_code=404, detail="Analyst not found")

    canonical_name = f.name  # Use the DB name for consistency

    uid = _get_user_id(credentials)

    if uid:
        # Authenticated user — subscribe by user_id
        existing = db.query(AnalystSubscription).filter(
            AnalystSubscription.user_id == uid,
            AnalystSubscription.forecaster_name == canonical_name,
        ).first()
        if existing:
            return {"status": "already_subscribed"}

        # Get user email for the record
        user = db.query(User).filter(User.id == uid).first()
        sub = AnalystSubscription(
            user_id=uid,
            email=user.email if user else None,
            forecaster_name=canonical_name,
        )
        db.add(sub)
        db.commit()
        return {"status": "subscribed"}
    else:
        # Anonymous — require email
        if not email or not email.strip():
            raise HTTPException(status_code=400, detail="Email is required")

        clean_email = email.strip().lower()
        existing = db.query(AnalystSubscription).filter(
            AnalystSubscription.email == clean_email,
            AnalystSubscription.forecaster_name == canonical_name,
        ).first()
        if existing:
            return {"status": "already_subscribed"}

        sub = AnalystSubscription(
            email=clean_email,
            forecaster_name=canonical_name,
        )
        db.add(sub)
        db.commit()
        return {"status": "subscribed"}


# ── DELETE /api/analysts/{name}/subscribe ────────────────────────────────────


@router.delete("/analysts/{name}/subscribe")
@limiter.limit("30/minute")
def unsubscribe_analyst(
    request: Request,
    name: str,
    email: Optional[str] = Query(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    db: Session = Depends(get_db),
):
    uid = _get_user_id(credentials)

    if uid:
        sub = db.query(AnalystSubscription).filter(
            AnalystSubscription.user_id == uid,
            func.lower(AnalystSubscription.forecaster_name) == name.lower(),
        ).first()
    elif email:
        sub = db.query(AnalystSubscription).filter(
            AnalystSubscription.email == email.strip().lower(),
            func.lower(AnalystSubscription.forecaster_name) == name.lower(),
        ).first()
    else:
        raise HTTPException(status_code=400, detail="Authentication or email required")

    if not sub:
        return {"status": "not_subscribed"}

    db.delete(sub)
    db.commit()
    return {"status": "unsubscribed"}

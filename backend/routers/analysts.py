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
from utils import append_youtube_timestamp
from rate_limit import limiter
from services.ticker_display import resolve_ticker_display_sector
from services.limits import MAX_FOLLOWS_PER_USER, FOLLOW_LIMIT_MESSAGE
from auth import get_current_user as _decode_token

_optional_bearer = HTTPBearer(auto_error=False)

router = APIRouter()


def _accuracy(correct: int, total: int) -> float:
    return round(correct / total * 100, 1) if total > 0 else 0


# ── GET /api/analysts ─────────────────────────────────────────────────────────


# Allowlisted ORDER BY expressions — the sort key is NEVER interpolated
# from user input, only used to select one of these fixed strings. The
# accuracy expression mirrors the Python source-precedence below (cached
# forecaster columns when populated, predictions aggregate otherwise).
# Deterministic id tiebreak so paginated/edge-cached pages never shuffle.
_ANALYST_SORTS = {
    "volume": "f.total_predictions DESC NULLS LAST, f.id ASC",
    "accuracy": (
        "(CASE WHEN COALESCE(f.total_predictions, 0) > 0 "
        "      THEN COALESCE(f.correct_predictions, 0)::float / NULLIF(f.total_predictions, 0) "
        "      ELSE COALESCE(agg.correct, 0)::float / NULLIF(agg.scored, 0) END) "
        "DESC NULLS LAST, f.id ASC"
    ),
    "recent": "agg.last_pred DESC NULLS LAST, f.id ASC",
}


def _like_escape(s: str) -> str:
    """Escape LIKE wildcards in user input (used with ESCAPE '\\')."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/analysts")
@limiter.limit("60/minute")
def list_analysts(
    request: Request,
    q: str = Query(""),
    platform: str = Query(None),
    sort: str = Query("volume"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """ONE aggregate query (platforms.py recipe, c47827b), now paginated —
    the full list is 6,300+ rows / ~1.3MB, and transfer dominated latency.
    Response body stays a bare array (per-row shape unchanged); the grand
    total rides in the X-Total-Count header so the pre-pagination frontend
    keeps working during the deploy gap."""
    from fastapi.responses import JSONResponse
    from sqlalchemy import text as sql_text

    clauses = []
    params: dict = {"limit": limit, "offset": offset}
    if q.strip():
        clauses.append(
            "(LOWER(f.name) LIKE :pattern ESCAPE '\\' "
            "OR LOWER(COALESCE(f.handle, '')) LIKE :pattern ESCAPE '\\')"
        )
        params["pattern"] = f"%{_like_escape(q.strip().lower())}%"
    if platform:
        clauses.append("f.platform = :platform")
        params["platform"] = platform
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    order_by = _ANALYST_SORTS.get(sort, _ANALYST_SORTS["volume"])

    total = db.execute(sql_text(
        f"SELECT COUNT(*) FROM forecasters f {where}"
    ), params).scalar() or 0

    rows = db.execute(sql_text(f"""
        SELECT f.id, f.name, f.handle, f.platform,
               f.total_predictions, f.correct_predictions,
               COALESCE(agg.total_all, 0) AS total_all,
               COALESCE(agg.scored, 0) AS scored,
               COALESCE(agg.correct, 0) AS correct,
               agg.last_pred
        FROM forecasters f
        LEFT JOIN (
            SELECT forecaster_id,
                   COUNT(*) AS total_all,
                   COUNT(*) FILTER (WHERE outcome IN ('hit','near','miss','correct','incorrect')) AS scored,
                   COUNT(*) FILTER (WHERE outcome IN ('hit','correct')) AS correct,
                   MAX(prediction_date) AS last_pred
            FROM predictions
            GROUP BY forecaster_id
        ) agg ON agg.forecaster_id = f.id
        {where}
        ORDER BY {order_by}
        LIMIT :limit OFFSET :offset
    """), params).fetchall()

    results = []
    for r in rows:
        # Same source-of-truth precedence as before: the cached forecaster
        # columns when populated, the predictions aggregate otherwise.
        cached_total = r[4] or 0
        if cached_total > 0:
            row_total = cached_total
            scored = cached_total  # cached stats are for scored predictions
            correct = r[5] or 0
        else:
            row_total = int(r[6])
            scored = int(r[7])
            correct = int(r[8])

        results.append({
            "id": r[0],
            "name": r[1],
            "handle": r[2],
            "platform": r[3],
            "total_predictions": row_total,
            "scored_predictions": scored,
            "correct_predictions": correct,
            "accuracy": _accuracy(correct, scored),
            "most_recent": r[9].isoformat() if r[9] else None,
        })

    return JSONResponse(content=results, headers={"X-Total-Count": str(total)})


# ── GET /api/analysts/subscriptions ───────────────────────────────────────────
#
# Lists the current authenticated user's followed analysts. Powers the
# "Followed Forecasters" section on /watchlist. Anonymous callers get
# an empty list (not 401) so the page can render quietly. JOINs
# analyst_subscriptions × forecasters by name (the subscription table
# stores forecaster_name, not forecaster_id — historical artefact).
#
# IMPORTANT: this literal-path route MUST be declared before the
# /analysts/{name} parameterized route below, or FastAPI's order-based
# matcher will route `subscriptions` as the {name} parameter and call
# analyst_profile() instead.


@router.get("/analysts/subscriptions")
@limiter.limit("60/minute")
def list_my_subscriptions(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    db: Session = Depends(get_db),
):
    uid = _get_user_id(credentials)
    if not uid:
        return []
    rows = db.query(AnalystSubscription, Forecaster).join(
        Forecaster, func.lower(Forecaster.name) == func.lower(AnalystSubscription.forecaster_name)
    ).filter(AnalystSubscription.user_id == uid).order_by(
        AnalystSubscription.created_at.desc()
    ).all()
    return [
        {
            "forecaster_id": f.id,
            "name": f.name,
            "handle": f.handle,
            "platform": f.platform,
            "slug": f.slug,
            "accuracy_rate": float(f.accuracy_score or 0),
            "total_predictions": int(f.total_predictions or 0),
            "subscribed_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s, f in rows
    ]


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
    scored = [p for p in all_preds if p.outcome in ("hit", "near", "miss", "correct", "incorrect")]
    correct = [p for p in scored if p.outcome in ("hit", "correct")]
    pending = [p for p in all_preds if p.outcome == "pending"]

    # Sector breakdown
    sector_stats = defaultdict(lambda: {"correct": 0, "total": 0})
    for p in scored:
        s = p.sector or "Other"
        sector_stats[s]["total"] += 1
        if p.outcome in ("hit", "correct"):
            sector_stats[s]["correct"] += 1

    sector_breakdown = sorted([
        {"sector": s, "accuracy": _accuracy(v["correct"], v["total"]), "total": v["total"]}
        for s, v in sector_stats.items() if v["total"] >= 1
    ], key=lambda x: x["total"], reverse=True)

    # Ticker breakdown
    ticker_stats = defaultdict(lambda: {"correct": 0, "total": 0})
    for p in scored:
        ticker_stats[p.ticker]["total"] += 1
        if p.outcome in ("hit", "correct"):
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
                "source_url": append_youtube_timestamp(p.source_url, p.source_type, p.source_timestamp_seconds, p.video_timestamp_sec),
                "evaluation_deferred": getattr(p, "evaluation_deferred", None),
                "evaluation_deferred_reason": getattr(p, "evaluation_deferred_reason", None),
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
            Prediction.outcome.in_(["hit","near","miss","correct","incorrect"]),
            Prediction.evaluation_date.isnot(None),
        )
        .order_by(Prediction.evaluation_date.asc())
        .all()
    )

    months = defaultdict(lambda: {"scored": 0, "correct": 0})
    for p in scored:
        key = p.evaluation_date.strftime("%Y-%m")
        months[key]["scored"] += 1
        if p.outcome in ("hit", "correct"):
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
                "sector": resolve_ticker_display_sector(p.ticker, p.sector),
                "prediction_date": p.prediction_date.isoformat() if p.prediction_date else None,
                "evaluation_date": p.evaluation_date.isoformat() if p.evaluation_date else None,
                "source_url": append_youtube_timestamp(p.source_url, p.source_type, p.source_timestamp_seconds, p.video_timestamp_sec),
                "exact_quote": p.exact_quote,
                "source_verbatim_quote": p.source_verbatim_quote,
                "evaluation_deferred": getattr(p, "evaluation_deferred", None),
                "evaluation_deferred_reason": getattr(p, "evaluation_deferred_reason", None),
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

        current_count = db.query(AnalystSubscription).filter(
            AnalystSubscription.user_id == uid,
        ).count()
        if current_count >= MAX_FOLLOWS_PER_USER:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "limit_reached",
                    "kind": "follows",
                    "limit": MAX_FOLLOWS_PER_USER,
                    "message": FOLLOW_LIMIT_MESSAGE,
                },
            )

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

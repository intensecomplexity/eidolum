"""
Share endpoints — OG meta pages and share data for predictions and profiles.
"""
import math
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from database import get_db
from models import User, UserPrediction
from rate_limit import limiter
from ticker_lookup import TICKER_INFO

router = APIRouter()

SITE_URL = "https://www.eidolum.com"


def _rank_name(scored: int) -> str:
    """Legacy compatibility — now uses XP levels."""
    return "Player"


# ── GET /api/predictions/{id}/share-data ──────────────────────────────────────


@router.get("/predictions/{prediction_id}/share-data")
@limiter.limit("60/minute")
def get_share_data(request: Request, prediction_id: int, db: Session = Depends(get_db)):
    pred = db.query(UserPrediction).filter(UserPrediction.id == prediction_id, UserPrediction.deleted_at.is_(None)).first()
    if not pred:
        raise HTTPException(status_code=404, detail="Prediction not found")

    user = db.query(User).filter(User.id == pred.user_id).first()
    username = user.username if user else "Unknown"
    ticker_name = TICKER_INFO.get(pred.ticker, pred.ticker)

    now = datetime.utcnow()
    days_left = max(0, (pred.expires_at - now).days) if pred.expires_at else 0

    scored_count = 0
    correct_count = 0
    if user:
        from sqlalchemy import func
        scored_count = db.query(func.count(UserPrediction.id)).filter(
            UserPrediction.user_id == user.id,
            UserPrediction.outcome.in_(["correct", "incorrect"]),
            UserPrediction.deleted_at.is_(None),
        ).scalar() or 0
        correct_count = db.query(func.count(UserPrediction.id)).filter(
            UserPrediction.user_id == user.id,
            UserPrediction.outcome == "correct",
            UserPrediction.deleted_at.is_(None),
        ).scalar() or 0

    accuracy = round(correct_count / scored_count * 100, 1) if scored_count > 0 else 0

    share_url = f"{SITE_URL}/prediction/{prediction_id}"

    if pred.outcome == "pending":
        tweet_text = f"I just called {pred.ticker} {pred.direction} at {pred.price_target} on @Eidolum. Scoring in {days_left} days. Think I'm wrong? \U0001F440 {share_url}"
    elif pred.outcome == "correct":
        tweet_text = f"Called it! My {pred.ticker} {pred.direction} call at {pred.price_target} was CORRECT on @Eidolum. \u2705 {share_url}"
    else:
        tweet_text = f"My {pred.ticker} {pred.direction} call at {pred.price_target} was scored on @Eidolum. {share_url}"

    return {
        "prediction_id": pred.id,
        "ticker": pred.ticker,
        "ticker_name": ticker_name,
        "direction": pred.direction,
        "price_target": pred.price_target,
        "price_at_call": float(pred.price_at_call) if pred.price_at_call else None,
        "current_price": float(pred.current_price) if pred.current_price else None,
        "evaluation_window_days": pred.evaluation_window_days,
        "outcome": pred.outcome,
        "days_left": days_left,
        "created_at": pred.created_at.isoformat() if pred.created_at else None,
        "expires_at": pred.expires_at.isoformat() if pred.expires_at else None,
        "user_id": pred.user_id,
        "username": username,
        "accuracy": accuracy,
        "scored_count": scored_count,
        "rank": _rank_name(scored_count),
        "share_url": share_url,
        "tweet_text": tweet_text,
        "tweet_url": f"https://twitter.com/intent/tweet?text={_url_encode(tweet_text)}",
    }


# ── GET /api/predictions/{id}/share-card (OG meta HTML) ──────────────────────


@router.get("/predictions/{prediction_id}/share-card", response_class=HTMLResponse)
@limiter.limit("60/minute")
def share_card_html(request: Request, prediction_id: int, db: Session = Depends(get_db)):
    pred = db.query(UserPrediction).filter(UserPrediction.id == prediction_id, UserPrediction.deleted_at.is_(None)).first()
    if not pred:
        return HTMLResponse("<html><body>Not found</body></html>", status_code=404)

    user = db.query(User).filter(User.id == pred.user_id).first()
    username = user.username if user else "Unknown"
    ticker_name = TICKER_INFO.get(pred.ticker, pred.ticker)
    share_url = f"{SITE_URL}/prediction/{prediction_id}"

    og_title = f"{username}'s {pred.ticker} prediction on Eidolum"
    timeframe = f"{pred.evaluation_window_days} day" if pred.evaluation_window_days else ""
    og_description = f"{pred.direction.capitalize()} on {pred.ticker} \u2014 Target: {pred.price_target} \u2014 {timeframe}"
    if pred.outcome in ("correct", "incorrect"):
        og_description = f"{pred.outcome.upper()} \u2014 {og_description}"

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>{og_title}</title>
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{og_description}">
<meta property="og:url" content="{share_url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Eidolum">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{og_title}">
<meta name="twitter:description" content="{og_description}">
<meta http-equiv="refresh" content="0;url={share_url}">
</head>
<body style="background:#0a0a0f;color:#e8e8e6;font-family:sans-serif;text-align:center;padding:40px">
<p>Redirecting to Eidolum...</p>
</body></html>"""

    return HTMLResponse(html)


# ── GET /api/profiles/{user_id}/share-data ────────────────────────────────────


@router.get("/profiles/{user_id}/share-data")
@limiter.limit("60/minute")
def get_profile_share_data(request: Request, user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    from sqlalchemy import func
    scored_count = db.query(func.count(UserPrediction.id)).filter(
        UserPrediction.user_id == user_id,
        UserPrediction.outcome.in_(["correct", "incorrect"]),
        UserPrediction.deleted_at.is_(None),
    ).scalar() or 0
    correct_count = db.query(func.count(UserPrediction.id)).filter(
        UserPrediction.user_id == user_id,
        UserPrediction.outcome == "correct",
        UserPrediction.deleted_at.is_(None),
    ).scalar() or 0
    accuracy = round(correct_count / scored_count * 100, 1) if scored_count > 0 else 0

    level = getattr(user, 'xp_level', 1) or 1
    share_url = f"{SITE_URL}/profile/{user_id}"
    tweet_text = f"My verified prediction track record: {accuracy}% accuracy across {scored_count} calls. Think you can beat me? {share_url} @Eidolum"

    return {
        "user_id": user_id,
        "username": user.username,
        "display_name": user.display_name,
        "accuracy": accuracy,
        "scored_count": scored_count,
        "rank": _rank_name(scored_count),
        "streak_best": user.streak_best or 0,
        "share_url": share_url,
        "tweet_text": tweet_text,
        "tweet_url": f"https://twitter.com/intent/tweet?text={_url_encode(tweet_text)}",
    }


def _url_encode(text: str) -> str:
    import urllib.parse
    return urllib.parse.quote(text, safe='')


# ── GET /api/embed/{username} — embeddable widget ────────────────────────────


@router.get("/embed/{username}", response_class=HTMLResponse)
@limiter.limit("120/minute")
def embed_widget(request: Request, username: str, db: Session = Depends(get_db)):
    from sqlalchemy import func
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return HTMLResponse("<html><body style='background:transparent'>User not found</body></html>", status_code=404)

    scored_count = db.query(func.count(UserPrediction.id)).filter(
        UserPrediction.user_id == user.id,
        UserPrediction.outcome.in_(["correct", "incorrect"]),
        UserPrediction.deleted_at.is_(None),
    ).scalar() or 0
    correct_count = db.query(func.count(UserPrediction.id)).filter(
        UserPrediction.user_id == user.id,
        UserPrediction.outcome == "correct",
        UserPrediction.deleted_at.is_(None),
    ).scalar() or 0
    accuracy = round(correct_count / scored_count * 100, 1) if scored_count > 0 else 0
    level = getattr(user, 'xp_level', 1) or 1

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:transparent}}
.w{{background:#0f1115;border:1px solid rgba(212,160,23,0.15);border-radius:10px;padding:12px 16px;display:flex;align-items:center;gap:12px;text-decoration:none;color:#e4e4e7;max-width:300px}}
.w:hover{{border-color:rgba(212,160,23,0.3)}}
.acc{{font-family:monospace;font-size:20px;font-weight:700;color:#D4A843}}
.meta{{font-size:11px;color:#a1a1aa}}
.lbl{{font-size:10px;color:#52525b}}
</style></head><body>
<a href="{SITE_URL}/profile/{user.id}" target="_blank" class="w">
<div><div class="acc">{accuracy}%</div><div class="lbl">accuracy</div></div>
<div style="width:1px;height:28px;background:rgba(212,160,23,0.15)"></div>
<div><div style="font-size:13px;font-weight:600">@{user.username}</div>
<div class="meta">Lv.{level} · {scored_count} scored</div>
<div class="lbl">Verified by Eidolum</div></div>
</a></body></html>"""
    return HTMLResponse(html)


# ══════════════════════════════════════════════════════════════════════════════
# "I Told You So" — brag sharing for correct predictions
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/predictions/{prediction_id}/told-you-so")
@limiter.limit("60/minute")
def told_you_so_data(request: Request, prediction_id: int, db: Session = Depends(get_db)):
    from middleware.auth import require_user
    from auth import get_current_user_dep

    pred = db.query(UserPrediction).filter(UserPrediction.id == prediction_id, UserPrediction.deleted_at.is_(None)).first()
    if not pred:
        raise HTTPException(status_code=404, detail="Prediction not found")
    if pred.outcome != "correct":
        raise HTTPException(status_code=400, detail="Only correct predictions can use I Told You So")

    user = db.query(User).filter(User.id == pred.user_id).first()
    username = user.username if user else "Unknown"
    ticker_name = TICKER_INFO.get(pred.ticker, pred.ticker)

    from sqlalchemy import func
    scored_count = db.query(func.count(UserPrediction.id)).filter(
        UserPrediction.user_id == pred.user_id,
        UserPrediction.outcome.in_(["correct", "incorrect"]),
        UserPrediction.deleted_at.is_(None),
    ).scalar() or 0
    correct_count = db.query(func.count(UserPrediction.id)).filter(
        UserPrediction.user_id == pred.user_id,
        UserPrediction.outcome == "correct",
        UserPrediction.deleted_at.is_(None),
    ).scalar() or 0
    accuracy = round(correct_count / scored_count * 100, 1) if scored_count > 0 else 0

    share_url = f"{SITE_URL}/prediction/{prediction_id}/told-you-so?ref={username}"

    price_entry = float(pred.price_at_call) if pred.price_at_call else None
    price_final = float(pred.current_price) if pred.current_price else None
    price_change = None
    if price_entry and price_final:
        price_change = round((price_final - price_entry) / price_entry * 100, 2)

    called_date = pred.created_at.strftime("%b %d, %Y") if pred.created_at else None
    scored_date = pred.evaluated_at.strftime("%b %d, %Y") if pred.evaluated_at else None

    tweet_text = f"I called {pred.ticker} {pred.direction} on {called_date} and I was right."
    if price_entry and price_final:
        tweet_text += f" ${price_entry} \u2192 ${price_final}."
    tweet_text += f" Receipts don't lie. \U0001F4C8 #IToldYouSo @Eidolum {share_url}"

    linkedin_url = f"https://www.linkedin.com/sharing/share-offsite/?url={_url_encode(share_url)}"

    return {
        "prediction_id": pred.id,
        "ticker": pred.ticker,
        "ticker_name": ticker_name,
        "direction": pred.direction,
        "price_target": pred.price_target,
        "price_entry": price_entry,
        "price_final": price_final,
        "price_change_percent": price_change,
        "called_date": called_date,
        "scored_date": scored_date,
        "outcome": "correct",
        "username": username,
        "accuracy": accuracy,
        "scored_count": scored_count,
        "rank": _rank_name(scored_count),
        "streak": user.streak_current if user else 0,
        "share_url": share_url,
        "tweet_text": tweet_text,
        "tweet_url": f"https://twitter.com/intent/tweet?text={_url_encode(tweet_text)}",
        "linkedin_url": linkedin_url,
    }


# ── OG meta page for told-you-so ──────────────────────────────────────────────


@router.get("/predictions/{prediction_id}/told-you-so-page", response_class=HTMLResponse)
@limiter.limit("60/minute")
def told_you_so_page(request: Request, prediction_id: int, db: Session = Depends(get_db)):
    pred = db.query(UserPrediction).filter(UserPrediction.id == prediction_id, UserPrediction.deleted_at.is_(None)).first()
    if not pred:
        return HTMLResponse("<html><body>Not found</body></html>", status_code=404)

    user = db.query(User).filter(User.id == pred.user_id).first()
    username = user.username if user else "Unknown"

    og_title = f"{username} called {pred.ticker} correctly on Eidolum"
    og_desc = f"I TOLD YOU SO \u2014 {pred.direction.capitalize()} on {pred.ticker} at {pred.price_target}. Verified correct."
    share_url = f"{SITE_URL}/prediction/{prediction_id}/told-you-so"

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>{og_title}</title>
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{og_desc}">
<meta property="og:url" content="{share_url}">
<meta property="og:site_name" content="Eidolum">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{og_title}">
<meta name="twitter:description" content="{og_desc}">
<meta http-equiv="refresh" content="0;url={share_url}">
</head><body style="background:#0a0a0f;color:#e8e8e6;text-align:center;padding:40px">
<p>Redirecting...</p>
</body></html>"""
    return HTMLResponse(html)


# ── Referral tracking ─────────────────────────────────────────────────────────


@router.post("/referrals/track")
@limiter.limit("30/minute")
def track_referral(request: Request, ref: str = "", prediction_id: int = 0, db: Session = Depends(get_db)):
    if not ref:
        return {"status": "skipped"}
    from models import ActivityEvent
    # Simple: log as activity event for now
    from activity import log_activity
    user = db.query(User).filter(User.username == ref).first()
    if user:
        log_activity(
            user_id=user.id, event_type="referral_click",
            description=f"Someone clicked {ref}'s shared prediction",
            data={"ref": ref, "prediction_id": prediction_id}, db=db,
        )
        db.commit()
    return {"status": "tracked"}

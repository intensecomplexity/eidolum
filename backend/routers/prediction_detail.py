"""
Full prediction detail endpoint — single source of truth for one prediction.
"""
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import User, UserPrediction, Prediction, Forecaster, PredictionReaction, PredictionComment
from rate_limit import limiter
from ticker_lookup import TICKER_INFO
from auth import get_current_user as _decode_token

router = APIRouter()
_optional_bearer = HTTPBearer(auto_error=False)


def _rank_name(scored: int) -> str:
    if scored >= 250: return "Legendary"
    if scored >= 100: return "Oracle"
    if scored >= 50: return "Strategist"
    if scored >= 25: return "Analyst"
    if scored >= 10: return "Novice"
    return "Unranked"


@router.get("/predictions/detail/{prediction_id}")
@limiter.limit("60/minute")
def get_prediction_detail(
    request: Request,
    prediction_id: int,
    source: str = Query("user"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    db: Session = Depends(get_db),
):
    now = datetime.utcnow()
    current_user_id = None
    if credentials and credentials.credentials:
        try:
            current_user_id = _decode_token(credentials.credentials).get("user_id")
        except Exception:
            pass

    if source == "user":
        pred = db.query(UserPrediction).filter(UserPrediction.id == prediction_id, UserPrediction.deleted_at.is_(None)).first()
        if not pred:
            raise HTTPException(status_code=404, detail="Prediction not found")

        user = db.query(User).filter(User.id == pred.user_id).first()
        scored_count = db.query(func.count(UserPrediction.id)).filter(UserPrediction.user_id == pred.user_id, UserPrediction.outcome.in_(["hit","near","miss","correct","incorrect"]), UserPrediction.deleted_at.is_(None)).scalar() or 0
        correct_count = db.query(func.count(UserPrediction.id)).filter(UserPrediction.user_id == pred.user_id, UserPrediction.outcome == "correct", UserPrediction.deleted_at.is_(None)).scalar() or 0
        accuracy = round(correct_count / scored_count * 100, 1) if scored_count > 0 else 0

        entry_price = float(pred.price_at_call) if pred.price_at_call else None
        current_price = float(pred.current_price) if pred.current_price else None
        pct_change = round((current_price - entry_price) / entry_price * 100, 2) if entry_price and current_price else None

        days_left = None
        if pred.expires_at and pred.outcome == "pending":
            days_left = max(0, (pred.expires_at - now).total_seconds() / 86400)

        result = {
            "id": pred.id,
            "source": "user",
            "ticker": pred.ticker,
            "ticker_name": TICKER_INFO.get(pred.ticker, pred.ticker),
            "direction": pred.direction,
            "price_target": pred.price_target,
            "price_at_call": entry_price,
            "current_price": current_price,
            "pct_change": pct_change,
            "evaluation_window_days": pred.evaluation_window_days,
            "reasoning": pred.reasoning,
            "template": getattr(pred, 'template', None) or "custom",
            "outcome": pred.outcome,
            "created_at": pred.created_at.isoformat() if pred.created_at else None,
            "expires_at": pred.expires_at.isoformat() if pred.expires_at else None,
            "evaluated_at": pred.evaluated_at.isoformat() if pred.evaluated_at else None,
            "days_left": round(days_left, 1) if days_left is not None else None,
            "user_id": pred.user_id,
            "username": user.username if user else None,
            "display_name": user.display_name if user else None,
            "user_type": (user.user_type or "player") if user else "player",
            "accuracy": accuracy,
            "scored_count": scored_count,
            "rank": _rank_name(scored_count),
        }

    elif source == "analyst":
        pred = db.query(Prediction).filter(Prediction.id == prediction_id).first()
        if not pred:
            raise HTTPException(status_code=404, detail="Prediction not found")

        forecaster = db.query(Forecaster).filter(Forecaster.id == pred.forecaster_id).first()

        result = {
            "id": pred.id,
            "source": "analyst",
            "ticker": pred.ticker,
            "ticker_name": TICKER_INFO.get(pred.ticker, pred.ticker),
            "direction": pred.direction,
            "price_target": str(pred.target_price) if pred.target_price else None,
            "price_at_call": pred.entry_price,
            "current_price": None,
            "pct_change": pred.actual_return,
            "evaluation_window_days": pred.window_days,
            "reasoning": pred.context,
            "template": None,
            "outcome": pred.outcome,
            "created_at": pred.prediction_date.isoformat() if pred.prediction_date else None,
            "expires_at": pred.evaluation_date.isoformat() if pred.evaluation_date else None,
            "evaluated_at": pred.evaluation_date.isoformat() if pred.evaluation_date else None,
            "days_left": None,
            "user_id": pred.forecaster_id,
            "username": forecaster.name if forecaster else None,
            "display_name": forecaster.name if forecaster else None,
            "user_type": "analyst",
            "accuracy": forecaster.accuracy_score if forecaster else 0,
            "scored_count": forecaster.total_predictions if forecaster else 0,
            "rank": "Analyst",
            "source_url": pred.source_url,
            "exact_quote": pred.exact_quote,
            "source_verbatim_quote": pred.source_verbatim_quote,
            "archive_url": pred.archive_url,
        }
    else:
        raise HTTPException(status_code=400, detail="source must be 'user' or 'analyst'")

    # Reactions
    reactions = db.query(PredictionReaction).filter(PredictionReaction.prediction_id == prediction_id, PredictionReaction.prediction_source == source).all()
    counts = {"agree": 0, "disagree": 0, "bold_call": 0, "no_way": 0}
    user_reaction = None
    for r in reactions:
        if r.reaction in counts:
            counts[r.reaction] += 1
        if current_user_id and r.user_id == current_user_id:
            user_reaction = r.reaction
    result["reactions"] = {**counts, "total": sum(counts.values()), "user_reaction": user_reaction}

    # Comments (latest 10)
    comments = db.query(PredictionComment).filter(PredictionComment.prediction_id == prediction_id, PredictionComment.prediction_source == source).order_by(PredictionComment.created_at.desc()).limit(10).all()
    comment_users = {u.id: u for u in db.query(User).filter(User.id.in_(set(c.user_id for c in comments))).all()} if comments else {}
    result["comments"] = [{
        "id": c.id, "user_id": c.user_id,
        "username": comment_users.get(c.user_id, None) and comment_users[c.user_id].username,
        "comment": c.comment,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    } for c in comments]
    result["comment_count"] = db.query(func.count(PredictionComment.id)).filter(PredictionComment.prediction_id == prediction_id, PredictionComment.prediction_source == source).scalar() or 0

    # Other predictions on same ticker
    if source == "user":
        others = db.query(UserPrediction, User.username).join(User, User.id == UserPrediction.user_id).filter(
            UserPrediction.ticker == result["ticker"], UserPrediction.outcome == "pending",
            UserPrediction.deleted_at.is_(None), UserPrediction.id != prediction_id,
        ).limit(5).all()
        result["others_on_ticker"] = [{"id": p.id, "username": u, "direction": p.direction, "price_target": p.price_target} for p, u in others]

    return result


# ── Evidence endpoint (ship #13) ─────────────────────────────────────────────

# In-memory cache for YouTube availability checks (24h TTL).
_yt_availability_cache: dict[str, tuple[float, bool]] = {}
_YT_AVAILABILITY_TTL = 24 * 3600  # 24 hours


def _check_video_available(video_id: str) -> bool:
    """HEAD-check YouTube oEmbed to see if the video still exists.
    Cached for 24 hours. Returns True on 200, False on 404/error."""
    import time as _time
    import httpx
    now = _time.time()
    cached = _yt_availability_cache.get(video_id)
    if cached and now - cached[0] < _YT_AVAILABILITY_TTL:
        return cached[1]
    url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
    try:
        with httpx.Client(timeout=5.0, follow_redirects=True) as client:
            r = client.head(url)
            available = (r.status_code == 200)
    except Exception:
        available = False
    _yt_availability_cache[video_id] = (now, available)
    return available


@router.get("/predictions/{prediction_id}/evidence")
@limiter.limit("60/minute")
def get_prediction_evidence(
    request: Request,
    prediction_id: int,
    db: Session = Depends(get_db),
):
    """Return the evidence chain for a YouTube prediction: the verbatim
    quote, the video timestamp, and the stored transcript excerpt with
    its SHA256 hash at capture time. This is the proof that the
    prediction was actually made on video — even if the forecaster
    deletes the source video, the SHA256-locked transcript in our
    video_transcripts table attests to what was said and when we
    captured it.
    """
    from sqlalchemy import text as sql_text
    from jobs.video_transcript_store import excerpt_around_quote

    row = db.execute(sql_text("""
        SELECT p.id, p.ticker, p.source_verbatim_quote,
               p.source_timestamp_seconds, p.source_timestamp_method,
               p.source_timestamp_confidence, p.source_url,
               COALESCE(p.transcript_video_id,
                        SUBSTRING(p.source_platform_id FROM 4 FOR 11)) as vid,
               vt.transcript_text, vt.sha256_hash, vt.captured_at,
               vt.video_title, vt.channel_name, vt.video_publish_date
        FROM predictions p
        LEFT JOIN video_transcripts vt ON vt.video_id =
            COALESCE(p.transcript_video_id,
                     SUBSTRING(p.source_platform_id FROM 4 FOR 11))
        WHERE p.id = :pid
    """), {"pid": prediction_id}).first()

    if not row:
        raise HTTPException(status_code=404, detail="prediction not found")

    (pid, ticker, quote, secs, method, conf, source_url, video_id,
     transcript_text, sha, captured_at, vtitle, channel, vpub) = row

    if not video_id:
        raise HTTPException(status_code=400, detail="not a YouTube prediction")

    # Construct the YouTube URL with timestamp anchor.
    if secs is not None:
        vurl = f"https://www.youtube.com/watch?v={video_id}&t={int(secs)}s"
    else:
        vurl = f"https://www.youtube.com/watch?v={video_id}"

    # Transcript excerpt — window around the verbatim quote.
    excerpt = excerpt_around_quote(transcript_text or "", quote or "", window=250) if transcript_text else None

    return {
        "prediction_id": pid,
        "ticker": ticker,
        "source_verbatim_quote": quote,
        "source_timestamp_seconds": int(secs) if secs is not None else None,
        "source_timestamp_method": method,
        "source_timestamp_confidence": float(conf) if conf is not None else None,
        "video_id": video_id,
        "video_url": vurl,
        "video_title": vtitle,
        "channel_name": channel,
        "video_publish_date": vpub.isoformat() if vpub else None,
        "transcript_captured": transcript_text is not None,
        "transcript_sha256": sha,
        "transcript_captured_at": captured_at.isoformat() if captured_at else None,
        "transcript_excerpt": excerpt,
        "transcript_char_count": len(transcript_text) if transcript_text else 0,
        "video_available": _check_video_available(video_id),
    }

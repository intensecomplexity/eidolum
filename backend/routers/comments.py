"""
Prediction comments — short text comments tied to predictions.
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import PredictionComment, UserPrediction, User
from middleware.auth import require_user
from rate_limit import limiter
from auth import get_current_user as _decode_token

router = APIRouter()
_optional_bearer = HTTPBearer(auto_error=False)

MAX_COMMENT_LEN = 280
MAX_COMMENTS_PER_PREDICTION = 3
MAX_COMMENTS_PER_DAY = 50


class CommentRequest(BaseModel):
    prediction_id: int
    prediction_source: str
    comment: str


def _rank_name(scored: int) -> str:
    if scored >= 250: return "Legendary"
    if scored >= 100: return "Oracle"
    if scored >= 50: return "Strategist"
    if scored >= 25: return "Analyst"
    if scored >= 10: return "Novice"
    return "Unranked"


def _comment_dict(c: PredictionComment, user: User | None) -> dict:
    scored = 0
    correct = 0
    if user:
        scored = getattr(user, '_scored_cache', 0)
        correct = getattr(user, '_correct_cache', 0)
    accuracy = round(correct / scored * 100, 1) if scored > 0 else 0

    return {
        "id": c.id,
        "prediction_id": c.prediction_id,
        "prediction_source": c.prediction_source,
        "user_id": c.user_id,
        "username": user.username if user else None,
        "display_name": user.display_name if user else None,
        "rank": _rank_name(scored),
        "accuracy": accuracy,
        "comment": c.comment,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


# ── POST /api/comments ───────────────────────────────────────────────────────


@router.post("/comments")
@limiter.limit("30/minute")
def create_comment(
    request: Request,
    req: CommentRequest,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    if req.prediction_source not in ("user", "analyst"):
        raise HTTPException(status_code=400, detail="prediction_source must be 'user' or 'analyst'")

    text = req.comment.strip()
    if len(text) < 2:
        raise HTTPException(status_code=400, detail="Comment must be at least 2 characters")
    if len(text) > MAX_COMMENT_LEN:
        raise HTTPException(status_code=400, detail=f"Comment must be under {MAX_COMMENT_LEN} characters")

    # Check per-prediction limit
    per_pred = (
        db.query(func.count(PredictionComment.id))
        .filter(
            PredictionComment.prediction_id == req.prediction_id,
            PredictionComment.prediction_source == req.prediction_source,
            PredictionComment.user_id == user_id,
        )
        .scalar() or 0
    )
    if per_pred >= MAX_COMMENTS_PER_PREDICTION:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_COMMENTS_PER_PREDICTION} comments per prediction")

    # Check daily limit
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    daily = (
        db.query(func.count(PredictionComment.id))
        .filter(PredictionComment.user_id == user_id, PredictionComment.created_at >= today_start)
        .scalar() or 0
    )
    if daily >= MAX_COMMENTS_PER_DAY:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_COMMENTS_PER_DAY} comments per day")

    comment = PredictionComment(
        prediction_id=req.prediction_id,
        prediction_source=req.prediction_source,
        user_id=user_id,
        comment=text,
    )
    db.add(comment)

    # Notify prediction owner (if user prediction and not self-commenting)
    if req.prediction_source == "user":
        pred = db.query(UserPrediction).filter(UserPrediction.id == req.prediction_id).first()
        if pred and pred.user_id != user_id:
            commenter = db.query(User).filter(User.id == user_id).first()
            cname = commenter.username if commenter else "Someone"
            preview = text[:60] + ("..." if len(text) > 60 else "")
            from notifications import create_notification
            create_notification(
                user_id=pred.user_id, type="comment",
                title="New Comment",
                message=f"{cname} commented on your {pred.ticker} call: \"{preview}\"",
                data={"prediction_id": pred.id, "comment_id": None}, db=db,
            )

    # XP
    try:
        from xp import award_xp
        award_xp(user_id, "comment_on_prediction", db)
    except Exception:
        pass

    db.commit()
    db.refresh(comment)

    user = db.query(User).filter(User.id == user_id).first()
    return _comment_dict(comment, user)


# ── GET /api/comments/{prediction_id}/{prediction_source} ─────────────────────


@router.get("/comments/{prediction_id}/{prediction_source}")
@limiter.limit("120/minute")
def get_comments(
    request: Request,
    prediction_id: int,
    prediction_source: str,
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    comments = (
        db.query(PredictionComment)
        .filter(
            PredictionComment.prediction_id == prediction_id,
            PredictionComment.prediction_source == prediction_source,
        )
        .order_by(PredictionComment.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    # Batch fetch users
    user_ids = set(c.user_id for c in comments)
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}

    return [_comment_dict(c, users.get(c.user_id)) for c in comments]


# ── DELETE /api/comments/{comment_id} ─────────────────────────────────────────


@router.delete("/comments/{comment_id}")
@limiter.limit("30/minute")
def delete_comment(
    request: Request,
    comment_id: int,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    comment = db.query(PredictionComment).filter(PredictionComment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.user_id != user_id:
        raise HTTPException(status_code=403, detail="Can only delete your own comments")

    db.delete(comment)
    db.commit()
    return {"status": "deleted"}


# ── GET /api/comments/count/{prediction_id}/{prediction_source} ───────────────


@router.get("/comments/count/{prediction_id}/{prediction_source}")
@limiter.limit("120/minute")
def comment_count(request: Request, prediction_id: int, prediction_source: str, db: Session = Depends(get_db)):
    count = (
        db.query(func.count(PredictionComment.id))
        .filter(
            PredictionComment.prediction_id == prediction_id,
            PredictionComment.prediction_source == prediction_source,
        )
        .scalar() or 0
    )
    return {"count": count}

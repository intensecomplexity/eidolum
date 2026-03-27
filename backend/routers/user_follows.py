import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from database import get_db
from models import User, UserPrediction, Follow
from middleware.auth import require_user
from rate_limit import limiter

router = APIRouter()


def _user_accuracy(user_id: int, db: Session) -> float:
    scored = (
        db.query(UserPrediction)
        .filter(UserPrediction.user_id == user_id, UserPrediction.outcome.in_(["correct", "incorrect"]))
        .all()
    )
    if not scored:
        return 0.0
    correct = sum(1 for p in scored if p.outcome == "correct")
    return round(correct / len(scored) * 100, 1)


# ── POST /api/follows/{user_id} ──────────────────────────────────────────────


@router.post("/follows/{user_id}")
@limiter.limit("30/minute")
def follow_user(
    request: Request,
    user_id: int,
    current_user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    if current_user_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    existing = (
        db.query(Follow)
        .filter(Follow.follower_id == current_user_id, Follow.following_id == user_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Already following this user")

    follow = Follow(follower_id=current_user_id, following_id=user_id)
    db.add(follow)
    db.commit()
    db.refresh(follow)

    return {"status": "following", "follower_id": current_user_id, "following_id": user_id}


# ── DELETE /api/follows/{user_id} ─────────────────────────────────────────────


@router.delete("/follows/{user_id}")
@limiter.limit("30/minute")
def unfollow_user(
    request: Request,
    user_id: int,
    current_user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    follow = (
        db.query(Follow)
        .filter(Follow.follower_id == current_user_id, Follow.following_id == user_id)
        .first()
    )
    if not follow:
        raise HTTPException(status_code=404, detail="Not following this user")

    db.delete(follow)
    db.commit()

    return {"status": "unfollowed"}


# ── GET /api/follows/{user_id}/followers ──────────────────────────────────────


@router.get("/follows/{user_id}/followers")
@limiter.limit("60/minute")
def get_followers(request: Request, user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    follows = (
        db.query(Follow)
        .filter(Follow.following_id == user_id)
        .all()
    )

    results = []
    for f in follows:
        follower = db.query(User).filter(User.id == f.follower_id).first()
        if not follower:
            continue
        results.append({
            "user_id": follower.id,
            "username": follower.username,
            "display_name": follower.display_name,
            "accuracy": _user_accuracy(follower.id, db),
        })

    return results


# ── GET /api/follows/{user_id}/following ──────────────────────────────────────


@router.get("/follows/{user_id}/following")
@limiter.limit("60/minute")
def get_following(request: Request, user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    follows = (
        db.query(Follow)
        .filter(Follow.follower_id == user_id)
        .all()
    )

    results = []
    for f in follows:
        target = db.query(User).filter(User.id == f.following_id).first()
        if not target:
            continue
        results.append({
            "user_id": target.id,
            "username": target.username,
            "display_name": target.display_name,
            "accuracy": _user_accuracy(target.id, db),
        })

    return results


# ── GET /api/feed ─────────────────────────────────────────────────────────────


@router.get("/feed")
@limiter.limit("60/minute")
def get_feed(
    request: Request,
    current_user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    # Get IDs of users I follow
    following_ids = [
        f.following_id
        for f in db.query(Follow.following_id).filter(Follow.follower_id == current_user_id).all()
    ]

    if not following_ids:
        return []

    rows = (
        db.query(UserPrediction, User.username)
        .join(User, User.id == UserPrediction.user_id)
        .filter(UserPrediction.user_id.in_(following_ids))
        .order_by(UserPrediction.created_at.desc())
        .limit(50)
        .all()
    )

    # Pre-compute accuracy for each user in the feed
    accuracy_cache = {}
    for _, username in rows:
        pass  # just need user_ids
    user_ids = set(p.user_id for p, _ in rows)
    for uid in user_ids:
        accuracy_cache[uid] = _user_accuracy(uid, db)

    results = []
    for pred, username in rows:
        results.append({
            "id": pred.id,
            "user_id": pred.user_id,
            "username": username,
            "accuracy": accuracy_cache.get(pred.user_id, 0.0),
            "ticker": pred.ticker,
            "direction": pred.direction,
            "price_target": pred.price_target,
            "price_at_call": float(pred.price_at_call) if pred.price_at_call else None,
            "evaluation_window_days": pred.evaluation_window_days,
            "reasoning": pred.reasoning,
            "created_at": pred.created_at.isoformat() if pred.created_at else None,
            "expires_at": pred.expires_at.isoformat() if pred.expires_at else None,
            "outcome": pred.outcome,
            "current_price": float(pred.current_price) if pred.current_price else None,
        })

    return results

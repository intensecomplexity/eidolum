"""
Ticker discussion threads — per-ticker comment boards.
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import TickerDiscussion, TickerDiscussionLike, User
from middleware.auth import require_user
from rate_limit import limiter
from utils.ticker import ticker_is_known

router = APIRouter()

MAX_TEXT_LEN = 500
MAX_PER_TICKER_PER_DAY = 10


class DiscussionPostRequest(BaseModel):
    text: str
    parent_id: Optional[int] = None


def _post_dict(d: TickerDiscussion, user: User | None, liked_by_me: bool = False) -> dict:
    return {
        "id": d.id,
        "user_id": d.user_id,
        "ticker": d.ticker,
        "username": user.username if user else None,
        "display_name": user.display_name if user else None,
        "xp_level": getattr(user, 'xp_level', 1) if user else 1,
        "text": d.text,
        "parent_id": d.parent_id,
        "likes_count": d.likes_count or 0,
        "liked_by_me": liked_by_me,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


@router.post("/ticker/{ticker}/discussions")
@limiter.limit("30/minute")
def create_discussion_post(
    request: Request,
    ticker: str,
    req: DiscussionPostRequest,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    ticker = ticker.upper().strip()
    text = req.text.strip()

    # Ship #13B Bug 12: don't let users attach a discussion thread to a
    # ticker that doesn't exist in the system. If the asset page would
    # 404, this endpoint should too, so the DB never accumulates
    # discussions keyed on bogus symbols.
    if not ticker_is_known(db, ticker):
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")

    if len(text) < 2:
        raise HTTPException(status_code=400, detail="Post must be at least 2 characters")
    if len(text) > MAX_TEXT_LEN:
        raise HTTPException(status_code=400, detail=f"Post must be under {MAX_TEXT_LEN} characters")

    from profanity_filter import is_profane, record_violation
    if is_profane(text):
        record_violation(user_id, text, "ticker_discussion")
        raise HTTPException(status_code=400, detail="Your post contains inappropriate language.")

    # Daily limit per ticker
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    daily = (
        db.query(func.count(TickerDiscussion.id))
        .filter(TickerDiscussion.user_id == user_id, TickerDiscussion.ticker == ticker, TickerDiscussion.created_at >= today_start)
        .scalar() or 0
    )
    if daily >= MAX_PER_TICKER_PER_DAY:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_PER_TICKER_PER_DAY} posts per ticker per day")

    # Validate parent exists and belongs to same ticker (one-level deep only)
    if req.parent_id:
        parent = db.query(TickerDiscussion).filter(TickerDiscussion.id == req.parent_id).first()
        if not parent or parent.ticker != ticker:
            raise HTTPException(status_code=400, detail="Invalid parent post")
        if parent.parent_id is not None:
            raise HTTPException(status_code=400, detail="Replies can only be one level deep")

    post = TickerDiscussion(user_id=user_id, ticker=ticker, text=text, parent_id=req.parent_id)
    db.add(post)
    db.commit()
    db.refresh(post)

    user = db.query(User).filter(User.id == user_id).first()
    return _post_dict(post, user)


@router.get("/ticker/{ticker}/discussions")
@limiter.limit("60/minute")
def get_discussion_posts(
    request: Request,
    ticker: str,
    sort: str = Query("newest"),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    ticker = ticker.upper().strip()

    # Get top-level posts
    query = db.query(TickerDiscussion).filter(
        TickerDiscussion.ticker == ticker,
        TickerDiscussion.parent_id.is_(None),
    )
    if sort == "likes":
        query = query.order_by(TickerDiscussion.likes_count.desc(), TickerDiscussion.created_at.desc())
    else:
        query = query.order_by(TickerDiscussion.created_at.desc())

    posts = query.offset(offset).limit(limit).all()

    # Get replies for these posts
    post_ids = [p.id for p in posts]
    replies = []
    if post_ids:
        replies = db.query(TickerDiscussion).filter(TickerDiscussion.parent_id.in_(post_ids)).order_by(TickerDiscussion.created_at.asc()).all()

    # Batch fetch users
    all_user_ids = set(p.user_id for p in posts) | set(r.user_id for r in replies)
    users = {u.id: u for u in db.query(User).filter(User.id.in_(all_user_ids)).all()} if all_user_ids else {}

    # Check likes by current user
    my_likes = set()
    try:
        from auth import get_current_user
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if token:
            me = get_current_user(token)
            if me:
                all_disc_ids = post_ids + [r.id for r in replies]
                liked = db.query(TickerDiscussionLike.discussion_id).filter(
                    TickerDiscussionLike.user_id == me["user_id"],
                    TickerDiscussionLike.discussion_id.in_(all_disc_ids),
                ).all()
                my_likes = set(l[0] for l in liked)
    except Exception:
        pass

    # Build reply map
    reply_map = {}
    for r in replies:
        reply_map.setdefault(r.parent_id, []).append(_post_dict(r, users.get(r.user_id), r.id in my_likes))

    result = []
    for p in posts:
        d = _post_dict(p, users.get(p.user_id), p.id in my_likes)
        d["replies"] = reply_map.get(p.id, [])
        result.append(d)

    return result


@router.post("/ticker/{ticker}/discussions/{post_id}/like")
@limiter.limit("60/minute")
def toggle_like(
    request: Request,
    ticker: str,
    post_id: int,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    post = db.query(TickerDiscussion).filter(TickerDiscussion.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    existing = db.query(TickerDiscussionLike).filter(
        TickerDiscussionLike.user_id == user_id,
        TickerDiscussionLike.discussion_id == post_id,
    ).first()

    if existing:
        db.delete(existing)
        post.likes_count = max(0, (post.likes_count or 0) - 1)
        db.commit()
        return {"liked": False, "likes_count": post.likes_count}
    else:
        db.add(TickerDiscussionLike(user_id=user_id, discussion_id=post_id))
        post.likes_count = (post.likes_count or 0) + 1
        db.commit()
        return {"liked": True, "likes_count": post.likes_count}


@router.delete("/ticker/{ticker}/discussions/{post_id}")
@limiter.limit("30/minute")
def delete_discussion_post(
    request: Request,
    ticker: str,
    post_id: int,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    post = db.query(TickerDiscussion).filter(TickerDiscussion.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.user_id != user_id:
        raise HTTPException(status_code=403, detail="Can only delete your own posts")

    db.delete(post)
    db.commit()
    return {"status": "deleted"}

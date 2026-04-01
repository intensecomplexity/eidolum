import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from typing import Optional

from database import get_db
from models import User, UserPrediction, Follow
from middleware.auth import require_user
from rate_limit import limiter
from ticker_lookup import search_tickers as _search_tickers
from auth import get_current_user as _decode_token

_optional_bearer = HTTPBearer(auto_error=False)

router = APIRouter()


def _rank_name(scored: int) -> str:
    if scored >= 250: return "Legendary"
    if scored >= 100: return "Oracle"
    if scored >= 50: return "Strategist"
    if scored >= 25: return "Analyst"
    if scored >= 10: return "Novice"
    return "Unranked"


def _user_accuracy(user_id: int, db: Session) -> float:
    scored = db.query(UserPrediction).filter(UserPrediction.user_id == user_id, UserPrediction.outcome.in_(["hit","near","miss","correct","incorrect"])).all()
    if not scored: return 0.0
    return round(sum(1 for p in scored if p.outcome == "correct") / len(scored) * 100, 1)


def _user_scored_count(user_id: int, db: Session) -> int:
    return db.query(func.count(UserPrediction.id)).filter(UserPrediction.user_id == user_id, UserPrediction.outcome.in_(["hit","near","miss","correct","incorrect"]), UserPrediction.deleted_at.is_(None)).scalar() or 0


def _accepted():
    """Filter for accepted friendships only."""
    return Follow.status == "accepted"


# ── GET /api/search ───────────────────────────────────────────────────────────


@router.get("/search")
@limiter.limit("60/minute")
def unified_search(request: Request, q: str = Query(""), credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer), db: Session = Depends(get_db)):
    query = q.strip()
    if not query:
        return {"tickers": [], "users": []}

    tickers = _search_tickers(query)
    for t in tickers:
        t["type"] = "ticker"

    pattern = f"%{query.lower()}%"
    user_rows = db.query(User).filter(or_(func.lower(User.username).like(pattern), func.lower(User.display_name).like(pattern))).limit(5).all()

    current_user_id = None
    if credentials and credentials.credentials:
        try:
            current_user_id = _decode_token(credentials.credentials).get("user_id")
        except Exception:
            pass

    friend_ids = set()
    if current_user_id:
        friend_ids = set(f.following_id for f in db.query(Follow.following_id).filter(Follow.follower_id == current_user_id, _accepted()).all())

    users = []
    for u in user_rows:
        scored = _user_scored_count(u.id, db)
        users.append({"user_id": u.id, "username": u.username, "display_name": u.display_name, "accuracy": _user_accuracy(u.id, db), "scored": scored, "rank": _rank_name(scored), "is_friend": u.id in friend_ids, "type": "user"})

    return {"tickers": tickers, "users": users}


# ── GET /api/friends/suggestions ──────────────────────────────────────────────


@router.get("/friends/suggestions")
@limiter.limit("30/minute")
def friend_suggestions(request: Request, current_user_id: int = Depends(require_user), db: Session = Depends(get_db)):
    friend_ids = set(f.following_id for f in db.query(Follow.following_id).filter(Follow.follower_id == current_user_id, _accepted()).all())
    pending_ids = set(f.following_id for f in db.query(Follow.following_id).filter(Follow.follower_id == current_user_id, Follow.status == "pending").all())
    exclude = friend_ids | pending_ids | {current_user_id}

    users = db.query(User).filter(User.id.notin_(exclude)).all()
    results = []
    for u in users:
        scored = _user_scored_count(u.id, db)
        if scored < 5: continue
        results.append({"user_id": u.id, "username": u.username, "display_name": u.display_name, "accuracy": _user_accuracy(u.id, db), "scored": scored, "rank": _rank_name(scored)})
    results.sort(key=lambda x: x["accuracy"], reverse=True)
    return results[:5]


# ── POST /api/follows/{user_id} — Send friend request ────────────────────────


@router.post("/follows/{user_id}")
@limiter.limit("30/minute")
def send_friend_request(request: Request, user_id: int, current_user_id: int = Depends(require_user), db: Session = Depends(get_db)):
    if current_user_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot friend yourself")

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    existing = db.query(Follow).filter(Follow.follower_id == current_user_id, Follow.following_id == user_id).first()
    if existing:
        if existing.status == "accepted":
            raise HTTPException(status_code=409, detail="Already friends")
        if existing.status == "pending":
            raise HTTPException(status_code=409, detail="Request already sent")

    follow = Follow(follower_id=current_user_id, following_id=user_id, status="pending")
    db.add(follow)

    from notifications import create_notification
    requester = db.query(User).filter(User.id == current_user_id).first()
    rname = requester.username if requester else "Someone"
    create_notification(user_id=user_id, type="friend_request", title="Friend Request", message=f"{rname} wants to add you as a friend", data={"from_user_id": current_user_id}, db=db)

    db.commit()
    return {"status": "pending", "message": "Friend request sent"}


# ── POST /api/follows/{user_id}/accept ────────────────────────────────────────


@router.post("/follows/{user_id}/accept")
@limiter.limit("30/minute")
def accept_friend_request(request: Request, user_id: int, current_user_id: int = Depends(require_user), db: Session = Depends(get_db)):
    # The pending request: follower_id=user_id (the person who sent it), following_id=current_user_id (me, the receiver)
    pending = db.query(Follow).filter(Follow.follower_id == user_id, Follow.following_id == current_user_id, Follow.status == "pending").first()
    if not pending:
        raise HTTPException(status_code=404, detail="No pending request from this user")

    pending.status = "accepted"

    # Create mutual follow
    reverse = db.query(Follow).filter(Follow.follower_id == current_user_id, Follow.following_id == user_id).first()
    if not reverse:
        db.add(Follow(follower_id=current_user_id, following_id=user_id, status="accepted"))
    elif reverse.status != "accepted":
        reverse.status = "accepted"

    from notifications import create_notification
    accepter = db.query(User).filter(User.id == current_user_id).first()
    aname = accepter.username if accepter else "Someone"
    create_notification(user_id=user_id, type="new_follower", title="Friend Request Accepted", message=f"{aname} accepted your friend request", data={"user_id": current_user_id}, db=db)

    # XP for both users
    try:
        from xp import award_xp
        award_xp(current_user_id, "friend_added", db)
        award_xp(user_id, "friend_added", db)
    except Exception:
        pass

    db.commit()
    return {"status": "accepted"}


# ── POST /api/follows/{user_id}/decline ───────────────────────────────────────


@router.post("/follows/{user_id}/decline")
@limiter.limit("30/minute")
def decline_friend_request(request: Request, user_id: int, current_user_id: int = Depends(require_user), db: Session = Depends(get_db)):
    pending = db.query(Follow).filter(Follow.follower_id == user_id, Follow.following_id == current_user_id, Follow.status == "pending").first()
    if not pending:
        raise HTTPException(status_code=404, detail="No pending request from this user")

    db.delete(pending)
    db.commit()
    return {"status": "declined"}


# ── GET /api/follows/requests — Incoming pending requests ─────────────────────


@router.get("/follows/requests")
@limiter.limit("60/minute")
def get_friend_requests(request: Request, current_user_id: int = Depends(require_user), db: Session = Depends(get_db)):
    pending = db.query(Follow).filter(Follow.following_id == current_user_id, Follow.status == "pending").order_by(Follow.created_at.desc()).all()

    results = []
    for f in pending:
        u = db.query(User).filter(User.id == f.follower_id).first()
        if not u: continue
        scored = _user_scored_count(u.id, db)
        results.append({
            "user_id": u.id, "username": u.username, "display_name": u.display_name,
            "accuracy": _user_accuracy(u.id, db), "rank": _rank_name(scored),
            "created_at": f.created_at.isoformat() if f.created_at else None,
        })
    return results


# ── GET /api/follows/sent — Outgoing pending requests ─────────────────────────


@router.get("/follows/sent")
@limiter.limit("60/minute")
def get_sent_requests(request: Request, current_user_id: int = Depends(require_user), db: Session = Depends(get_db)):
    pending = db.query(Follow).filter(Follow.follower_id == current_user_id, Follow.status == "pending").all()

    results = []
    for f in pending:
        u = db.query(User).filter(User.id == f.following_id).first()
        if not u: continue
        results.append({"user_id": u.id, "username": u.username, "display_name": u.display_name, "created_at": f.created_at.isoformat() if f.created_at else None})
    return results


# ── DELETE /api/follows/{user_id} — Unfriend (both directions) ────────────────


@router.delete("/follows/{user_id}")
@limiter.limit("30/minute")
def unfriend(request: Request, user_id: int, current_user_id: int = Depends(require_user), db: Session = Depends(get_db)):
    # Delete both directions
    for a, b in [(current_user_id, user_id), (user_id, current_user_id)]:
        row = db.query(Follow).filter(Follow.follower_id == a, Follow.following_id == b).first()
        if row:
            db.delete(row)
    db.commit()
    return {"status": "unfriended"}


# ── GET /api/follows/{user_id}/followers — Accepted friends only ──────────────


@router.get("/follows/{user_id}/followers")
@limiter.limit("60/minute")
def get_followers(request: Request, user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    follows = db.query(Follow).filter(Follow.following_id == user_id, _accepted()).all()
    results = []
    for f in follows:
        u = db.query(User).filter(User.id == f.follower_id).first()
        if not u: continue
        results.append({"user_id": u.id, "username": u.username, "display_name": u.display_name, "accuracy": _user_accuracy(u.id, db)})
    return results


# ── GET /api/follows/{user_id}/following — Accepted friends only ──────────────


@router.get("/follows/{user_id}/following")
@limiter.limit("60/minute")
def get_following(request: Request, user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    follows = db.query(Follow).filter(Follow.follower_id == user_id, _accepted()).all()
    results = []
    for f in follows:
        u = db.query(User).filter(User.id == f.following_id).first()
        if not u: continue
        results.append({"user_id": u.id, "username": u.username, "display_name": u.display_name, "accuracy": _user_accuracy(u.id, db)})
    return results


# ── GET /api/feed — Accepted friends only ─────────────────────────────────────


@router.get("/feed")
@limiter.limit("60/minute")
def get_feed(request: Request, current_user_id: int = Depends(require_user), db: Session = Depends(get_db)):
    following_ids = [f.following_id for f in db.query(Follow.following_id).filter(Follow.follower_id == current_user_id, _accepted()).all()]
    if not following_ids:
        return []

    rows = db.query(UserPrediction, User.username).join(User, User.id == UserPrediction.user_id).filter(UserPrediction.user_id.in_(following_ids)).order_by(UserPrediction.created_at.desc()).limit(50).all()

    accuracy_cache = {}
    for p, _ in rows:
        if p.user_id not in accuracy_cache:
            accuracy_cache[p.user_id] = _user_accuracy(p.user_id, db)

    return [{
        "id": pred.id, "user_id": pred.user_id, "username": username,
        "accuracy": accuracy_cache.get(pred.user_id, 0.0),
        "ticker": pred.ticker, "direction": pred.direction, "price_target": pred.price_target,
        "price_at_call": float(pred.price_at_call) if pred.price_at_call else None,
        "evaluation_window_days": pred.evaluation_window_days, "reasoning": pred.reasoning,
        "created_at": pred.created_at.isoformat() if pred.created_at else None,
        "expires_at": pred.expires_at.isoformat() if pred.expires_at else None,
        "outcome": pred.outcome,
        "current_price": float(pred.current_price) if pred.current_price else None,
    } for pred, username in rows]

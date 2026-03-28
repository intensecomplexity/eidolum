from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import PredictionReaction, UserPrediction
from middleware.auth import require_user
from rate_limit import limiter
from auth import get_current_user as _decode_token

router = APIRouter()
_optional_bearer = HTTPBearer(auto_error=False)

VALID_REACTIONS = {"agree", "disagree", "bold_call", "no_way"}


class ReactionRequest(BaseModel):
    prediction_id: int
    prediction_source: str
    reaction: str


# ── POST /api/reactions ───────────────────────────────────────────────────────


@router.post("/reactions")
@limiter.limit("60/minute")
def create_reaction(
    request: Request,
    req: ReactionRequest,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    if req.prediction_source not in ("user", "analyst"):
        raise HTTPException(status_code=400, detail="prediction_source must be 'user' or 'analyst'")
    if req.reaction not in VALID_REACTIONS:
        raise HTTPException(status_code=400, detail=f"reaction must be one of: {', '.join(VALID_REACTIONS)}")

    # Cannot react to your own prediction
    if req.prediction_source == "user":
        pred = db.query(UserPrediction).filter(UserPrediction.id == req.prediction_id).first()
        if pred and pred.user_id == user_id:
            raise HTTPException(status_code=400, detail="Cannot react to your own prediction")

    existing = db.query(PredictionReaction).filter(
        PredictionReaction.prediction_id == req.prediction_id,
        PredictionReaction.prediction_source == req.prediction_source,
        PredictionReaction.user_id == user_id,
    ).first()

    if existing:
        existing.reaction = req.reaction
    else:
        db.add(PredictionReaction(
            prediction_id=req.prediction_id,
            prediction_source=req.prediction_source,
            user_id=user_id,
            reaction=req.reaction,
        ))

    db.commit()
    return {"status": "ok", "reaction": req.reaction}


# ── DELETE /api/reactions/{prediction_id}/{prediction_source} ─────────────────


@router.delete("/reactions/{prediction_id}/{prediction_source}")
@limiter.limit("60/minute")
def remove_reaction(
    request: Request,
    prediction_id: int,
    prediction_source: str,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    existing = db.query(PredictionReaction).filter(
        PredictionReaction.prediction_id == prediction_id,
        PredictionReaction.prediction_source == prediction_source,
        PredictionReaction.user_id == user_id,
    ).first()

    if existing:
        db.delete(existing)
        db.commit()

    return {"status": "removed"}


# ── GET /api/reactions/{prediction_id}/{prediction_source} ────────────────────


@router.get("/reactions/{prediction_id}/{prediction_source}")
@limiter.limit("120/minute")
def get_reactions(
    request: Request,
    prediction_id: int,
    prediction_source: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    db: Session = Depends(get_db),
):
    reactions = (
        db.query(PredictionReaction)
        .filter(
            PredictionReaction.prediction_id == prediction_id,
            PredictionReaction.prediction_source == prediction_source,
        )
        .all()
    )

    counts = {"agree": 0, "disagree": 0, "bold_call": 0, "no_way": 0}
    for r in reactions:
        if r.reaction in counts:
            counts[r.reaction] += 1

    user_reaction = None
    if credentials and credentials.credentials:
        try:
            uid = _decode_token(credentials.credentials).get("user_id")
            if uid:
                ur = next((r for r in reactions if r.user_id == uid), None)
                if ur:
                    user_reaction = ur.reaction
        except Exception:
            pass

    return {
        **counts,
        "total": sum(counts.values()),
        "user_reaction": user_reaction,
    }

import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from models import Season, SeasonEntry, User
from rate_limit import limiter
from seasons import ensure_current_season

router = APIRouter()


# ── GET /api/seasons ──────────────────────────────────────────────────────────


@router.get("/seasons")
@limiter.limit("60/minute")
def list_seasons(request: Request, db: Session = Depends(get_db)):
    seasons = db.query(Season).order_by(Season.starts_at.desc()).all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "starts_at": s.starts_at.isoformat() if s.starts_at else None,
            "ends_at": s.ends_at.isoformat() if s.ends_at else None,
            "status": s.status,
        }
        for s in seasons
    ]


# ── GET /api/seasons/current ──────────────────────────────────────────────────


@router.get("/seasons/current")
@limiter.limit("60/minute")
def get_current_season(request: Request, db: Session = Depends(get_db)):
    season = ensure_current_season(db)
    return {
        "id": season.id,
        "name": season.name,
        "starts_at": season.starts_at.isoformat() if season.starts_at else None,
        "ends_at": season.ends_at.isoformat() if season.ends_at else None,
        "status": season.status,
    }


# ── GET /api/seasons/{season_id}/leaderboard ──────────────────────────────────


@router.get("/seasons/{season_id}/leaderboard")
@limiter.limit("60/minute")
def season_leaderboard(request: Request, season_id: int, db: Session = Depends(get_db)):
    season = db.query(Season).filter(Season.id == season_id).first()
    if not season:
        raise HTTPException(status_code=404, detail="Season not found")

    entries = (
        db.query(SeasonEntry, User)
        .join(User, User.id == SeasonEntry.user_id)
        .filter(SeasonEntry.season_id == season_id, SeasonEntry.predictions_scored >= 5)
        .all()
    )

    results = []
    for entry, user in entries:
        accuracy = (
            round(entry.predictions_correct / entry.predictions_scored * 100, 1)
            if entry.predictions_scored > 0
            else 0.0
        )
        results.append({
            "user_id": user.id,
            "username": user.username,
            "predictions_made": entry.predictions_made,
            "predictions_scored": entry.predictions_scored,
            "predictions_correct": entry.predictions_correct,
            "accuracy": accuracy,
        })

    results.sort(key=lambda x: x["accuracy"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return results

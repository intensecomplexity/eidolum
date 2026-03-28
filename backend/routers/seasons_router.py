import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from models import Season, SeasonEntry, User
from rate_limit import limiter
from seasons import ensure_current_season

router = APIRouter()

ICON_EMOJI = {"bull": "\U0001F402", "hawk": "\U0001F985", "serpent": "\U0001F40D", "wolf": "\U0001F43A"}


def _season_dict(s: Season) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "starts_at": s.starts_at.isoformat() if s.starts_at else None,
        "ends_at": s.ends_at.isoformat() if s.ends_at else None,
        "status": s.status,
        "theme_color": s.theme_color,
        "theme_icon": s.theme_icon,
        "theme_emoji": ICON_EMOJI.get(s.theme_icon, ""),
    }


@router.get("/seasons")
@limiter.limit("60/minute")
def list_seasons(request: Request, db: Session = Depends(get_db)):
    seasons = db.query(Season).order_by(Season.starts_at.desc()).all()
    return [_season_dict(s) for s in seasons]


@router.get("/seasons/current")
@limiter.limit("60/minute")
def get_current_season(request: Request, db: Session = Depends(get_db)):
    season = ensure_current_season(db)
    return _season_dict(season)


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
        accuracy = round(entry.predictions_correct / entry.predictions_scored * 100, 1) if entry.predictions_scored > 0 else 0.0
        results.append({
            "user_id": user.id,
            "username": user.username,
            "user_type": user.user_type or "player",
            "predictions_made": entry.predictions_made,
            "predictions_scored": entry.predictions_scored,
            "predictions_correct": entry.predictions_correct,
            "accuracy": accuracy,
        })

    results.sort(key=lambda x: x["accuracy"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return {"season": _season_dict(season), "leaderboard": results}

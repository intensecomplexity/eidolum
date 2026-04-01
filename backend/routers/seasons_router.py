import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from database import get_db
from models import Season, SeasonEntry, User
from rate_limit import limiter
from seasons import ensure_current_season

router = APIRouter()


def _season_dict(s: Season) -> dict:
    # Compute quarter label from start date
    quarter_label = ""
    if s.starts_at:
        q = (s.starts_at.month - 1) // 3 + 1
        quarter_label = f"Q{q} {s.starts_at.year}"

    return {
        "id": s.id,
        "name": s.name,
        "quarter_label": quarter_label,
        "subtitle": s.theme_icon or "",
        "starts_at": s.starts_at.isoformat() if s.starts_at else None,
        "ends_at": s.ends_at.isoformat() if s.ends_at else None,
        "status": s.status,
        "theme_color": s.theme_color,
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

    # Also include analyst predictions scored during this season
    analyst_lb = []
    if season.starts_at and season.ends_at:
        try:
            analyst_rows = db.execute(sql_text("""
                SELECT f.id, f.name, f.handle,
                       COUNT(*) as total,
                       SUM(CASE WHEN p.outcome = 'correct' THEN 1 ELSE 0 END) as correct
                FROM predictions p
                JOIN forecasters f ON f.id = p.forecaster_id
                WHERE p.outcome IN ('hit','near','miss','correct','incorrect')
                  AND COALESCE(p.evaluated_at, p.evaluation_date) >= :start
                  AND COALESCE(p.evaluated_at, p.evaluation_date) < :end
                GROUP BY f.id, f.name, f.handle
                HAVING COUNT(*) >= 2
                ORDER BY ROUND(SUM(CASE WHEN p.outcome='correct' THEN 1 ELSE 0 END)::numeric / NULLIF(COUNT(*), 0) * 100, 1) DESC, COUNT(*) DESC
                LIMIT 10
            """), {"start": season.starts_at, "end": season.ends_at}).fetchall()

            for i, r in enumerate(analyst_rows):
                acc = round(r[4] / r[3] * 100, 1) if r[3] > 0 else 0
                analyst_lb.append({
                    "forecaster_id": r[0], "name": r[1], "handle": r[2],
                    "predictions_scored": r[3], "predictions_correct": r[4],
                    "accuracy": acc, "rank": i + 1, "user_type": "analyst",
                })
        except Exception:
            pass

    return {
        "season": _season_dict(season),
        "leaderboard": results,
        "analyst_leaderboard": analyst_lb,
    }

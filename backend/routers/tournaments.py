"""
Prediction Tournament system — all endpoints gated behind tournaments_enabled feature flag.
Returns 404 when disabled so the feature is completely invisible.
"""
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from database import get_db
from middleware.auth import require_user, require_admin_user
from rate_limit import limiter
from models import Config

router = APIRouter()


def _tournaments_enabled(db: Session) -> bool:
    row = db.query(Config).filter(Config.key == "tournaments_enabled").first()
    return row and row.value == "true"


def _require_enabled(db: Session):
    if not _tournaments_enabled(db):
        raise HTTPException(status_code=404, detail="Not found")


# ── Models ───────────────────────────────────────────────────────────────────

class CreateTournamentRequest(BaseModel):
    name: str
    start_date: str  # YYYY-MM-DD
    end_date: str
    entry_deadline: str
    max_participants: int = 100


class EntryRequest(BaseModel):
    picks: list  # [{ticker, direction, target_price?}, ...]


# ── Public endpoints ─────────────────────────────────────────────────────────

@router.get("/tournaments")
@limiter.limit("60/minute")
def list_tournaments(request: Request, db: Session = Depends(get_db)):
    _require_enabled(db)
    rows = db.execute(sql_text("""
        SELECT id, name, status, start_date, end_date, entry_deadline, max_participants,
               (SELECT COUNT(*) FROM tournament_entries WHERE tournament_id = t.id) as entries
        FROM tournaments t
        WHERE status IN ('upcoming', 'active', 'completed')
        ORDER BY start_date DESC
        LIMIT 20
    """)).fetchall()
    return [
        {"id": r[0], "name": r[1], "status": r[2],
         "start_date": r[3].isoformat() if r[3] else None,
         "end_date": r[4].isoformat() if r[4] else None,
         "entry_deadline": r[5].isoformat() if r[5] else None,
         "max_participants": r[6], "entries": r[7]}
        for r in rows
    ]


@router.get("/tournaments/{tournament_id}")
@limiter.limit("60/minute")
def get_tournament(request: Request, tournament_id: int, db: Session = Depends(get_db)):
    _require_enabled(db)
    t = db.execute(sql_text("""
        SELECT id, name, status, start_date, end_date, entry_deadline, max_participants
        FROM tournaments WHERE id = :tid
    """), {"tid": tournament_id}).first()
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")

    # Leaderboard
    results = db.execute(sql_text("""
        SELECT tr.user_id, u.username, u.display_name, tr.score, tr.rank,
               tr.hits, tr.nears, tr.misses, tr.prize_badge
        FROM tournament_results tr
        JOIN users u ON u.id = tr.user_id
        WHERE tr.tournament_id = :tid
        ORDER BY tr.score DESC, tr.rank ASC
    """), {"tid": tournament_id}).fetchall()

    leaderboard = [
        {"user_id": r[0], "username": r[1], "display_name": r[2],
         "score": float(r[3]) if r[3] else 0, "rank": r[4],
         "hits": r[5] or 0, "nears": r[6] or 0, "misses": r[7] or 0,
         "prize_badge": r[8]}
        for r in results
    ]

    entries_count = db.execute(sql_text(
        "SELECT COUNT(*) FROM tournament_entries WHERE tournament_id = :tid"
    ), {"tid": tournament_id}).scalar() or 0

    return {
        "id": t[0], "name": t[1], "status": t[2],
        "start_date": t[3].isoformat() if t[3] else None,
        "end_date": t[4].isoformat() if t[4] else None,
        "entry_deadline": t[5].isoformat() if t[5] else None,
        "max_participants": t[6],
        "entries": entries_count,
        "leaderboard": leaderboard,
    }


@router.post("/tournaments/{tournament_id}/enter")
@limiter.limit("10/minute")
def enter_tournament(
    request: Request,
    tournament_id: int,
    req: EntryRequest,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    _require_enabled(db)

    # Check tournament exists and is accepting entries
    t = db.execute(sql_text("""
        SELECT status, entry_deadline, max_participants FROM tournaments WHERE id = :tid
    """), {"tid": tournament_id}).first()
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if t[0] != "upcoming":
        raise HTTPException(status_code=400, detail="Tournament is no longer accepting entries")
    if t[1] and datetime.utcnow() > t[1]:
        raise HTTPException(status_code=400, detail="Entry deadline has passed")

    # Check max participants
    count = db.execute(sql_text(
        "SELECT COUNT(*) FROM tournament_entries WHERE tournament_id = :tid"
    ), {"tid": tournament_id}).scalar() or 0
    if t[2] and count >= t[2]:
        raise HTTPException(status_code=400, detail="Tournament is full")

    # Check not already entered
    existing = db.execute(sql_text(
        "SELECT 1 FROM tournament_entries WHERE tournament_id = :tid AND user_id = :uid"
    ), {"tid": tournament_id, "uid": user_id}).first()
    if existing:
        raise HTTPException(status_code=409, detail="Already entered this tournament")

    # Validate picks
    if not req.picks or len(req.picks) != 5:
        raise HTTPException(status_code=400, detail="Must pick exactly 5 stocks")

    for pick in req.picks:
        if not pick.get("ticker") or not pick.get("direction"):
            raise HTTPException(status_code=400, detail="Each pick needs a ticker and direction")
        if pick["direction"] not in ("bullish", "bearish", "neutral"):
            raise HTTPException(status_code=400, detail="Direction must be bullish, bearish, or neutral")

    # Check no duplicate tickers
    tickers = [p["ticker"].upper() for p in req.picks]
    if len(set(tickers)) != 5:
        raise HTTPException(status_code=400, detail="Each pick must be a different ticker")

    db.execute(sql_text("""
        INSERT INTO tournament_entries (tournament_id, user_id, picks, submitted_at)
        VALUES (:tid, :uid, :picks, :now)
    """), {"tid": tournament_id, "uid": user_id, "picks": json.dumps(req.picks), "now": datetime.utcnow()})
    db.commit()

    return {"status": "entered", "tournament_id": tournament_id}


@router.get("/tournaments/{tournament_id}/my-entry")
@limiter.limit("60/minute")
def my_entry(
    request: Request,
    tournament_id: int,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    _require_enabled(db)
    row = db.execute(sql_text("""
        SELECT picks, submitted_at FROM tournament_entries
        WHERE tournament_id = :tid AND user_id = :uid
    """), {"tid": tournament_id, "uid": user_id}).first()
    if not row:
        return {"entered": False}

    picks = json.loads(row[0]) if row[0] else []

    # Get current score if tournament is active/completed
    result = db.execute(sql_text("""
        SELECT score, rank, hits, nears, misses FROM tournament_results
        WHERE tournament_id = :tid AND user_id = :uid
    """), {"tid": tournament_id, "uid": user_id}).first()

    return {
        "entered": True,
        "picks": picks,
        "submitted_at": row[1].isoformat() if row[1] else None,
        "score": float(result[0]) if result and result[0] else None,
        "rank": result[1] if result else None,
        "hits": result[2] if result else None,
        "nears": result[3] if result else None,
        "misses": result[4] if result else None,
    }


# ── Feature flag check for nav visibility ────────────────────────────────────

@router.get("/tournaments/enabled")
@limiter.limit("120/minute")
def tournaments_enabled(request: Request, db: Session = Depends(get_db)):
    return {"enabled": _tournaments_enabled(db)}


# ── Admin endpoints ──────────────────────────────────────────────────────────

@router.post("/admin/toggle-tournaments")
@limiter.limit("10/minute")
def toggle_tournaments(request: Request, admin_id: int = Depends(require_admin_user), db: Session = Depends(get_db)):
    row = db.query(Config).filter(Config.key == "tournaments_enabled").first()
    if row:
        row.value = "false" if row.value == "true" else "true"
    else:
        db.add(Config(key="tournaments_enabled", value="true"))
    db.commit()
    new_val = db.query(Config).filter(Config.key == "tournaments_enabled").first()
    return {"tournaments_enabled": new_val.value == "true" if new_val else False}


@router.post("/admin/tournaments")
@limiter.limit("10/minute")
def create_tournament(
    request: Request,
    req: CreateTournamentRequest,
    admin_id: int = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    db.execute(sql_text("""
        INSERT INTO tournaments (name, status, start_date, end_date, entry_deadline, max_participants, created_at)
        VALUES (:name, 'upcoming', :sd, :ed, :dl, :mp, :now)
    """), {
        "name": req.name,
        "sd": datetime.strptime(req.start_date, "%Y-%m-%d"),
        "ed": datetime.strptime(req.end_date, "%Y-%m-%d"),
        "dl": datetime.strptime(req.entry_deadline, "%Y-%m-%d"),
        "mp": req.max_participants,
        "now": datetime.utcnow(),
    })
    db.commit()
    return {"status": "created", "name": req.name}


@router.post("/admin/tournaments/{tournament_id}/finalize")
@limiter.limit("5/minute")
def finalize_tournament(
    request: Request,
    tournament_id: int,
    admin_id: int = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    from jobs.tournament_scorer import score_tournament
    result = score_tournament(tournament_id, db)
    return result

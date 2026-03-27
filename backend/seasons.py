"""
Season helper — ensures a season exists for the current quarter.
Call ensure_current_season(db) on startup and before submitting predictions.
"""
import datetime
from sqlalchemy.orm import Session
from models import Season


def ensure_current_season(db: Session) -> Season:
    """Return the active season for the current quarter, creating it if needed."""
    now = datetime.datetime.utcnow()

    # Check for an existing active season that covers right now
    active = (
        db.query(Season)
        .filter(Season.status == "active", Season.starts_at <= now, Season.ends_at > now)
        .first()
    )
    if active:
        return active

    # Determine current quarter boundaries
    year = now.year
    quarter = (now.month - 1) // 3 + 1
    month_start = (quarter - 1) * 3 + 1
    starts_at = datetime.datetime(year, month_start, 1)

    if quarter == 4:
        ends_at = datetime.datetime(year + 1, 1, 1)
    else:
        ends_at = datetime.datetime(year, month_start + 3, 1)

    name = f"Q{quarter} {year}"

    # Check if this season already exists (maybe status was set wrong)
    existing = db.query(Season).filter(Season.name == name).first()
    if existing:
        existing.status = "active"
        db.commit()
        return existing

    # Mark any old active seasons as completed
    old_active = db.query(Season).filter(Season.status == "active").all()
    for s in old_active:
        s.status = "completed"

    season = Season(name=name, starts_at=starts_at, ends_at=ends_at, status="active")
    db.add(season)
    db.commit()
    db.refresh(season)
    print(f"[Seasons] Created {name} ({starts_at.date()} - {ends_at.date()})")
    return season

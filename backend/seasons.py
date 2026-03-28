"""
Season helper — ensures a season exists for the current quarter.
Call ensure_current_season(db) on startup and before submitting predictions.
"""
import datetime
from sqlalchemy.orm import Session
from models import Season

SEASON_THEMES = {
    1: {"name": "Season of the Bull",    "color": "#22c55e", "icon": "bull"},
    2: {"name": "Season of the Hawk",    "color": "#4A9EFF", "icon": "hawk"},
    3: {"name": "Season of the Serpent", "color": "#A855F7", "icon": "serpent"},
    4: {"name": "Season of the Wolf",    "color": "#EF4444", "icon": "wolf"},
}


def ensure_current_season(db: Session) -> Season:
    """Return the active season for the current quarter, creating it if needed."""
    now = datetime.datetime.utcnow()

    active = (
        db.query(Season)
        .filter(Season.status == "active", Season.starts_at <= now, Season.ends_at > now)
        .first()
    )
    if active:
        return active

    year = now.year
    quarter = (now.month - 1) // 3 + 1
    month_start = (quarter - 1) * 3 + 1
    starts_at = datetime.datetime(year, month_start, 1)
    ends_at = datetime.datetime(year + 1, 1, 1) if quarter == 4 else datetime.datetime(year, month_start + 3, 1)

    theme = SEASON_THEMES[quarter]
    name = f"{theme['name']} \u2014 {year}"

    # Check if this exact season already exists
    existing = (
        db.query(Season)
        .filter(Season.starts_at == starts_at, Season.ends_at == ends_at)
        .first()
    )
    if existing:
        existing.status = "active"
        if not existing.theme_color:
            existing.theme_color = theme["color"]
            existing.theme_icon = theme["icon"]
            existing.name = name
        db.commit()
        return existing

    # Mark old active seasons as completed
    for s in db.query(Season).filter(Season.status == "active").all():
        s.status = "completed"

    season = Season(
        name=name,
        starts_at=starts_at,
        ends_at=ends_at,
        status="active",
        theme_color=theme["color"],
        theme_icon=theme["icon"],
    )
    db.add(season)
    db.commit()
    db.refresh(season)
    print(f"[Seasons] Created {name} ({starts_at.date()} - {ends_at.date()})")
    return season

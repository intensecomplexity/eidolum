"""
Season helper — ensures a season exists for the current quarter.
Each season has a unique epic name that never repeats.
"""
import datetime
from sqlalchemy.orm import Session
from models import Season

SEASON_NAMES = {
    "2026-Q1": {"name": "The Reckoning",  "subtitle": "Prove your calls or fall behind.", "color": "#EF4444"},
    "2026-Q2": {"name": "Ascension",      "subtitle": "Rise through the noise.",         "color": "#4A9EFF"},
    "2026-Q3": {"name": "Onslaught",      "subtitle": "No mercy. No excuses.",           "color": "#F59E0B"},
    "2026-Q4": {"name": "The Prophecy",   "subtitle": "Who saw it coming?",              "color": "#A855F7"},
    "2027-Q1": {"name": "Vanguard",       "subtitle": "Lead from the front.",            "color": "#22c55e"},
    "2027-Q2": {"name": "Dominion",       "subtitle": "Claim your territory.",           "color": "#EF4444"},
    "2027-Q3": {"name": "Apex",           "subtitle": "Only the sharpest survive.",      "color": "#F59E0B"},
    "2027-Q4": {"name": "Eclipse",        "subtitle": "Darkness reveals the truth.",     "color": "#6366f1"},
    "2028-Q1": {"name": "Crucible",       "subtitle": "Forged under pressure.",          "color": "#f97316"},
    "2028-Q2": {"name": "Sovereign",      "subtitle": "Rule by accuracy.",               "color": "#4A9EFF"},
    "2028-Q3": {"name": "Inferno",        "subtitle": "Burn through the noise.",         "color": "#EF4444"},
    "2028-Q4": {"name": "Revelation",     "subtitle": "The final verdict.",              "color": "#A855F7"},
}

ROTATING_COLORS = ["#EF4444", "#4A9EFF", "#F59E0B", "#A855F7", "#22c55e", "#f97316", "#6366f1"]


def _get_season_meta(year: int, quarter: int) -> dict:
    key = f"{year}-Q{quarter}"
    if key in SEASON_NAMES:
        return SEASON_NAMES[key]
    # Fallback for years beyond 2028
    idx = ((year - 2029) * 4 + quarter) % len(ROTATING_COLORS)
    return {"name": f"Season {(year - 2026) * 4 + quarter}", "subtitle": "The grind continues.", "color": ROTATING_COLORS[idx]}


def ensure_current_season(db: Session) -> Season:
    now = datetime.datetime.utcnow()

    active = db.query(Season).filter(Season.status == "active", Season.starts_at <= now, Season.ends_at > now).first()
    if active:
        return active

    year = now.year
    quarter = (now.month - 1) // 3 + 1
    month_start = (quarter - 1) * 3 + 1
    starts_at = datetime.datetime(year, month_start, 1)
    ends_at = datetime.datetime(year + 1, 1, 1) if quarter == 4 else datetime.datetime(year, month_start + 3, 1)

    meta = _get_season_meta(year, quarter)

    existing = db.query(Season).filter(Season.starts_at == starts_at, Season.ends_at == ends_at).first()
    if existing:
        existing.status = "active"
        existing.name = meta["name"]
        existing.theme_color = meta["color"]
        existing.theme_icon = meta.get("subtitle", "")
        db.commit()
        return existing

    for s in db.query(Season).filter(Season.status == "active").all():
        s.status = "completed"

    season = Season(
        name=meta["name"],
        starts_at=starts_at,
        ends_at=ends_at,
        status="active",
        theme_color=meta["color"],
        theme_icon=meta.get("subtitle", ""),  # reuse theme_icon column for subtitle
    )
    db.add(season)
    db.commit()
    db.refresh(season)
    print(f"[Seasons] Created: {meta['name']} ({starts_at.date()} - {ends_at.date()})")
    return season

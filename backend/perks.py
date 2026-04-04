"""
Level-based perks system — 10 levels with tangible benefits.
Perks are cosmetic, convenience, and expression only.
Premium analytics, API access, verified badges, and strategy marketplace
are reserved for future paid subscription tiers.
"""

LEVEL_PERKS = {
    1: {
        "name": "Newcomer", "xp_required": 0,
        "max_predictions_per_day": 5, "max_active_duels": 2,
        "deletion_window_minutes": 5, "reasoning_max_chars": 280,
        "can_duel_anyone": False, "can_comment": False,
        "custom_title": False, "pin_predictions": 0,
        "profile_border": "none", "comment_highlight": False,
        "profile_bio": False, "reasoning_public": False, "endorse_limit": 0,
    },
    2: {"name": "Watcher", "xp_required": 100, "max_predictions_per_day": 8, "profile_bio": True},
    3: {"name": "Caller", "xp_required": 300, "max_predictions_per_day": 10, "can_duel_anyone": True, "reasoning_public": True},
    4: {"name": "Trader", "xp_required": 600, "deletion_window_minutes": 10, "can_comment": True},
    5: {"name": "Sharpshooter", "xp_required": 1200, "max_predictions_per_day": 15, "custom_title": True, "pin_predictions": 1},
    6: {"name": "Tactician", "xp_required": 2500, "max_predictions_per_day": 20, "max_active_duels": 5, "reasoning_max_chars": 500},
    7: {"name": "Veteran", "xp_required": 5000, "deletion_window_minutes": 15, "profile_border": "glow"},
    8: {"name": "Master", "xp_required": 8000, "max_predictions_per_day": 30, "comment_highlight": True, "max_active_duels": 10, "reasoning_max_chars": 750},
    9: {"name": "Oracle", "xp_required": 14000, "profile_border": "animated", "pin_predictions": 2, "endorse_limit": 5},
    10: {
        "name": "Seer", "xp_required": 25000,
        "max_predictions_per_day": -1, "max_active_duels": -1,
        "deletion_window_minutes": 30, "reasoning_max_chars": 1000,
        "profile_border": "seer", "endorse_limit": 10,
    },
}

PERK_DESCRIPTIONS = {
    2: "Profile bio, 8 predictions/day",
    3: "Duel anyone, public reasoning, 10/day",
    4: "Comments unlocked, 10 min delete window",
    5: "Custom title, pin 1 prediction, 15/day",
    6: "20/day, 5 duels, 500 char reasoning",
    7: "Glowing profile border, 15 min delete",
    8: "Highlighted comments, 30/day, 10 duels",
    9: "Animated border, pin 2, endorse 5 users",
    10: "Unlimited predictions and duels, Seer ring",
}

TITLE_OPTIONS = [
    "Market Watcher", "Chart Reader", "Trend Spotter", "Risk Taker",
    "Contrarian", "Deep Value", "Momentum Player", "The Oracle",
    "Bear Hunter", "Bull Runner", "Diamond Hands", "Paper Hands Killer",
    "Sector Specialist", "Macro Thinker", "Day One", "Night Owl",
    "Silent Sniper", "Loud and Right", "Data Driven", "Gut Feeling",
]


def get_user_perks(user_level: int) -> dict:
    """Build complete perks by applying overrides up to user_level. -1 = unlimited."""
    perks = dict(LEVEL_PERKS[1])
    for lvl in sorted(LEVEL_PERKS.keys()):
        if lvl > user_level or lvl == 1:
            continue
        for k, v in LEVEL_PERKS[lvl].items():
            if k not in ("name", "xp_required"):
                perks[k] = v
    return perks


def get_level_name(level: int) -> str:
    """Get the name for a level number."""
    if level in LEVEL_PERKS:
        return LEVEL_PERKS[level]["name"]
    return "Newcomer"


def get_level_for_xp(xp: int) -> int:
    """Calculate level from XP total."""
    level = 1
    for lvl in sorted(LEVEL_PERKS.keys()):
        if xp >= LEVEL_PERKS[lvl]["xp_required"]:
            level = lvl
    return level


def get_xp_for_next_level(xp: int) -> int:
    """Get XP needed for the next level."""
    for lvl in sorted(LEVEL_PERKS.keys()):
        if LEVEL_PERKS[lvl]["xp_required"] > xp:
            return LEVEL_PERKS[lvl]["xp_required"]
    return LEVEL_PERKS[10]["xp_required"]


def get_next_perk_info(user_level: int) -> dict | None:
    for lvl in sorted(LEVEL_PERKS.keys()):
        if lvl > user_level and lvl > 1:
            return {"next_perk_level": lvl, "next_perk_description": PERK_DESCRIPTIONS.get(lvl, "")}
    return None


def get_all_perks_display(user_level: int) -> list[dict]:
    result = []
    for lvl in sorted(LEVEL_PERKS.keys()):
        if lvl == 1:
            continue
        result.append({
            "level": lvl,
            "name": LEVEL_PERKS[lvl].get("name", ""),
            "description": PERK_DESCRIPTIONS.get(lvl, ""),
            "xp_required": LEVEL_PERKS[lvl].get("xp_required", 0),
            "unlocked": user_level >= lvl,
        })
    return result

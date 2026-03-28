"""
Level-based perks system — tangible benefits unlocked at each level.
"""

LEVEL_PERKS = {
    1: {
        "max_predictions_per_day": 5,
        "max_active_duels": 2,
        "deletion_window_minutes": 5,
        "reasoning_max_chars": 280,
        "can_duel_anyone": False,
        "custom_title": False,
        "profile_border": "none",
        "comment_highlight": False,
    },
    3: {"max_predictions_per_day": 8},
    5: {
        "max_predictions_per_day": 10,
        "max_active_duels": 3,
        "can_duel_anyone": True,
        "reasoning_max_chars": 500,
        "profile_border": "subtle",
    },
    7: {"deletion_window_minutes": 10},
    10: {
        "max_predictions_per_day": 15,
        "max_active_duels": 5,
        "reasoning_max_chars": 750,
        "custom_title": True,
        "comment_highlight": True,
        "profile_border": "glow",
    },
    13: {"deletion_window_minutes": 15, "max_predictions_per_day": 20},
    15: {"max_active_duels": 10, "reasoning_max_chars": 1000, "profile_border": "animated"},
    18: {"max_predictions_per_day": 30},
    20: {"max_predictions_per_day": 50, "profile_border": "legendary"},
    25: {
        "max_predictions_per_day": -1,
        "max_active_duels": -1,
        "deletion_window_minutes": 30,
        "reasoning_max_chars": 2000,
        "profile_border": "eidolon",
    },
}

# Descriptions per level
PERK_DESCRIPTIONS = {
    3: "Increased daily predictions from 5 to 8",
    5: "Duel anyone, longer reasoning, 10 daily predictions",
    7: "Deletion window extended to 10 minutes",
    10: "Custom title, highlighted comments, glowing profile",
    13: "15 min deletion window, 20 daily predictions",
    15: "Animated profile border, 1000 char reasoning",
    18: "30 daily predictions",
    20: "Legendary profile border, 50 daily predictions",
    25: "Unlimited predictions, unlimited duels, Eidolon border",
}

TITLE_OPTIONS = [
    "Market Watcher", "Chart Reader", "Trend Spotter", "Risk Taker",
    "Contrarian", "Deep Value", "Momentum Player", "The Oracle",
    "Bear Hunter", "Bull Runner", "Diamond Hands", "Paper Hands Killer",
    "Sector Specialist", "Macro Thinker", "Day One", "Night Owl",
    "Silent Sniper", "Loud and Right", "Data Driven", "Gut Feeling",
]


def get_user_perks(user_level: int) -> dict:
    """Build the complete perks object for a given level.
    Starts from level 1 defaults and applies overrides up to user_level.
    -1 means unlimited.
    """
    perks = dict(LEVEL_PERKS[1])  # Start with defaults
    for lvl in sorted(LEVEL_PERKS.keys()):
        if lvl > user_level:
            break
        if lvl == 1:
            continue
        perks.update(LEVEL_PERKS[lvl])
    return perks


def get_next_perk_info(user_level: int) -> dict | None:
    """Returns info about the next perk unlock."""
    for lvl in sorted(LEVEL_PERKS.keys()):
        if lvl > user_level and lvl > 1:
            return {
                "next_perk_level": lvl,
                "next_perk_description": PERK_DESCRIPTIONS.get(lvl, "New perks unlock"),
            }
    return None


def get_all_perks_display(user_level: int) -> list[dict]:
    """Returns a list of all perks with unlock status for display."""
    result = []
    for lvl in sorted(LEVEL_PERKS.keys()):
        if lvl == 1:
            continue
        desc = PERK_DESCRIPTIONS.get(lvl, "")
        result.append({
            "level": lvl,
            "description": desc,
            "unlocked": user_level >= lvl,
        })
    return result

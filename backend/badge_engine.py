"""
Badge evaluation engine — checks all 39 badge conditions and awards newly
unlocked badges.  Called after every user prediction is scored.

Usage:
    from badge_engine import evaluate_badges
    new_badges = evaluate_badges(user_id, db)
"""
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
from models import User, UserPrediction, Achievement, Duel, Season, SeasonEntry

logger = logging.getLogger(__name__)

# ─── Sector map ───────────────────────────────────────────────────────────────

SECTOR_MAP = {
    "AAPL": "Tech", "MSFT": "Tech", "NVDA": "Tech", "AMD": "Tech",
    "INTC": "Tech", "QCOM": "Tech", "GOOGL": "Tech", "META": "Tech",
    "AMZN": "Tech", "NFLX": "Tech", "CRM": "Tech", "AVGO": "Tech",
    "ORCL": "Tech", "PLTR": "Tech", "ARM": "Tech", "SMCI": "Tech",
    "MU": "Tech",
    "JPM": "Finance", "GS": "Finance", "BAC": "Finance",
    "WFC": "Finance", "COIN": "Finance",
    "XOM": "Energy", "CVX": "Energy",
    "BTC": "Crypto", "ETH": "Crypto", "SOL": "Crypto", "MSTR": "Crypto",
}


def get_sector(ticker: str) -> str:
    return SECTOR_MAP.get(ticker, "Other")


# ─── Badge metadata (name, description, icon, category) ──────────────────────

BADGE_INFO = {
    # Accuracy
    "first-blood":       {"name": "First Blood",       "description": "Get your first prediction scored",         "icon": "🎯", "category": "Accuracy"},
    "sharpshooter":      {"name": "Sharpshooter",      "description": "5 correct predictions",                    "icon": "🔫", "category": "Accuracy"},
    "sniper-elite":      {"name": "Sniper Elite",      "description": "80% accuracy with 20 scored",              "icon": "🎯", "category": "Accuracy"},
    "perfect-week":      {"name": "Perfect Week",      "description": "5 correct in one calendar week",           "icon": "📅", "category": "Accuracy"},
    "ice-cold":          {"name": "Ice Cold",          "description": "10 consecutive correct predictions",       "icon": "❄️", "category": "Accuracy"},
    # Streaks
    "hot-streak":        {"name": "Hot Streak",        "description": "Best streak of 5",                         "icon": "🔥", "category": "Streaks"},
    "on-fire":           {"name": "On Fire",           "description": "Best streak of 10",                        "icon": "⭐", "category": "Streaks"},
    "untouchable":       {"name": "Untouchable",       "description": "Best streak of 20",                        "icon": "👑", "category": "Streaks"},
    "comeback-kid":      {"name": "Comeback Kid",      "description": "3 wrong then 5 right in a row",            "icon": "🔄", "category": "Streaks"},
    # Volume
    "vol-10":            {"name": "Getting Started",   "description": "10 predictions submitted",                 "icon": "📊", "category": "Volume"},
    "vol-50":            {"name": "Consistent Caller", "description": "50 predictions submitted",                 "icon": "📈", "category": "Volume"},
    "vol-100":           {"name": "Century Club",      "description": "100 predictions submitted",                "icon": "🏆", "category": "Volume"},
    "vol-500":           {"name": "Prediction Factory","description": "500 predictions submitted",                "icon": "🏭", "category": "Volume"},
    "vol-1000":          {"name": "Infinity Caller",   "description": "1000 predictions submitted",               "icon": "♾️", "category": "Volume"},
    # Timing
    "speed-demon":       {"name": "Speed Demon",       "description": "Correct call with 7-day window or less",   "icon": "⚡", "category": "Timing"},
    "day-trader":        {"name": "Day Trader",        "description": "Correct call with 1-day window",           "icon": "⏱️", "category": "Timing"},
    "swing-king":        {"name": "Swing King",        "description": "5 correct short-term calls (7 days or less)", "icon": "🏄", "category": "Timing"},
    "patient-capital":   {"name": "Patient Capital",   "description": "Correct 365 day call",                     "icon": "🧘", "category": "Timing"},
    "time-lord":         {"name": "Time Lord",         "description": "Correct at 5 different timeframes",        "icon": "⌛", "category": "Timing"},
    "marathon-runner":   {"name": "Marathon Runner",   "description": "Correct call with 180 day window",         "icon": "🏃", "category": "Timing"},
    # Sectors
    "sector-master":     {"name": "Sector Master",     "description": "70% accuracy in a sector with 5 calls",    "icon": "🎯", "category": "Sectors"},
    "diamond-hands":     {"name": "Diamond Hands",     "description": "10 correct crypto predictions",            "icon": "💎", "category": "Sectors"},
    "tech-guru":         {"name": "Tech Guru",         "description": "15 correct tech predictions",              "icon": "💻", "category": "Sectors"},
    "diversified":       {"name": "Diversified",       "description": "Correct in 5 distinct sectors",            "icon": "🌐", "category": "Sectors"},
    "oil-baron":         {"name": "Oil Baron",         "description": "5 correct energy predictions",             "icon": "🛢️", "category": "Sectors"},
    "money-printer":     {"name": "Money Printer",     "description": "10 correct finance predictions",           "icon": "💵", "category": "Sectors"},
    # Conviction
    "perma-bull":        {"name": "Perma Bull",        "description": "20 correct bullish calls",                 "icon": "🐂", "category": "Conviction"},
    "perma-bear":        {"name": "Bear Whisperer",    "description": "10 correct bearish calls",                 "icon": "🐻", "category": "Conviction"},
    "contrarian":        {"name": "Contrarian",        "description": "Correct call against the crowd",           "icon": "🤔", "category": "Conviction"},
    "strong-conviction": {"name": "Strong Conviction", "description": "3 correct on one ticker",                  "icon": "💪", "category": "Conviction"},
    "flip-master":       {"name": "Flip Master",       "description": "Correct bull & bear on same ticker",       "icon": "🔀", "category": "Conviction"},
    # Prestige
    "level-5":           {"name": "Sharpshooter",       "description": "Reach Level 5",                            "icon": "🎯", "category": "Prestige"},
    "level-10":          {"name": "Eidolon",            "description": "Reach Level 10 — the ultimate level",      "icon": "👁️", "category": "Prestige"},
    "top-10":            {"name": "Top 10",            "description": "Reach top 10 on community leaderboard",    "icon": "🎯", "category": "Prestige"},
    "summit":            {"name": "The Summit",        "description": "Reach #1 on community leaderboard",        "icon": "🏔️", "category": "Prestige"},
    "duel-win":          {"name": "Duelist",           "description": "Win 10 duels",                             "icon": "⚔️", "category": "Prestige"},
    "season-top5":       {"name": "Season Contender",  "description": "Finish top 5 in a completed season",       "icon": "🥇", "category": "Prestige"},
    "crowd-favorite":    {"name": "Crowd Favorite",    "description": "Get 50 total reactions across your predictions", "icon": "❤️", "category": "Conviction"},
    "against-the-grain": {"name": "Against the Grain", "description": "Correct prediction where 70% disagreed",        "icon": "🏊", "category": "Conviction"},
    "earnings-whisper":  {"name": "Earnings Whisper",  "description": "5 correct earnings play predictions",              "icon": "📊", "category": "Timing"},
    "momentum-master":   {"name": "Momentum Master",   "description": "10 correct momentum trade predictions",            "icon": "🚀", "category": "Timing"},
    "thesis-proven":     {"name": "Thesis Proven",     "description": "3 correct macro thesis predictions",               "icon": "🌍", "category": "Conviction"},
    "debate-starter":    {"name": "Debate Starter",    "description": "3 predictions each reaching 20 reactions",          "icon": "💬", "category": "Conviction"},
    "return-3":          {"name": "Curious",           "description": "3 day prediction streak",                            "icon": "📅", "category": "Prestige"},
    "return-7":          {"name": "Committed",         "description": "7 day prediction streak",                            "icon": "📅", "category": "Prestige"},
    "return-30":         {"name": "Dedicated",         "description": "30 day prediction streak",                           "icon": "📅", "category": "Prestige"},
    "return-100":        {"name": "Obsessed",          "description": "100 day prediction streak",                          "icon": "🔥", "category": "Prestige"},
    # Weekly Challenges
    "weekly-1":          {"name": "Challenge Accepted", "description": "Complete 1 weekly challenge",                          "icon": "📋", "category": "Prestige"},
    "weekly-5":          {"name": "Weekly Warrior",     "description": "Complete 5 weekly challenges",                         "icon": "⚔️", "category": "Prestige"},
    "weekly-10":         {"name": "Never Miss",         "description": "Complete 10 weekly challenges",                        "icon": "🏅", "category": "Prestige"},
    # XP
    "xp-first":          {"name": "First XP",           "description": "Earn your first XP",                                  "icon": "⚡", "category": "Prestige"},
    "xp-500":            {"name": "XP Grinder",         "description": "Earn 500 total XP",                                   "icon": "💪", "category": "Prestige"},
    "xp-5000":           {"name": "XP Machine",         "description": "Earn 5000 total XP",                                  "icon": "🔋", "category": "Prestige"},
    "xp-daily-cap":      {"name": "Max Effort",         "description": "Hit the daily XP cap",                                "icon": "🔥", "category": "Prestige"},
}

ALL_BADGE_IDS = list(BADGE_INFO.keys())

# ─── Leaderboard cache ────────────────────────────────────────────────────────

_last_leaderboard_check: float = 0
_leaderboard_cache: list[dict] = []
_LEADERBOARD_TTL = 3600  # seconds


def _get_cached_leaderboard(db: Session) -> list[dict]:
    global _last_leaderboard_check, _leaderboard_cache
    now = time.time()
    if _leaderboard_cache and now - _last_leaderboard_check < _LEADERBOARD_TTL:
        return _leaderboard_cache

    users = db.query(User).all()
    board = []
    for u in users:
        scored = (
            db.query(UserPrediction)
            .filter(UserPrediction.user_id == u.id, UserPrediction.outcome.in_(["correct", "incorrect"]))
            .all()
        )
        sc = len(scored)
        if sc < 10:
            continue
        cc = sum(1 for p in scored if p.outcome == "correct")
        board.append({"user_id": u.id, "accuracy": round(cc / sc * 100, 2), "scored_count": sc})

    board.sort(key=lambda x: (x["accuracy"], x["scored_count"]), reverse=True)
    for i, entry in enumerate(board):
        entry["rank"] = i + 1

    _leaderboard_cache = board
    _last_leaderboard_check = now
    return board


# ─── Main entry point ────────────────────────────────────────────────────────


def evaluate_badges(user_id: int, db: Session) -> list[str]:
    """Check all 39 badge conditions. Awards new badges. Returns list of newly awarded badge_ids."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return []

    existing = set(
        row.badge_id
        for row in db.query(Achievement.badge_id).filter(Achievement.user_id == user_id).all()
    )

    all_preds = (
        db.query(UserPrediction)
        .filter(UserPrediction.user_id == user_id)
        .order_by(UserPrediction.created_at.asc())
        .all()
    )
    total_preds = len(all_preds)
    scored = [p for p in all_preds if p.outcome in ("correct", "incorrect")]
    correct = [p for p in scored if p.outcome == "correct"]
    scored_preds = len(scored)
    correct_preds = len(correct)
    accuracy = (correct_preds / scored_preds) if scored_preds > 0 else 0.0  # 0-1 ratio

    outcome_seq = [p.outcome for p in all_preds if p.outcome in ("correct", "incorrect")]
    streak_best = user.streak_best or 0

    newly_awarded: list[str] = []

    def _award(badge_id: str):
        if badge_id not in existing:
            db.add(Achievement(user_id=user_id, badge_id=badge_id))
            existing.add(badge_id)
            newly_awarded.append(badge_id)
            logger.info(f"Badge awarded: {badge_id} to user {user_id}")

    # ── ACCURACY ──────────────────────────────────────────────────────────

    if "first-blood" not in existing and scored_preds >= 1:
        _award("first-blood")

    if "sharpshooter" not in existing and correct_preds >= 5:
        _award("sharpshooter")

    if "sniper-elite" not in existing and scored_preds >= 20 and accuracy >= 0.80:
        _award("sniper-elite")

    if "perfect-week" not in existing and correct_preds >= 5:
        weeks: dict[tuple, int] = defaultdict(int)
        for p in correct:
            if p.evaluated_at:
                iso = p.evaluated_at.isocalendar()
                weeks[(iso[0], iso[1])] += 1
        if any(cnt >= 5 for cnt in weeks.values()):
            _award("perfect-week")

    if "ice-cold" not in existing:
        run = 0
        for o in outcome_seq:
            run = run + 1 if o == "correct" else 0
            if run >= 10:
                _award("ice-cold")
                break

    # ── STREAKS ───────────────────────────────────────────────────────────

    if "hot-streak" not in existing and streak_best >= 5:
        _award("hot-streak")
    if "on-fire" not in existing and streak_best >= 10:
        _award("on-fire")
    if "untouchable" not in existing and streak_best >= 20:
        _award("untouchable")

    if "comeback-kid" not in existing:
        bad_run = 0
        good_run = 0
        for o in outcome_seq:
            if o == "incorrect":
                bad_run = bad_run + 1 if good_run == 0 else 1
                good_run = 0
            else:
                if bad_run >= 3:
                    good_run += 1
                    if good_run >= 5:
                        _award("comeback-kid")
                        break
                else:
                    bad_run = 0
                    good_run = 0

    # ── VOLUME ────────────────────────────────────────────────────────────

    if "vol-10" not in existing and total_preds >= 10:
        _award("vol-10")
    if "vol-50" not in existing and total_preds >= 50:
        _award("vol-50")
    if "vol-100" not in existing and total_preds >= 100:
        _award("vol-100")
    if "vol-500" not in existing and total_preds >= 500:
        _award("vol-500")
    if "vol-1000" not in existing and total_preds >= 1000:
        _award("vol-1000")

    # ── TIMING ────────────────────────────────────────────────────────────

    if "speed-demon" not in existing:
        if any(p.evaluation_window_days <= 7 for p in correct):
            _award("speed-demon")

    if "day-trader" not in existing:
        if any(p.evaluation_window_days == 1 for p in correct):
            _award("day-trader")

    if "swing-king" not in existing:
        if sum(1 for p in correct if p.evaluation_window_days <= 7) >= 5:
            _award("swing-king")

    if "patient-capital" not in existing:
        if any(p.evaluation_window_days == 365 for p in correct):
            _award("patient-capital")

    if "time-lord" not in existing:
        if len(set(p.evaluation_window_days for p in correct)) >= 5:
            _award("time-lord")

    if "marathon-runner" not in existing:
        if any(p.evaluation_window_days >= 180 for p in correct):
            _award("marathon-runner")

    # ── SECTORS ───────────────────────────────────────────────────────────

    sector_scored: dict[str, dict] = defaultdict(lambda: {"correct": 0, "total": 0})
    for p in scored:
        s = get_sector(p.ticker)
        sector_scored[s]["total"] += 1
        if p.outcome == "correct":
            sector_scored[s]["correct"] += 1

    sector_correct: dict[str, int] = defaultdict(int)
    for p in correct:
        sector_correct[get_sector(p.ticker)] += 1

    if "sector-master" not in existing:
        for s, stats in sector_scored.items():
            if stats["total"] >= 5 and stats["correct"] / stats["total"] >= 0.70:
                _award("sector-master")
                break

    if "diamond-hands" not in existing and sector_correct.get("Crypto", 0) >= 10:
        _award("diamond-hands")
    if "tech-guru" not in existing and sector_correct.get("Tech", 0) >= 15:
        _award("tech-guru")
    if "diversified" not in existing:
        if len(set(get_sector(p.ticker) for p in correct)) >= 5:
            _award("diversified")
    if "oil-baron" not in existing and sector_correct.get("Energy", 0) >= 5:
        _award("oil-baron")
    if "money-printer" not in existing and sector_correct.get("Finance", 0) >= 10:
        _award("money-printer")

    # ── CONVICTION ────────────────────────────────────────────────────────

    bull_correct = [p for p in correct if p.direction == "bullish"]
    bear_correct = [p for p in correct if p.direction == "bearish"]

    if "perma-bull" not in existing and len(bull_correct) >= 20:
        _award("perma-bull")
    if "perma-bear" not in existing and len(bear_correct) >= 10:
        _award("perma-bear")

    if "contrarian" not in existing and total_preds < 200:
        for p in correct:
            w_start = p.created_at - timedelta(days=15)
            w_end = p.created_at + timedelta(days=15)
            total_on_ticker = (
                db.query(func.count(UserPrediction.id))
                .filter(UserPrediction.ticker == p.ticker,
                        UserPrediction.created_at >= w_start,
                        UserPrediction.created_at <= w_end)
                .scalar()
            )
            if total_on_ticker < 5:
                continue
            same_dir = (
                db.query(func.count(UserPrediction.id))
                .filter(UserPrediction.ticker == p.ticker,
                        UserPrediction.direction == p.direction,
                        UserPrediction.created_at >= w_start,
                        UserPrediction.created_at <= w_end)
                .scalar()
            )
            if same_dir / total_on_ticker < 0.20:
                _award("contrarian")
                break

    if "strong-conviction" not in existing:
        tc: dict[str, int] = defaultdict(int)
        for p in correct:
            tc[p.ticker] += 1
        if any(c >= 3 for c in tc.values()):
            _award("strong-conviction")

    if "flip-master" not in existing:
        bt = set(p.ticker for p in bull_correct)
        brt = set(p.ticker for p in bear_correct)
        if bt & brt:
            _award("flip-master")

    # ── PRESTIGE ──────────────────────────────────────────────────────────

    # Level-based badges
    user_xp_level = getattr(user, 'xp_level', 1) or 1
    if "level-5" not in existing and user_xp_level >= 5:
        _award("level-5")
    if "level-10" not in existing and user_xp_level >= 10:
        _award("level-10")

    if "top-10" not in existing or "summit" not in existing:
        board = _get_cached_leaderboard(db)
        if "top-10" not in existing:
            for entry in board[:10]:
                if entry["user_id"] == user_id:
                    _award("top-10")
                    break
        if "summit" not in existing:
            if board and board[0]["user_id"] == user_id:
                _award("summit")

    # duel-win: 10+ duel wins
    if "duel-win" not in existing:
        duel_wins = (
            db.query(func.count(Duel.id))
            .filter(Duel.winner_id == user_id, Duel.status == "completed")
            .scalar()
        )
        if duel_wins >= 10:
            _award("duel-win")

    # season-top5: top 5 in any completed season with 5+ scored
    if "season-top5" not in existing:
        completed_seasons = db.query(Season).filter(Season.status == "completed").all()
        for season in completed_seasons:
            entries = (
                db.query(SeasonEntry)
                .filter(SeasonEntry.season_id == season.id, SeasonEntry.predictions_scored >= 5)
                .all()
            )
            if not entries:
                continue
            ranked = sorted(
                entries,
                key=lambda e: (e.predictions_correct / e.predictions_scored if e.predictions_scored else 0),
                reverse=True,
            )
            top5_ids = [e.user_id for e in ranked[:5]]
            if user_id in top5_ids:
                _award("season-top5")
                break

    # ── REACTIONS ─────────────────────────────────────────────────────────

    from models import PredictionReaction

    # crowd-favorite: 50 total reactions on your predictions
    if "crowd-favorite" not in existing:
        total_reactions = (
            db.query(func.count(PredictionReaction.id))
            .filter(PredictionReaction.prediction_source == "user")
            .join(UserPrediction, UserPrediction.id == PredictionReaction.prediction_id)
            .filter(UserPrediction.user_id == user_id)
            .scalar() or 0
        )
        if total_reactions >= 50:
            _award("crowd-favorite")

    # against-the-grain: correct prediction with 70%+ disagree/no_way reactions
    if "against-the-grain" not in existing:
        for p in correct:
            rxns = (
                db.query(PredictionReaction)
                .filter(PredictionReaction.prediction_id == p.id, PredictionReaction.prediction_source == "user")
                .all()
            )
            if len(rxns) < 5:
                continue
            negative = sum(1 for r in rxns if r.reaction in ("disagree", "no_way"))
            if negative / len(rxns) >= 0.70:
                _award("against-the-grain")
                break

    # ── TEMPLATE BADGES ───────────────────────────────────────────────────

    if "earnings-whisper" not in existing:
        ec = sum(1 for p in correct if getattr(p, 'template', None) == 'earnings_play')
        if ec >= 5:
            _award("earnings-whisper")

    if "momentum-master" not in existing:
        mc = sum(1 for p in correct if getattr(p, 'template', None) == 'momentum_trade')
        if mc >= 10:
            _award("momentum-master")

    if "thesis-proven" not in existing:
        tc = sum(1 for p in correct if getattr(p, 'template', None) == 'macro_thesis')
        if tc >= 3:
            _award("thesis-proven")

    # debate-starter: 3 predictions with 20+ reactions each
    if "debate-starter" not in existing:
        hot_count = 0
        for p in all_preds:
            rxn_count = (
                db.query(func.count(PredictionReaction.id))
                .filter(PredictionReaction.prediction_id == p.id, PredictionReaction.prediction_source == "user")
                .scalar() or 0
            )
            if rxn_count >= 20:
                hot_count += 1
            if hot_count >= 3:
                _award("debate-starter")
                break

    # ── RETURN STREAK BADGES ─────────────────────────────────────────────

    ret_best = user.return_streak_best or 0
    if "return-3" not in existing and ret_best >= 3:
        _award("return-3")
    if "return-7" not in existing and ret_best >= 7:
        _award("return-7")
    if "return-30" not in existing and ret_best >= 30:
        _award("return-30")
    if "return-100" not in existing and ret_best >= 100:
        _award("return-100")

    # ── WEEKLY CHALLENGE BADGES ────────────────────────────────────────────

    try:
        from models import WeeklyChallengeProgress
        weekly_completed = db.query(func.count(WeeklyChallengeProgress.id)).filter(
            WeeklyChallengeProgress.user_id == user_id,
            WeeklyChallengeProgress.completed == 1,
        ).scalar() or 0
        if "weekly-1" not in existing and weekly_completed >= 1:
            _award("weekly-1")
        if "weekly-5" not in existing and weekly_completed >= 5:
            _award("weekly-5")
        if "weekly-10" not in existing and weekly_completed >= 10:
            _award("weekly-10")
    except Exception:
        pass

    # ── XP BADGES ───────────────────────────────────────────────────────

    xp_total = getattr(user, 'xp_total', 0) or 0
    xp_today = getattr(user, 'xp_today', 0) or 0
    xp_level = getattr(user, 'xp_level', 1) or 1
    if "xp-first" not in existing and xp_total >= 1:
        _award("xp-first")
    if "xp-500" not in existing and xp_total >= 500:
        _award("xp-500")
    if "xp-5000" not in existing and xp_total >= 5000:
        _award("xp-5000")
    if "xp-daily-cap" not in existing and xp_today >= 300:
        _award("xp-daily-cap")

    # ── Persist ───────────────────────────────────────────────────────────

    if newly_awarded:
        from notifications import create_notification
        from activity import log_activity
        for bid in newly_awarded:
            info = BADGE_INFO.get(bid, {})
            create_notification(
                user_id=user_id, type="badge_earned",
                title="Badge Unlocked!",
                message=f"You earned the {info.get('name', bid)} badge: {info.get('description', '')}",
                data={"badge_id": bid}, db=db,
            )
            log_activity(
                user_id=user_id, event_type="badge_earned",
                description=f"{user.username} earned the {info.get('name', bid)} badge",
                data={"badge_id": bid, "badge_name": info.get('name', bid)}, db=db,
            )
        # XP for each badge
        try:
            from xp import award_xp
            for _ in newly_awarded:
                award_xp(user_id, "badge_earned", db)
        except Exception:
            pass

        db.commit()
        logger.info(f"[BadgeEngine] User {user_id}: awarded {len(newly_awarded)} badge(s): {newly_awarded}")

    return newly_awarded


# ─── Progress calculator (used by achievements endpoint) ─────────────────────


def compute_progress(user_id: int, db: Session) -> dict[str, dict]:
    """For each badge, return {"current": int, "target": int}.

    Only returns entries for badges that have meaningful numeric progress.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {}

    all_preds = (
        db.query(UserPrediction)
        .filter(UserPrediction.user_id == user_id)
        .order_by(UserPrediction.created_at.asc())
        .all()
    )
    total_preds = len(all_preds)
    scored = [p for p in all_preds if p.outcome in ("correct", "incorrect")]
    correct = [p for p in scored if p.outcome == "correct"]
    scored_preds = len(scored)
    correct_preds = len(correct)
    streak_best = user.streak_best or 0

    # Pre-compute sector correct counts
    sector_correct: dict[str, int] = defaultdict(int)
    for p in correct:
        sector_correct[get_sector(p.ticker)] += 1

    # Longest consecutive correct run
    longest_run = 0
    run = 0
    for p in all_preds:
        if p.outcome == "correct":
            run += 1
            longest_run = max(longest_run, run)
        elif p.outcome == "incorrect":
            run = 0

    # Correct short-term count
    short_correct = sum(1 for p in correct if p.evaluation_window_days <= 7)

    # Distinct timeframes
    distinct_windows = len(set(p.evaluation_window_days for p in correct))

    # Direction counts
    bull_correct_cnt = sum(1 for p in correct if p.direction == "bullish")
    bear_correct_cnt = sum(1 for p in correct if p.direction == "bearish")

    # Ticker conviction
    tc: dict[str, int] = defaultdict(int)
    for p in correct:
        tc[p.ticker] += 1
    max_ticker_correct = max(tc.values()) if tc else 0

    # Distinct sectors with correct
    distinct_sectors = len(set(get_sector(p.ticker) for p in correct))

    # Duel wins
    duel_wins = (
        db.query(func.count(Duel.id))
        .filter(Duel.winner_id == user_id, Duel.status == "completed")
        .scalar() or 0
    )

    # Best week correct count
    weeks: dict[tuple, int] = defaultdict(int)
    for p in correct:
        if p.evaluated_at:
            iso = p.evaluated_at.isocalendar()
            weeks[(iso[0], iso[1])] += 1
    best_week = max(weeks.values()) if weeks else 0

    progress = {
        # Accuracy
        "first-blood":       {"current": scored_preds,     "target": 1},
        "sharpshooter":      {"current": correct_preds,    "target": 5},
        "sniper-elite":      {"current": scored_preds,     "target": 20},
        "perfect-week":      {"current": best_week,        "target": 5},
        "ice-cold":          {"current": longest_run,      "target": 10},
        # Streaks
        "hot-streak":        {"current": streak_best,      "target": 5},
        "on-fire":           {"current": streak_best,      "target": 10},
        "untouchable":       {"current": streak_best,      "target": 20},
        # Volume
        "vol-10":            {"current": total_preds,      "target": 10},
        "vol-50":            {"current": total_preds,      "target": 50},
        "vol-100":           {"current": total_preds,      "target": 100},
        "vol-500":           {"current": total_preds,      "target": 500},
        "vol-1000":          {"current": total_preds,      "target": 1000},
        # Timing
        "swing-king":        {"current": short_correct,    "target": 5},
        "time-lord":         {"current": distinct_windows, "target": 5},
        # Sectors
        "diamond-hands":     {"current": sector_correct.get("Crypto", 0),  "target": 10},
        "tech-guru":         {"current": sector_correct.get("Tech", 0),    "target": 15},
        "diversified":       {"current": distinct_sectors,                  "target": 5},
        "oil-baron":         {"current": sector_correct.get("Energy", 0),  "target": 5},
        "money-printer":     {"current": sector_correct.get("Finance", 0), "target": 10},
        # Conviction
        "perma-bull":        {"current": bull_correct_cnt, "target": 20},
        "perma-bear":        {"current": bear_correct_cnt, "target": 10},
        "strong-conviction": {"current": max_ticker_correct, "target": 3},
        # Prestige
        "level-5":           {"current": getattr(user, 'xp_level', 1) or 1, "target": 5},
        "level-10":          {"current": getattr(user, 'xp_level', 1) or 1, "target": 10},
        "duel-win":          {"current": duel_wins,        "target": 10},
        "crowd-favorite":    {"current": 0,                "target": 50},
        "earnings-whisper":  {"current": sum(1 for p in correct if getattr(p, 'template', None) == 'earnings_play'), "target": 5},
        "momentum-master":   {"current": sum(1 for p in correct if getattr(p, 'template', None) == 'momentum_trade'), "target": 10},
        "thesis-proven":     {"current": sum(1 for p in correct if getattr(p, 'template', None) == 'macro_thesis'), "target": 3},
        "return-3":          {"current": user.return_streak_best or 0, "target": 3},
        "return-7":          {"current": user.return_streak_best or 0, "target": 7},
        "return-30":         {"current": user.return_streak_best or 0, "target": 30},
        "return-100":        {"current": user.return_streak_best or 0, "target": 100},
    }

    # Weekly challenge badges
    try:
        from models import WeeklyChallengeProgress
        wc = db.query(func.count(WeeklyChallengeProgress.id)).filter(
            WeeklyChallengeProgress.user_id == user_id,
            WeeklyChallengeProgress.completed == 1,
        ).scalar() or 0
        progress["weekly-1"] = {"current": wc, "target": 1}
        progress["weekly-5"] = {"current": wc, "target": 5}
        progress["weekly-10"] = {"current": wc, "target": 10}
    except Exception:
        pass

    # XP badges
    xp_total = getattr(user, 'xp_total', 0) or 0
    xp_level = getattr(user, 'xp_level', 1) or 1
    progress["xp-first"] = {"current": min(xp_total, 1), "target": 1}
    progress["xp-500"] = {"current": min(xp_total, 500), "target": 500}
    progress["xp-5000"] = {"current": min(xp_total, 5000), "target": 5000}

    return progress

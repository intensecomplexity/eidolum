"""
Phase 2 scheduled jobs:
  - evaluate_user_predictions()  — every 15 min
  - evaluate_duels()             — every 15 min
  - check_season_completion()    — every hour
"""
import os
import httpx
from datetime import datetime
from decimal import Decimal
from sqlalchemy.orm import Session
from models import User, UserPrediction, Duel, Season, SeasonEntry

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")

# ── Shared price helper ───────────────────────────────────────────────────────

_price_cache: dict[str, float] = {}


def _fetch_price(ticker: str) -> float | None:
    """Fetch current price. Tries Finnhub, then Alpha Vantage, then yfinance."""
    if ticker in _price_cache:
        return _price_cache[ticker]

    if FINNHUB_KEY:
        try:
            r = httpx.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": ticker, "token": FINNHUB_KEY},
                timeout=10,
            )
            price = r.json().get("c")
            if price and price > 0:
                result = round(float(price), 2)
                _price_cache[ticker] = result
                return result
        except Exception:
            pass

    try:
        from jobs.evaluator import get_current_price
        result = get_current_price(ticker)
        if result:
            _price_cache[ticker] = result
        return result
    except Exception:
        return None


def _parse_target(target_str: str) -> float | None:
    try:
        return float(target_str.strip().replace("$", "").replace(",", ""))
    except (ValueError, AttributeError):
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 1. evaluate_user_predictions
# ══════════════════════════════════════════════════════════════════════════════


def evaluate_user_predictions(db: Session):
    """Score expired pending user predictions. Updates streaks, seasons, badges."""
    _price_cache.clear()
    now = datetime.utcnow()
    print(f"[UserEval] Running at {now.isoformat()}")

    overdue = (
        db.query(UserPrediction)
        .filter(
            UserPrediction.outcome == "pending",
            UserPrediction.expires_at.isnot(None),
            UserPrediction.expires_at <= now,
        )
        .all()
    )

    if not overdue:
        print("[UserEval] No expired predictions")
        return

    correct_count = 0
    incorrect_count = 0
    affected_user_ids = set()

    for p in overdue:
        if not p.ticker:
            continue

        price = _fetch_price(p.ticker)
        if price is None:
            continue

        entry = float(p.price_at_call) if p.price_at_call else None
        if entry is None:
            continue

        # Determine outcome based on direction vs price movement
        if p.direction == "bullish":
            outcome = "correct" if price > entry else "incorrect"
        elif p.direction == "bearish":
            outcome = "correct" if price < entry else "incorrect"
        else:
            continue

        p.outcome = outcome
        p.evaluated_at = now
        p.current_price = Decimal(str(price))

        if outcome == "correct":
            correct_count += 1
        else:
            incorrect_count += 1

        affected_user_ids.add(p.user_id)

        # Update streak on the user row
        user = db.query(User).filter(User.id == p.user_id).first()
        if user:
            if outcome == "correct":
                user.streak_current = (user.streak_current or 0) + 1
                if user.streak_current > (user.streak_best or 0):
                    user.streak_best = user.streak_current
            else:
                user.streak_current = 0

        # Update season_entries
        _update_season_scored(p.user_id, outcome, db)

    db.commit()

    total = correct_count + incorrect_count
    print(f"[UserEval] Evaluated {total} user predictions: {correct_count} correct, {incorrect_count} incorrect")

    # Run badge engine for affected users
    try:
        from badge_engine import evaluate_badges
        for uid in affected_user_ids:
            evaluate_badges(uid, db)
    except Exception as e:
        print(f"[UserEval] Badge engine error: {e}")


def _update_season_scored(user_id: int, outcome: str, db: Session):
    """Increment predictions_scored (and predictions_correct) on the current season entry."""
    season = db.query(Season).filter(Season.status == "active").first()
    if not season:
        return

    entry = (
        db.query(SeasonEntry)
        .filter(SeasonEntry.season_id == season.id, SeasonEntry.user_id == user_id)
        .first()
    )
    if not entry:
        # User submitted before seasons existed; create an entry now
        entry = SeasonEntry(season_id=season.id, user_id=user_id, predictions_made=0)
        db.add(entry)

    entry.predictions_scored = (entry.predictions_scored or 0) + 1
    if outcome == "correct":
        entry.predictions_correct = (entry.predictions_correct or 0) + 1


# ══════════════════════════════════════════════════════════════════════════════
# 2. evaluate_duels
# ══════════════════════════════════════════════════════════════════════════════


def evaluate_duels(db: Session):
    """Score expired active duels. Determines winner by target accuracy."""
    _price_cache.clear()
    now = datetime.utcnow()
    print(f"[DuelEval] Running at {now.isoformat()}")

    expired = (
        db.query(Duel)
        .filter(
            Duel.status == "active",
            Duel.expires_at.isnot(None),
            Duel.expires_at <= now,
        )
        .all()
    )

    if not expired:
        print("[DuelEval] No expired duels")
        return

    evaluated = 0
    for duel in expired:
        price = _fetch_price(duel.ticker)
        if price is None:
            continue

        start_price = float(duel.price_at_start) if duel.price_at_start else None
        c_target = _parse_target(duel.challenger_target)
        o_target = _parse_target(duel.opponent_target)

        if start_price is None:
            continue

        # Did the price go up or down from start?
        price_went_up = price >= start_price

        # Check if each player's direction was right
        c_dir_right = (
            (duel.challenger_direction == "bullish" and price_went_up) or
            (duel.challenger_direction == "bearish" and not price_went_up)
        )
        o_dir_right = (
            (duel.opponent_direction == "bullish" and price_went_up) or
            (duel.opponent_direction == "bearish" and not price_went_up)
        )

        winner_id = None

        if c_dir_right and not o_dir_right:
            # Challenger's direction was right, opponent was wrong
            winner_id = duel.challenger_id
        elif o_dir_right and not c_dir_right:
            # Opponent's direction was right, challenger was wrong
            winner_id = duel.opponent_id
        else:
            # Both right or both wrong — compare target distance
            c_dist = abs(price - c_target) if c_target is not None else float("inf")
            o_dist = abs(price - o_target) if o_target is not None else float("inf")

            if c_dist < o_dist:
                winner_id = duel.challenger_id
            elif o_dist < c_dist:
                winner_id = duel.opponent_id
            else:
                # Perfect tie — challenger wins (they initiated)
                winner_id = duel.challenger_id

        duel.winner_id = winner_id
        duel.status = "completed"
        duel.evaluated_at = now
        evaluated += 1

    db.commit()
    print(f"[DuelEval] Evaluated {evaluated} duels")


# ══════════════════════════════════════════════════════════════════════════════
# 3. check_season_completion
# ══════════════════════════════════════════════════════════════════════════════


def check_season_completion(db: Session):
    """Mark expired active seasons as completed."""
    now = datetime.utcnow()

    expired = (
        db.query(Season)
        .filter(Season.status == "active", Season.ends_at <= now)
        .all()
    )

    for season in expired:
        season.status = "completed"
        print(f"[Seasons] Completed season: {season.name}")

    if expired:
        db.commit()

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
from notifications import create_notification
from activity import log_activity

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")

_price_cache: dict[str, float] = {}

STREAK_MILESTONES = {5, 10, 15, 20}


def _fetch_price(ticker: str) -> float | None:
    if ticker in _price_cache:
        return _price_cache[ticker]
    if FINNHUB_KEY:
        try:
            r = httpx.get("https://finnhub.io/api/v1/quote", params={"symbol": ticker, "token": FINNHUB_KEY}, timeout=10)
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

        # Update streak
        user = db.query(User).filter(User.id == p.user_id).first()
        if user:
            if outcome == "correct":
                user.streak_current = (user.streak_current or 0) + 1
                if user.streak_current > (user.streak_best or 0):
                    user.streak_best = user.streak_current
                # Streak milestone
                if user.streak_current in STREAK_MILESTONES:
                    create_notification(
                        user_id=p.user_id, type="streak_milestone",
                        title="Streak Milestone!",
                        message=f"You're on a {user.streak_current} prediction streak!",
                        data={"streak": user.streak_current}, db=db,
                    )
                    log_activity(
                        user_id=p.user_id, event_type="streak_milestone",
                        description=f"{user.username} hit a {user.streak_current} prediction streak!",
                        data={"streak_count": user.streak_current}, db=db,
                    )
            else:
                user.streak_current = 0

        # Prediction scored notification
        if outcome == "correct":
            msg = f"Your {p.direction} call on {p.ticker} was correct! Target: {p.price_target}, Final price: ${price}. Share your win \u2192"
        else:
            msg = f"Your {p.direction} call on {p.ticker} was incorrect. Target: {p.price_target}, Final price: ${price}"
        create_notification(
            user_id=p.user_id, type="prediction_scored",
            title="You Called It!" if outcome == "correct" else "Prediction Scored",
            message=msg,
            data={"prediction_id": p.id, "outcome": outcome, "ticker": p.ticker, "told_you_so": outcome == "correct"}, db=db,
        )
        _uname = user.username if user else "Someone"
        log_activity(
            user_id=p.user_id, event_type="prediction_scored",
            description=f"{_uname}'s {p.ticker} call was {outcome}",
            ticker=p.ticker,
            data={"prediction_id": p.id, "outcome": outcome, "ticker": p.ticker}, db=db,
        )

        _update_season_scored(p.user_id, outcome, db)

    db.commit()

    total = correct_count + incorrect_count
    print(f"[UserEval] Evaluated {total} user predictions: {correct_count} correct, {incorrect_count} incorrect")

    # Badge engine
    try:
        from badge_engine import evaluate_badges
        for uid in affected_user_ids:
            evaluate_badges(uid, db)
    except Exception as e:
        print(f"[UserEval] Badge engine error: {e}")


def _update_season_scored(user_id: int, outcome: str, db: Session):
    season = db.query(Season).filter(Season.status == "active").first()
    if not season:
        return
    entry = (
        db.query(SeasonEntry)
        .filter(SeasonEntry.season_id == season.id, SeasonEntry.user_id == user_id)
        .first()
    )
    if not entry:
        entry = SeasonEntry(season_id=season.id, user_id=user_id, predictions_made=0)
        db.add(entry)
    entry.predictions_scored = (entry.predictions_scored or 0) + 1
    if outcome == "correct":
        entry.predictions_correct = (entry.predictions_correct or 0) + 1


# ══════════════════════════════════════════════════════════════════════════════
# 2. evaluate_duels
# ══════════════════════════════════════════════════════════════════════════════


def evaluate_duels(db: Session):
    _price_cache.clear()
    now = datetime.utcnow()
    print(f"[DuelEval] Running at {now.isoformat()}")

    expired = (
        db.query(Duel)
        .filter(Duel.status == "active", Duel.expires_at.isnot(None), Duel.expires_at <= now)
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

        price_went_up = price >= start_price
        c_dir_right = (duel.challenger_direction == "bullish" and price_went_up) or (duel.challenger_direction == "bearish" and not price_went_up)
        o_dir_right = (duel.opponent_direction == "bullish" and price_went_up) or (duel.opponent_direction == "bearish" and not price_went_up)

        if c_dir_right and not o_dir_right:
            winner_id = duel.challenger_id
        elif o_dir_right and not c_dir_right:
            winner_id = duel.opponent_id
        else:
            c_dist = abs(price - c_target) if c_target is not None else float("inf")
            o_dist = abs(price - o_target) if o_target is not None else float("inf")
            winner_id = duel.challenger_id if c_dist <= o_dist else duel.opponent_id

        duel.winner_id = winner_id
        duel.status = "completed"
        duel.evaluated_at = now
        evaluated += 1

        # Notifications for both players
        challenger = db.query(User).filter(User.id == duel.challenger_id).first()
        opponent = db.query(User).filter(User.id == duel.opponent_id).first()
        c_name = challenger.username if challenger else "Unknown"
        o_name = opponent.username if opponent else "Unknown"

        for uid, is_winner in [(duel.challenger_id, winner_id == duel.challenger_id), (duel.opponent_id, winner_id == duel.opponent_id)]:
            other_name = o_name if uid == duel.challenger_id else c_name
            result = "won" if is_winner else "lost"
            msg = f"You won the {duel.ticker} duel against {other_name}!" if is_winner else f"You lost the {duel.ticker} duel against {other_name}"
            create_notification(
                user_id=uid, type="duel_result",
                title="Duel Complete!",
                message=msg,
                data={"duel_id": duel.id, "result": result}, db=db,
            )

        # Activity: duel completed
        winner_name = c_name if winner_id == duel.challenger_id else o_name
        loser_name = o_name if winner_id == duel.challenger_id else c_name
        log_activity(
            user_id=winner_id, event_type="duel_completed",
            description=f"{winner_name} won the {duel.ticker} duel against {loser_name}",
            ticker=duel.ticker,
            data={"duel_id": duel.id, "winner": winner_name, "loser": loser_name, "ticker": duel.ticker}, db=db,
        )

    db.commit()
    print(f"[DuelEval] Evaluated {evaluated} duels")


# ══════════════════════════════════════════════════════════════════════════════
# 3. check_season_completion
# ══════════════════════════════════════════════════════════════════════════════


def check_season_completion(db: Session):
    now = datetime.utcnow()

    expired = db.query(Season).filter(Season.status == "active", Season.ends_at <= now).all()

    for season in expired:
        season.status = "completed"
        print(f"[Seasons] Completed season: {season.name}")

        # Notify participants
        entries = (
            db.query(SeasonEntry)
            .filter(SeasonEntry.season_id == season.id, SeasonEntry.predictions_scored >= 1)
            .all()
        )
        ranked = sorted(
            entries,
            key=lambda e: (e.predictions_correct / e.predictions_scored if e.predictions_scored else 0),
            reverse=True,
        )
        for i, entry in enumerate(ranked):
            rank = i + 1
            accuracy = round(entry.predictions_correct / entry.predictions_scored * 100, 1) if entry.predictions_scored > 0 else 0
            create_notification(
                user_id=entry.user_id, type="season_ended",
                title="Season Complete!",
                message=f"You finished #{rank} in {season.name} with {accuracy}% accuracy",
                data={"season_id": season.id, "rank": rank, "accuracy": accuracy}, db=db,
            )

    if expired:
        db.commit()

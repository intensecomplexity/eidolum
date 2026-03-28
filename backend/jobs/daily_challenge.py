"""
Daily Challenge jobs:
  - create_daily_challenge: 9:00 AM EST weekdays (picks ticker, fetches open price)
  - score_daily_challenge: 4:30 PM EST weekdays (fetches close price, scores entries)
"""
import os
import random
import httpx
from datetime import datetime, date, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import func
from models import DailyChallenge, DailyChallengeEntry, User
from notifications import create_notification
from activity import log_activity
from ticker_lookup import TICKER_INFO

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")

# Popular tickers get 3x weight
POPULAR = {"NVDA", "TSLA", "AAPL", "META", "BTC", "AMZN", "GOOGL"}
CRYPTO = {"BTC", "ETH", "SOL"}
ALL_TICKERS = list(TICKER_INFO.keys())


def _fetch_price(ticker: str) -> float | None:
    if FINNHUB_KEY:
        try:
            r = httpx.get("https://finnhub.io/api/v1/quote", params={"symbol": ticker, "token": FINNHUB_KEY}, timeout=10)
            price = r.json().get("c")
            if price and price > 0:
                return round(float(price), 2)
        except Exception:
            pass
    try:
        from jobs.evaluator import get_current_price
        return get_current_price(ticker)
    except Exception:
        return None


def pick_daily_ticker(db: Session) -> str:
    """Pick a ticker that hasn't been used in the last 7 days."""
    week_ago = date.today() - timedelta(days=7)
    recent = [
        r[0] for r in db.query(DailyChallenge.ticker)
        .filter(DailyChallenge.challenge_date >= week_ago)
        .all()
    ]
    recent_set = set(recent)

    # Build weighted pool
    pool = []
    for t in ALL_TICKERS:
        if t in recent_set:
            continue
        weight = 3 if t in POPULAR else 1
        pool.extend([t] * weight)

    if not pool:
        pool = [t for t in ALL_TICKERS if t not in recent_set] or ALL_TICKERS

    return random.choice(pool)


def create_daily_challenge(db: Session):
    """Create today's daily challenge. Called at 9:00 AM EST weekdays."""
    today = date.today()
    print(f"[DailyChallenge] Creating challenge for {today}")

    # Check if already exists
    existing = db.query(DailyChallenge).filter(DailyChallenge.challenge_date == today).first()
    if existing:
        print(f"[DailyChallenge] Already exists for {today}")
        return

    ticker = pick_daily_ticker(db)
    price = _fetch_price(ticker)
    ticker_name = TICKER_INFO.get(ticker, ticker)

    challenge = DailyChallenge(
        ticker=ticker,
        ticker_name=ticker_name,
        price_at_open=Decimal(str(price)) if price else None,
        challenge_date=today,
        status="active",
    )
    db.add(challenge)

    # Activity event
    log_activity(
        user_id=0, event_type="daily_challenge",
        description=f"Daily Challenge: {ticker} ({ticker_name}) — Bull or Bear?",
        ticker=ticker, data={"ticker": ticker}, db=db,
    )

    db.commit()
    print(f"[DailyChallenge] Created: {ticker} @ ${price}")


def score_daily_challenge(db: Session):
    """Score today's daily challenge. Called at 4:30 PM EST weekdays."""
    today = date.today()
    print(f"[DailyChallenge] Scoring challenge for {today}")

    challenge = db.query(DailyChallenge).filter(
        DailyChallenge.challenge_date == today,
        DailyChallenge.status == "active",
    ).first()

    if not challenge:
        print("[DailyChallenge] No active challenge to score")
        return

    price = _fetch_price(challenge.ticker)
    if price is None:
        print("[DailyChallenge] Could not fetch close price")
        return

    challenge.price_at_close = Decimal(str(price))
    open_price = float(challenge.price_at_open) if challenge.price_at_open else 0

    if price > open_price:
        challenge.correct_direction = "bullish"
    elif price < open_price:
        challenge.correct_direction = "bearish"
    else:
        challenge.correct_direction = "bullish"  # tie goes to bull

    challenge.status = "completed"

    # Score all entries
    entries = db.query(DailyChallengeEntry).filter(DailyChallengeEntry.challenge_id == challenge.id).all()
    correct_count = 0
    total = len(entries)

    for entry in entries:
        if entry.direction == challenge.correct_direction:
            entry.outcome = "correct"
            correct_count += 1
        else:
            entry.outcome = "incorrect"

        # Update user daily streaks
        user = db.query(User).filter(User.id == entry.user_id).first()
        if user:
            if entry.outcome == "correct":
                user.daily_streak_current = (user.daily_streak_current or 0) + 1
                if user.daily_streak_current > (user.daily_streak_best or 0):
                    user.daily_streak_best = user.daily_streak_current
            else:
                user.daily_streak_current = 0

            # Notify
            pct = round(correct_count / total * 100) if total > 0 else 0
            if entry.outcome == "correct":
                msg = f"You got today's challenge right! {pct}% of players agreed with you."
            else:
                msg = f"Today's {challenge.ticker} challenge was {challenge.correct_direction}. Better luck tomorrow!"
            create_notification(user_id=entry.user_id, type="prediction_scored", title="Daily Challenge Scored!", message=msg, data={"challenge_id": challenge.id}, db=db)

    # Activity event
    community_acc = round(correct_count / total * 100, 1) if total > 0 else 0
    log_activity(
        user_id=0, event_type="daily_challenge_scored",
        description=f"Daily Challenge: {challenge.ticker} was {challenge.correct_direction}. {community_acc}% of {total} players got it right.",
        ticker=challenge.ticker, data={"ticker": challenge.ticker, "correct": challenge.correct_direction, "accuracy": community_acc}, db=db,
    )

    db.commit()
    print(f"[DailyChallenge] Scored: {challenge.ticker} = {challenge.correct_direction}, {correct_count}/{total} correct")

"""
Daily Challenge jobs:
  - create_daily_challenge: weekdays at 14:30 UTC (9:30 AM EST)
  - score_daily_challenge: weekdays at 21:30 UTC (4:30 PM EST)
  - For crypto: create at 00:00 UTC, score at 00:00 UTC next day
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

POPULAR = {"NVDA", "TSLA", "AAPL", "META", "BTC", "AMZN", "GOOGL"}
CRYPTO = {"BTC", "ETH", "SOL"}
ALL_TICKERS = list(TICKER_INFO.keys())


def _fetch_quote(ticker: str) -> dict | None:
    """Fetch quote from Finnhub. Returns dict with 'c' (current), 'o' (open), 'pc' (prev close)."""
    if not FINNHUB_KEY:
        print(f"[DailyChallenge] No FINNHUB_KEY set")
        return None

    # Crypto tickers need special Finnhub symbol format
    symbol = ticker
    if ticker in CRYPTO:
        symbol = f"BINANCE:{ticker}USDT"

    try:
        r = httpx.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": symbol, "token": FINNHUB_KEY},
            timeout=10,
        )
        data = r.json()

        if data.get("c") and data["c"] > 0:
            return data

        # Crypto fallback: try without exchange prefix
        if ticker in CRYPTO:
            r2 = httpx.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": ticker, "token": FINNHUB_KEY},
                timeout=10,
            )
            data2 = r2.json()
            if data2.get("c") and data2["c"] > 0:
                return data2

        print(f"[DailyChallenge] Finnhub returned no data for {ticker} (symbol: {symbol})")
        return None

    except Exception as e:
        print(f"[DailyChallenge] Finnhub API error for {ticker}: {e}")
        return None


def _get_price(ticker: str) -> float | None:
    """Get current price. Tries Finnhub, falls back to evaluator."""
    quote = _fetch_quote(ticker)
    if quote:
        return round(float(quote["c"]), 2)

    # Fallback
    try:
        from jobs.evaluator import get_current_price
        result = get_current_price(ticker)
        if result:
            return round(result, 2)
    except Exception as e:
        print(f"[DailyChallenge] Fallback price error for {ticker}: {e}")

    return None


def _get_open_price(ticker: str) -> float | None:
    """Get today's opening price from Finnhub."""
    quote = _fetch_quote(ticker)
    if quote and quote.get("o") and quote["o"] > 0:
        return round(float(quote["o"]), 2)
    # If no open price, use current as proxy
    if quote and quote.get("c") and quote["c"] > 0:
        return round(float(quote["c"]), 2)
    return _get_price(ticker)


def pick_daily_ticker(db: Session, force_ticker: str | None = None) -> str:
    """Pick a ticker. If force_ticker is provided, use that instead."""
    if force_ticker and force_ticker.upper() in set(ALL_TICKERS):
        return force_ticker.upper()

    week_ago = date.today() - timedelta(days=7)
    recent = [
        r[0] for r in db.query(DailyChallenge.ticker)
        .filter(DailyChallenge.challenge_date >= week_ago)
        .all()
    ]
    recent_set = set(recent)

    pool = []
    for t in ALL_TICKERS:
        if t in recent_set:
            continue
        weight = 3 if t in POPULAR else 1
        pool.extend([t] * weight)

    if not pool:
        pool = [t for t in ALL_TICKERS if t not in recent_set] or ALL_TICKERS

    return random.choice(pool)


def create_daily_challenge(db: Session, force_ticker: str | None = None):
    """Create today's daily challenge."""
    today = date.today()
    print(f"[DailyChallenge] Creating challenge for {today}")

    existing = db.query(DailyChallenge).filter(DailyChallenge.challenge_date == today).first()
    if existing:
        print(f"[DailyChallenge] Already exists for {today}: {existing.ticker}")
        return existing

    ticker = pick_daily_ticker(db, force_ticker)
    open_price = _get_open_price(ticker)
    ticker_name = TICKER_INFO.get(ticker, ticker)

    if open_price is None:
        print(f"[DailyChallenge] WARNING: Could not fetch open price for {ticker}, creating challenge anyway")

    challenge = DailyChallenge(
        ticker=ticker,
        ticker_name=ticker_name,
        price_at_open=Decimal(str(open_price)) if open_price else None,
        challenge_date=today,
        status="active",
    )
    db.add(challenge)

    log_activity(
        user_id=0, event_type="daily_challenge",
        description=f"Daily Challenge: {ticker} ({ticker_name}) — Bull or Bear?",
        ticker=ticker, data={"ticker": ticker}, db=db,
    )

    db.commit()
    db.refresh(challenge)
    print(f"[DailyChallenge] Created: {ticker} at open price ${open_price}")
    return challenge


def score_daily_challenge(db: Session):
    """Score today's (or any active) daily challenge."""
    today = date.today()
    print(f"[DailyChallenge] Scoring for {today}")

    challenge = db.query(DailyChallenge).filter(
        DailyChallenge.status == "active",
    ).order_by(DailyChallenge.challenge_date.desc()).first()

    if not challenge:
        print("[DailyChallenge] No active challenge to score")
        return

    price = _get_price(challenge.ticker)
    if price is None:
        print(f"[DailyChallenge] Could not fetch close price for {challenge.ticker}")
        return

    challenge.price_at_close = Decimal(str(price))
    open_price = float(challenge.price_at_open) if challenge.price_at_open else 0

    if price > open_price:
        challenge.correct_direction = "bullish"
    elif price < open_price:
        challenge.correct_direction = "bearish"
    else:
        challenge.correct_direction = "bullish"

    challenge.status = "completed"

    entries = db.query(DailyChallengeEntry).filter(DailyChallengeEntry.challenge_id == challenge.id).all()
    correct_count = 0
    total = len(entries)

    for entry in entries:
        if entry.direction == challenge.correct_direction:
            entry.outcome = "correct"
            correct_count += 1
        else:
            entry.outcome = "incorrect"

        user = db.query(User).filter(User.id == entry.user_id).first()
        if user:
            if entry.outcome == "correct":
                user.daily_streak_current = (user.daily_streak_current or 0) + 1
                if user.daily_streak_current > (user.daily_streak_best or 0):
                    user.daily_streak_best = user.daily_streak_current
            else:
                user.daily_streak_current = 0

            pct = round(correct_count / total * 100) if total > 0 else 0
            if entry.outcome == "correct":
                msg = f"You got today's challenge right! {pct}% of players agreed with you."
            else:
                msg = f"Today's {challenge.ticker} challenge was {challenge.correct_direction}. Better luck tomorrow!"
            create_notification(user_id=entry.user_id, type="prediction_scored", title="Daily Challenge Scored!", message=msg, data={"challenge_id": challenge.id}, db=db)

    community_acc = round(correct_count / total * 100, 1) if total > 0 else 0
    log_activity(
        user_id=0, event_type="daily_challenge_scored",
        description=f"Daily Challenge: {challenge.ticker} was {challenge.correct_direction}. {community_acc}% of {total} players got it right.",
        ticker=challenge.ticker, data={"ticker": challenge.ticker, "correct": challenge.correct_direction, "accuracy": community_acc}, db=db,
    )

    db.commit()
    print(f"[DailyChallenge] Scored: {challenge.ticker} = {challenge.correct_direction}, {correct_count}/{total} correct")


def ensure_daily_challenge_exists(db: Session):
    """On startup, create today's challenge if it doesn't exist and it's a weekday after market open."""
    today = date.today()
    now = datetime.utcnow()

    existing = db.query(DailyChallenge).filter(DailyChallenge.challenge_date == today).first()
    if existing:
        print(f"[DailyChallenge] Startup: challenge exists for today ({existing.ticker})")
        return

    # Only auto-create on weekdays after 14:30 UTC, or any day for crypto
    is_weekday = today.weekday() < 5
    past_market_open = now.hour >= 14 or (now.hour == 14 and now.minute >= 30)

    if is_weekday and past_market_open:
        print("[DailyChallenge] Startup: no challenge for today, creating one")
        create_daily_challenge(db)
    else:
        print(f"[DailyChallenge] Startup: no challenge yet (weekday={is_weekday}, past_open={past_market_open})")

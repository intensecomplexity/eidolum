"""
Daily Challenge jobs:
  - Weekdays: create at 14:30 UTC (9:30 AM EST), score stocks at 21:30 UTC, score crypto at 23:55 UTC
  - Weekends: create at 00:05 UTC (crypto only), score at 23:55 UTC
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
CRYPTO_LIST = list(CRYPTO)


def _fetch_quote(ticker: str) -> dict | None:
    if not FINNHUB_KEY:
        print("[DailyChallenge] No FINNHUB_KEY set")
        return None
    symbol = f"BINANCE:{ticker}USDT" if ticker in CRYPTO else ticker
    try:
        r = httpx.get("https://finnhub.io/api/v1/quote", params={"symbol": symbol, "token": FINNHUB_KEY}, timeout=10)
        data = r.json()
        if data.get("c") and data["c"] > 0:
            return data
        if ticker in CRYPTO:
            r2 = httpx.get("https://finnhub.io/api/v1/quote", params={"symbol": ticker, "token": FINNHUB_KEY}, timeout=10)
            data2 = r2.json()
            if data2.get("c") and data2["c"] > 0:
                return data2
        print(f"[DailyChallenge] Finnhub no data for {ticker}")
        return None
    except Exception as e:
        print(f"[DailyChallenge] Finnhub error for {ticker}: {e}")
        return None


def _get_price(ticker: str) -> float | None:
    quote = _fetch_quote(ticker)
    if quote:
        return round(float(quote["c"]), 2)
    try:
        from jobs.evaluator import get_current_price
        result = get_current_price(ticker)
        if result:
            return round(result, 2)
    except Exception:
        pass
    return None


def _get_open_price(ticker: str) -> float | None:
    quote = _fetch_quote(ticker)
    if quote and quote.get("o") and quote["o"] > 0:
        return round(float(quote["o"]), 2)
    if quote and quote.get("c") and quote["c"] > 0:
        return round(float(quote["c"]), 2)
    return _get_price(ticker)


def pick_daily_ticker(db: Session, force_ticker: str | None = None, crypto_only: bool = False) -> str:
    if force_ticker and force_ticker.upper() in set(ALL_TICKERS):
        return force_ticker.upper()

    week_ago = date.today() - timedelta(days=7)
    recent = set(r[0] for r in db.query(DailyChallenge.ticker).filter(DailyChallenge.challenge_date >= week_ago).all())

    candidates = CRYPTO_LIST if crypto_only else ALL_TICKERS
    pool = []
    for t in candidates:
        if t in recent:
            continue
        weight = 3 if t in POPULAR else 1
        pool.extend([t] * weight)

    if not pool:
        pool = [t for t in candidates if t not in recent] or candidates

    return random.choice(pool)


def create_daily_challenge(db: Session, force_ticker: str | None = None):
    today = date.today()
    is_weekend = today.weekday() >= 5
    print(f"[DailyChallenge] Creating for {today} (weekend={is_weekend})")

    existing = db.query(DailyChallenge).filter(DailyChallenge.challenge_date == today).first()
    if existing:
        print(f"[DailyChallenge] Already exists: {existing.ticker}")
        return existing

    ticker = pick_daily_ticker(db, force_ticker, crypto_only=is_weekend)
    open_price = _get_open_price(ticker)
    ticker_name = TICKER_INFO.get(ticker, ticker)

    if open_price is None:
        print(f"[DailyChallenge] WARNING: No price for {ticker}")

    challenge = DailyChallenge(
        ticker=ticker,
        ticker_name=ticker_name,
        price_at_open=Decimal(str(open_price)) if open_price else None,
        challenge_date=today,
        status="active",
    )
    db.add(challenge)
    log_activity(user_id=0, event_type="daily_challenge", description=f"Daily Challenge: {ticker} ({ticker_name}) — Bull or Bear?", ticker=ticker, data={"ticker": ticker, "is_crypto": ticker in CRYPTO}, db=db)
    db.commit()
    db.refresh(challenge)
    print(f"[DailyChallenge] Created: {ticker} @ ${open_price}")
    return challenge


def score_daily_challenge(db: Session):
    today = date.today()
    print(f"[DailyChallenge] Scoring for {today}")

    challenge = db.query(DailyChallenge).filter(DailyChallenge.status == "active").order_by(DailyChallenge.challenge_date.desc()).first()
    if not challenge:
        print("[DailyChallenge] No active challenge to score")
        return

    price = _get_price(challenge.ticker)
    if price is None:
        print(f"[DailyChallenge] No close price for {challenge.ticker}")
        return

    challenge.price_at_close = Decimal(str(price))
    open_price = float(challenge.price_at_open) if challenge.price_at_open else 0
    challenge.correct_direction = "bullish" if price >= open_price else "bearish"
    challenge.status = "completed"

    entries = db.query(DailyChallengeEntry).filter(DailyChallengeEntry.challenge_id == challenge.id).all()
    correct_count = 0
    total = len(entries)

    for entry in entries:
        entry.outcome = "correct" if entry.direction == challenge.correct_direction else "incorrect"
        if entry.outcome == "correct":
            correct_count += 1

        user = db.query(User).filter(User.id == entry.user_id).first()
        if user:
            if entry.outcome == "correct":
                user.daily_streak_current = (user.daily_streak_current or 0) + 1
                if user.daily_streak_current > (user.daily_streak_best or 0):
                    user.daily_streak_best = user.daily_streak_current
            else:
                user.daily_streak_current = 0

            pct = round(correct_count / total * 100) if total > 0 else 0
            msg = f"You got today's challenge right! {pct}% of players agreed." if entry.outcome == "correct" else f"Today's {challenge.ticker} was {challenge.correct_direction}. Better luck tomorrow!"
            create_notification(user_id=entry.user_id, type="prediction_scored", title="Daily Challenge Scored!", message=msg, data={"challenge_id": challenge.id}, db=db)

    community_acc = round(correct_count / total * 100, 1) if total > 0 else 0
    log_activity(user_id=0, event_type="daily_challenge_scored", description=f"Daily Challenge: {challenge.ticker} was {challenge.correct_direction}. {community_acc}% of {total} got it right.", ticker=challenge.ticker, data={"ticker": challenge.ticker, "correct": challenge.correct_direction, "accuracy": community_acc}, db=db)
    db.commit()
    print(f"[DailyChallenge] Scored: {challenge.ticker} = {challenge.correct_direction}, {correct_count}/{total} correct")


def ensure_daily_challenge_exists(db: Session):
    """On startup, create today's challenge if missing. Weekends get crypto."""
    today = date.today()
    now = datetime.utcnow()
    is_weekend = today.weekday() >= 5

    existing = db.query(DailyChallenge).filter(DailyChallenge.challenge_date == today).first()
    if existing:
        print(f"[DailyChallenge] Startup: exists ({existing.ticker})")
        return

    if is_weekend:
        # Weekends: always create a crypto challenge
        print("[DailyChallenge] Startup: weekend, creating crypto challenge")
        create_daily_challenge(db)
    elif now.hour >= 14 or (now.hour == 14 and now.minute >= 30):
        # Weekday after market open
        print("[DailyChallenge] Startup: weekday post-open, creating challenge")
        create_daily_challenge(db)
    else:
        print(f"[DailyChallenge] Startup: weekday pre-open, skipping")

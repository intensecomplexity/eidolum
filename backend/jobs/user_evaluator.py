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
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from sqlalchemy.orm import Session
from models import User, UserPrediction, Duel, Season, SeasonEntry
from notifications import create_notification
from activity import log_activity

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "").strip()

_price_cache: dict[str, float] = {}
_price_sources: dict[str, str] = {}

STREAK_MILESTONES = {5, 10, 15, 20}

CRYPTO_TICKERS = {"BTC": "BINANCE:BTCUSDT", "ETH": "BINANCE:ETHUSDT", "SOL": "BINANCE:SOLUSDT"}

# Thread pool for timeout-wrapping slow calls
_executor = ThreadPoolExecutor(max_workers=2)


def _fetch_price(ticker: str) -> float | None:
    """Fetch price with strict timeouts on every external call."""
    if ticker in _price_cache:
        return _price_cache[ticker]

    print(f"[UserEval] Fetching price for {ticker}...")

    # Attempt 1: Finnhub (fast, 5s timeout)
    if FINNHUB_KEY:
        symbols = [ticker]
        if ticker in CRYPTO_TICKERS:
            symbols.insert(0, CRYPTO_TICKERS[ticker])
        for sym in symbols:
            try:
                r = httpx.get(
                    "https://finnhub.io/api/v1/quote",
                    params={"symbol": sym, "token": FINNHUB_KEY},
                    timeout=5,
                )
                data = r.json()
                current = float(data.get("c", 0) or 0)
                prev_close = float(data.get("pc", 0) or 0)
                if current > 0:
                    _price_cache[ticker] = round(current, 2)
                    _price_sources[ticker] = "finnhub_current"
                    print(f"[UserEval] {ticker}: ${current} (Finnhub current)")
                    return _price_cache[ticker]
                if prev_close > 0:
                    _price_cache[ticker] = round(prev_close, 2)
                    _price_sources[ticker] = "finnhub_prev_close"
                    print(f"[UserEval] {ticker}: ${prev_close} (Finnhub prev close)")
                    return _price_cache[ticker]
                print(f"[UserEval] Finnhub returned 0 for {sym}")
            except Exception as e:
                print(f"[UserEval] Finnhub error for {sym}: {e}")
    else:
        print("[UserEval] FINNHUB_KEY not set, skipping Finnhub")

    # Attempt 2: yfinance with 10s timeout via thread pool
    try:
        def _yf_fetch():
            import yfinance as yf
            t = yf.Ticker(ticker)
            h = t.history(period="5d")
            if h is not None and not h.empty:
                return round(float(h['Close'].iloc[-1]), 2)
            return None

        future = _executor.submit(_yf_fetch)
        result = future.result(timeout=10)
        if result and result > 0:
            _price_cache[ticker] = result
            _price_sources[ticker] = "yfinance"
            print(f"[UserEval] {ticker}: ${result} (yfinance)")
            return result
    except FuturesTimeout:
        print(f"[UserEval] yfinance TIMEOUT for {ticker} (>10s)")
    except Exception as e:
        print(f"[UserEval] yfinance error for {ticker}: {e}")

    print(f"[UserEval] ALL sources failed for {ticker}")
    _price_sources[ticker] = "failed"
    return None


def _parse_target(target_str: str) -> float | None:
    try:
        return float(target_str.strip().replace("$", "").replace(",", ""))
    except (ValueError, AttributeError):
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 1. evaluate_user_predictions
# ══════════════════════════════════════════════════════════════════════════════


def evaluate_user_predictions(db: Session) -> list[dict]:
    """Score all expired user predictions. Returns list of results."""
    _price_cache.clear()
    _price_sources.clear()
    results = []
    now = datetime.utcnow()
    print(f"[UserEval] Running at {now.isoformat()}")

    overdue = (
        db.query(UserPrediction)
        .filter(
            UserPrediction.outcome == "pending",
            UserPrediction.expires_at.isnot(None),
            UserPrediction.expires_at <= now,
            UserPrediction.deleted_at.is_(None),
        )
        .all()
    )

    if not overdue:
        print("[UserEval] No expired predictions to evaluate")
        return results

    print(f"[UserEval] Found {len(overdue)} expired predictions")

    correct_count = 0
    incorrect_count = 0
    affected_user_ids = set()

    for p in overdue:
        try:
            if not p.ticker:
                continue

            price = _fetch_price(p.ticker)
            if price is None:
                print(f"[UserEval] Skipping prediction {p.id} — no price for {p.ticker}")
                continue

            entry = float(p.price_at_call) if p.price_at_call else None
            if entry is None:
                print(f"[UserEval] Skipping prediction {p.id} — no entry price")
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

            print(f"[UserEval] #{p.id}: {p.ticker} {p.direction} entry=${entry} now=${price} → {outcome}")

            results.append({
                "id": p.id, "ticker": p.ticker, "direction": p.direction,
                "outcome": outcome, "entry_price": entry, "price_used": price,
                "source": _price_sources.get(p.ticker, "unknown"),
            })

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
                    if user.streak_current in STREAK_MILESTONES:
                        create_notification(
                            user_id=p.user_id, type="streak_milestone",
                            title="Streak Milestone!",
                            message=f"You're on a {user.streak_current} prediction streak!",
                            data={"streak": user.streak_current}, db=db,
                        )
                else:
                    user.streak_current = 0

            # Notification
            if outcome == "correct":
                msg = f"Your {p.direction} call on {p.ticker} was correct! Final price: ${price}"
            else:
                msg = f"Your {p.direction} call on {p.ticker} was incorrect. Final price: ${price}"
            create_notification(
                user_id=p.user_id, type="prediction_scored",
                title="You Called It!" if outcome == "correct" else "Prediction Scored",
                message=msg,
                data={"prediction_id": p.id, "outcome": outcome, "ticker": p.ticker}, db=db,
            )

            _uname = user.username if user else "Someone"
            log_activity(
                user_id=p.user_id, event_type="prediction_scored",
                description=f"{_uname}'s {p.ticker} call was {outcome}",
                ticker=p.ticker,
                data={"prediction_id": p.id, "outcome": outcome, "ticker": p.ticker}, db=db,
            )

            _update_season_scored(p.user_id, outcome, db)

            # XP
            try:
                from xp import award_xp
                award_xp(p.user_id, "prediction_scored_correct" if outcome == "correct" else "prediction_scored_incorrect", db)
            except Exception:
                pass

            # Commit each prediction individually
            db.commit()
            print(f"[UserEval] Committed #{p.id} as {outcome}")

        except Exception as e:
            db.rollback()
            print(f"[UserEval] ERROR on prediction {p.id}: {e}")
            import traceback
            traceback.print_exc()
            continue

    total = correct_count + incorrect_count
    print(f"[UserEval] Done: {total} evaluated ({correct_count} correct, {incorrect_count} incorrect)")

    # Badge engine
    try:
        from badge_engine import evaluate_badges
        for uid in affected_user_ids:
            evaluate_badges(uid, db)
    except Exception as e:
        print(f"[UserEval] Badge engine error: {e}")

    # Rival checks
    try:
        from rivals import check_rival_changes
        for uid in affected_user_ids:
            check_rival_changes(uid, db)
        db.commit()
    except Exception as e:
        print(f"[UserEval] Rival check error: {e}")

    return results


def _update_season_scored(user_id: int, outcome: str, db: Session):
    """Credit the season that covers the current scoring time."""
    now = datetime.utcnow()
    season = (
        db.query(Season)
        .filter(Season.starts_at <= now, Season.ends_at > now)
        .first()
    )
    if not season:
        # Fallback to active season
        season = db.query(Season).filter(Season.status == "active").first()
    if not season:
        return
    entry = (
        db.query(SeasonEntry)
        .filter(SeasonEntry.season_id == season.id, SeasonEntry.user_id == user_id)
        .first()
    )
    if not entry:
        entry = SeasonEntry(season_id=season.id, user_id=user_id)
        db.add(entry)
    entry.predictions_scored = (entry.predictions_scored or 0) + 1
    if outcome == "correct":
        entry.predictions_correct = (entry.predictions_correct or 0) + 1


# ══════════════════════════════════════════════════════════════════════════════
# 2. evaluate_duels
# ══════════════════════════════════════════════════════════════════════════════


def evaluate_duels(db: Session):
    now = datetime.utcnow()
    print(f"[DuelEval] Running at {now.isoformat()}")

    overdue = (
        db.query(Duel)
        .filter(
            Duel.status == "active",
            Duel.expires_at.isnot(None),
            Duel.expires_at <= now,
        )
        .all()
    )

    if not overdue:
        print("[DuelEval] No expired duels")
        return

    evaluated = 0

    for duel in overdue:
        price = _fetch_price(duel.ticker)
        if price is None:
            continue

        start_price = float(duel.price_at_start) if duel.price_at_start else None
        if start_price is None:
            continue

        c_target = _parse_target(duel.challenger_target)
        o_target = _parse_target(duel.opponent_target) if duel.opponent_target else None

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

        challenger = db.query(User).filter(User.id == duel.challenger_id).first()
        opponent = db.query(User).filter(User.id == duel.opponent_id).first()
        c_name = challenger.username if challenger else "Unknown"
        o_name = opponent.username if opponent else "Unknown"

        for uid, is_winner in [(duel.challenger_id, winner_id == duel.challenger_id), (duel.opponent_id, winner_id == duel.opponent_id)]:
            other_name = o_name if uid == duel.challenger_id else c_name
            msg = f"You won the {duel.ticker} duel against {other_name}!" if is_winner else f"You lost the {duel.ticker} duel against {other_name}"
            create_notification(
                user_id=uid, type="duel_result",
                title="Duel Complete!",
                message=msg,
                data={"duel_id": duel.id, "result": "won" if is_winner else "lost"}, db=db,
            )

        winner_name = c_name if winner_id == duel.challenger_id else o_name
        loser_name = o_name if winner_id == duel.challenger_id else c_name
        log_activity(
            user_id=winner_id, event_type="duel_completed",
            description=f"{winner_name} won the {duel.ticker} duel against {loser_name}",
            ticker=duel.ticker,
            data={"duel_id": duel.id, "winner": winner_name, "loser": loser_name}, db=db,
        )

        try:
            from xp import award_xp
            award_xp(winner_id, "duel_won", db)
        except Exception:
            pass

    db.commit()
    print(f"[DuelEval] Evaluated {evaluated} duels")


# ══════════════════════════════════════════════════════════════════════════════
# 3. check_season_completion
# ══════════════════════════════════════════════════════════════════════════════


def check_season_completion(db: Session):
    now = datetime.utcnow()
    seasons = db.query(Season).filter(Season.status == "active", Season.ends_at <= now).all()
    for season in seasons:
        season.status = "completed"
        print(f"[SeasonCheck] Season {season.id} ({season.name}) completed")
    if seasons:
        db.commit()

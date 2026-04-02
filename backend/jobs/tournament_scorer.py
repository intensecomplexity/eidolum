"""
Tournament scoring job — scores all picks in active tournaments.
Runs daily during active tournaments via scheduler.
Uses the same three-tier system: HIT (1.0) / NEAR (0.5) / MISS (0).
"""
import json
import os
from datetime import datetime, timedelta
from sqlalchemy import text as sql_text

from jobs.historical_evaluator import _get_tolerance, _TOLERANCE, _MIN_MOVEMENT

TIINGO_KEY = os.getenv("TIINGO_API_KEY", "").strip()


def _get_price(ticker: str) -> float | None:
    """Get current price for a ticker."""
    if TIINGO_KEY:
        import httpx
        try:
            r = httpx.get(
                f"https://api.tiingo.com/iex/{ticker}",
                params={"token": TIINGO_KEY},
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and data:
                    return float(data[0].get("last") or data[0].get("tngoLast") or 0)
        except Exception:
            pass
    # Fallback to Finnhub
    finnhub_key = os.getenv("FINNHUB_KEY", "").strip()
    if finnhub_key:
        import httpx
        try:
            r = httpx.get("https://finnhub.io/api/v1/quote",
                          params={"symbol": ticker, "token": finnhub_key}, timeout=8)
            c = r.json().get("c")
            if c and float(c) > 0:
                return float(c)
        except Exception:
            pass
    return None


def score_picks(picks: list, start_prices: dict, current_prices: dict, window_days: int = 7) -> dict:
    """Score a set of picks. Returns {score, hits, nears, misses, total_return, details}."""
    hits = nears = misses = 0
    total_return = 0
    details = []
    tolerance = _get_tolerance(window_days, _TOLERANCE)
    min_movement = _get_tolerance(window_days, _MIN_MOVEMENT)

    for pick in picks:
        ticker = pick.get("ticker", "").upper()
        direction = pick.get("direction", "bullish")
        target = pick.get("target_price")
        if target:
            try:
                target = float(target)
            except (ValueError, TypeError):
                target = None

        entry = start_prices.get(ticker)
        current = current_prices.get(ticker)

        if not entry or not current:
            details.append({"ticker": ticker, "outcome": "pending", "return_pct": 0})
            continue

        raw_move = round(((current - entry) / entry) * 100, 2)

        if direction == "neutral":
            abs_ret = abs(raw_move)
            outcome = "hit" if abs_ret <= 5.0 else "near" if abs_ret <= 10.0 else "miss"
        elif target and target > 0:
            target_dist = abs(current - target) / target * 100
            if direction == "bullish":
                outcome = "hit" if (current >= target or target_dist <= tolerance) else "near" if raw_move >= min_movement else "miss"
            else:
                outcome = "hit" if (current <= target or target_dist <= tolerance) else "near" if raw_move <= -min_movement else "miss"
        else:
            if direction == "bullish":
                outcome = "hit" if raw_move > 0 else "miss"
            else:
                outcome = "hit" if raw_move < 0 else "miss"

        if outcome == "hit":
            hits += 1
        elif outcome == "near":
            nears += 1
        else:
            misses += 1

        total_return += raw_move if direction == "bullish" else -raw_move
        details.append({"ticker": ticker, "outcome": outcome, "return_pct": raw_move})

    score = hits * 1.0 + nears * 0.5
    return {"score": score, "hits": hits, "nears": nears, "misses": misses,
            "total_return": round(total_return, 2), "details": details}


def update_live_scores(db):
    """Update running scores for all active tournaments. Called by scheduler."""
    import time

    active = db.execute(sql_text(
        "SELECT id, start_date, end_date FROM tournaments WHERE status = 'active'"
    )).fetchall()

    if not active:
        return

    for tournament in active:
        tid = tournament[0]
        entries = db.execute(sql_text(
            "SELECT id, user_id, picks FROM tournament_entries WHERE tournament_id = :tid"
        ), {"tid": tid}).fetchall()

        if not entries:
            continue

        # Collect all tickers
        all_tickers = set()
        for entry in entries:
            picks = json.loads(entry[2]) if entry[2] else []
            for p in picks:
                all_tickers.add(p.get("ticker", "").upper())

        # Fetch current prices
        prices = {}
        for ticker in all_tickers:
            price = _get_price(ticker)
            if price:
                prices[ticker] = price
            time.sleep(0.3)

        # Use start_date prices as entry prices (simplified: use current for now)
        # In production, you'd fetch historical prices at start_date
        start_prices = prices  # TODO: fetch historical start_date prices

        # Score each entry
        for entry in entries:
            picks = json.loads(entry[2]) if entry[2] else []
            result = score_picks(picks, start_prices, prices)

            # Upsert result
            existing = db.execute(sql_text(
                "SELECT 1 FROM tournament_results WHERE tournament_id = :tid AND user_id = :uid"
            ), {"tid": tid, "uid": entry[1]}).first()

            if existing:
                db.execute(sql_text("""
                    UPDATE tournament_results SET score=:s, hits=:h, nears=:n, misses=:m
                    WHERE tournament_id=:tid AND user_id=:uid
                """), {"s": result["score"], "h": result["hits"], "n": result["nears"],
                       "m": result["misses"], "tid": tid, "uid": entry[1]})
            else:
                db.execute(sql_text("""
                    INSERT INTO tournament_results (tournament_id, user_id, score, hits, nears, misses)
                    VALUES (:tid, :uid, :s, :h, :n, :m)
                """), {"tid": tid, "uid": entry[1], "s": result["score"],
                       "h": result["hits"], "n": result["nears"], "m": result["misses"]})

        db.commit()
        print(f"[Tournament] Scored {len(entries)} entries for tournament {tid}")


def score_tournament(tournament_id: int, db) -> dict:
    """Finalize a tournament: score, rank, award badges."""
    # Update status
    db.execute(sql_text("UPDATE tournaments SET status = 'completed' WHERE id = :tid"), {"tid": tournament_id})

    # Get all results ordered by score
    results = db.execute(sql_text("""
        SELECT tr.user_id, tr.score FROM tournament_results
        WHERE tr.tournament_id = :tid ORDER BY tr.score DESC
    """), {"tid": tournament_id}).fetchall()

    # Assign ranks and badges
    badges = {1: "tournament_gold", 2: "tournament_silver", 3: "tournament_bronze"}
    for i, r in enumerate(results):
        rank = i + 1
        badge = badges.get(rank)
        db.execute(sql_text("""
            UPDATE tournament_results SET rank = :rank, prize_badge = :badge
            WHERE tournament_id = :tid AND user_id = :uid
        """), {"rank": rank, "badge": badge, "tid": tournament_id, "uid": r[0]})

    db.commit()
    return {"status": "finalized", "participants": len(results),
            "winner": results[0][0] if results else None}

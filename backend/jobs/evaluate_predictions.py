"""
Prediction evaluator — checks pending predictions against actual stock prices.
Uses Finnhub API for prices (yfinance blocked on Railway).
"""


def evaluate_all_pending(db):
    """Evaluate pending predictions using Finnhub API for stock prices."""
    import os
    import httpx
    import time
    from datetime import datetime
    from models import Prediction

    FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")
    if not FINNHUB_KEY:
        print("[Evaluator] No FINNHUB_KEY — cannot evaluate")
        return

    pending = db.query(Prediction).filter(
        Prediction.outcome == "pending",
        Prediction.ticker.isnot(None),
    ).limit(500).all()

    if not pending:
        print("[Evaluator] No pending predictions")
        return

    print(f"[Evaluator] Evaluating {len(pending)} predictions using Finnhub...")
    evaluated = 0
    errors = 0
    price_cache = {}

    for p in pending:
        try:
            ticker = (p.ticker or "").upper().strip()
            if not ticker or len(ticker) > 6:
                continue

            if ticker not in price_cache:
                try:
                    r = httpx.get(
                        "https://finnhub.io/api/v1/quote",
                        params={"symbol": ticker, "token": FINNHUB_KEY},
                        timeout=10,
                    )
                    data = r.json()
                    current = data.get("c", 0)
                    prev_close = data.get("pc", 0)
                    open_price = data.get("o", 0)

                    if current and current > 0:
                        price_cache[ticker] = {
                            "current": current,
                            "prev_close": prev_close,
                            "open": open_price,
                        }
                        print(f"[Evaluator] {ticker}: current=${current}, prev_close=${prev_close}")
                    else:
                        print(f"[Evaluator] {ticker}: no price data from Finnhub: {data}")
                        price_cache[ticker] = None

                    time.sleep(1.1)
                except Exception as e:
                    print(f"[Evaluator] Finnhub error for {ticker}: {e}")
                    price_cache[ticker] = None
                    errors += 1
                    continue

            prices = price_cache.get(ticker)
            if not prices:
                continue

            current_price = prices["current"]
            entry_price = prices["prev_close"] or prices["open"]

            if not entry_price or entry_price == 0:
                continue

            direction = (p.direction or "bullish").lower()
            if direction in ("bear", "bearish"):
                outcome = "correct" if current_price <= entry_price else "incorrect"
            else:
                outcome = "correct" if current_price >= entry_price else "incorrect"

            pct_return = round(((current_price - entry_price) / entry_price) * 100, 2)
            if direction in ("bear", "bearish"):
                pct_return = -pct_return

            p.outcome = outcome
            p.entry_price = entry_price
            p.actual_return = pct_return
            p.alpha = pct_return
            evaluated += 1

            if evaluated % 50 == 0:
                db.commit()
                print(f"[Evaluator] Committed {evaluated}...")

        except Exception as e:
            print(f"[Evaluator] Error on {p.id}: {e}")
            errors += 1

    db.commit()
    print(f"[Evaluator] Done: evaluated {evaluated}, errors {errors}")

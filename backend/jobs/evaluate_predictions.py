"""
Prediction evaluator — checks pending predictions against actual stock prices.
Uses yfinance (free, no API key). Uses latest available market data.
"""


def evaluate_all_pending(db):
    """Evaluate pending predictions using latest available market data."""
    import yfinance as yf
    import time
    from datetime import datetime, timedelta
    from models import Prediction

    pending = db.query(Prediction).filter(
        Prediction.outcome == "pending",
        Prediction.ticker.isnot(None),
    ).limit(500).all()

    if not pending:
        print("[Evaluator] No pending predictions to evaluate")
        return

    print(f"[Evaluator] Evaluating {len(pending)} pending predictions...")
    evaluated = 0
    errors = 0

    # Cache ticker data to avoid repeated API calls
    ticker_cache = {}

    for p in pending:
        try:
            ticker = (p.ticker or "").upper().strip()
            if not ticker or len(ticker) > 6:
                continue

            if ticker not in ticker_cache:
                try:
                    stock = yf.Ticker(ticker)
                    hist = stock.history(period="3mo")
                    if hist.empty:
                        hist = stock.history(period="6mo")
                    if hist.empty:
                        print(f"[Evaluator] No data at all for {ticker}")
                        ticker_cache[ticker] = None
                        continue
                    ticker_cache[ticker] = hist
                    time.sleep(0.3)
                except Exception as e:
                    print(f"[Evaluator] yfinance error for {ticker}: {e}")
                    ticker_cache[ticker] = None
                    errors += 1
                    continue

            hist = ticker_cache[ticker]
            if hist is None:
                continue

            entry_price = float(hist["Close"].iloc[0])
            current_price = float(hist["Close"].iloc[-1])

            if entry_price == 0:
                continue

            direction = (p.direction or "bullish").lower()
            if direction in ("bear", "bearish"):
                outcome = "correct" if current_price < entry_price else "incorrect"
            else:
                outcome = "correct" if current_price > entry_price else "incorrect"

            pct_return = round(((current_price - entry_price) / entry_price) * 100, 2)
            if direction in ("bear", "bearish"):
                pct_return = -pct_return

            p.outcome = outcome
            p.entry_price = entry_price
            p.actual_return = pct_return
            p.alpha = pct_return

            evaluated += 1

            if evaluated <= 20:
                print(f"[Evaluator] {ticker} ({direction}): ${entry_price:.2f} -> ${current_price:.2f} ({pct_return:+.1f}%) = {outcome}")

            if evaluated % 50 == 0:
                db.commit()
                print(f"[Evaluator] Committed {evaluated} so far...")

        except Exception as e:
            print(f"[Evaluator] Error on prediction {p.id}: {e}")
            errors += 1
            continue

    db.commit()
    print(f"[Evaluator] Done: evaluated {evaluated}, errors {errors}")

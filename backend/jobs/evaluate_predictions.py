"""
Prediction evaluator — checks pending predictions against actual stock prices.
Uses yfinance (free, no API key). Runs every hour.
"""


def evaluate_all_pending(db):
    """Evaluate all pending predictions by checking actual stock prices via yfinance."""
    import yfinance as yf
    import time
    from datetime import datetime, timedelta
    from models import Prediction

    one_day_ago = datetime.utcnow() - timedelta(days=1)

    pending = db.query(Prediction).filter(
        Prediction.outcome == "pending",
        Prediction.ticker.isnot(None),
        Prediction.prediction_date < one_day_ago,
    ).limit(500).all()

    if not pending:
        print("[Evaluator] No pending predictions to evaluate")
        return

    print(f"[Evaluator] Evaluating {len(pending)} pending predictions...")
    evaluated = 0
    errors = 0

    for p in pending:
        try:
            ticker = (p.ticker or "").upper().strip()
            if not ticker or len(ticker) > 6:
                continue

            pred_date = p.prediction_date
            if not pred_date:
                continue

            stock = yf.Ticker(ticker)

            # Get price around prediction date
            start = pred_date - timedelta(days=7)
            end = pred_date + timedelta(days=7)
            hist = stock.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))

            if hist.empty:
                print(f"[Evaluator] No price data for {ticker} around {pred_date.date()}")
                errors += 1
                continue

            entry_price = float(hist["Close"].iloc[min(len(hist) // 2, len(hist) - 1)])

            # Get current price
            current_hist = stock.history(period="5d")
            if current_hist.empty:
                print(f"[Evaluator] No current price for {ticker}")
                errors += 1
                continue
            current_price = float(current_hist["Close"].iloc[-1])

            # Determine outcome
            direction = (p.direction or "bullish").lower()
            if direction in ("bear", "bearish"):
                outcome = "correct" if current_price < entry_price else "incorrect"
            else:
                outcome = "correct" if current_price > entry_price else "incorrect"

            # Calculate return
            pct_return = round(((current_price - entry_price) / entry_price) * 100, 2)
            if direction in ("bear", "bearish"):
                pct_return = -pct_return

            # Update prediction
            p.outcome = outcome
            p.entry_price = entry_price
            p.actual_return = pct_return
            p.alpha = pct_return

            evaluated += 1
            print(f"[Evaluator] {ticker} ({direction}): ${entry_price:.2f} -> ${current_price:.2f} ({pct_return:+.1f}%) = {outcome}")

            if evaluated % 10 == 0:
                db.commit()

            time.sleep(0.3)

        except Exception as e:
            print(f"[Evaluator] Error on prediction {p.id} ({p.ticker}): {e}")
            errors += 1
            continue

    db.commit()
    print(f"[Evaluator] Done: evaluated {evaluated}, errors {errors}, total pending was {len(pending)}")

"""
Prediction evaluator — checks pending predictions against actual stock prices.
Uses yfinance (free, no API key). Runs every hour.
"""
import time
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import Prediction
from jobs.price_checker import get_stock_price_on_date, get_current_price


def evaluate_all_pending(db: Session):
    """Evaluate pending predictions by checking actual stock prices."""
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
    skipped_no_entry = 0
    skipped_no_final = 0
    skipped_unknown = 0

    for p in pending:
        try:
            ticker = (p.ticker or "").upper().strip()
            if not ticker or ticker == "UNKNOWN":
                skipped_unknown += 1
                continue

            pred_date_str = p.prediction_date.strftime("%Y-%m-%d") if p.prediction_date else None
            if not pred_date_str:
                continue

            entry_price = p.entry_price or get_stock_price_on_date(ticker, pred_date_str)
            if not entry_price:
                skipped_no_entry += 1
                print(f"[Evaluator] No entry price for {ticker} on {pred_date_str}")
                continue

            eval_date = p.prediction_date + timedelta(days=p.window_days or 365)
            now = datetime.utcnow()

            if now >= eval_date:
                eval_date_str = eval_date.strftime("%Y-%m-%d")
                final_price = get_stock_price_on_date(ticker, eval_date_str)
                if not final_price:
                    print(f"[Evaluator] No eval-date price for {ticker} on {eval_date_str}")
            else:
                final_price = get_current_price(ticker)
                if not final_price:
                    print(f"[Evaluator] No current price for {ticker}")

            if not final_price:
                skipped_no_final += 1
                continue

            # Determine outcome
            direction = (p.direction or "bullish").lower()
            if direction in ("bull", "bullish"):
                if p.target_price:
                    outcome = "correct" if final_price >= p.target_price else "incorrect"
                else:
                    outcome = "correct" if final_price > entry_price else "incorrect"
            elif direction in ("bear", "bearish"):
                if p.target_price:
                    outcome = "correct" if final_price <= p.target_price else "incorrect"
                else:
                    outcome = "correct" if final_price < entry_price else "incorrect"
            else:
                continue

            pct_return = round(((final_price - entry_price) / entry_price) * 100, 2)
            if direction in ("bear", "bearish"):
                pct_return = -pct_return

            p.outcome = outcome
            if not p.entry_price:
                p.entry_price = entry_price
            p.actual_return = pct_return
            p.evaluation_date = datetime.utcnow()
            p.alpha = pct_return
            db.commit()
            evaluated += 1

            print(f"[Evaluator] {ticker} ({direction}): ${entry_price} -> ${final_price} ({pct_return:+.1f}%) = {outcome}")
            time.sleep(0.3)

        except Exception as e:
            print(f"[Evaluator] Error for prediction {p.id} ({p.ticker}): {e}")
            db.rollback()

    print(f"[Evaluator] Done: {evaluated} evaluated, {skipped_unknown} unknown ticker, {skipped_no_entry} no entry price, {skipped_no_final} no final price")

import datetime
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Forecaster, Prediction
from utils import compute_forecaster_stats

router = APIRouter()


def _build_signals(db: Session, ticker_filter: str = None):
    """Build contrarian signals from prediction consensus data."""
    predictions = db.query(Prediction).all()
    forecasters_map = {f.id: f for f in db.query(Forecaster).all()}
    acc_cache = {}

    def get_acc(fid):
        if fid not in acc_cache:
            f = forecasters_map.get(fid)
            if f:
                s = compute_forecaster_stats(f, db)
                acc_cache[fid] = s["accuracy_rate"]
            else:
                acc_cache[fid] = 0
        return acc_cache[fid]

    # Group by ticker
    ticker_sides = defaultdict(lambda: {"bullish": set(), "bearish": set()})
    for p in predictions:
        ticker_sides[p.ticker][p.direction].add(p.forecaster_id)

    signals = []
    for ticker, sides in ticker_sides.items():
        if ticker_filter and ticker != ticker_filter:
            continue
        bull_count = len(sides["bullish"])
        bear_count = len(sides["bearish"])
        total = bull_count + bear_count
        if total < 5:
            continue

        consensus_pct = round(max(bull_count, bear_count) / total * 100, 1)
        if consensus_pct < 75:
            continue

        direction = "bullish" if bull_count > bear_count else "bearish"
        contrarian_direction = "bearish" if direction == "bullish" else "bullish"

        # Top forecasters on each side
        bull_list = sorted(
            [{"id": fid, "name": forecasters_map[fid].name, "accuracy": get_acc(fid)}
             for fid in sides["bullish"] if fid in forecasters_map],
            key=lambda x: x["accuracy"], reverse=True
        )
        bear_list = sorted(
            [{"id": fid, "name": forecasters_map[fid].name, "accuracy": get_acc(fid)}
             for fid in sides["bearish"] if fid in forecasters_map],
            key=lambda x: x["accuracy"], reverse=True
        )

        signals.append({
            "ticker": ticker,
            "consensus_pct": consensus_pct,
            "direction": direction,
            "contrarian_direction": contrarian_direction,
            "bull_count": bull_count,
            "bear_count": bear_count,
            "total_predictions": total,
            "top_bulls": bull_list[:3],
            "top_bears": bear_list[:3],
            "historical_note": (
                f"When 75%+ of tracked investors agree on a stock, "
                f"it has underperformed the S&P 500 in 61% of cases historically."
            ),
        })

    signals.sort(key=lambda x: x["consensus_pct"], reverse=True)
    return signals


@router.get("/contrarian-signals")
def get_contrarian_signals(db: Session = Depends(get_db)):
    """Return top contrarian signals — tickers with 75%+ consensus."""
    return _build_signals(db)[:5]


@router.get("/contrarian-signals/{ticker}")
def get_contrarian_signal_for_ticker(ticker: str, db: Session = Depends(get_db)):
    """Return contrarian signal for a specific ticker."""
    signals = _build_signals(db, ticker_filter=ticker.upper())
    if not signals:
        return None
    return signals[0]

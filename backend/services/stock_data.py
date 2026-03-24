"""
Fetch historical stock prices via yfinance and evaluate prediction outcomes.
"""
import datetime
from typing import Optional

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False


def get_price_at_date(ticker: str, date: datetime.datetime) -> Optional[float]:
    """Return closing price for ticker on the closest trading day to `date`."""
    if not YFINANCE_AVAILABLE:
        return None
    try:
        start = date - datetime.timedelta(days=5)
        end = date + datetime.timedelta(days=5)
        df = yf.download(ticker, start=start.strftime("%Y-%m-%d"),
                         end=end.strftime("%Y-%m-%d"), progress=False, auto_adjust=True)
        if df.empty:
            return None
        # Closest row to requested date
        df = df.sort_index()
        target_ts = date.timestamp()
        closest = min(df.index, key=lambda t: abs(t.timestamp() - target_ts))
        return float(df.loc[closest]["Close"])
    except Exception:
        return None


def get_return_pct(ticker: str, start_date: datetime.datetime, end_date: datetime.datetime) -> Optional[float]:
    """Return percentage price change for ticker between two dates."""
    p_start = get_price_at_date(ticker, start_date)
    p_end = get_price_at_date(ticker, end_date)
    if p_start and p_end and p_start != 0:
        return round((p_end - p_start) / p_start * 100, 2)
    return None


def get_sp500_return(start_date: datetime.datetime, end_date: datetime.datetime) -> Optional[float]:
    return get_return_pct("SPY", start_date, end_date)


def evaluate_prediction(direction: str, actual_return: float) -> str:
    """Determine if a prediction was correct given the actual return."""
    if direction == "bullish":
        return "correct" if actual_return > 0 else "incorrect"
    elif direction == "bearish":
        return "correct" if actual_return < 0 else "incorrect"
    return "pending"

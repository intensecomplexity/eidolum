"""
Stock price fetcher using yfinance — completely free, no API key needed.
"""
import yfinance as yf
from datetime import datetime, timedelta
from functools import lru_cache


@lru_cache(maxsize=500)
def get_stock_price_on_date(ticker: str, date_str: str) -> float | None:
    """Get the closing price of a stock on a specific date."""
    try:
        stock = yf.Ticker(ticker)
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
        start = target_date - timedelta(days=5)
        end = target_date + timedelta(days=5)
        hist = stock.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
        if hist.empty:
            return None
        closest = hist.index[hist.index.get_indexer([target_date], method="nearest")[0]]
        return round(float(hist.loc[closest]["Close"]), 2)
    except Exception as e:
        print(f"[PriceChecker] Error fetching {ticker} on {date_str}: {e}")
        return None


def get_current_price(ticker: str) -> float | None:
    """Get the current/latest closing price."""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d")
        if hist.empty:
            return None
        return round(float(hist["Close"].iloc[-1]), 2)
    except Exception as e:
        print(f"[PriceChecker] Error fetching current price for {ticker}: {e}")
        return None

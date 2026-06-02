"""
Stock price fetcher using yfinance — completely free, no API key needed.

Write-through layer (2026-06-02): price_bars is the L2 cache. On Railway,
yfinance is blocked at egress (reference_eidolum_yfinance_blocked memory)
so this entire function effectively fails up there. Hitting price_bars
first lets the Railway evaluator's no_data-retry path succeed for any
ticker whose history we already harvested locally — which is most of
them (20M bars across 10,747 tickers as of the Phase 4 harvest).
"""
import yfinance as yf
from datetime import datetime, timedelta
from functools import lru_cache


@lru_cache(maxsize=500)
def get_stock_price_on_date(ticker: str, date_str: str) -> float | None:
    """Get the closing price of a stock on a specific date.

    L1 = lru_cache (in-process, 500 entries).
    L2 = price_bars (free, fast, indexed PK lookup).
    L3 = yfinance live (blocked on Railway egress; LOCAL only).
    """
    # L2: price_bars
    try:
        from services.price_store import get_close as _local_close, persist_bar as _local_persist
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        hit = _local_close(ticker, target_date)
        if hit is not None:
            return round(float(hit), 2)
    except Exception:
        _local_persist = None  # so the post-fetch persist branch can no-op

    # L3: yfinance live
    try:
        stock = yf.Ticker(ticker)
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
        start = target_date - timedelta(days=5)
        end = target_date + timedelta(days=5)
        hist = stock.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
        if hist.empty:
            return None
        closest = hist.index[hist.index.get_indexer([target_date], method="nearest")[0]]
        close = round(float(hist.loc[closest]["Close"]), 2)
        # Write-through to price_bars
        if _local_persist is not None:
            try:
                _local_persist(ticker, closest.date(), close, source="yfinance_live")
            except Exception:
                pass
        return close
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

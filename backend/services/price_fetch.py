"""
Crypto-aware price fetching for prediction evaluation.

The historical evaluator's `_fetch_history` was equity-only and silently
fell through to the equity ticker for crypto symbols whose letters
collide with a real US stock ticker (BTC the biotech, ETH the obscure
ETF, etc.). That collision corrupted every crypto prediction we tried
to lock — Stock Moe's vault and ~6 of Marko's 13 scored predictions
were all running off equity prices.

This module makes the resolution explicit:

  - `is_crypto(ticker)` is the single source of truth for "this is a
    crypto ticker, never let it fall through to an equity fetcher".
  - `polygon_crypto_history(ticker)` hits Polygon's X:{SYMBOL}USD
    daily-aggregates endpoint, which is the right source for spot
    crypto price history.
  - `fetch_crypto_history(ticker)` returns the {date_str: close} dict
    shape the historical evaluator expects so it can drop straight
    into the existing `_fetch_history` plumbing.

This module is intentionally narrow — it does NOT replace the equity
price fetchers in historical_evaluator.py / retry_no_data.py. Those
keep their FMP / Tiingo / Polygon equity chain. The crypto branch
just gets routed here BEFORE the equity fetchers see the ticker.
"""
import os
from datetime import datetime, timedelta

import httpx

from crypto_prices import CRYPTO_TICKERS, is_crypto

POLYGON_KEY = os.getenv("MASSIVE_API_KEY", "").strip()
TIINGO_KEY = os.getenv("TIINGO_API_KEY", "").strip()

# Process-wide cache so a single batch run only hits Polygon once per
# crypto ticker. Same shape (and same lifetime semantics) as
# historical_evaluator._history_cache.
_crypto_history_cache: dict[str, dict] = {}


def polygon_crypto_symbol(ticker: str) -> str:
    """Map a bare crypto ticker (BTC, ETH) to its Polygon symbol (X:BTCUSD)."""
    return f"X:{ticker.upper()}USD"


def polygon_crypto_history(ticker: str, days: int = 730) -> dict:
    """Fetch daily close history for a crypto ticker from Polygon.

    Returns {date_str: close_price}. Empty dict on any failure or when
    the Polygon key is unset (production has it; local dev usually
    does not, which is fine — the caller falls back to no_data).
    """
    if not POLYGON_KEY:
        return {}
    sym = polygon_crypto_symbol(ticker)
    end = datetime.utcnow().date()
    start = end - timedelta(days=days)
    try:
        r = httpx.get(
            f"https://api.polygon.io/v2/aggs/ticker/{sym}/range/1/day/{start}/{end}",
            params={"adjusted": "true", "sort": "asc", "limit": "5000", "apiKey": POLYGON_KEY},
            timeout=15,
        )
        if r.status_code != 200:
            return {}
        prices: dict[str, float] = {}
        for bar in (r.json().get("results") or []):
            ts_ms = bar.get("t")
            close = bar.get("c")
            if ts_ms and close and float(close) > 0:
                ds = datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
                prices[ds] = round(float(close), 2)
        return prices
    except Exception:
        return {}


def tiingo_crypto_history(ticker: str, days: int = 1825) -> dict:
    """Fetch daily close history for a crypto ticker from Tiingo.

    Fallback for when Polygon rejects the MASSIVE_API_KEY (verified 401
    "Unknown API Key" from inside the worker pod on 2026-04-12). Tiingo
    crypto is free and returns the same daily close shape we need.
    Returns {date_str: close_price} or {} on any failure.
    """
    if not TIINGO_KEY:
        return {}
    sym = f"{ticker.lower()}usd"
    end = datetime.utcnow().date()
    start = end - timedelta(days=days)
    try:
        r = httpx.get(
            "https://api.tiingo.com/tiingo/crypto/prices",
            params={
                "tickers": sym,
                "startDate": str(start),
                "endDate": str(end),
                "resampleFreq": "1day",
                "token": TIINGO_KEY,
            },
            timeout=20,
        )
        if r.status_code != 200:
            return {}
        payload = r.json()
        if not payload:
            return {}
        price_data = payload[0].get("priceData") or []
        prices: dict[str, float] = {}
        for bar in price_data:
            date_iso = bar.get("date", "")
            close = bar.get("close")
            if date_iso and close and float(close) > 0:
                prices[date_iso[:10]] = round(float(close), 2)
        return prices
    except Exception:
        return {}


def fetch_crypto_history(ticker: str) -> dict:
    """Cached wrapper: try Polygon first, fall back to Tiingo on empty.
    Returns {} for non-crypto tickers so callers can use this as a
    guarded short-circuit in front of an equity fetcher chain."""
    if not is_crypto(ticker):
        return {}
    sym = ticker.upper()
    if sym in _crypto_history_cache:
        return _crypto_history_cache[sym]
    prices = polygon_crypto_history(sym)
    if not prices:
        prices = tiingo_crypto_history(sym)
    if prices:
        _crypto_history_cache[sym] = prices
    return prices


def clear_crypto_cache() -> None:
    """Match the symmetric end-of-batch cache clear in historical_evaluator."""
    _crypto_history_cache.clear()


__all__ = [
    "CRYPTO_TICKERS",
    "is_crypto",
    "polygon_crypto_symbol",
    "polygon_crypto_history",
    "tiingo_crypto_history",
    "fetch_crypto_history",
    "clear_crypto_cache",
]

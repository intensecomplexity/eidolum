"""
Crypto price lookup using CoinGecko (free, no API key needed).
Detects crypto tickers and maps them to CoinGecko IDs.
"""
import time
import httpx

# Crypto ticker → CoinGecko ID mapping
CRYPTO_TICKERS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "XRP": "ripple",
    "BNB": "binancecoin",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "LTC": "litecoin",
    "NEAR": "near",
    "APT": "aptos",
    "ARB": "arbitrum",
    "OP": "optimism",
    "FIL": "filecoin",
    "SHIB": "shiba-inu",
    "TRX": "tron",
    "XLM": "stellar",
    "ALGO": "algorand",
    "HBAR": "hedera-hashgraph",
    "BCH": "bitcoin-cash",
    "SAND": "the-sandbox",
}

# Canonical human-readable name for every crypto ticker we recognize.
# Used at API-serialization time to override ticker_sectors.company_name
# when a ticker letter collides with a real US equity (LTC/SOL/LINK/etc.).
# The evaluator already prices these as crypto (services/price_fetch.py);
# this dict aligns the user-facing label with the pricing reality.
CRYPTO_NAMES = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "SOL": "Solana",
    "XRP": "XRP",
    "LTC": "Litecoin",
    "LINK": "Chainlink",
    "DOGE": "Dogecoin",
    "ADA": "Cardano",
    "DOT": "Polkadot",
    "AVAX": "Avalanche",
    "UNI": "Uniswap",
    "ATOM": "Cosmos",
    "NEAR": "NEAR Protocol",
    "SHIB": "Shiba Inu",
    "TRX": "Tron",
    "XLM": "Stellar",
    "ALGO": "Algorand",
    "HBAR": "Hedera",
    "BCH": "Bitcoin Cash",
    "SAND": "The Sandbox",
    "BNB": "BNB",
    "MATIC": "Polygon",
    "APT": "Aptos",
    "ARB": "Arbitrum",
    "OP": "Optimism",
    "FIL": "Filecoin",
}

# Cache: {ticker: (price, timestamp)}
_crypto_cache: dict[str, tuple[float, float]] = {}
_CACHE_TTL = 300  # 5 minutes


def is_crypto(ticker: str) -> bool:
    return ticker.upper() in CRYPTO_TICKERS


def get_crypto_display_name(ticker: str) -> str | None:
    """Return the canonical crypto display name for a ticker, or None
    if the ticker isn't on the crypto allowlist."""
    if not ticker:
        return None
    return CRYPTO_NAMES.get(ticker.upper())


def get_crypto_price(ticker: str) -> float | None:
    """Get current crypto price from CoinGecko. Cached for 5 minutes."""
    ticker = ticker.upper()
    if ticker not in CRYPTO_TICKERS:
        return None

    now = time.time()
    cached = _crypto_cache.get(ticker)
    if cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]

    coin_id = CRYPTO_TICKERS[ticker]
    try:
        r = httpx.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": coin_id, "vs_currencies": "usd", "include_24hr_change": "true"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            coin_data = data.get(coin_id, {})
            price = coin_data.get("usd")
            if price and price > 0:
                _crypto_cache[ticker] = (round(float(price), 2), now)
                return round(float(price), 2)
    except Exception:
        pass

    return None


def get_crypto_price_data(ticker: str) -> dict | None:
    """Get crypto price with 24h change data. For ticker detail endpoints."""
    ticker = ticker.upper()
    if ticker not in CRYPTO_TICKERS:
        return None

    now = time.time()
    coin_id = CRYPTO_TICKERS[ticker]
    try:
        r = httpx.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": coin_id, "vs_currencies": "usd", "include_24hr_change": "true"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            coin_data = data.get(coin_id, {})
            price = coin_data.get("usd")
            change_pct = coin_data.get("usd_24h_change")
            if price and price > 0:
                price = round(float(price), 2)
                pct = round(float(change_pct), 2) if change_pct else 0
                change = round(price * pct / 100, 2)
                from ticker_lookup import TICKER_INFO
                return {
                    "ticker": ticker,
                    "name": TICKER_INFO.get(ticker, ticker),
                    "current_price": price,
                    "price_change_24h": change,
                    "price_change_percent": pct,
                    "_ts": now,
                }
    except Exception:
        pass
    return None

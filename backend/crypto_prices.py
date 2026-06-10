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


# ── Symbol disambiguation (2026-06-10 ship) ─────────────────────────────────
#
# Two "same symbol, two companies" problems:
#
# 1. CRYPTO-EQUITY COLLISIONS — coin symbols that also identify a real
#    equity. Disambiguated BY SOURCE: equity-analyst scrapers (Benzinga
#    ratings, FMP grades) publish price targets on the EQUITY, never the
#    coin, so rows from those sources get equity treatment (sector +
#    price); every other source means the coin. ETH is the documented
#    exception and is NOT in COLLISION_SYMBOLS: its equity era (Ethan
#    Allen, renamed ETD in 2019) is dead, and 2 analyst-source rows from
#    May 2021 are verifiably Ethereum (entry ~$3,485) — ETH stays
#    always-coin; the Ethan-Allen-era rows are flagged is_ambiguous_symbol.
#
# 2. TICKER REUSE — a symbol reassigned to a new company. Old-era rows
#    can't be reliably re-scored (company delisted/renamed), so they are
#    flagged is_ambiguous_symbol (hidden from user surfaces, kept for
#    admin/audit). KNOWN_TICKER_REASSIGNMENTS is the forward guard: the
#    Benzinga ingest paths flag any new row whose prediction_date falls
#    in the old era.
#
# TO EXTEND: new collision -> add the symbol to COLLISION_SYMBOLS (only
# if a real equity actively trades under it). New reuse -> add a
# KNOWN_TICKER_REASSIGNMENTS entry with the cutover date; rows dated
# before the cutover get flagged at ingest. Then run a
# scripts/disambiguate_symbols.py-style backfill for existing rows.

EQUITY_ANALYST_SOURCES = {
    "massive_benzinga", "benzinga_api", "benzinga_rss", "benzinga_web",
    "fmp_grades", "fmp_ratings", "fmp_pt", "fmp_daily_grades",
    "fmp_upgrades", "marketbeat_rss", "yfinance", "alphavantage", "finnhub",
}

# Coin symbols with a real equity identity (audited 2026-06-10):
# LTC=LTC Properties, SOL=Emeren, SAND=Sandstorm Gold, BCH=Banco de
# Chile, TRX=TRX Gold, ARB=Arbitron (historical), ATOM=Atomera.
COLLISION_SYMBOLS = {"LTC", "SOL", "SAND", "BCH", "TRX", "ARB", "ATOM"}

# symbol -> (cutover ISO date, old identity, new identity). Rows dated
# BEFORE the cutover belong to the old company and are flagged.
KNOWN_TICKER_REASSIGNMENTS = {
    "LB": ("2021-08-02", "L Brands", "LandBridge Company"),
    "APC": ("2019-08-08", "Anadarko Petroleum", "ARKO Petroleum"),
    "ARB": ("2014-01-01", "Arbitron", "AltShares ETF / Arbitrum coin"),
    # Corrected 2026-06-11: Ethan Allen kept the ETH ticker until
    # 2021-08-16 (NYSE change to ETD) — the original 2019 date was wrong
    # and mislabeled two May-2021 analyst rows as Ethereum.
    "ETH": ("2021-08-16", "Ethan Allen Interiors (now ETD)", "Ethereum / ETF"),
}

# ── Recovery layer (2026-06-11): price paths for recovered identities ──────
#
# PRICE_TICKER_OVERRIDES is consumed ONLY by the evaluator's equity
# branch (historical_evaluator._fetch_history with force_equity=True).
# Display keeps the original ticker. Three shapes:
#   {"fetch_as": "ETD"}                      — clean rename continuity:
#       fetch the current symbol's series (providers backfill the full
#       history under the new ticker).
#   {"terminal": {"after": "YYYY-MM-DD", "stock": ("RGLD", 0.0625)}}
#       — acquisition paid in stock: real bars up to the close, then
#       synthetic post-event points = ratio x acquirer close (verified
#       deal terms; never fabricates in-era prices).
#   {"terminal": {"after": "YYYY-MM-DD", "cash": 1.95}}
#       — cash-out (going private): flat realized value after the event.
#
# TO EXTEND for a future rename/acquisition: add the entry here, add the
# symbol to EQUITY_ERA_ROUTES (or COLLISION_SYMBOLS if it also collides
# with a coin), then run a scripts/recover_ambiguous_predictions.py-style
# re-evaluation for the affected rows.
PRICE_TICKER_OVERRIDES = {
    "ETH": {"fetch_as": "ETD"},  # Ethan Allen -> ETD (renamed 2021-08-16)
    "SAND": {"terminal": {"after": "2025-10-20", "stock": ("RGLD", 0.0625)}},
    "SOL": {"terminal": {"after": "2025-12-12", "cash": 1.95}},  # $2.00/ADS - $0.05 fee
}

# Symbols whose EQUITY identity is era-bound rather than coexisting:
# analyst-source rows dated before the cutover route to the equity.
# (ETH can't live in COLLISION_SYMBOLS — post-2021 the symbol means the
# coin/ETF even for analyst sources.)
EQUITY_ERA_ROUTES = {"ETH": "2021-08-16"}


def equity_route_for_row(ticker: str, source: str | None,
                         prediction_date=None) -> bool:
    """True when a prediction ROW should be priced as the equity despite
    its symbol also meaning a coin. Collision symbols route purely by
    source; era-bound symbols (ETH/Ethan Allen) additionally require the
    row to predate the reassignment cutover."""
    t = (ticker or "").upper().strip()
    if not source or source not in EQUITY_ANALYST_SOURCES:
        return False
    if t in COLLISION_SYMBOLS:
        return True
    era = EQUITY_ERA_ROUTES.get(t)
    if era and prediction_date is not None:
        d = (prediction_date.date() if hasattr(prediction_date, "date")
             else prediction_date)
        return d.isoformat() < era
    return False


def is_crypto_for_source(ticker: str, source: str | None = None) -> bool:
    """Source-aware is_crypto. For COLLISION_SYMBOLS, crypto treatment
    applies ONLY when the row does NOT come from an equity-analyst
    source. Non-collision coins (BTC, ETH, DOGE, ...) are crypto
    regardless of source — identical to is_crypto()."""
    t = (ticker or "").upper().strip()
    if t not in CRYPTO_TICKERS:
        return False
    if t in COLLISION_SYMBOLS and source and source in EQUITY_ANALYST_SOURCES:
        return False
    return True


def is_stale_reassigned(ticker: str, prediction_date) -> bool:
    """True when a prediction on a reused symbol is dated before the
    reassignment cutover — i.e. it belongs to the OLD company and must
    be flagged is_ambiguous_symbol at ingest."""
    entry = KNOWN_TICKER_REASSIGNMENTS.get((ticker or "").upper().strip())
    if not entry or prediction_date is None:
        return False
    cutover = entry[0]
    d = prediction_date.date() if hasattr(prediction_date, "date") else prediction_date
    return d.isoformat() < cutover

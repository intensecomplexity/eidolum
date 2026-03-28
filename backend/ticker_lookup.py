"""
Ticker lookup — maps company names, aliases, and ticker symbols to canonical tickers.
Used by the search endpoint and the submit endpoint to resolve user input.
"""

# Full company names for each supported ticker
TICKER_INFO = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corp.",
    "NVDA": "NVIDIA Corp.",
    "TSLA": "Tesla Inc.",
    "AMZN": "Amazon.com Inc.",
    "META": "Meta Platforms Inc.",
    "GOOGL": "Alphabet Inc.",
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "SOL": "Solana",
    "NFLX": "Netflix Inc.",
    "AMD": "Advanced Micro Devices Inc.",
    "INTC": "Intel Corp.",
    "QCOM": "Qualcomm Inc.",
    "JPM": "JPMorgan Chase & Co.",
    "GS": "Goldman Sachs Group Inc.",
    "BAC": "Bank of America Corp.",
    "WFC": "Wells Fargo & Co.",
    "XOM": "Exxon Mobil Corp.",
    "CVX": "Chevron Corp.",
    "CRM": "Salesforce Inc.",
    "AVGO": "Broadcom Inc.",
    "ORCL": "Oracle Corp.",
    "PLTR": "Palantir Technologies Inc.",
    "RKLB": "Rocket Lab USA Inc.",
    "COIN": "Coinbase Global Inc.",
    "MSTR": "MicroStrategy Inc.",
    "ARM": "Arm Holdings plc",
    "SMCI": "Super Micro Computer Inc.",
    "MU": "Micron Technology Inc.",
}

# Map of lowercase query -> canonical ticker
# Includes: ticker itself, company name, and all common aliases
TICKER_MAP = {}

# Auto-populate: each ticker maps to itself (lowercase)
for _t in TICKER_INFO:
    TICKER_MAP[_t.lower()] = _t

# Auto-populate: each full company name (lowercase)
for _t, _name in TICKER_INFO.items():
    TICKER_MAP[_name.lower()] = _t

# Manual aliases
_ALIASES = {
    # Tech
    "apple": "AAPL",
    "apple inc": "AAPL",
    "microsoft": "MSFT",
    "nvidia": "NVDA",
    "tesla": "TSLA",
    "amazon": "AMZN",
    "meta": "META",
    "facebook": "META",
    "fb": "META",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "netflix": "NFLX",
    "amd": "AMD",
    "advanced micro devices": "AMD",
    "intel": "INTC",
    "qualcomm": "QCOM",
    "salesforce": "CRM",
    "broadcom": "AVGO",
    "oracle": "ORCL",
    "palantir": "PLTR",
    "rocket lab": "RKLB",
    "rocketlab": "RKLB",
    "arm": "ARM",
    "arm holdings": "ARM",
    "super micro": "SMCI",
    "supermicro": "SMCI",
    "micron": "MU",
    # Finance
    "jpmorgan": "JPM",
    "jp morgan": "JPM",
    "chase": "JPM",
    "goldman sachs": "GS",
    "goldman": "GS",
    "bank of america": "BAC",
    "bofa": "BAC",
    "wells fargo": "WFC",
    "coinbase": "COIN",
    "microstrategy": "MSTR",
    # Energy
    "exxon": "XOM",
    "exxon mobil": "XOM",
    "exxonmobil": "XOM",
    "chevron": "CVX",
    # Crypto
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "ether": "ETH",
    "solana": "SOL",
}

for _alias, _ticker in _ALIASES.items():
    TICKER_MAP[_alias.lower()] = _ticker


def resolve_ticker(query: str) -> str | None:
    """Resolve a user input string to a canonical ticker symbol, or None if not found."""
    q = query.strip().lower()
    return TICKER_MAP.get(q)


def search_tickers(query: str) -> list[dict]:
    """Search tickers by partial match on symbol or company name. Returns up to 5 results.

    Priority: exact ticker > exact name > partial ticker > partial name.
    """
    q = query.strip().lower()
    if not q:
        return []

    exact_ticker = []
    exact_name = []
    partial_ticker = []
    partial_name = []

    for ticker, name in TICKER_INFO.items():
        t_low = ticker.lower()
        n_low = name.lower()

        if t_low == q:
            exact_ticker.append({"ticker": ticker, "name": name, "match_type": "ticker"})
        elif n_low == q or q in TICKER_MAP and TICKER_MAP[q] == ticker:
            exact_name.append({"ticker": ticker, "name": name, "match_type": "name"})
        elif q in t_low:
            partial_ticker.append({"ticker": ticker, "name": name, "match_type": "ticker"})
        elif q in n_low:
            partial_name.append({"ticker": ticker, "name": name, "match_type": "name"})
        else:
            # Check aliases
            for alias, mapped in _ALIASES.items():
                if mapped == ticker and q in alias:
                    partial_name.append({"ticker": ticker, "name": name, "match_type": "name"})
                    break

    # Deduplicate while preserving order
    seen = set()
    results = []
    for item in exact_ticker + exact_name + partial_ticker + partial_name:
        if item["ticker"] not in seen:
            seen.add(item["ticker"])
            results.append(item)
        if len(results) >= 5:
            break

    return results

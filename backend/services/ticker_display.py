"""Display-name overrides for tickers whose letters collide with crypto
symbols.

The `ticker_sectors` table maps tickers to their US-equity company record
(e.g. LTC → "LTC Properties Inc", SOL → "Emeren Group Ltd", LINK →
"Interlink Electronics"). For tickers that also represent a crypto asset,
the evaluator routes through `services.price_fetch.fetch_crypto_history`
so the SCORING is correct — but the display label on the frontend would
still show the equity company name, which is misleading.

These helpers centralize the override at the API-serialization layer:

- `resolve_ticker_display_name(ticker, fallback)` — returns the
  canonical crypto name from `CRYPTO_NAMES` when the ticker is on the
  crypto allowlist, otherwise returns `fallback`.
- `resolve_ticker_display_sector(ticker, fallback)` — returns
  "Cryptocurrency" for crypto tickers, otherwise `fallback`.

The DB rows in `ticker_sectors` are intentionally untouched — this
module is the single place that decides what the user sees.
"""
from crypto_prices import CRYPTO_NAMES, is_crypto


CRYPTO_SECTOR_LABEL = "Cryptocurrency"


def resolve_ticker_display_name(ticker: str | None, fallback: str | None) -> str | None:
    if ticker and is_crypto(ticker):
        return CRYPTO_NAMES.get(ticker.upper()) or fallback
    return fallback


def resolve_ticker_display_sector(ticker: str | None, fallback: str | None) -> str | None:
    if ticker and is_crypto(ticker):
        return CRYPTO_SECTOR_LABEL
    return fallback


__all__ = [
    "CRYPTO_SECTOR_LABEL",
    "resolve_ticker_display_name",
    "resolve_ticker_display_sector",
]

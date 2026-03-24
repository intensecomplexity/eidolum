"""
Parse predictions from video titles and descriptions using keyword + regex heuristics.
"""
import re
from dataclasses import dataclass
from typing import Optional

BULL_KEYWORDS = [
    "buy", "long", "bullish", "breakout", "price target", "will reach",
    "going to $", "moon", "outperform", "strong buy", "accumulate",
    "upside", "surge", "rally", "undervalued", "cheap", "opportunity",
]

BEAR_KEYWORDS = [
    "sell", "short", "bearish", "crash", "overvalued", "avoid",
    "going down", "collapse", "bubble", "put", "drop", "dump",
    "downside", "correction", "recession", "danger", "warning",
]

# Common US-listed tickers (expandable)
KNOWN_TICKERS = {
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "TSLA",
    "AMD", "INTC", "QCOM", "AVGO", "CRM", "ADBE", "ORCL",
    "JPM", "GS", "BAC", "WFC", "MS", "V", "MA", "AXP",
    "XOM", "CVX", "OXY", "COP", "BP",
    "JNJ", "PFE", "MRK", "ABBV", "LLY",
    "PLTR", "NET", "SNOW", "DDOG", "ZS",
    "SPY", "QQQ", "IWM", "DIA",
    "BTC", "ETH",
}

TICKER_PATTERN = re.compile(r'\b([A-Z]{1,5})\b')
PRICE_TARGET_PATTERN = re.compile(r'\$\s?(\d[\d,]*(?:\.\d+)?)\s*(?:price\s*target|target|PT)?', re.IGNORECASE)


@dataclass
class ParsedPrediction:
    ticker: str
    direction: str          # "bullish" | "bearish"
    target_price: Optional[float]
    context: str
    window_days: int = 30
    time_horizon: str = "short"  # "short" | "medium" | "long" | "custom"


def parse_predictions(title: str, description: str = "") -> list[ParsedPrediction]:
    """
    Extract structured predictions from a video title + description.
    Returns a list of ParsedPrediction (may be empty).
    """
    text = f"{title} {description[:500]}"
    text_lower = text.lower()

    tickers = _extract_tickers(text)
    if not tickers:
        return []

    direction = _detect_direction(text_lower)
    if direction is None:
        return []

    target_price = _extract_price_target(text)

    window_days, time_horizon = _infer_time_horizon(text_lower, direction)

    results = []
    for ticker in tickers:
        results.append(ParsedPrediction(
            ticker=ticker,
            direction=direction,
            target_price=target_price,
            context=title[:200],
            window_days=window_days,
            time_horizon=time_horizon,
        ))
    return results


def _extract_tickers(text: str) -> list[str]:
    candidates = TICKER_PATTERN.findall(text)
    return [t for t in candidates if t in KNOWN_TICKERS]


def _detect_direction(text_lower: str) -> Optional[str]:
    bull_score = sum(1 for kw in BULL_KEYWORDS if kw in text_lower)
    bear_score = sum(1 for kw in BEAR_KEYWORDS if kw in text_lower)
    if bull_score > bear_score:
        return "bullish"
    if bear_score > bull_score:
        return "bearish"
    return None


def _extract_price_target(text: str) -> Optional[float]:
    matches = PRICE_TARGET_PATTERN.findall(text)
    if matches:
        try:
            return float(matches[0].replace(",", ""))
        except ValueError:
            pass
    return None


# Patterns for explicit time frames: "within 30 days", "in 6 months", "by end of year"
_DAYS_PATTERN = re.compile(r'(?:within|in|next)\s+(\d+)\s*days?', re.IGNORECASE)
_WEEKS_PATTERN = re.compile(r'(?:within|in|next)\s+(\d+)\s*weeks?', re.IGNORECASE)
_MONTHS_PATTERN = re.compile(r'(?:within|in|next)\s+(\d+)\s*months?', re.IGNORECASE)
_YEARS_PATTERN = re.compile(r'(?:within|in|next)\s+(\d+)\s*years?', re.IGNORECASE)

SHORT_TERM_KEYWORDS = [
    "sell now", "avoid", "get out", "take profit", "sell immediately",
    "this week", "right now", "today", "tomorrow", "dump now",
    "buy now", "buy today", "buy immediately",
]

LONG_TERM_KEYWORDS = [
    "long term", "long-term", "next year", "years from now",
    "decade", "hold forever", "generational", "retirement",
    "5 year", "10 year", "multi-year",
]


def _infer_time_horizon(text_lower: str, direction: str) -> tuple[int, str]:
    """
    Infer window_days and time_horizon from prediction text.
    Returns (window_days, time_horizon).

    Rules:
    - Explicit "within X days/weeks/months" → use that, "custom"
    - Short-term language → 30 days, "short"
    - Long-term language → 365 days, "long"
    - Default → 90 days, "medium"
    """
    # Check for explicit time frames first
    m = _DAYS_PATTERN.search(text_lower)
    if m:
        return int(m.group(1)), "custom"

    m = _WEEKS_PATTERN.search(text_lower)
    if m:
        return int(m.group(1)) * 7, "custom"

    m = _MONTHS_PATTERN.search(text_lower)
    if m:
        return int(m.group(1)) * 30, "custom"

    m = _YEARS_PATTERN.search(text_lower)
    if m:
        return int(m.group(1)) * 365, "custom"

    # Check for short-term language
    if any(kw in text_lower for kw in SHORT_TERM_KEYWORDS):
        return 30, "short"

    # Check for long-term language
    if any(kw in text_lower for kw in LONG_TERM_KEYWORDS):
        return 365, "long"

    # Default: medium-term
    return 90, "medium"

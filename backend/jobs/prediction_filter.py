"""
Shared prediction filter — used by all scrapers to decide if text is a real,
falsifiable prediction worth tracking.

A text passes if:
  1. It mentions a specific asset (ASSET_PATTERN)
  2. It contains a directional/predictive claim (DIRECTION_PATTERN)
  3. It does NOT start with a vague non-prediction phrase (VAGUE_REJECT)
"""
import re

# Must mention a specific asset or market
ASSET_PATTERN = re.compile(
    r'\$[A-Z]{1,5}|bitcoin|btc|ethereum|eth|tesla|tsla|nvidia|nvda|apple|aapl|'
    r'microsoft|msft|google|googl|amazon|amzn|meta|dogecoin|doge|solana|sol|'
    r's&p|nasdaq|dow|sp500|stock|crypto|market',
    re.IGNORECASE
)

# Must contain a directional/predictive verb or phrase
DIRECTION_PATTERN = re.compile(
    r'will (reach|hit|go|rise|fall|drop|crash|moon|surge|collapse|be worth)|'
    r'(going to|going up|going down|price target|my target|I think .{0,30}(buy|sell|worth|reach|hit))|'
    r'(buy|sell|short|long) .{0,20}(here|now|today|this)|'
    r'(bull|bear|bullish|bearish) on|'
    r'(overvalued|undervalued|to \$[0-9]|target of \$|by (end of|year end|Q[1-4]|20[0-9]{2}))|'
    r'(calls|puts) (on|for)|predict|forecast|expect .{0,30}(price|value|reach)',
    re.IGNORECASE
)

# Reject vague statements that aren't actually predictions
VAGUE_REJECT = re.compile(
    r"^(I (own|hold|bought|sold|have)|still (own|holding)|just (bought|sold)|"
    r"(the )?people'?s |is (the future|amazing|great|incredible|terrible))",
    re.IGNORECASE
)


def is_prediction(text: str) -> bool:
    """Return True if text looks like a real, falsifiable prediction."""
    if not text:
        return False
    if VAGUE_REJECT.search(text[:80]):
        return False
    return bool(ASSET_PATTERN.search(text) and DIRECTION_PATTERN.search(text))

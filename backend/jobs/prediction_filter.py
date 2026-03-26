"""
Shared prediction filter — used by all scrapers to decide if text is a real,
falsifiable prediction worth tracking.

A text passes if it contains any predictive/directional language.
No separate asset check — finance channels almost always mention tickers in context.
"""
import re

PREDICTION_PATTERN = re.compile(
    r'(will|going to|expect|target|buy|sell|bull|bear|bullish|bearish|'
    r'price target|price of|worth|reach|hit|crash|moon|\$[0-9]|[0-9]+\%)',
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
    return bool(PREDICTION_PATTERN.search(text))

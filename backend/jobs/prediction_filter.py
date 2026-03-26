"""
Shared prediction filter — used by ALL scrapers to decide if text is a real,
specific, falsifiable prediction worth tracking.

A text passes ONLY if it contains a specific falsifiable claim (price target,
directional call with specifics, etc). Vague sentiment is rejected.
"""
import re

# A prediction MUST contain at least one of these — a specific falsifiable claim
MUST_HAVE = re.compile(
    r'('
    r'will (reach|hit|go to|rise to|fall to|drop to|crash to|be worth|trade at)'
    r'|price target'
    r'|target (of|price|\:)?\s*\$?[0-9]'
    r'|going to \$?[0-9]'
    r'|to \$[0-9]'
    r'|\$[0-9,]+\s*(target|price|by|eoy|eom)'
    r'|(bull|bear)(ish)? on \$?[A-Z]'
    r'|(over|under)valued'
    r'|i (expect|predict|think).{0,60}(reach|hit|go|rise|fall|drop|target|worth|\$[0-9])'
    r'|forecast.{0,40}\$?[0-9]'
    r'|by (end of|year.end|eoy|q[1-4]|20[0-9]{2}).{0,40}\$?[0-9]'
    r'|(short|long).{0,30}\$?[A-Z]{1,5}'
    r'|(buy|sell) (here|now|today|at \$)'
    r'|(calls|puts) (on|for) \$?[A-Z]'
    r'|bottom (is |at |\:)\$?[0-9]'
    r'|top (is |at |\:)\$?[0-9]'
    r')',
    re.IGNORECASE
)

# Reject these — they are statements, not predictions
REJECT = re.compile(
    r'^('
    r'i (own|hold|bought|sold|have|am holding|still own)'
    r'|just (bought|sold|added)'
    r"|(the )?people'?s "
    r'|is (the future|amazing|great|incredible|terrible|here)'
    r'|this is (the future|amazing)'
    r'|gm |good morning'
    r'|thread|daily|weekly|discussion'
    r')',
    re.IGNORECASE
)


def is_valid_prediction(text: str) -> bool:
    """Returns True only if text contains a specific falsifiable prediction."""
    if not text or len(text) < 20:
        return False
    if REJECT.search(text):
        return False
    if not MUST_HAVE.search(text):
        return False
    return True


# Backward-compatible alias so existing imports don't break
is_prediction = is_valid_prediction

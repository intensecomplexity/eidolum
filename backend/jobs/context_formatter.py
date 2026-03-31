"""
Generate human-readable prediction context from raw analyst rating data.
"""

BULLISH_RATINGS = {"buy", "outperform", "overweight", "strong buy", "strong_buy", "positive", "top pick"}
BEARISH_RATINGS = {"sell", "underperform", "underweight", "strong sell", "strong_sell", "negative", "reduce"}
NEUTRAL_RATINGS = {"hold", "neutral", "market perform", "market_perform", "equal weight", "equal_weight",
                   "sector perform", "sector_perform", "in line", "in_line", "peer perform", "peer_perform",
                   "market weight", "market_weight"}


def _sentiment(rating: str) -> str:
    r = rating.lower().replace("_", " ").strip()
    if r in BULLISH_RATINGS or any(b in r for b in BULLISH_RATINGS):
        return "Bullish"
    if r in BEARISH_RATINGS or any(b in r for b in BEARISH_RATINGS):
        return "Bearish"
    return "Neutral"


def _clean_rating(rating: str) -> str:
    return rating.replace("_", " ").strip().title()


def format_context(firm: str, action: str, rating: str, ticker: str, price_target=None) -> str:
    """Generate a human-readable context string from analyst rating data."""
    action_lower = (action or "").lower().replace("_", " ").strip()
    rating_clean = _clean_rating(rating or "")
    sentiment = _sentiment(rating or "")
    pt_str = f" Target: ${float(price_target):,.2f}" if price_target else ""

    # Determine action description
    if "upgrade" in action_lower:
        desc = f"Upgraded to {rating_clean}"
    elif "downgrade" in action_lower:
        desc = f"Downgraded to {rating_clean}"
    elif "initiate" in action_lower or "start" in action_lower:
        desc = f"Started coverage with {rating_clean} rating"
    elif "maintain" in action_lower:
        desc = f"Maintains {rating_clean} rating"
    elif "reiterate" in action_lower:
        desc = f"Reaffirms {rating_clean} rating"
    elif "resume" in action_lower:
        desc = f"Resumed coverage with {rating_clean} rating"
    else:
        desc = f"{rating_clean} rating" if rating_clean else action_lower.title()

    return f"{firm}: {sentiment} — {desc} on {ticker}.{pt_str}"

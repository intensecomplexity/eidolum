"""
Eidolum Prediction Validator — Layer 2 Defense
No prediction enters the database without passing ALL checks.
"""
import re


# Valid analyst action phrases — the article must contain one of these
ANALYST_ACTIONS = [
    "upgrades", "upgraded", "upgrade",
    "downgrades", "downgraded", "downgrade",
    "initiates coverage", "initiated coverage",
    "reiterates", "reiterated", "maintains", "maintained",
    "raises price target", "raised price target",
    "raises target", "raised target",
    "lowers price target", "lowered price target",
    "lowers target", "lowered target",
    "cuts price target", "cut price target",
    "cuts target", "cut target",
    "sets price target", "set price target",
    "boosts price target", "boosted price target",
    "slashes price target", "slashed price target",
    "resumed coverage", "resumes coverage",
    "starts coverage", "started coverage",
]

# Valid rating words — the article must also contain one of these
RATING_WORDS = [
    "buy", "sell", "hold", "neutral",
    "overweight", "underweight",
    "outperform", "underperform",
    "market perform", "sector perform",
    "strong buy", "strong sell",
    "price target", "target price",
    "pt of", "pt to", "target of $", "target to $",
    "fair value", "conviction buy", "top pick",
]

# Headlines matching these patterns are NOT predictions — reject immediately
REJECT_PATTERNS = [
    r"\?$",  # Headlines ending with ? are clickbait questions
    r"signs? agreement", r"framework agreement", r"partnership",
    r"acquisition", r"acquires", r"merger", r"merges",
    r"reports? earnings", r"quarterly results", r"revenue (growth|fell|rose)",
    r"earnings (beat|miss|call|report)", r"beats? estimates", r"misses? estimates",
    r"dividend", r"stock split", r"buyback", r"repurchase",
    r"appoints?", r"names? .*(CEO|CFO|CTO|COO)", r"hires?", r"board of directors",
    r"patent", r"FDA approval", r"FDA clears", r"clinical trial", r"regulatory",
    r"lawsuit", r"settlement", r"investigation", r"subpoena",
    r"launches? (new |its )", r"announces? (new |its |a )",
    r"expands? (into|to|its)", r"opens? (new|its|a)",
    r"signs? (deal|contract|agreement)",
    r"(supply|supplier|framework) agreement",
    r"production capacity", r"manufacturing",
]

# Bullish indicators
BULLISH_SIGNALS = [
    "upgrades", "upgraded", "upgrade",
    "buy", "overweight", "outperform",
    "raises target", "raised target", "raises price target", "raised price target",
    "boosts target", "boosted target", "boosts price target",
    "strong buy", "top pick", "conviction buy",
    r"initiates.*buy", r"initiates.*overweight", r"initiates.*outperform",
    r"reiterates.*buy", r"reiterates.*overweight", r"reiterates.*outperform",
    r"maintains.*buy", r"maintains.*overweight", r"maintains.*outperform",
    "bullish",
]

# Bearish indicators
BEARISH_SIGNALS = [
    "downgrades", "downgraded", "downgrade",
    "sell", "underweight", "underperform",
    "lowers target", "lowered target", "lowers price target", "lowered price target",
    "cuts target", "cut target", "cuts price target", "cut price target",
    "slashes target", "slashed target",
    "strong sell",
    r"initiates.*sell", r"initiates.*underweight", r"initiates.*underperform",
    r"reiterates.*sell", r"reiterates.*underweight", r"reiterates.*underperform",
    r"maintains.*sell", r"maintains.*underweight", r"maintains.*underperform",
    "bearish", "reduce",
]


def is_real_prediction(headline, summary=""):
    """
    Layer 1 check: Is this article a REAL analyst prediction?
    Must have BOTH an analyst action AND a rating word.
    Must NOT match any reject pattern.
    """
    combined = (headline + " " + summary).lower()

    # Check reject patterns first
    for pattern in REJECT_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            return False

    # Must have at least one analyst action
    has_action = any(action in combined for action in ANALYST_ACTIONS)

    # Must have at least one rating word
    has_rating = any(rating in combined for rating in RATING_WORDS)

    # BOTH required
    return has_action and has_rating


def get_direction(headline, summary=""):
    """Extract bullish/bearish direction. Returns None if ambiguous."""
    combined = (headline + " " + summary).lower()

    bull_score = 0
    bear_score = 0

    for signal in BULLISH_SIGNALS:
        if re.search(signal, combined):
            bull_score += 1

    for signal in BEARISH_SIGNALS:
        if re.search(signal, combined):
            bear_score += 1

    if bull_score > bear_score:
        return "bullish"
    elif bear_score > bull_score:
        return "bearish"

    # Ambiguous — reject
    return None


def validate_prediction(ticker, direction, source_url, archive_url, context, forecaster_id):
    """
    Layer 2 check: Does this prediction have ALL required fields?
    Returns (is_valid, reason) tuple.
    """
    # 1. Must have a valid ticker
    if not ticker or not isinstance(ticker, str):
        return False, "Missing ticker"
    ticker = ticker.strip().upper()
    if len(ticker) > 8 or len(ticker) < 1:
        return False, f"Invalid ticker length: {ticker}"
    if not re.match(r"^[A-Z0-9.]{1,8}$", ticker):
        return False, f"Invalid ticker format: {ticker}"

    # 2. Must have a direction
    if not direction or direction not in ("bullish", "bearish"):
        return False, f"Invalid direction: {direction}"

    # 3. Must have a real source URL
    if not source_url or not source_url.startswith("http"):
        return False, "Missing or invalid source URL"
    fake_url_patterns = [
        "yahoo.com/quote", "stockanalysis.com", "goldmansachs.com/market-data",
        "jpmorgan.com/market-data", "morganstanley.com/market-data",
        "bankofamerica.com/market-data", "citigroup.com/market-data",
    ]
    for pattern in fake_url_patterns:
        if pattern in source_url:
            return False, f"Fake URL pattern: {pattern}"

    # 4. Must have an archive URL
    if not archive_url or not archive_url.startswith("http"):
        return False, "Missing archive URL"

    # 5. Must have context/headline
    if not context or len(context) < 10:
        return False, "Missing or too short context"

    # 6. Context must not be fake data
    fake_context_patterns = [
        "Analyst consensus:", "Price target for", "Analyst price target:",
        "<figure>", "<img", "wp-post-image", "<!DOCTYPE",
    ]
    for pattern in fake_context_patterns:
        if pattern in (context or ""):
            return False, f"Fake context pattern: {pattern}"

    # 7. Must have a forecaster
    if not forecaster_id:
        return False, "Missing forecaster"

    return True, "Valid"


def cleanup_invalid_predictions(db):
    """
    Layer 3: Hourly cleanup — scan ALL predictions and delete rule violators.
    """
    from sqlalchemy import text as sql_text

    deleted = 0

    # Delete predictions with fake URLs
    r = db.execute(sql_text("""
        DELETE FROM predictions WHERE
            source_url IS NULL
            OR source_url = ''
            OR source_url NOT LIKE 'http%'
            OR source_url LIKE '%yahoo.com/quote%'
            OR source_url LIKE '%stockanalysis.com%'
            OR source_url LIKE '%goldmansachs.com/market-data%'
            OR source_url LIKE '%jpmorgan.com/market-data%'
            OR source_url LIKE '%morganstanley.com/market-data%'
    """))
    deleted += r.rowcount

    # Delete predictions with fake content
    r = db.execute(sql_text("""
        DELETE FROM predictions WHERE
            context LIKE 'Analyst consensus:%'
            OR context LIKE 'Price target for%'
            OR exact_quote LIKE '<%'
            OR exact_quote LIKE '%<figure>%'
            OR exact_quote LIKE '%<img%'
    """))
    deleted += r.rowcount

    # Delete predictions with no ticker or direction
    r = db.execute(sql_text("""
        DELETE FROM predictions WHERE
            ticker IS NULL OR ticker = '' OR ticker = 'UNKNOWN'
            OR direction IS NULL OR direction = ''
            OR direction NOT IN ('bullish', 'bearish')
    """))
    deleted += r.rowcount

    # Delete predictions where headline is clearly NOT a prediction
    r = db.execute(sql_text("""
        DELETE FROM predictions WHERE
            context LIKE '%?'
            OR context LIKE '%Signs Agreement%'
            OR context LIKE '%signs agreement%'
            OR context LIKE '%Framework Agreement%'
            OR context LIKE '%Reports Earnings%'
            OR context LIKE '%reports earnings%'
            OR context LIKE '%Quarterly Results%'
            OR context LIKE '%Appoints%'
            OR context LIKE '%appoints%'
            OR context LIKE '%Launches New%'
            OR context LIKE '%launches new%'
            OR context LIKE '%Announces New%'
            OR context LIKE '%announces new%'
            OR context LIKE '%Production Capacity%'
            OR context LIKE '%production capacity%'
    """))
    deleted += r.rowcount

    db.commit()

    if deleted > 0:
        print(f"[Defense L3] Cleaned up {deleted} invalid predictions")

    return deleted

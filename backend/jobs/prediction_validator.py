"""
Eidolum Prediction Validator — 3-Layer Defense System
"""
import re

# === LAYER 1: Scraper filter ===

# Analyst action phrases — multi-word preferred, standalone only when safe with AND rating check
ANALYST_ACTIONS = [
    "upgrades", "upgraded", "upgrades to", "upgraded to",
    "downgrades", "downgraded", "downgrades to", "downgraded to",
    "initiates coverage", "initiated coverage", "initiates with",
    "reiterates buy", "reiterates sell", "reiterates hold",
    "reiterates overweight", "reiterates underweight",
    "reiterates outperform", "reiterates underperform",
    "reiterated buy", "reiterated sell", "reiterated hold",
    "reiterated overweight", "reiterated underweight",
    "maintains buy", "maintains sell", "maintains hold",
    "maintains overweight", "maintains underweight",
    "maintained buy", "maintained sell", "maintained hold",
    "raises price target", "raised price target",
    "raises target to", "raised target to",
    "lowers price target", "lowered price target",
    "lowers target to", "lowered target to",
    "cuts price target", "cut price target",
    "cuts target to", "cut target to",
    "sets price target", "set price target",
    "boosts price target", "boosted price target",
    "slashes price target", "slashed price target",
    "price target of $", "price target to $",
    "target price of $", "target price to $",
    "pt of $", "pt to $",
    "resumed coverage", "resumes coverage",
    "starts coverage", "started coverage",
]

# Rating words — article MUST also contain one of these
RATING_WORDS = [
    "buy", "sell", "hold", "neutral",
    "overweight", "underweight", "equal weight", "equal-weight",
    "outperform", "underperform", "market perform", "sector perform",
    "strong buy", "strong sell",
    "price target", "target price", "pt of", "pt to",
    "target of $", "target to $", "fair value",
    "conviction buy", "top pick",
]

# Reject patterns — if headline matches, it's NOT a prediction
REJECT_PATTERNS = [
    r"\?$",  # Clickbait questions
    # Job/economic news that triggers "cuts"/"raises"
    r"job cuts?", r"layoffs?", r"workforce reduction",
    r"rate cuts?", r"tax cuts?", r"cost.?cutting",
    r"interest rate", r"fed (rate|decision|meeting)",
    r"unemployment", r"inflation (data|report|rate)",
    r"GDP (growth|report|data)", r"economic (data|report|growth)",
    # Commodity / market movement reports
    r"(oil|crude|gold|silver|copper) (price|falls?|rises?|drops?)",
    r"shares? (spike|fall|rise|drop|surge|tumble|plunge)",
    r"stock (spike|fall|rise|drop|surge|tumble|plunge)",
    r"market (rally|crash|correction|pullback|sell.?off)",
    # Press releases / corporate news
    r"signs? (agreement|deal|contract)", r"framework agreement",
    r"partnership", r"acquisition", r"acquires", r"merger", r"merges",
    r"production capacity", r"manufacturing", r"supply agreement",
    # Earnings / financial reports
    r"(beats?|misses?) (earnings|estimates|expectations)",
    r"(reports?|posts?) (earnings|revenue|profit|loss)",
    r"(Q[1-4]|quarterly|annual) (results|earnings|revenue)",
    r"reports? earnings", r"quarterly results", r"revenue (growth|fell|rose|up|down)",
    r"earnings (beat|miss|call|report)", r"earnings per share", r"EPS of",
    # Corporate actions
    r"dividend", r"stock split", r"buyback", r"repurchase",
    r"appoints?", r"names? .*(CEO|CFO|CTO|COO)", r"hires?", r"board of directors",
    # Regulatory / legal
    r"patent", r"FDA approval", r"FDA clears", r"clinical trial", r"regulatory",
    r"lawsuit", r"settlement", r"investigation", r"subpoena",
    # Product / business news
    r"launches? (new|its|a)\b", r"announces? (new|its|a)\b",
    r"expands? (into|to|its)", r"opens? (new|its|a)\b",
    # Past-tense market reports
    r"\b(falls?|fell|drops?|dropped|tumbles?|tumbled|plunges?|plunged|slips?|slipped|slides?|slid)\b.*\b(sharply|heavily|significantly|percent|%)",
    r"\b(spikes?|spiked|surges?|surged|soars?|soared|jumps?|jumped|rallied|rallies)\b.*\b(sharply|heavily|significantly|higher|percent|%)",
    r"\b(shares?|stock) (rise|rises|rose|fall|falls|fell|drop|drops|dropped|spike|spikes|spiked|surge|surges|surged)\b",
]

# Bullish signals — direction scoring (multi-word to avoid false matches)
BULLISH_SIGNALS = [
    "upgrades", "upgraded",
    "raises price target", "raised price target",
    "raises target to", "raised target to",
    "boosts price target", "boosted price target",
    "reiterates buy", "reiterated buy",
    "reiterates overweight", "reiterated overweight",
    "reiterates outperform", "reiterated outperform",
    "maintains buy", "maintained buy",
    "maintains overweight", "maintained overweight",
    "strong buy", "top pick", "conviction buy",
    # Standalone verbs — safe here because direction is only checked AFTER is_real_prediction passes
    "raises", "raised", "boosts", "boosted",
    "buy", "overweight", "outperform",
]

# Bearish signals — direction scoring
BEARISH_SIGNALS = [
    "downgrades", "downgraded",
    "lowers price target", "lowered price target",
    "lowers target to", "lowered target to",
    "cuts price target", "cut price target",
    "cuts target to", "cut target to",
    "slashes price target", "slashed price target",
    # Standalone verbs — safe here because direction is only checked AFTER is_real_prediction passes
    "lowers", "lowered", "cuts", "cut", "slashes", "slashed",
    "reiterates sell", "reiterated sell",
    "reiterates underweight", "reiterated underweight",
    "reiterates underperform", "reiterated underperform",
    "maintains sell", "maintained sell",
    "maintains underweight", "maintained underweight",
    "strong sell",
    "sell", "underweight", "underperform",
]

# Platform names that should NEVER be used as forecaster names
PLATFORMS = [
    "yahoo finance", "seeking alpha", "seekingalpha", "marketwatch",
    "cnbc", "bloomberg", "reuters", "financial times", "ft.com",
    "business insider", "forbes", "kiplinger", "the economist",
    "benzinga", "investorplace", "thestreet", "tipranks",
    "youtube", "twitter", "x.com", "access newswire",
    "globe newswire", "pr newswire", "business wire",
]

# Known analyst/firm names to extract from headlines
KNOWN_ANALYSTS = [
    # Major banks
    "goldman sachs", "jp morgan", "jpmorgan", "morgan stanley",
    "bank of america", "bofa", "citi", "citigroup", "citibank",
    "ubs", "barclays", "deutsche bank", "wells fargo", "hsbc",
    "credit suisse", "bnp paribas", "socgen", "nomura",
    # Mid-tier banks / research firms
    "wedbush", "oppenheimer", "piper sandler", "needham",
    "bernstein", "cowen", "jefferies", "raymond james",
    "stifel", "baird", "keybanc", "bmo capital", "rbc capital",
    "evercore", "wolfe research", "loop capital", "truist",
    "mizuho", "susquehanna", "rosenblatt", "canaccord",
    "guggenheim", "macquarie", "scotiabank", "td cowen",
    "william blair", "northland", "benchmark", "b. riley",
    "argus research", "cfra", "new street research",
    "daiwa", "sanford bernstein", "atlantic equities",
    "d.a. davidson", "stephens", "ladenburg thalmann",
    "maxim group", "h.c. wainwright", "roth capital",
    "lake street", "craig-hallum", "chardan",
    # Famous individuals
    "dan ives", "tom lee", "cathie wood", "jim cramer",
    "michael burry", "ray dalio", "bill ackman", "warren buffett",
    "david kostin", "ed yardeni", "liz ann sonders",
    "michael saylor", "chamath palihapitiya", "carl icahn",
    # Research / advisory firms
    "ark invest", "fundstrat", "morningstar", "zacks",
    "s&p global", "fitch", "moody", "capital economics",
]


def is_real_prediction(headline, summary=""):
    """Layer 1: Is this a real analyst prediction?"""
    combined = (headline + " " + summary).lower()

    # Check reject patterns first
    for pattern in REJECT_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            return False

    # Must have analyst action AND rating word
    has_action = any(a in combined for a in ANALYST_ACTIONS)
    has_rating = any(r in combined for r in RATING_WORDS)

    return has_action and has_rating


def get_direction(headline, summary=""):
    """Extract direction. Returns None if ambiguous."""
    combined = (headline + " " + summary).lower()
    bull = sum(1 for s in BULLISH_SIGNALS if s in combined)
    bear = sum(1 for s in BEARISH_SIGNALS if s in combined)
    if bull > bear:
        return "bullish"
    if bear > bull:
        return "bearish"
    return None


def extract_forecaster_name(headline, source=""):
    """
    Extract REAL analyst/firm name from headline.
    Returns None if no known analyst found — article should be SKIPPED.
    """
    combined = (headline + " " + source).lower()

    # ONLY return a name if it's in KNOWN_ANALYSTS
    for name in KNOWN_ANALYSTS:
        if name in combined:
            return name.title()

    # Try regex: "{Multi-Word Firm} upgrades/downgrades..."
    # Must be at least 2 words to avoid "Job", "Oil", "Stock" etc.
    match = re.search(
        r"^([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)+)\s+"
        r"(?:upgrades?|downgrades?|initiates?|reiterates?|maintains?|raises?|lowers?|cuts?|sets?|boosts?)",
        headline,
    )
    if match:
        firm = match.group(1).strip()
        # Must be multi-word and not a platform
        if " " in firm and firm.lower() not in PLATFORMS and len(firm) > 4:
            return firm

    # No real analyst found → caller should SKIP this article
    return None


def validate_prediction(ticker, direction, source_url, archive_url, context, forecaster_id):
    """Layer 2: Check all required fields."""
    if not ticker or not re.match(r"^[A-Z0-9.]{1,8}$", ticker.strip().upper()):
        return False, "Invalid ticker"
    if not direction or direction not in ("bullish", "bearish"):
        return False, "Invalid direction"
    if not source_url or not source_url.startswith("http"):
        return False, "Invalid source URL"
    fake_urls = [
        "yahoo.com/quote", "stockanalysis.com", "goldmansachs.com/market-data",
        "jpmorgan.com/market-data", "morganstanley.com/market-data",
    ]
    for pattern in fake_urls:
        if pattern in source_url:
            return False, f"Fake URL: {pattern}"
    if not archive_url or not archive_url.startswith("http"):
        return False, "Missing archive URL"
    if not context or len(context) < 10:
        return False, "Missing context"
    fake_content = [
        "Analyst consensus:", "Price target for", "<figure>", "<img", "wp-post-image",
    ]
    for pattern in fake_content:
        if pattern in (context or ""):
            return False, f"Fake content: {pattern}"
    if not forecaster_id:
        return False, "Missing forecaster"
    return True, "Valid"


def cleanup_invalid_predictions(db):
    """Layer 3: Hourly cleanup — delete rule violators."""
    from sqlalchemy import text as sql_text

    deleted = 0

    # Fake URLs
    r = db.execute(sql_text("""
        DELETE FROM predictions WHERE
            source_url IS NULL OR source_url = '' OR source_url NOT LIKE 'http%'
            OR source_url LIKE '%yahoo.com/quote%'
            OR source_url LIKE '%stockanalysis.com%'
            OR source_url LIKE '%goldmansachs.com/market-data%'
    """))
    deleted += r.rowcount

    # Fake content
    r = db.execute(sql_text("""
        DELETE FROM predictions WHERE
            context LIKE 'Analyst consensus:%'
            OR context LIKE 'Price target for%'
            OR exact_quote LIKE '<%'
            OR exact_quote LIKE '%<figure>%'
            OR exact_quote LIKE '%<img%'
    """))
    deleted += r.rowcount

    # Missing required fields
    r = db.execute(sql_text("""
        DELETE FROM predictions WHERE
            ticker IS NULL OR ticker = '' OR ticker = 'UNKNOWN'
            OR direction IS NULL OR direction = ''
            OR direction NOT IN ('bullish', 'bearish')
    """))
    deleted += r.rowcount

    # Non-prediction content that slipped through
    r = db.execute(sql_text("""
        DELETE FROM predictions WHERE
            context LIKE '%?'
            OR context LIKE '%job cuts%' OR context LIKE '%Job Cuts%'
            OR context LIKE '%layoff%' OR context LIKE '%Layoff%'
            OR context LIKE '%Signs Agreement%' OR context LIKE '%signs agreement%'
            OR context LIKE '%Framework Agreement%' OR context LIKE '%framework agreement%'
            OR context LIKE '%Reports Earnings%' OR context LIKE '%reports earnings%'
            OR context LIKE '%Quarterly Results%' OR context LIKE '%quarterly results%'
            OR context LIKE '%Appoints%' OR context LIKE '%appoints%'
            OR context LIKE '%Production Capacity%' OR context LIKE '%production capacity%'
            OR context LIKE '%Falls Sharply%' OR context LIKE '%falls sharply%'
            OR context LIKE '%Shares Spike%' OR context LIKE '%shares spike%'
            OR context LIKE '%Stock Drops%' OR context LIKE '%stock drops%'
            OR context LIKE '%rate cut%' OR context LIKE '%Rate Cut%'
            OR context LIKE '%tax cut%' OR context LIKE '%Tax Cut%'
    """))
    deleted += r.rowcount

    db.commit()
    if deleted > 0:
        print(f"[Defense L3] Cleaned up {deleted} invalid predictions")
    return deleted

"""
Eidolum Prediction Validator — 3-Layer Defense System
50 rejection categories + sentiment rule + forecaster extraction
"""
import re

# === LAYER 1: Scraper filter ===

# EXACT action phrases — headline MUST contain at least one of these. No exceptions.
# If the headline doesn't have one of these, it's NOT a prediction.
EXACT_ACTIONS = [
    # Upgrade/downgrade — standalone is safe because product upgrades are caught by REJECT_PATTERNS
    "upgrades to", "upgraded to", "upgrade to",
    "downgrades to", "downgraded to", "downgrade to",
    "upgrades", "upgraded", "downgrades", "downgraded",
    # Upgrade/downgrade passive
    "upgraded at", "downgraded at",
    "upgraded from", "downgraded from",
    "upgraded by", "downgraded by",
    # Coverage initiation
    "initiates coverage", "initiated coverage", "initiates with",
    "resumes coverage", "resumed coverage",
    "starts coverage", "started coverage",
    # Price target changes
    "raises price target", "raised price target",
    "lowers price target", "lowered price target",
    "cuts price target", "cut price target",
    "sets price target", "set price target",
    "boosts price target", "boosted price target",
    "slashes price target", "slashed price target",
    "price target to $", "price target of $",
    "target price to $", "target price of $",
    "target of $", "target to $",
    "pt of $", "pt to $",
    # Reiterations with specific rating
    "reiterates buy", "reiterated buy",
    "reiterates sell", "reiterated sell",
    "reiterates hold", "reiterated hold",
    "reiterates overweight", "reiterated overweight",
    "reiterates underweight", "reiterated underweight",
    "reiterates outperform", "reiterated outperform",
    "reiterates underperform", "reiterated underperform",
    "reiterates neutral", "reiterated neutral",
    # Maintains with specific rating
    "maintains buy", "maintained buy",
    "maintains sell", "maintained sell",
    "maintains hold", "maintained hold",
    "maintains overweight", "maintained overweight",
    "maintains underweight", "maintained underweight",
    "maintains outperform", "maintained outperform",
    "maintains underperform", "maintained underperform",
    "maintains neutral", "maintained neutral",
]

# Commentary words that LOOK like actions but ARE NOT predictions
# If headline contains these WITHOUT an EXACT_ACTION, it's rejected
COMMENTARY_WORDS = [
    "sees", "faces", "facing",
    "could", "may", "might",
    "wary", "cautious", "confident", "optimistic", "pessimistic",
    "expects", "expected", "believes", "thinks",
    "warns", "warned", "flags", "flagged",
    "notes", "noted", "highlights", "highlighted",
    "points to", "calls attention", "calls into question",
    "eyes", "watching", "monitoring",
    "suggests", "argues", "contends",
    "anticipates", "predicts", "forecasts",
    "views", "considers", "questions",
]

# === ALL 50 REJECTION CATEGORIES ===
REJECT_PATTERNS = [
    # 1. Press releases / partnerships / M&A
    r"signs? (agreement|deal|contract)", r"framework agreement",
    r"partnership", r"strategic alliance", r"joint venture",
    r"acquisition", r"acquires", r"acquired", r"merger", r"merges",
    r"buyout", r"takeover",

    # 2. Past-tense market reports
    r"\b(falls?|fell|drops?|dropped|tumbles?|tumbled|plunges?|plunged|slips?|slipped|slides?|slid|declines?|declined)\b",
    r"\b(spikes?|spiked|surges?|surged|soars?|soared|jumps?|jumped|rallied|rallies|climbs?|climbed)\b",
    r"shares? (rise|rose|fall|fell|drop|dropped|spike|spiked|surge|surged)",
    r"stock (rise|rose|fall|fell|drop|dropped|spike|spiked|surge|surged)",

    # 3. Clickbait questions
    r"\?\s*$",

    # 6. Non-price-target cuts/raises
    r"job cuts?", r"layoffs?", r"workforce reduction", r"job losses",
    r"rate cuts?", r"tax cuts?", r"cost.?cutting", r"spending cuts?",
    r"pay cuts?", r"salary cuts?", r"budget cuts?",

    # 7. Earnings
    r"reports? earnings", r"quarterly results", r"annual results",
    r"earnings (beat|miss|call|report|preview|recap|surprise)",
    r"beats? estimates", r"misses? estimates",
    r"earnings per share", r"EPS of", r"revenue of \$",
    r"what to expect.*earnings", r"ahead of earnings", r"after earnings",

    # 8. Corporate actions
    r"dividend", r"stock split", r"reverse split",
    r"buyback", r"repurchase", r"share repurchase",
    r"appoints?", r"appointed", r"names? .*(CEO|CFO|CTO|COO|CIO)",
    r"hires?", r"hired", r"board of directors",
    r"steps? down", r"resigns?", r"resigned", r"retires?",

    # 9. Product/service upgrades (not stock upgrades)
    r"upgrades? (its|the|their|new|software|hardware|platform|app|system|service|feature|lineup|display|iphone|ipad|mac)",
    r"software update", r"new (version|release|feature|product|model)",
    r"unveils?", r"introduces?", r"rolls? out",

    # 10. Company targets (not price targets)
    r"targets? (same.day|carbon|net.zero|neutrality|delivery|market|users?|growth|revenue|production)",
    r"aims? (to|for)", r"plans? to", r"seeks? to", r"sets? goal",

    # 11. Government/regulatory
    r"SEC (targets?|charges?|investigat|sues?|fines?)",
    r"DOJ", r"FTC", r"antitrust",
    r"FDA (approv|reject|clear|delay)",
    r"regulatory (approv|clear|delay|hurdle)",
    r"sanctions?", r"tariffs?", r"trade war",
    r"clinical trial", r"patent",

    # 12. Credit ratings (not stock ratings)
    r"moody'?s (upgrades?|downgrades?|affirm)",
    r"(fitch|s&p) (upgrades?|downgrades?|affirm)",
    r"credit (rating|outlook)", r"bond (rating|yield)",
    r"sovereign (debt|rating)",

    # 13. Insider activity
    r"(CEO|CFO|CTO|insider|director|officer) (sells?|sold|buys?|bought|dumps?)",
    r"insider (selling|buying|trading)", r"13[FD] filing",

    # 14. Index rebalancing
    r"(added|removed|included|excluded) (to|from|in) .*(S&P|Nasdaq|Russell|Dow|index)",
    r"index (rebalance|reconstitution)",

    # 15. Historical comparisons
    r"last time (this|that)", r"historically",

    # 16. Options activity
    r"unusual (options?|activity)", r"options? (activity|volume|flow)",
    r"(call|put) (volume|buying|selling)",

    # 17. Short interest
    r"short (interest|squeeze|seller)", r"most shorted", r"heavily shorted",

    # 18. Macro/economic
    r"fed (rate|decision|meeting|minutes|chair)",
    r"interest rate (decision|hike|cut)",
    r"inflation (data|report|rate|reading)",
    r"GDP (growth|report|data)", r"unemployment (rate|claims|data)",
    r"economic (data|report|growth|recession|outlook)",
    r"recession (fears?|risk|odds)",

    # 19. Unnamed sources / rumors
    r"according to sources", r"sources say",
    r"rumou?rs?", r"reportedly",

    # 20. Listicles
    r"\d+ (best|top|stocks?|picks?|reasons?) (to|for|why)",
    r"best stocks? (to|for)", r"stocks? to (buy|sell|watch|avoid)",

    # 21. Price milestones
    r"(hits?|reaches?|crosses?|breaks?) .*(high|low|record|milestone)",
    r"all.time (high|low)", r"52.week (high|low)",

    # 22. Comparison articles
    r"\bvs\.?\b", r"\bversus\b", r"which (is|stock) (better|best)",

    # 24. Earnings previews
    r"earnings preview", r"what to (watch|expect|know)",
    r"key (metrics|things|numbers) to watch",

    # 26. Sector rotation
    r"(investors?|money) (rotating|flowing|moving) (into|out of)",
    r"sector (rotation|performance)",

    # 28. Social media buzz
    r"trending on", r"most (discussed|mentioned)",
    r"(retail|reddit|wallstreetbets) (investors?|traders?)",

    # 30. Management commentary
    r"(CEO|CFO|CTO|chief|founder|chairman) (says?|said|told|sees?|expects?|believes?)",
    r"management (says?|sees?|expects?|commentary)",

    # 31. Dividend articles
    r"(high|best|top).yield", r"dividend (stock|aristocrat)",
    r"passive income",

    # 32. IPO/SPAC
    r"\bIPO\b", r"\bSPAC\b", r"goes? public", r"direct listing",

    # 33. Crypto infrastructure
    r"(bitcoin|btc) (mining|hash.?rate|halving)",
    r"(blockchain|defi|nft|stablecoin) (launch|update)",

    # 34. Geopolitical
    r"(war|conflict|invasion) .*(impact|affect)",
    r"geopolitical (risk|tension)",

    # 36. Buyback programs
    r"\$[\d.]+ ?(billion|million|B|M) (buyback|repurchase)",

    # 37. Conference/event
    r"(presents?|speaks?) at .* conference",
    r"investor (day|conference|presentation)",

    # 39. General advice
    r"buy the dip", r"time to buy", r"should (you|investors?) (buy|sell)",

    # 40. Estimates without recommendation
    r"(consensus|analyst) estimate",

    # 41. ETF flows
    r"(inflows?|outflows?) (into|from|of)", r"fund flows?",

    # 42. M&A rumors
    r"(could|may|might) (be )?acquired", r"(buyout|takeover) (rumou?r|speculation)",

    # 43. Company guidance
    r"(guides?|guidance) .*(revenue|earnings|EPS)",
    r"(full.year|quarterly|annual) (guidance|outlook)",

    # 44. Price reaction
    r"(rises?|falls?|drops?|gains?|loses?) .*(%|percent) (after|on|following|amid)",

    # 45. Awards
    r"(named|awarded|recognized) .*(most|best|top|fortune)",

    # 46. Supply chain
    r"supply chain", r"(shortage|disruption|bottleneck)",

    # 47. Legal
    r"(lawsuit|sues?|sued|litigation|settlement|settles?)",
    r"(fined?|penalty|investigation|probe|subpoena)",

    # 48. Technical analysis without analyst
    r"(golden|death) cross", r"(RSI|MACD|moving average|bollinger)",
    r"(support|resistance) (level|at)", r"(overbought|oversold)",
    r"(technical|chart) (analysis|pattern|signal)",

    # 49. Analyst commentary without action
    r"(sees?|views?) .* as (transformational|disruptive|opportunity|risk)",

    # 50. Hypotheticals
    r"if .* (hits?|reaches?|falls? to|drops? to)",
    r"here'?s what (happens|it means)",
    r"(scenario|case) (analysis|study)",
]

# Sentiment-only phrases — opinions, NOT measurable predictions
SENTIMENT_ONLY = [
    "wary of", "confident of", "cautious on", "optimistic about",
    "pessimistic about", "constructive on", "warming to", "cooling on",
    "skeptical of", "concerned about", "comfortable with", "uncomfortable with",
    "excited about", "enthusiastic about", "remains positive", "remains cautious",
    "remains neutral", "positive on", "negative on",
    "favors", "likes", "prefers", "sees value in", "sees opportunity in",
    "sees upside potential", "sees downside risk",
    "could rally", "could decline", "could bounce", "could fall",
    "may outperform", "may underperform", "might bounce", "might fall",
    "believes", "thinks", "feels", "suggests", "argues", "expects",
    "considers", "anticipates",
    "looks attractive", "looks expensive", "looks cheap",
    "well positioned", "poorly positioned",
    "strong fundamentals", "weak fundamentals",
    "headwinds", "tailwinds",
]

# Strong actions that override sentiment
STRONG_ACTIONS = [
    "upgrades", "upgraded", "downgrades", "downgraded",
    "raises price target", "raised price target",
    "lowers price target", "lowered price target",
    "cuts price target", "cut price target",
    "initiates coverage", "initiated coverage",
    "price target of $", "price target to $",
]

# Bullish signals — direction scoring
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
    "lowers", "lowered", "cuts", "cut", "slashes", "slashed",
    "reiterates sell", "reiterated sell",
    "reiterates underweight", "reiterated underweight",
    "reiterates underperform", "reiterated underperform",
    "maintains sell", "maintained sell",
    "maintains underweight", "maintained underweight",
    "strong sell",
    "sell", "underweight", "underperform",
]

# Platform names — NEVER use as forecaster
PLATFORMS = [
    "yahoo finance", "seeking alpha", "seekingalpha", "marketwatch",
    "cnbc", "bloomberg", "reuters", "financial times", "ft.com",
    "business insider", "forbes", "kiplinger", "the economist",
    "benzinga", "investorplace", "thestreet", "tipranks",
    "youtube", "twitter", "x.com", "access newswire",
    "globe newswire", "pr newswire", "business wire",
]

# Known analyst/firm names
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

# Canonical name -> all known aliases (lowercase)
FORECASTER_ALIASES = {
    "Bernstein": ["bernstein", "sanford bernstein", "sanford c. bernstein", "ab bernstein", "alliance bernstein", "alliancebernstein"],
    "Goldman Sachs": ["goldman sachs", "goldman"],
    "JP Morgan": ["jp morgan", "jpmorgan", "j.p. morgan", "j.p.morgan"],
    "Morgan Stanley": ["morgan stanley"],
    "Bank Of America": ["bank of america", "bofa", "bofa securities", "merrill lynch", "merrill"],
    "Citi": ["citi", "citigroup", "citibank", "citi research"],
    "Deutsche Bank": ["deutsche bank", "db securities"],
    "UBS": ["ubs", "ubs group", "ubs securities"],
    "Barclays": ["barclays", "barclays capital"],
    "Wells Fargo": ["wells fargo", "wells fargo securities"],
    "HSBC": ["hsbc", "hsbc securities", "hsbc global"],
    "Credit Suisse": ["credit suisse"],
    "Jefferies": ["jefferies", "jefferies group"],
    "Raymond James": ["raymond james", "raymond james financial"],
    "Needham": ["needham", "needham & company", "needham and company"],
    "Wedbush": ["wedbush", "wedbush securities", "wedbush morgan"],
    "Piper Sandler": ["piper sandler", "piper", "piper jaffray"],
    "Cowen": ["cowen", "cowen and company", "td cowen"],
    "Oppenheimer": ["oppenheimer", "oppenheimer & co", "oppenheimer holdings"],
    "Stifel": ["stifel", "stifel nicolaus", "stifel financial"],
    "Baird": ["baird", "robert w. baird", "robert baird", "rw baird"],
    "KeyBanc": ["keybanc", "keybanc capital", "keybanc capital markets"],
    "BMO Capital": ["bmo capital", "bmo", "bmo capital markets"],
    "RBC Capital": ["rbc capital", "rbc", "rbc capital markets"],
    "Evercore": ["evercore", "evercore isi"],
    "Wolfe Research": ["wolfe research", "wolfe"],
    "Loop Capital": ["loop capital", "loop capital markets"],
    "Truist": ["truist", "truist securities", "truist financial"],
    "Mizuho": ["mizuho", "mizuho securities", "mizuho financial"],
    "Susquehanna": ["susquehanna", "susquehanna financial", "susquehanna international"],
    "Rosenblatt": ["rosenblatt", "rosenblatt securities"],
    "Canaccord": ["canaccord", "canaccord genuity"],
    "Guggenheim": ["guggenheim", "guggenheim securities", "guggenheim partners"],
    "Macquarie": ["macquarie", "macquarie group", "macquarie capital"],
    "Scotiabank": ["scotiabank", "scotia capital", "scotia"],
    "William Blair": ["william blair"],
    "B. Riley": ["b. riley", "b riley", "b. riley securities", "b riley financial"],
    "Argus Research": ["argus", "argus research"],
    "CFRA": ["cfra", "cfra research"],
    "New Street Research": ["new street", "new street research"],
    "H.C. Wainwright": ["h.c. wainwright", "hc wainwright", "wainwright"],
    "Roth Capital": ["roth capital", "roth", "roth mkm", "roth/mkm"],
    "Lake Street": ["lake street", "lake street capital"],
    "Craig-Hallum": ["craig-hallum", "craig hallum"],
    "Benchmark": ["benchmark", "benchmark company"],
    "D.A. Davidson": ["d.a. davidson", "da davidson"],
    "Cathie Wood": ["cathie wood", "cathy wood", "cathie woods"],
    "Jim Cramer": ["jim cramer", "cramer"],
    "Dan Ives": ["dan ives", "daniel ives"],
    "Tom Lee": ["tom lee", "thomas lee"],
    "Michael Burry": ["michael burry", "burry"],
    "Ray Dalio": ["ray dalio", "dalio"],
    "Bill Ackman": ["bill ackman", "ackman", "pershing square"],
    "Warren Buffett": ["warren buffett", "buffett", "berkshire"],
    "ARK Invest": ["ark invest", "ark innovation", "arkk"],
    "Fundstrat": ["fundstrat", "fundstrat global", "fundstrat global advisors"],
    "Morningstar": ["morningstar"],
    "Zacks": ["zacks", "zacks investment", "zacks investment research"],
    "S&P Global": ["s&p global", "standard and poor", "standard & poor"],
}


def resolve_forecaster_alias(name):
    """Given any variation of a firm name, return the canonical name."""
    if not name:
        return None
    name_lower = name.lower().strip()
    for canonical, aliases in FORECASTER_ALIASES.items():
        if name_lower in aliases or name_lower == canonical.lower():
            return canonical
    return name


# Company names that are NOT forecasters
COMPANY_NAMES = [
    "apple", "microsoft", "google", "alphabet", "amazon", "nvidia", "tesla", "meta",
    "netflix", "adobe", "salesforce", "amd", "intel", "qualcomm", "broadcom",
    "walmart", "costco", "disney", "boeing", "caterpillar",
    "nike", "starbucks", "mcdonalds", "coca-cola", "pepsi", "procter",
    "exxon", "chevron", "pfizer", "johnson", "merck", "abbvie",
    "honeywell", "lockheed", "raytheon", "general electric",
    "palantir", "snowflake", "crowdstrike", "coinbase", "rivian",
    "uber", "lyft", "airbnb", "doordash", "snap", "pinterest",
    "moderna", "biontech", "regeneron", "gilead",
]


def is_real_prediction(headline, summary=""):
    """Layer 1: Maximum strictness — must contain an EXACT action phrase."""
    combined = (headline + " " + summary).lower()

    # Check all 50 rejection categories
    for pattern in REJECT_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            return False

    # MUST contain at least one EXACT action phrase. No exceptions.
    has_exact_action = any(a in combined for a in EXACT_ACTIONS)
    if not has_exact_action:
        return False

    # If commentary words are present, the exact action must ALSO be present
    # (already guaranteed by the check above, but reject if ONLY commentary)
    has_commentary = any(c in combined for c in COMMENTARY_WORDS)
    if has_commentary and not has_exact_action:
        return False

    return True


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
    """Extract REAL analyst/firm name. Returns canonical name via aliases."""
    combined = (headline + " " + source).lower()

    # Check all aliases — return canonical name
    for canonical, aliases in FORECASTER_ALIASES.items():
        for alias in aliases:
            if alias in combined:
                return canonical

    # Fallback: check KNOWN_ANALYSTS (for names not in aliases)
    for name in KNOWN_ANALYSTS:
        if name in combined:
            return resolve_forecaster_alias(name.title())

    # Regex: "{Multi-Word Firm} upgrades/downgrades..."
    match = re.search(
        r"^([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)+)\s+"
        r"(?:upgrades?|downgrades?|initiates?|reiterates?|maintains?|raises?|lowers?|cuts?|sets?|boosts?)",
        headline,
    )
    if match:
        firm = match.group(1).strip()
        if (" " in firm
                and firm.lower() not in PLATFORMS
                and firm.lower() not in COMPANY_NAMES
                and len(firm) > 4):
            return resolve_forecaster_alias(firm)

    # Passive pattern: "AAPL downgraded at {Firm}" or "AAPL upgraded by {Firm}"
    match2 = re.search(
        r"(?:upgraded|downgraded|initiated) (?:at|by) ([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)",
        headline,
    )
    if match2:
        firm = match2.group(1).strip()
        if (firm.lower() not in COMPANY_NAMES
                and firm.lower() not in PLATFORMS
                and len(firm) > 3):
            if firm.lower() in KNOWN_ANALYSTS or " " in firm:
                return resolve_forecaster_alias(firm)

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

    r = db.execute(sql_text("""
        DELETE FROM predictions WHERE
            source_url IS NULL OR source_url = '' OR source_url NOT LIKE 'http%'
            OR source_url LIKE '%yahoo.com/quote%'
            OR source_url LIKE '%stockanalysis.com%'
    """))
    deleted += r.rowcount

    r = db.execute(sql_text("""
        DELETE FROM predictions WHERE
            context LIKE 'Analyst consensus:%'
            OR context LIKE 'Price target for%'
            OR exact_quote LIKE '<%'
    """))
    deleted += r.rowcount

    r = db.execute(sql_text("""
        DELETE FROM predictions WHERE
            ticker IS NULL OR ticker = '' OR ticker = 'UNKNOWN'
            OR direction IS NULL OR direction = ''
            OR direction NOT IN ('bullish', 'bearish')
    """))
    deleted += r.rowcount

    r = db.execute(sql_text("""
        DELETE FROM predictions WHERE
            context LIKE '%?'
            OR LOWER(context) LIKE '%job cuts%'
            OR LOWER(context) LIKE '%layoff%'
            OR LOWER(context) LIKE '%signs agreement%'
            OR LOWER(context) LIKE '%framework agreement%'
            OR LOWER(context) LIKE '%reports earnings%'
            OR LOWER(context) LIKE '%quarterly results%'
            OR LOWER(context) LIKE '%appoints%'
            OR LOWER(context) LIKE '%production capacity%'
            OR LOWER(context) LIKE '%rate cut%'
            OR LOWER(context) LIKE '%tax cut%'
            OR LOWER(context) LIKE '%all-time high%'
            OR LOWER(context) LIKE '%hits record%'
            OR LOWER(context) LIKE '%ipo%'
            OR LOWER(context) LIKE '%goes public%'
            OR LOWER(context) LIKE '%buy the dip%'
            OR LOWER(context) LIKE '%unusual options%'
            OR LOWER(context) LIKE '%short interest%'
            OR LOWER(context) LIKE '%short squeeze%'
    """))
    deleted += r.rowcount

    # Sentiment/commentary without real action
    r = db.execute(sql_text("""
        DELETE FROM predictions WHERE
            (LOWER(context) LIKE '%wary of%' OR LOWER(context) LIKE '%confident of%'
             OR LOWER(context) LIKE '%cautious on%' OR LOWER(context) LIKE '%optimistic about%'
             OR LOWER(context) LIKE '%pessimistic about%' OR LOWER(context) LIKE '%skeptical of%'
             OR LOWER(context) LIKE '%concerned about%' OR LOWER(context) LIKE '%warming to%'
             OR LOWER(context) LIKE '%cooling on%'
             OR LOWER(context) LIKE '% sees %' OR LOWER(context) LIKE '% faces %'
             OR LOWER(context) LIKE '% facing %' OR LOWER(context) LIKE '% warns %'
             OR LOWER(context) LIKE '% flags %' OR LOWER(context) LIKE '% eyes %'
             OR LOWER(context) LIKE '% expects %' OR LOWER(context) LIKE '% believes %'
             OR LOWER(context) LIKE '% could %' OR LOWER(context) LIKE '% may %'
             OR LOWER(context) LIKE '% might %' OR LOWER(context) LIKE '% highlights %'
             OR LOWER(context) LIKE '% notes %')
            AND LOWER(context) NOT LIKE '%upgrades to%'
            AND LOWER(context) NOT LIKE '%downgrades to%'
            AND LOWER(context) NOT LIKE '%upgraded to%'
            AND LOWER(context) NOT LIKE '%downgraded to%'
            AND LOWER(context) NOT LIKE '%upgraded at%'
            AND LOWER(context) NOT LIKE '%downgraded at%'
            AND LOWER(context) NOT LIKE '%price target%'
            AND LOWER(context) NOT LIKE '%initiates coverage%'
            AND LOWER(context) NOT LIKE '%maintains buy%'
            AND LOWER(context) NOT LIKE '%maintains sell%'
            AND LOWER(context) NOT LIKE '%reiterates buy%'
            AND LOWER(context) NOT LIKE '%reiterates sell%'
    """))
    deleted += r.rowcount

    db.commit()
    if deleted > 0:
        print(f"[Defense L3] Cleaned up {deleted} invalid predictions")
    return deleted

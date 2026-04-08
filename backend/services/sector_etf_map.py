"""Map sector keywords to the ETF that tracks them.

Used by the sector_call prediction type. When Haiku extracts a sector
phrase from a tweet ("semis are going to rip"), this module resolves
the phrase to a tradeable ETF proxy ("SOXX") so the evaluator can
score the call against real prices.
"""

# Canonical sector → ETF mapping. Keys must be lowercase. Multiple keys
# can map to the same ETF (synonyms). Add new entries cautiously and
# only when the mapping is unambiguous and tradeable on US exchanges.
SECTOR_ETF_MAP: dict[str, str] = {
    # Technology
    "tech": "XLK",
    "technology": "XLK",
    "tech sector": "XLK",
    "tech stocks": "XLK",
    # Semiconductors (sub-sector — more specific than tech)
    "semis": "SOXX",
    "semiconductors": "SOXX",
    "chips": "SOXX",
    "chip stocks": "SOXX",
    "semiconductor": "SOXX",
    "semiconductor stocks": "SOXX",
    # Financials
    "financials": "XLF",
    "banks": "XLF",
    "financial sector": "XLF",
    "big banks": "XLF",
    "regional banks": "KRE",
    "regionals": "KRE",
    "regional bank": "KRE",
    # Energy
    "energy": "XLE",
    "oil": "XLE",
    "oil stocks": "XLE",
    "energy sector": "XLE",
    "oil and gas": "XLE",
    "energy stocks": "XLE",
    # Healthcare
    "healthcare": "XLV",
    "health care": "XLV",
    "pharma": "XLV",
    "pharmaceutical": "XLV",
    "biotech": "XBI",
    "biotechs": "XBI",
    "biotech stocks": "XBI",
    # Consumer
    "consumer": "XLY",
    "consumer discretionary": "XLY",
    "discretionary": "XLY",
    "retail": "XLY",
    "retail stocks": "XLY",
    "consumer staples": "XLP",
    "staples": "XLP",
    # Industrials
    "industrials": "XLI",
    "industrial": "XLI",
    "industrial stocks": "XLI",
    # Utilities
    "utilities": "XLU",
    "utes": "XLU",
    "utility stocks": "XLU",
    # Real estate
    "real estate": "XLRE",
    "reits": "XLRE",
    "reit": "XLRE",
    "homebuilders": "XHB",
    "housing": "XHB",
    "home builders": "XHB",
    "homebuilder": "XHB",
    # Materials
    "materials": "XLB",
    "basic materials": "XLB",
    "raw materials": "XLB",
    # Communication services
    "communication services": "XLC",
    "communications": "XLC",
    "comms": "XLC",
    "media": "XLC",
    # Broad market (used as the SPY benchmark inside the scorer; also
    # accepted as a fallback if Haiku returns "the market")
    "market": "SPY",
    "stocks": "SPY",
    "equities": "SPY",
    "the market": "SPY",
    "broad market": "SPY",
    "s&p": "SPY",
    "s&p 500": "SPY",
    "spx": "SPY",
}


def resolve_sector_to_etf(sector_phrase: str) -> str | None:
    """Normalize a sector phrase and return its ETF proxy, or None.

    Returns None if the phrase is empty or unrecognized. The caller is
    responsible for rejecting the prediction (with reason='sector_etf_unknown')
    when None comes back.
    """
    if not sector_phrase:
        return None
    normalized = sector_phrase.strip().lower()
    if not normalized:
        return None
    return SECTOR_ETF_MAP.get(normalized)


# Pre-computed lowercase sorted-by-length-desc list used by the validator
# to detect "did the sector phrase appear literally in the tweet?". Sorting
# by length desc ensures multi-word phrases are matched before single-word
# substrings (e.g. "regional banks" matches before "banks").
_SECTOR_PHRASES_BY_LEN = sorted(SECTOR_ETF_MAP.keys(), key=len, reverse=True)


def find_sector_phrase_in_text(text: str) -> str | None:
    """Return the longest sector phrase that appears literally in the text.

    Used as a defense-in-depth check against Haiku hallucinating sectors.
    Case-insensitive whole-substring match. Returns None if no recognized
    sector phrase is present.
    """
    if not text:
        return None
    lower = text.lower()
    for phrase in _SECTOR_PHRASES_BY_LEN:
        if phrase in lower:
            return phrase
    return None

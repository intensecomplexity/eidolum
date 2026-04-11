"""Canonical sector taxonomy.

Every user-facing "sector" label must be one of the 11 Morningstar
sectors (or the permitted "Unknown" fallback). The tickers table
historically holds a mixed bag of raw SIC industry descriptions
("SERVICES-VIDEO TAPE RENTAL"), GICS sub-industries
("Life Sciences Tools & Services"), and Morningstar-style strings
— this helper maps any of those into the allowed set so the
frontend never renders a leaked SIC blob as a sector chip.

Callers:
  - routers/assets.py (ticker/asset consensus endpoint)
  - routers/forecasters.py (sector chips + sector_count)
  - routers/community.py (consensus endpoint)
  - routers/smart_money.py (card sector badge)

Do NOT drop the raw column from the DB — it is still useful for
research/backfill. Only canonicalize on the way out of the API.
"""
from __future__ import annotations

# The 11 Morningstar sectors. Nothing outside this set should render
# as a user-facing sector chip.
MORNINGSTAR_SECTORS: tuple[str, ...] = (
    "Technology",
    "Healthcare",
    "Financial Services",
    "Energy",
    "Consumer Cyclical",
    "Consumer Defensive",
    "Industrials",
    "Communication Services",
    "Real Estate",
    "Utilities",
    "Basic Materials",
)

UNKNOWN_SECTOR = "Unknown"

ALLOWED_SECTORS: tuple[str, ...] = MORNINGSTAR_SECTORS + (UNKNOWN_SECTOR,)
_ALLOWED_LOWER = {s.lower(): s for s in ALLOWED_SECTORS}

# Explicit mapping for leaked SIC / GICS / Yahoo sub-industry strings we
# have observed in production. Keep keys lower-cased for case-insensitive
# matching. Values MUST be one of MORNINGSTAR_SECTORS.
RAW_SECTOR_ALIASES: dict[str, str] = {
    # The specific leaks surfaced during the Ship #13 sweep
    "services-video tape rental": "Communication Services",
    "service-video tape rental": "Communication Services",
    "motor vehicles & passenger car bodies": "Consumer Cyclical",
    "consumer products": "Consumer Defensive",
    "professional services": "Industrials",
    "packaging": "Industrials",
    "communications": "Communication Services",
    "life sciences tools & services": "Healthcare",
    "marine": "Industrials",
    "commercial services & supplies": "Industrials",
    "building": "Industrials",
    "diversified consumer services": "Consumer Cyclical",

    # Other commonly-observed SIC / GICS strings
    "consumer goods": "Consumer Defensive",
    "consumer services": "Consumer Cyclical",
    "consumer discretionary": "Consumer Cyclical",
    "consumer staples": "Consumer Defensive",
    "financial": "Financial Services",
    "financials": "Financial Services",
    "banking": "Financial Services",
    "banks": "Financial Services",
    "insurance": "Financial Services",
    "diversified financials": "Financial Services",
    "capital markets": "Financial Services",
    "real estate investment trusts": "Real Estate",
    "reits": "Real Estate",
    "basic resources": "Basic Materials",
    "materials": "Basic Materials",
    "chemicals": "Basic Materials",
    "metals & mining": "Basic Materials",
    "paper & forest products": "Basic Materials",
    "oil & gas": "Energy",
    "oil, gas & consumable fuels": "Energy",
    "energy equipment & services": "Energy",
    "health care": "Healthcare",
    "health care equipment & services": "Healthcare",
    "pharmaceuticals": "Healthcare",
    "pharmaceuticals, biotechnology & life sciences": "Healthcare",
    "biotechnology": "Healthcare",
    "biotech": "Healthcare",
    "medical devices": "Healthcare",
    "technology hardware & equipment": "Technology",
    "software & services": "Technology",
    "semiconductors & semiconductor equipment": "Technology",
    "information technology": "Technology",
    "it": "Technology",
    "telecommunication services": "Communication Services",
    "telecommunications": "Communication Services",
    "telecom": "Communication Services",
    "media": "Communication Services",
    "media & entertainment": "Communication Services",
    "entertainment": "Communication Services",
    "capital goods": "Industrials",
    "transportation": "Industrials",
    "commercial & professional services": "Industrials",
    "automobiles & components": "Consumer Cyclical",
    "automobile": "Consumer Cyclical",
    "retail": "Consumer Cyclical",
    "retailing": "Consumer Cyclical",
    "food & staples retailing": "Consumer Defensive",
    "food, beverage & tobacco": "Consumer Defensive",
    "household & personal products": "Consumer Defensive",
    "utility": "Utilities",
    "household products": "Consumer Defensive",

    # Non-Morningstar bucket labels the pipeline sometimes emits
    "crypto": UNKNOWN_SECTOR,
    "index": UNKNOWN_SECTOR,
    "other": UNKNOWN_SECTOR,
    "n/a": UNKNOWN_SECTOR,
    "unknown": UNKNOWN_SECTOR,
    "": UNKNOWN_SECTOR,
}

# Substring fallback — catches raw SIC strings we haven't explicitly
# mapped. Order matters: the first matching rule wins, so put the most
# specific patterns first (e.g. "oil & gas" before "gas").
_SUBSTRING_RULES: tuple[tuple[str, str], ...] = (
    ("pharmaceutical", "Healthcare"),
    ("biotech", "Healthcare"),
    ("biological", "Healthcare"),
    ("medical", "Healthcare"),
    ("hospital", "Healthcare"),
    ("health", "Healthcare"),
    ("drug", "Healthcare"),
    ("life science", "Healthcare"),
    ("semiconductor", "Technology"),
    ("software", "Technology"),
    ("computer", "Technology"),
    ("internet", "Technology"),
    ("data processing", "Technology"),
    ("technology", "Technology"),
    ("electronic", "Technology"),
    ("petroleum", "Energy"),
    ("oil & gas", "Energy"),
    ("oil and gas", "Energy"),
    ("coal", "Energy"),
    ("energy", "Energy"),
    ("bank", "Financial Services"),
    ("insurance", "Financial Services"),
    ("credit", "Financial Services"),
    ("broker", "Financial Services"),
    ("asset management", "Financial Services"),
    ("financial", "Financial Services"),
    ("reit", "Real Estate"),
    ("real estate", "Real Estate"),
    ("realty", "Real Estate"),
    ("electric", "Utilities"),
    ("natural gas distribution", "Utilities"),
    ("water utility", "Utilities"),
    ("utility", "Utilities"),
    ("utilities", "Utilities"),
    ("chemical", "Basic Materials"),
    ("metal", "Basic Materials"),
    ("mining", "Basic Materials"),
    ("paper", "Basic Materials"),
    ("steel", "Basic Materials"),
    ("aluminum", "Basic Materials"),
    ("material", "Basic Materials"),
    ("telecom", "Communication Services"),
    ("broadcasting", "Communication Services"),
    ("publishing", "Communication Services"),
    ("cable", "Communication Services"),
    ("movie", "Communication Services"),
    ("video", "Communication Services"),
    ("entertainment", "Communication Services"),
    ("media", "Communication Services"),
    ("communication", "Communication Services"),
    ("advertising", "Communication Services"),
    ("motor vehicle", "Consumer Cyclical"),
    ("automobile", "Consumer Cyclical"),
    ("auto part", "Consumer Cyclical"),
    ("apparel", "Consumer Cyclical"),
    ("footwear", "Consumer Cyclical"),
    ("restaurant", "Consumer Cyclical"),
    ("leisure", "Consumer Cyclical"),
    ("lodging", "Consumer Cyclical"),
    ("hotel", "Consumer Cyclical"),
    ("retail", "Consumer Cyclical"),
    ("home building", "Consumer Cyclical"),
    ("luxury", "Consumer Cyclical"),
    ("consumer discretionary", "Consumer Cyclical"),
    ("consumer cyclical", "Consumer Cyclical"),
    ("grocery", "Consumer Defensive"),
    ("food", "Consumer Defensive"),
    ("beverage", "Consumer Defensive"),
    ("tobacco", "Consumer Defensive"),
    ("household", "Consumer Defensive"),
    ("personal product", "Consumer Defensive"),
    ("consumer defensive", "Consumer Defensive"),
    ("consumer staples", "Consumer Defensive"),
    ("aerospace", "Industrials"),
    ("defense", "Industrials"),
    ("machinery", "Industrials"),
    ("construction", "Industrials"),
    ("airlines", "Industrials"),
    ("railroad", "Industrials"),
    ("shipping", "Industrials"),
    ("trucking", "Industrials"),
    ("logistics", "Industrials"),
    ("industrial", "Industrials"),
    ("transportation", "Industrials"),
    ("engineering", "Industrials"),
    ("services-", "Industrials"),  # generic SIC "services-foo" catchall
)


def canonical_sector(raw: str | None) -> str:
    """Return the Morningstar-canonical sector for a raw sector string.

    Input is typically read from ``tickers.sector`` or a SIC description.
    Output is always one of :data:`ALLOWED_SECTORS` (the 11 Morningstar
    sectors plus ``"Unknown"``).

    The match is case-insensitive. We try, in order:
      1. Exact-match against the allowed set
      2. Explicit alias lookup (``RAW_SECTOR_ALIASES``)
      3. Substring rule fallback (``_SUBSTRING_RULES``)
      4. ``"Unknown"`` if nothing matches
    """
    if raw is None:
        return UNKNOWN_SECTOR
    s = str(raw).strip().lower()
    if not s:
        return UNKNOWN_SECTOR
    allowed = _ALLOWED_LOWER.get(s)
    if allowed:
        return allowed
    alias = RAW_SECTOR_ALIASES.get(s)
    if alias:
        return alias
    for substr, sector in _SUBSTRING_RULES:
        if substr in s:
            return sector
    return UNKNOWN_SECTOR


def canonical_sectors_distinct(raws) -> set[str]:
    """Return the set of distinct canonical sectors from an iterable of
    raw strings. Excludes ``Unknown`` so a forecaster whose tickers all
    map to Unknown doesn't inflate the sector count.
    """
    out = set()
    for r in raws:
        c = canonical_sector(r)
        if c != UNKNOWN_SECTOR:
            out.add(c)
    return out

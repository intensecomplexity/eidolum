"""Post-classifier validation gate.

Rejects garbage predictions before they become rows in `predictions`.
Six rules, run in order by `validate_or_reject`. Each rule is an
independently unit-testable function returning ``(accepted, reason)``.

Schema notes (verified 2026-05-16):
  * There is no `stock_prices` table. Ticker-realness uses `ticker_sectors`
    (~12k rows; ticker -> company_name), which is the populated reference.
  * `predictions.context` is a templated label ("Channel: Bull/Bear on
    TICKER"), NOT the analyst's words. The real quoted text is
    `source_verbatim_quote`. All text rules (2/3/4/6) therefore operate on
    the verbatim quote, not `context`.

This module performs only read-only DB queries — never writes. Rule 5
detects contradictions; the caller (youtube_classifier) performs the
`excluded_from_training` write via `contradicting_ids()`.
"""
import re
from sqlalchemy import text

# exclusion_rule_version is varchar(16) — keep <=16 chars.
RULE_VERSION = "classifier_gate"

# reason code -> telemetry counter key (Step 4 cycle stats line)
TELEMETRY_KEYS = {
    "invalid_ticker": "invalid_ticker",
    "ticker_not_in_context": "ticker_not_in_context",
    "ad_read": "ad_read",
    "past_tense_only": "past_tense",
    "contradictory_pair": "contradictory",
    "context_too_short": "context_short",
}

_CORP_SUFFIXES = {
    "inc", "inc.", "incorporated", "corp", "corp.", "corporation",
    "co", "co.", "company", "companies", "ltd", "ltd.", "llc",
    "plc", "holdings", "group", "sa", "ag", "nv", "the",
}


def _clean_name(company_name):
    """Derive a short, matchable name: 'Lowe's Companies, Inc.' -> "Lowe's",
    'AXT Inc' -> 'AXT', 'Alphabet Inc.' -> 'Alphabet'."""
    if not company_name:
        return None
    base = company_name.split(",")[0].strip()
    words = base.split()
    while words and words[-1].lower().strip(".") in _CORP_SUFFIXES:
        words.pop()
    cleaned = " ".join(words).strip()
    return cleaned or None


def _ticker_names(ticker, db):
    """All matchable names for a ticker: company_name, its cleaned form,
    and every alias from company_name_aliases. Lower-cased, >=3 chars."""
    if not ticker:
        return []
    t = ticker.upper().strip()
    names = set()
    row = db.execute(
        text("SELECT company_name FROM ticker_sectors WHERE ticker=:t LIMIT 1"),
        {"t": t},
    ).first()
    if row and row[0]:
        names.add(row[0].strip())
        cn = _clean_name(row[0])
        if cn:
            names.add(cn)
    for r in db.execute(
        text("SELECT alias FROM company_name_aliases WHERE ticker=:t"),
        {"t": t},
    ).fetchall():
        if r[0]:
            names.add(r[0].strip())
    return [n.lower() for n in names if n and len(n) >= 3]


def _word_in(needle, haystack_lower):
    """Case-insensitive word-boundary match of `needle` inside a
    already-lower-cased haystack."""
    if not needle:
        return False
    return re.search(r"\b" + re.escape(needle.lower()) + r"\b",
                     haystack_lower) is not None


# ── Rule 1 ────────────────────────────────────────────────────────────────
def check_ticker_real(ticker, db):
    """Ticker must exist in `ticker_sectors` with a non-NULL company_name.
    Placeholder pseudo-tickers (MACRO, INDEX, ...) have a NULL name."""
    if not ticker or not ticker.strip():
        return False, "invalid_ticker"
    row = db.execute(
        text("SELECT 1 FROM ticker_sectors "
             "WHERE ticker=:t AND company_name IS NOT NULL LIMIT 1"),
        {"t": ticker.upper().strip()},
    ).first()
    return (True, None) if row else (False, "invalid_ticker")


# ── Rule 2 ────────────────────────────────────────────────────────────────
def check_ticker_in_quote(ticker, quote, db):
    """The ticker symbol OR the company name/alias must appear in the
    verbatim quote. Catches wrong-ticker misattribution (e.g. LOW assigned
    to a Home Depot segment). When no quote is available, accept — a
    missing quote can't prove misattribution."""
    if not quote or not quote.strip():
        return True, None
    q = quote.lower()
    t = (ticker or "").upper().strip()
    if not t:
        return False, "ticker_not_in_context"
    if _word_in(t, q):
        return True, None
    for name in _ticker_names(ticker, db):
        if _word_in(name, q):
            return True, None
    return False, "ticker_not_in_context"


# ── Rule 3 ────────────────────────────────────────────────────────────────
_AD_PATTERNS = [
    re.compile(r"\b(sponsored|sponsor) (of|by|today|this video|this episode)\b", re.I),
    re.compile(r"\b(today.{0,10}sponsor|brought to you by)\b", re.I),
    re.compile(r"\b(use code|promo code|use my link|use the link)\b", re.I),
    re.compile(r"\b(sign up at|head over to|head to|check out)\s+\w+\.(com|io|net)\b", re.I),
    re.compile(r"\b(limited time|special offer|first month free|discount code)\b", re.I),
    re.compile(r"\b(this episode is brought|episode sponsor)\b", re.I),
]


def check_ad_read(quote):
    """Reject sponsor/ad-read segments. Operates on the verbatim quote —
    ad copy never appears in the templated `context`."""
    if not quote:
        return True, None
    for pat in _AD_PATTERNS:
        if pat.search(quote):
            return False, "ad_read"
    return True, None


# ── Rule 4 ────────────────────────────────────────────────────────────────
_PAST_MARKERS = [
    re.compile(r"\breported\b", re.I), re.compile(r"\bposted\b", re.I),
    re.compile(r"\bannounced\b", re.I), re.compile(r"\bdelivered\b", re.I),
    re.compile(r"\breleased\b", re.I), re.compile(r"\bearnings beat\b", re.I),
    re.compile(r"\bbeat estimates\b", re.I), re.compile(r"\bmissed estimates\b", re.I),
    re.compile(r"\bgrew \d+%", re.I), re.compile(r"\bincreased to \$", re.I),
]
_FORWARD_MARKERS = [
    re.compile(r"\bexpect", re.I), re.compile(r"\bwill\b", re.I),
    re.compile(r"\bgoing to\b", re.I), re.compile(r"\btarget\b", re.I),
    re.compile(r"\bby (q\d|year|month)", re.I), re.compile(r"\bnext quarter\b", re.I),
    re.compile(r"\bcould reach\b", re.I), re.compile(r"\bi think\b", re.I),
    re.compile(r"\bi believe\b", re.I), re.compile(r"\bpredict", re.I),
]


def check_past_tense(quote):
    """Reject pure past-tense news reporting: a past marker present AND no
    forward-looking marker anywhere in the quote."""
    if not quote:
        return True, None
    if not any(p.search(quote) for p in _PAST_MARKERS):
        return True, None
    if any(p.search(quote) for p in _FORWARD_MARKERS):
        return True, None
    return False, "past_tense_only"


# ── Rule 5 ────────────────────────────────────────────────────────────────
def contradicting_ids(source_url, direction, ticker, db,
                      ref_time=None, exclude_id=None):
    """Read-only: ids of opposite-direction predictions for the same
    source_url AND the same ticker within 60 minutes. Scoping by ticker is
    essential — a roundup video that is bullish on one stock and bearish on
    another is not a contradiction. `ref_time` defaults to NOW() (live
    inserts); pass a row's created_at for backtesting historical data."""
    if not source_url or not ticker or direction not in ("bullish", "bearish"):
        return []
    opposite = "bearish" if direction == "bullish" else "bullish"
    params = {"u": source_url, "d": opposite, "tk": ticker.upper().strip(),
              "x": exclude_id or -1}
    if ref_time is None:
        sql = ("SELECT id FROM predictions WHERE source_url=:u AND direction=:d "
               "AND ticker=:tk AND id<>:x "
               "AND created_at >= NOW() - INTERVAL '60 minutes'")
    else:
        sql = ("SELECT id FROM predictions WHERE source_url=:u AND direction=:d "
               "AND ticker=:tk AND id<>:x "
               "AND created_at >= :ref - INTERVAL '60 minutes' "
               "AND created_at <= :ref + INTERVAL '60 minutes'")
        params["ref"] = ref_time
    return [r[0] for r in db.execute(text(sql), params).fetchall()]


def check_contradiction(source_url, direction, ticker, db,
                        ref_time=None, exclude_id=None):
    """Reject if an opposite-direction prediction exists for the same
    source_url and ticker within 60 minutes. The caller is responsible for
    also excluding the existing row(s) — see `contradicting_ids`."""
    if contradicting_ids(source_url, direction, ticker, db, ref_time, exclude_id):
        return False, "contradictory_pair"
    return True, None


# ── Rule 6 ────────────────────────────────────────────────────────────────
def check_min_length(quote):
    """Reject too-short evidence. Operates on the verbatim quote (the
    templated `context` is ~27 chars for most rows and would reject ~55%
    of all predictions). A missing quote is accepted — Rules 2/3/4 already
    abstain on missing quotes, so Rule 6 stays consistent."""
    if quote is None or not quote.strip():
        return True, None
    if len(quote.strip()) < 40:
        return False, "context_too_short"
    return True, None


# ── Orchestrator ──────────────────────────────────────────────────────────
def validate_or_reject(pred, db, ref_time=None, exclude_id=None):
    """Run all six rules in order. Returns ``(accepted, reason)``.

    `pred` keys used: ticker, direction, source_url, source_verbatim_quote.
    Read-only — no writes. When this returns ``(False, "contradictory_pair")``
    the caller must also exclude `contradicting_ids(...)`.
    """
    ticker = pred.get("ticker")
    quote = pred.get("source_verbatim_quote")

    ok, reason = check_ticker_real(ticker, db)
    if not ok:
        return False, reason
    ok, reason = check_ticker_in_quote(ticker, quote, db)
    if not ok:
        return False, reason
    ok, reason = check_ad_read(quote)
    if not ok:
        return False, reason
    ok, reason = check_past_tense(quote)
    if not ok:
        return False, reason
    ok, reason = check_contradiction(
        pred.get("source_url"), pred.get("direction"), ticker, db,
        ref_time, exclude_id)
    if not ok:
        return False, reason
    ok, reason = check_min_length(quote)
    if not ok:
        return False, reason
    return True, None

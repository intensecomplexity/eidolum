"""Post-classifier validation gate.

Rejects garbage predictions before they become rows in `predictions`.
Twelve rules, run in order by `validate_or_reject`. Each rule is an
independently unit-testable function returning ``(accepted, reason)``.

Schema notes (verified 2026-05-16):
  * There is no `stock_prices` table. Ticker-realness uses `ticker_sectors`
    (~12k rows; ticker -> company_name), which is the populated reference.
  * `predictions.context` is a templated label ("Channel: Bull/Bear on
    TICKER"), NOT the analyst's words. The real quoted text is
    `source_verbatim_quote`. All text rules (2/3/4/6/7/10) therefore operate
    on the verbatim quote, not `context`.

This module performs only read-only DB queries — never writes. Rule 5
detects contradictions; the caller (youtube_classifier) performs the
`excluded_from_training` write via `contradicting_ids()`.

Per-rule kill switches:
  * CLASSIFIER_RULE_REPORTED_SPEECH (Rule 7)        default enforce
  * CLASSIFIER_RULE_HYPOTHETICAL_SCENARIO (Rule 10) default enforce
  * CLASSIFIER_RULE_QUESTION_RHETORICAL (Rule 11)   default shadow
  * CLASSIFIER_RULE_DATE_PASSED (Rule 12)           default shadow
  * CLASSIFIER_RULE_BASKET_BROAD (Rule 13)          default shadow
  * CLASSIFIER_RULE_NEWS_RECAP (Rule 14)            default shadow

Each accepts enforce / shadow / off — flip via Railway env vars without
redeploying. Rules 11-14 ship in SHADOW: they log would-be rejections
("[rule_NN_shadow] would reject ...") and let the row insert, so we can
collect rejection telemetry for ~24h before deciding enforce per rule.
Rule numbering skips 8/9 — reserved for the rest of the
hypothetical-handling policy (Tier 2 hide, Tier 3 conditional).
"""
import logging
import os
import re
from datetime import date, datetime, timedelta
from sqlalchemy import text

log = logging.getLogger(__name__)

# exclusion_rule_version is varchar(16) — keep <=16 chars.
RULE_VERSION = "classifier_gate"

# Rule 7 kill switch — flip via Railway env var:
#   CLASSIFIER_RULE_REPORTED_SPEECH=enforce  (default) block matches
#   CLASSIFIER_RULE_REPORTED_SPEECH=shadow   log would-be rejections, let through
#   CLASSIFIER_RULE_REPORTED_SPEECH=off      skip rule entirely
_REPORTED_SPEECH_MODE = os.environ.get(
    "CLASSIFIER_RULE_REPORTED_SPEECH", "enforce"
).lower()

# Rule 10 kill switch — same enforce/shadow/off semantics as Rule 7.
# Tier 1 hypotheticals only ("in a bull case", "imagine if",
# "hypothetically"). Tier 2 hedges ("could", "might") must NOT match —
# those are tagged conviction=hedged elsewhere, not gate-rejected.
_HYPOTHETICAL_SCENARIO_MODE = os.environ.get(
    "CLASSIFIER_RULE_HYPOTHETICAL_SCENARIO", "enforce"
).lower()

# Rules 11-14 kill switches — same enforce/shadow/off semantics, but these
# DEFAULT TO shadow (log-only) so a fresh ship collects telemetry without
# blocking inserts. Flip to enforce per-rule via Railway env var after review.
_QUESTION_RHETORICAL_MODE = os.environ.get(
    "CLASSIFIER_RULE_QUESTION_RHETORICAL", "shadow"
).lower()
_DATE_PASSED_MODE = os.environ.get(
    "CLASSIFIER_RULE_DATE_PASSED", "shadow"
).lower()
_BASKET_BROAD_MODE = os.environ.get(
    "CLASSIFIER_RULE_BASKET_BROAD", "shadow"
).lower()
_NEWS_RECAP_MODE = os.environ.get(
    "CLASSIFIER_RULE_NEWS_RECAP", "shadow"
).lower()

# reason code -> telemetry counter key (Step 4 cycle stats line)
TELEMETRY_KEYS = {
    "invalid_ticker": "invalid_ticker",
    "ticker_not_in_context": "ticker_not_in_context",
    "ad_read": "ad_read",
    "past_tense_only": "past_tense",
    "contradictory_pair": "contradictory",
    "context_too_short": "context_short",
    "reported_speech": "reported_speech",
    "hypothetical_scenario": "hypothetical_scenario",
    "question_rhetorical": "question_rhetorical",
    "prediction_date_passed": "prediction_date_passed",
    "basket_too_broad": "basket_too_broad",
    "news_recap_no_prediction": "news_recap",
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


# ── Rule 7 ────────────────────────────────────────────────────────────────
# Attribution verbs that signal third-person reporting. Case-insensitive
# since transcripts vary in casing on these.
_REPORTED_SPEECH_PATTERNS = [
    re.compile(
        r"\b(?:said|stated|claimed|mentioned|warned|predicted|tweeted|posted|"
        r"wrote|told|argued|insisted|noted|forecasted?|recommended|advised|"
        r"reiterated)\b",
        re.I,
    ),
    re.compile(r"\baccording to\b", re.I),
    # "per <CapitalizedName>" — the trailing name MUST start with a
    # capital letter to avoid matching common-noun uses like "$10 per
    # share". "per" itself stays case-insensitive so sentence-initial
    # "Per Goldman Sachs..." also catches.
    re.compile(r"(?i:\bper)\s+[A-Z][a-z]+"),
    # "<Capitalized Name> believes/thinks/expects/..." — strict caps on the
    # name pattern so this fires only on proper nouns, not common-word
    # collocations. (?i:...) keeps the verb list case-insensitive.
    re.compile(
        r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+"
        r"(?i:believes|thinks|expects|is\s+calling|has\s+been\s+calling|"
        r"is\s+predicting|sees|projects)\b"
    ),
    re.compile(
        r"\bin (?:his|her|their) (?:latest|recent|new)?\s*"
        r"(?:note|report|interview|appearance|tweet|post)\b",
        re.I,
    ),
]

# First-person prediction language — overrides reported-speech rejection so
# a row that genuinely is the speaker's own call but also references a
# third party ("My call: NVDA $1500; Buffett also said something") passes.
# Contractions ("We're", "I'll", "I've") are accepted via the optional
# '\w+ group after the pronoun.
_FIRST_PERSON_OVERRIDE = re.compile(
    r"\b(?:I|we|my|our|me)(?:'\w+)?\b(?:\s+\w+){0,5}\s+"
    r"(?:think(?:ing)?|believe|expect(?:ing)?|predict(?:ing)?|"
    r"see(?:ing)?|project(?:ing)?|target(?:ing)?|call(?:ing)?|"
    r"am\s+calling)\b",
    re.I,
)


def check_reported_speech(quote):
    """Reject reported-speech predictions ("Cathie Wood said TSLA to $2000").

    The verbatim quote captures what the classifier extracted as
    evidence; if that text attributes the prediction to a third party
    rather than the channel's own forward-looking statement, the row
    violates the Seven-Pillars "named forecaster" rule — we should not
    credit MarketWatch / Yahoo Finance / etc. for a Cathie-Wood call
    they're merely reporting on.

    First-person hedges are checked first so a prediction that *also*
    references a third party (e.g. "My call: NVDA $1500, Buffett also
    said something about Apple") passes.
    """
    if not quote or not quote.strip():
        return True, None
    if _FIRST_PERSON_OVERRIDE.search(quote):
        return True, None
    for pat in _REPORTED_SPEECH_PATTERNS:
        if pat.search(quote):
            return False, "reported_speech"
    return True, None


# ── Rule 10 ───────────────────────────────────────────────────────────────
# Pure scenario / hypothetical markers — narrow patterns only to keep
# precision high. Tier-2 hedged commitments ("could", "might", "may")
# MUST NOT match; those are separately tagged conviction=hedged and stay
# in the data layer. Tier-3 explicit conditionals ("if X then Y") are
# extracted as conditional_call category and also MUST NOT match here.
_HYPOTHETICAL_SCENARIO_PATTERNS = [
    re.compile(r"\bin a (?:bull|bear|base|worst|best)[\s-]?case\b", re.I),
    re.compile(r"\bin a scenario where\b", re.I),
    re.compile(r"\bimagine if\b", re.I),
    re.compile(r"\blet'?s (?:say|imagine|pretend)\b", re.I),
    re.compile(r"\bhypothetically\b", re.I),
    re.compile(r"\bin a world where\b", re.I),
    re.compile(r"\bpurely hypothetical\b", re.I),
    re.compile(r"\bif we assume\b", re.I),
    re.compile(r"\bin (?:the )?bull[\s-]?case scenario\b", re.I),
    re.compile(r"\bin (?:the )?bear[\s-]?case scenario\b", re.I),
]


def check_hypothetical_scenario(quote):
    """Reject Tier-1 pure hypothetical scenarios ("in a bull case TSLA
    hits 300", "imagine if NVDA doubled", "hypothetically MSFT to 500").

    No first-person override — "I think in a bull case TSLA hits 300" is
    still scenario analysis, not a committed call. The speaker is musing
    about a possible world, not stating their position.

    Critical precision constraint: Tier-2 hedged commitments using
    'could' / 'might' / 'may' / 'should' MUST NOT match these patterns —
    they're real (if soft) predictions and are handled via conviction
    metadata, not gate-rejection. The patterns above are deliberately
    narrow (proper scenario framings) rather than catching all
    speculation language.
    """
    if not quote or not quote.strip():
        return True, None
    for pat in _HYPOTHETICAL_SCENARIO_PATTERNS:
        if pat.search(quote):
            return False, "hypothetical_scenario"
    return True, None


# ── Rule 11 ───────────────────────────────────────────────────────────────
# A bare rhetorical question with no committed answer is not a prediction.
# "Could AAPL break out?" on its own is musing, not a call. The moment the
# speaker answers it ("...? Yes, here's why I think so.") a commitment marker
# appears and the row passes.
_RHETORICAL_START = re.compile(
    r"^\s*(?:could|will|can|should|would|is|are|does|won't|couldn't|"
    r"wouldn't|shouldn't|isn't|what|when|where|how)\b",
    re.I,
)
_COMMITMENT_MARKERS = re.compile(
    r"\bi\s+think\b|\bi\s+expect\b|\bi\s+see\b|\bi\s+believe\b|"
    r"\bi\s+project\b|\bi\s+target\b|\bmy\s+target\b|\bmy\s+forecast\b|"
    r"\bgoing\s+to\b|\bwill\s+hit\b|\bshould\s+reach\b|\bwill\s+reach\b|"
    r"\bhere'?s\s+why\b|\byes\b",
    re.I,
)


def check_question_rhetorical(quote):
    """Reject a quote that is a bare question with no commitment.

    Three conditions, all required:
      * after stripping trailing whitespace/punctuation other than '?',
        the quote ENDS with '?' (an answer would add text past the '?')
      * it STARTS with an interrogative word (Could/Will/What/...)
      * it contains NO first-person commitment marker anywhere

    The end-with-'?' gate alone passes the documented negatives, e.g.
    "Will TSLA hit 300? Yes, here's why I think so." — the answer text
    after the '?' means the trimmed quote no longer ends with '?'.
    """
    if not quote or not quote.strip():
        return True, None
    q = quote.strip()
    trimmed = re.sub(r"[\s.!,;:]+$", "", q)
    if not trimmed.endswith("?"):
        return True, None
    if not _RHETORICAL_START.search(q):
        return True, None
    if _COMMITMENT_MARKERS.search(q):
        return True, None
    return False, "question_rhetorical"


# ── Rule 12 ───────────────────────────────────────────────────────────────
# timeframe_category -> representative horizon in days. We use each bucket's
# UPPER bound (the longest horizon in the bucket) so the rule fires only when
# even the most generous reading of the window had already expired at publish
# time — minimizing false positives. Mirrors youtube_classifier's BUCKET
# MAPPING table.
_CATEGORY_DAYS = {
    "day_trading": 1,
    "options_short": 7,
    "swing_trade": 21,
    "technical_chart": 30,
    "fundamental_quarterly": 90,
    "cyclical_medium": 180,
    "macro_thesis": 730,
    "long_term_fundamental": 1825,
}


def _to_date(v):
    """Coerce a date / datetime / ISO-ish string into a `date`, else None."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    return None


def check_date_passed(prediction_date, video_published_at,
                      window_days=None, inferred_timeframe_days=None,
                      timeframe_category=None):
    """Reject a call whose target window had already expired BEFORE the
    video was published — a backward-looking recap ("BTC should have hit
    100k by 2024" said in a 2025 video), not a forward commitment.

        target_date = prediction_date + horizon_days
        reject iff target_date < video_published_at

    horizon_days precedence: window_days -> inferred_timeframe_days ->
    timeframe_category lookup. If prediction_date or video_published_at is
    missing, or no horizon can be resolved, SKIP (accept) — never reject on
    insufficient data. Does NOT catch targets that are merely past relative
    to NOW(); those score normally via the historical evaluator.
    """
    pd = _to_date(prediction_date)
    vp = _to_date(video_published_at)
    if pd is None or vp is None:
        return True, None

    days = None
    try:
        if window_days is not None and int(window_days) > 0:
            days = int(window_days)
        elif inferred_timeframe_days is not None and int(inferred_timeframe_days) > 0:
            days = int(inferred_timeframe_days)
    except (TypeError, ValueError):
        days = None
    if days is None and timeframe_category:
        days = _CATEGORY_DAYS.get(str(timeframe_category).strip().lower())
    if not days or days <= 0:
        return True, None

    if pd + timedelta(days=days) < vp:
        return False, "prediction_date_passed"
    return True, None


# ── Rule 13 ───────────────────────────────────────────────────────────────
# Basket-only mentions: the speaker names a basket ("the magnificent seven")
# but never the individual ticker the classifier extracted. We reject the
# extraction unless the ticker is named individually somewhere in the quote
# (by symbol or by a known company name/alias). Basket phrases and ticker
# symbols/aliases are disjoint vocabularies, so a plain whole-quote
# individual-mention check is both correct and the safest (0-FP) reading of
# "outside the basket-mention sentence".
_FAANG_MEMBERS = {"META", "AAPL", "AMZN", "NFLX", "GOOGL", "GOOG", "MSFT",
                  "TSLA", "NVDA"}
_BIGTECH_MEMBERS = {"META", "AAPL", "AMZN", "GOOGL", "MSFT", "NVDA", "TSLA"}
_CLOUD_MEMBERS = {"MSFT", "GOOGL", "AMZN", "ORCL", "CRM", "SNOW"}
_CHIP_MEMBERS = {"NVDA", "AMD", "INTC", "AVGO", "TSM", "MU", "QCOM", "AMAT",
                 "LRCX", "KLAC"}
_AI_MEMBERS = {"NVDA", "AMD", "MSFT", "GOOGL", "META", "PLTR", "SMCI"}
_BANK_MEMBERS = {"JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC"}
_AIRLINE_MEMBERS = {"DAL", "UAL", "AAL", "LUV", "ALK", "JBLU"}
_HOMEBUILDER_MEMBERS = {"DHI", "LEN", "NVR", "PHM", "TOL", "KBH"}
_REIT_MEMBERS = {"AMT", "EQIX", "PSA", "SPG", "O", "PLD"}

_BASKETS = [
    (re.compile(r"\bfaangm?\b", re.I), _FAANG_MEMBERS),
    (re.compile(r"\bmagnificent\s+(?:seven|7)\b", re.I), _FAANG_MEMBERS),
    (re.compile(r"\bmag\s?7\b", re.I), _FAANG_MEMBERS),
    (re.compile(r"\bbig\s+tech\s+stocks\b", re.I), _BIGTECH_MEMBERS),
    (re.compile(r"\bthe\s+cloud\s+names\b", re.I), _CLOUD_MEMBERS),
    (re.compile(r"\bthe\s+chip\s+stocks\b", re.I), _CHIP_MEMBERS),
    (re.compile(r"\bsemiconductor\s+stocks\b", re.I), _CHIP_MEMBERS),
    (re.compile(r"\bai\s+stocks\b", re.I), _AI_MEMBERS),
    (re.compile(r"\bthe\s+banks\b", re.I), _BANK_MEMBERS),
    (re.compile(r"\bthe\s+airlines\b", re.I), _AIRLINE_MEMBERS),
    (re.compile(r"\bthe\s+homebuilders\b", re.I), _HOMEBUILDER_MEMBERS),
    (re.compile(r"\bthe\s+reits\b", re.I), _REIT_MEMBERS),
]


def check_basket_too_broad(quote, ticker, db=None):
    """Reject when a basket the ticker belongs to is named but the ticker
    itself is never named individually in the quote.

    Pass (accept) the moment the ticker symbol — or any of its company
    name/aliases when `db` is provided — appears in the quote: that is an
    individual call ("...the magnificent seven, especially NVDA which I
    think hits 200" keeps NVDA, drops AAPL/META). With db=None only the
    symbol is checked (used by the offline fixture runner).
    """
    if not quote or not quote.strip():
        return True, None
    t = (ticker or "").upper().strip()
    if not t:
        return True, None
    members = None
    for pat, member_set in _BASKETS:
        if t in member_set and pat.search(quote):
            members = member_set
            break
    if members is None:
        return True, None
    ql = quote.lower()
    if _word_in(t, ql):
        return True, None
    if db is not None:
        for name in _ticker_names(ticker, db):
            if _word_in(name, ql):
                return True, None
    return False, "basket_too_broad"


# ── Rule 14 ───────────────────────────────────────────────────────────────
# Past-tense market reporting with zero forward commitment is a news recap,
# not a prediction. Distinct from Rule 4 (which keys off a different, smaller
# past/forward marker set): Rule 14 only runs when Rule 4 did not reject, and
# requires a heavier evidentiary bar (>=2 distinct past markers, 0 forward).
_RECAP_PAST_MARKERS = [
    re.compile(p, re.I) for p in (
        r"\bshares closed\b", r"\bstock fell\b", r"\brallied today\b",
        r"\bdropped today\b", r"\breported earnings\b", r"\bannounced today\b",
        r"\bclosed at\b", r"\bfinished the day\b", r"\btraded down\b",
        r"\btraded up\b", r"\bwas up\b", r"\bwas down\b",
        r"\bended the session\b",
    )
]
_RECAP_FORWARD_MARKERS = [
    re.compile(p, re.I) for p in (
        r"\bi think\b", r"\bi expect\b", r"\bi see\b", r"\bi believe\b",
        r"\bi project\b", r"\bi target\b", r"\bmy target\b", r"\bgoing to\b",
        r"\bwill hit\b", r"\bshould reach\b", r"\bwill reach\b",
        r"\bnext month\b", r"\bnext quarter\b", r"\bnext year\b",
    )
]


def check_news_recap(quote, rule_4_already_rejected=False):
    """Reject past-tense market recap with no forward-looking commitment.

    Coordinates with Rule 4: if Rule 4 already rejected the quote as
    past_tense_only, this is a no-op (the orchestrator only reaches Rule 14
    when Rule 4 passed, so `rule_4_already_rejected` is False there; the
    flag exists for isolated unit testing). Fires when >=2 distinct past
    markers are present and zero forward markers.
    """
    if rule_4_already_rejected:
        return True, None
    if not quote or not quote.strip():
        return True, None
    past = sum(1 for p in _RECAP_PAST_MARKERS if p.search(quote))
    if past < 2:
        return True, None
    if any(p.search(quote) for p in _RECAP_FORWARD_MARKERS):
        return True, None
    return False, "news_recap_no_prediction"


# ── Orchestrator ──────────────────────────────────────────────────────────
def validate_or_reject(pred, db, ref_time=None, exclude_id=None):
    """Run all twelve rules in order. Returns ``(accepted, reason)``.

    `pred` keys used: ticker, direction, source_url, source_verbatim_quote
    (Rules 1-7,10,11,13,14) plus prediction_date, video_published_at,
    window_days, inferred_timeframe_days, timeframe_category (Rule 12 —
    absent from the live caller's fields dict today, so Rule 12 abstains in
    production until that plumbing lands).
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
    # Rule 7 — reported-speech rejection. Gated by env var so we can flip
    # to shadow/off without redeploying if false-positives surface at scale.
    if _REPORTED_SPEECH_MODE != "off":
        ok, reason = check_reported_speech(quote)
        if not ok:
            if _REPORTED_SPEECH_MODE == "shadow":
                log.warning(
                    "[rule_7_shadow] would reject %s via reported_speech: %s",
                    ticker, (quote or "")[:120],
                )
            else:  # 'enforce' (default; unknown values also enforce defensively)
                log.info(
                    "[rule_7_enforce] rejected %s via reported_speech: %s",
                    ticker, (quote or "")[:120],
                )
                return False, "reported_speech"
    # Rule 10 — Tier-1 hypothetical-scenario rejection. Same env-var
    # kill-switch pattern as Rule 7.
    if _HYPOTHETICAL_SCENARIO_MODE != "off":
        ok, reason = check_hypothetical_scenario(quote)
        if not ok:
            if _HYPOTHETICAL_SCENARIO_MODE == "shadow":
                log.warning(
                    "[rule_10_shadow] would reject %s via hypothetical_scenario: %s",
                    ticker, (quote or "")[:120],
                )
            else:  # 'enforce' (default; unknown values also enforce defensively)
                log.info(
                    "[rule_10_enforce] rejected %s via hypothetical_scenario: %s",
                    ticker, (quote or "")[:120],
                )
                return False, "hypothetical_scenario"
    # Rule 11 — rhetorical-question rejection. Ships in SHADOW (default);
    # logs would-be rejections and lets the row through until promoted.
    if _QUESTION_RHETORICAL_MODE != "off":
        ok, reason = check_question_rhetorical(quote)
        if not ok:
            if _QUESTION_RHETORICAL_MODE == "shadow":
                log.warning(
                    "[rule_11_shadow] would reject %s via question_rhetorical: %s",
                    ticker, (quote or "")[:120],
                )
            else:  # 'enforce' (unknown values also enforce defensively)
                log.info(
                    "[rule_11_enforce] rejected %s via question_rhetorical: %s",
                    ticker, (quote or "")[:120],
                )
                return False, "question_rhetorical"
    # Rule 12 — target-window-expired-before-publish rejection. SHADOW
    # default. Reads date/timeframe keys that the live caller does not yet
    # forward, so it abstains in production until that plumbing lands.
    if _DATE_PASSED_MODE != "off":
        ok, reason = check_date_passed(
            pred.get("prediction_date"), pred.get("video_published_at"),
            pred.get("window_days"), pred.get("inferred_timeframe_days"),
            pred.get("timeframe_category"))
        if not ok:
            if _DATE_PASSED_MODE == "shadow":
                log.warning(
                    "[rule_12_shadow] would reject %s via prediction_date_passed: %s",
                    ticker, (quote or "")[:120],
                )
            else:  # 'enforce' (unknown values also enforce defensively)
                log.info(
                    "[rule_12_enforce] rejected %s via prediction_date_passed: %s",
                    ticker, (quote or "")[:120],
                )
                return False, "prediction_date_passed"
    # Rule 13 — basket-only-mention rejection. SHADOW default.
    if _BASKET_BROAD_MODE != "off":
        ok, reason = check_basket_too_broad(quote, ticker, db)
        if not ok:
            if _BASKET_BROAD_MODE == "shadow":
                log.warning(
                    "[rule_13_shadow] would reject %s via basket_too_broad: %s",
                    ticker, (quote or "")[:120],
                )
            else:  # 'enforce' (unknown values also enforce defensively)
                log.info(
                    "[rule_13_enforce] rejected %s via basket_too_broad: %s",
                    ticker, (quote or "")[:120],
                )
                return False, "basket_too_broad"
    # Rule 14 — news-recap (past-tense, no forward commitment) rejection.
    # SHADOW default. Only reached when Rule 4 (past_tense) did not reject,
    # so rule_4_already_rejected is implicitly False here.
    if _NEWS_RECAP_MODE != "off":
        ok, reason = check_news_recap(quote)
        if not ok:
            if _NEWS_RECAP_MODE == "shadow":
                log.warning(
                    "[rule_14_shadow] would reject %s via news_recap_no_prediction: %s",
                    ticker, (quote or "")[:120],
                )
            else:  # 'enforce' (unknown values also enforce defensively)
                log.info(
                    "[rule_14_enforce] rejected %s via news_recap_no_prediction: %s",
                    ticker, (quote or "")[:120],
                )
                return False, "news_recap_no_prediction"
    return True, None

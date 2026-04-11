"""Ship #12 — read-only training-set audit.

Scans `predictions` and flags rows that look poisonous for the fine-tune
training set. Writes NOTHING to the database. Emits a JSON report to
backend/scripts/ship_12_audit_report.json and prints a human-readable
counts table to stdout.

Exposes `run_audit(conn)` as an importable function so tests can seed a
fixture DB and assert row counts without shelling out.

The audit logic is *Postgres-first but dialect-portable*: the SELECT
stage uses standard SQL (structural filters only), and the regex stage
is done in Python against the fetched rows. That means sqlite fixtures
work too — we don't rely on `~*` or `\\m...\\M` in SQL.

Schema adaptations from the original ship spec, noted for the record:
  - `raw_text` does not exist on `predictions`. We concatenate
    (context || exact_quote || quote_context) into a virtual text blob
    called `source_text` for the regex pass. The pronoun-opener check
    still runs against `context` alone, because we're judging what the
    extractor chose as the context string.
  - `timeframe = '3mo'` is not a real column/value. The canonical "3-month
    default" is `window_days = 90` and `timeframe_source` is NULL or
    not 'explicit' (the Ship #8/#9 metadata-enrichment stack owns that
    marker).
  - `direction IN ('hold','neutral')` is kept as-is; in practice only
    `'neutral'` ever appears, but the IN clause is harmless and stays
    aligned with the spec.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from typing import Dict, List, Sequence, Tuple

RULE_VERSION = "v12.3"

# Hard-coded protection list. Even if a future rule rewrite would
# otherwise flag these rows, the audit drops them silently.
#
# Each entry is a (prediction_id, reason) pair so the protection is
# auditable. Add to this list with a comment explaining WHY — we are
# saying "the rule is too greedy here, do not let it touch this row
# until the rule has been independently validated".
PHASE_A_PROTECTED_IDS: dict[int, str] = {
    # 606202 META — Chip Stock Investor: "if we were looking to buy one
    # of these stocks for the first time right now we would be going
    # with Meta". Already scored outcome=hit with entry_price $294.29.
    # The basket phrasing fires ("one of these"), but the speaker named
    # Meta as the conviction pick out of the basket — excluding it
    # would invalidate a real win. Phase A eyeball, 2026-04-11.
    606202: "conviction pick from basket — already scored hit",
}

REASONS: Tuple[str, ...] = (
    "disclosure_misroute",
    "invented_timeframe",
    "unresolvable_reference",
    "basket_shoehorn",
    "duplicate_source",
)

# v12.3 — synthetic-template ingest sources. These pipelines emit a fixed
# template ("{Bank}: {Direction} — {Action} on {TICKER}.") and blanket-stamp
# window_days=90 because analyst rating changes don't carry a horizon.
# The Shape A invented_timeframe rule flags only rows from these sources;
# youtube_haiku_v1 and x_scraper transcript rows are deliberately spared
# because they carry real subjective speaker content even when the horizon
# was never volunteered.
_SYNTHETIC_TEMPLATE_SOURCES: Tuple[str, ...] = (
    "fmp_grades",
    "massive_benzinga",
    "alphavantage",
)

# --- regex patterns (Python re, case-insensitive) -------------------------

# Ownership voice: first-person pronoun within a short window of an
# ownership verb. Matches "we hold", "I'm long", "our position in", etc.
_OWNERSHIP_RE = re.compile(
    r"\b(?:we|i|our|my|i'm|we're|i am|we are)\b"
    r".{0,40}?"
    r"\b(?:hold(?:ing)?|long|short|own(?:ing)?|position|stake|"
    r"invested\s+in|bought|sold|accumulat)",
    re.IGNORECASE | re.DOTALL,
)

# Analyst-rating voice: "we rate X a hold", "X is a buy rating", etc.
# If the row matches this, it's a legit ticker_call neutral, not a
# disclosure mis-route.
_RATING_VOICE_RE = re.compile(
    r"\brate[sd]?\b.{0,20}?\b(?:hold|neutral|buy|sell)\b"
    r"|\b(?:hold|buy|sell)\b.{0,20}?\brating\b",
    re.IGNORECASE | re.DOTALL,
)

# "Invented timeframe" no longer uses regex — window_days/timeframe_source
# do the work. But we still exempt rows whose source text explicitly
# mentions any time unit at all, to stay conservative and to match the
# spec's "any explicit unit exempts it" carve-out.
_EXPLICIT_TIMEFRAME_RE = re.compile(
    r"\b(?:\d+\s*(?:day|week|month|year)s?|days?|weeks?|months?|years?"
    r"|eow|eom|eoy|quarter|q[1-4]|next\s+quarter|by\s+(?:jan|feb|mar|apr|may|"
    r"jun|jul|aug|sep|oct|nov|dec))\b",
    re.IGNORECASE,
)

# Unresolvable reference: context opens with a pronoun/definite ref
# with no clear antecedent. We only flag when the ticker symbol is
# literally absent from all three source columns AND the context does
# not contain a $TICKER anywhere.
_PRONOUN_OPENER_RE = re.compile(
    r"^\s*(?:it|they|them|this|that|these|those|the\s+stock|"
    r"the\s+company|the\s+name|the\s+ticker)\b",
    re.IGNORECASE,
)
_CASHTAG_RE = re.compile(r"\$[A-Z]{1,5}\b")

# --- v12.3 basket phrasing rewrite ----------------------------------------
#
# v12.2 was a single-signal rule (one basket phrase fires → exclude). The
# Phase A eyeball found 6 of 8 flagged rows were false positives because
# the rule never checked whether the speaker was actually walking a list
# of tickers, never checked whether they singled out a conviction pick,
# and didn't even confirm the row was YouTube-sourced (an X tweet about
# a single ticker was getting flagged because of a bug-decoded date).
#
# v12.3 requires ALL THREE of the following to fire before flagging:
#
#   Signal 1 — MULTI-TICKER CO-OCCURRENCE
#     The row's source_platform_id starts with "yt_<video_id>_" and the
#     SAME yt_<video_id>_ prefix produced ≥ 3 distinct ticker_call rows.
#     One ticker alone from a video is never a basket. X-sourced rows
#     are NEVER baskets (single-ticker tweets).
#
#   Signal 2 — BASKET PHRASING IN CONTEXT
#     The context text contains a phrase that, in plain English,
#     enumerates a candidate set ("one of these", "two of these
#     stocks", "among the seven", "another supplier", etc.).
#
#   Signal 3 — NO CONVICTION MARKER
#     The context text does NOT promote one ticker above the basket
#     ("would be Meta", "going with Meta", "Meta is my pick"). When a
#     speaker names a conviction pick, that ticker stays clean and the
#     OTHER tickers in the same video are still candidates for flagging.
#
# Anything in PHASE_A_PROTECTED_IDS bypasses the rule entirely.

_BASKET_PHRASING_PATTERNS: tuple[str, ...] = (
    r"\bone\s+of\s+these\b",
    r"\bany\s+of\s+these\b",
    r"\bamong\s+the(?:se)?\s+(?:\d+|two|three|four|five|six|seven|eight|nine|ten)\b",
    r"\bthese\s+(?:\d+|two|three|four|five|six|seven|eight|nine|ten)\s+stocks\b",
    r"\btwo\s+of\s+these\b",
    # v12.4: tightened from v12.3's `\banother\s+\S(?:.{2,40}?)\s(...)`
    # which false-positived on "another $3,500 to that Roth IRA to buy
    # some Tesla stock" — "another" was qualifying the dollar amount,
    # not the stock. The negative lookahead `(?![$\d])` rejects
    # immediate $ or digit followers, and the structure now requires
    # "another <word> <word> <noun>" instead of "another <anything>
    # <noun>". 606405 TSLA stops triggering; "another Key Automotive
    # supplier" still does.
    r"\banother\s+(?![$\d])\S+\s+\S{2,40}?\s(?:supplier|play|name|stock|pick)s?\b",
    r"\bmy\s+\w+\s+(?:picks|buys)\s+(?:among|from|out\s+of)\b",
    r"\bif\s+you\s+(?:really\s+)?want(?:ed)?\s+to\s+(?:add|buy|own)\s+(?:two|three|a\s+few|some)\s+of\b",
    r"\bi(?:'d|\s+would)\s+(?:go|pick|choose)\s+with\b",
)
_BASKET_PHRASING_RE = re.compile(
    "|".join(_BASKET_PHRASING_PATTERNS), re.IGNORECASE | re.DOTALL,
)

# Conviction marker templates. {ticker} is replaced per-row with a
# case-insensitive word-boundary match for the prediction's ticker
# symbol. Use _CONVICTION_STANDALONE for endorsement language that
# applies regardless of which ticker the row carries.
_CONVICTION_TEMPLATES: tuple[str, ...] = (
    r"\bgoing\s+with\s+{ticker}\b",
    r"\bwould\s+be\s+{ticker}\b",
    r"\bi(?:'d|\s+would)\s+(?:go|pick|choose)\s+with\s+{ticker}\b",
    r"\b{ticker}\s+is\s+my\s+(?:answer|pick|choice|top)\b",
    r"\bif\s+i\s+had\s+to\s+pick\s+one,\s+{ticker}\b",
)

# v12.4 — standalone conviction markers. These are endorsement phrases
# that elevate a ticker above a basket whether or not the speaker named
# the symbol verbatim. Added because "Qualcomm is another top pick for
# 2023" (605937 QCOM, scored hit) was being flagged as basket_shoehorn
# under v12.3 — the speaker WAS endorsing Qualcomm by name, just via the
# ranking phrase rather than a possessive pronoun. Adding "top pick" as
# a standalone marker means QCOM and similar rows score clean.
#
# `\btop\s+pick\b` covers "my top pick", "another top pick",
# "another top pick for 2023", etc. The two more-specific entries below
# are kept for self-documentation even though the broad pattern
# subsumes them.
_CONVICTION_STANDALONE: tuple[str, ...] = (
    r"\btop\s+pick\b",
    r"\banother\s+top\s+pick\b",
    r"\bone\s+of\s+(?:our|my|the)\s+top\s+picks\b",
    r"\bhigh(?:est)?\s+conviction\b",
)


def _has_conviction_marker(context: str, ticker: str) -> bool:
    """True iff the context promotes this ticker above a basket.

    Standalone markers (top pick, highest conviction, ...) fire on the
    context alone — endorsement language is endorsement language.
    Templated markers substitute the row's ticker into a placeholder so
    we only credit conviction when the speaker actually named THIS
    ticker as their pick.
    """
    if not context:
        return False
    # v12.4: standalone first — these are cheaper and the most common
    # win path for already-scored hit rows.
    for pat in _CONVICTION_STANDALONE:
        if re.search(pat, context, re.IGNORECASE):
            return True
    tk = (ticker or "").strip()
    if tk:
        token = re.escape(tk)
    else:
        token = r"[A-Z]{1,5}"
    for tpl in _CONVICTION_TEMPLATES:
        pattern = tpl.replace("{ticker}", token)
        if re.search(pattern, context, re.IGNORECASE):
            return True
    return False


def _video_prefix(source_platform_id: str | None) -> str | None:
    """Return the 'yt_<video_id>_' prefix for a YouTube source row, else None."""
    if not source_platform_id:
        return None
    if not source_platform_id.startswith("yt_"):
        return None
    # source_platform_id is "yt_<video_id>_<TICKER>". The video_id can
    # contain underscores (rare but legal in YouTube IDs), so split from
    # the right rather than splitting on the second underscore.
    head, _sep, _tail = source_platform_id.rpartition("_")
    if not head or head == "yt":
        return None
    return head + "_"


# --- candidate SELECTs (structural filters only; regex runs in Python) ----
#
# We SELECT wide and filter in Python. The structural predicates here
# are intentionally broad so the Python regex pass is what actually
# produces the flag list.

_SELECT_DISCLOSURE_CANDIDATES = """
SELECT id, ticker, context, exact_quote, quote_context, direction,
       target_price, created_at
FROM predictions
WHERE direction IN ('neutral', 'hold')
  AND excluded_from_training = FALSE
"""

# v12.3 — Shape A: source-list rule. All filtering is done in SQL —
# window_days=90 + timeframe_source NULL/empty + verified_by IN the
# synthetic-template list. The Python pass is a no-op id extractor.
# Predicate intentionally narrowed from `<> 'explicit'` to `= ''` so we
# only flag rows that volunteered no horizon at all (the v12.1 broader
# predicate would have caught any non-'explicit' tag, including future
# extractor markers we don't want to retroactively poison).
_SELECT_INVENTED_TIMEFRAME_CANDIDATES = (
    """
SELECT id, ticker, context, exact_quote, quote_context, window_days,
       timeframe_source, created_at
FROM predictions
WHERE window_days = 90
  AND (timeframe_source IS NULL OR timeframe_source = '')
  AND verified_by IN ("""
    + ", ".join(f"'{s}'" for s in _SYNTHETIC_TEMPLATE_SOURCES)
    + """)
  AND excluded_from_training = FALSE
"""
)

_SELECT_UNRESOLVABLE_REF_CANDIDATES = """
SELECT id, ticker, context, exact_quote, quote_context, created_at
FROM predictions
WHERE context IS NOT NULL
  AND excluded_from_training = FALSE
"""

_SELECT_BASKET_CANDIDATES = """
SELECT id, ticker, context, exact_quote, quote_context,
       source_platform_id, created_at
FROM predictions
WHERE context IS NOT NULL
  AND excluded_from_training = FALSE
"""

# Sibling lookup: every (yt_<video_id>_, ticker) pair across the WHOLE
# predictions table, not just the basket candidate set. We need this to
# decide whether a row's video had ≥3 distinct ticker calls. Filtering
# on excluded_from_training=FALSE here would lie to the rule (a video
# can be a real basket even if some of its rows are already excluded).
_SELECT_VIDEO_TICKER_PAIRS = """
SELECT source_platform_id, ticker
FROM predictions
WHERE source_platform_id LIKE 'yt\\_%' ESCAPE '\\'
  AND ticker IS NOT NULL
"""

_SELECT_DUPLICATE_SOURCE = """
SELECT id, source_platform_id, created_at
FROM predictions
WHERE source_platform_id IS NOT NULL
  AND excluded_from_training = FALSE
ORDER BY source_platform_id ASC, created_at ASC, id ASC
"""


def _source_text(row: Sequence) -> str:
    """Concatenate context + exact_quote + quote_context into one blob."""
    parts = []
    for v in row:
        if v:
            parts.append(str(v))
    return " ".join(parts)


def _fetch(conn, sql: str) -> List[tuple]:
    cur = conn.cursor()
    cur.execute(sql)
    rows = cur.fetchall()
    cur.close()
    return rows


def _filter_disclosure_misroute(rows: List[tuple]) -> List[int]:
    """rows: (id, ticker, context, exact_quote, quote_context, direction,
    target_price, created_at). Flags ownership-voice rows unless they
    also look like analyst-rating voice."""
    flagged = []
    for r in rows:
        _id, _ticker, context, exact_quote, quote_context = r[0], r[1], r[2], r[3], r[4]
        blob = _source_text((context, exact_quote, quote_context))
        if not _OWNERSHIP_RE.search(blob):
            continue
        if _RATING_VOICE_RE.search(blob):
            continue
        flagged.append(_id)
    return flagged


def _filter_invented_timeframe(rows: List[tuple]) -> List[int]:
    """v12.3 — flag only synthetic-template rows from analyst-rating ingests.
    The 90-day window is a blanket ingest default, not a speaker horizon.
    youtube_haiku_v1 and x_scraper transcript rows are deliberately
    excluded from this rule because they carry real subjective opinions
    worth training on, even when the speaker never volunteered a horizon.

    All filtering happens in the SELECT (window_days=90 + timeframe_source
    NULL/empty + verified_by IN _SYNTHETIC_TEMPLATE_SOURCES). The prior
    v12.1 _EXPLICIT_TIMEFRAME_RE regex pass has been removed — the SQL is
    sufficient and faster, and the regex was over-broad on long
    transcripts that mentioned a time unit tangentially.
    """
    return [r[0] for r in rows]


def _filter_unresolvable_reference(rows: List[tuple]) -> List[int]:
    """rows: (id, ticker, context, exact_quote, quote_context, created_at).
    Flags when:
      - context opens with a pronoun
      - ticker symbol is literally absent from all three source columns
      - no $TICKER cashtag anywhere in context
    """
    flagged = []
    for r in rows:
        _id = r[0]
        ticker = (r[1] or "").upper()
        context = r[2] or ""
        blob = _source_text((r[2], r[3], r[4]))
        if not _PRONOUN_OPENER_RE.search(context):
            continue
        if ticker and re.search(r"\b" + re.escape(ticker) + r"\b", blob, re.IGNORECASE):
            continue
        if _CASHTAG_RE.search(context):
            continue
        flagged.append(_id)
    return flagged


def _build_video_ticker_map(rows: List[tuple]) -> dict[str, set[str]]:
    """rows: (source_platform_id, ticker). Returns {video_prefix: set(tickers)}."""
    out: dict[str, set[str]] = {}
    for r in rows:
        spid, ticker = r[0], r[1]
        prefix = _video_prefix(spid)
        if not prefix:
            continue
        out.setdefault(prefix, set()).add((ticker or "").upper())
    return out


def _filter_basket_shoehorn(
    rows: List[tuple],
    video_ticker_map: dict[str, set[str]],
) -> List[int]:
    """rows: (id, ticker, context, exact_quote, quote_context,
    source_platform_id, created_at).

    v12.3 — three-signal AND. See the comment block above
    `_BASKET_PHRASING_PATTERNS` for the full rationale. Each row must
    satisfy ALL of:

      Signal 1: the row is YouTube-sourced and its video produced ≥3
                distinct ticker_call rows.
      Signal 2: the context contains a basket-phrasing pattern.
      Signal 3: the context does NOT contain a conviction marker that
                promotes this row's ticker above the basket.

    Anything in PHASE_A_PROTECTED_IDS is dropped silently.
    """
    flagged: List[int] = []
    for r in rows:
        _id, ticker = r[0], (r[1] or "").upper()
        context = r[2] or ""
        spid = r[5] if len(r) > 5 else None

        if _id in PHASE_A_PROTECTED_IDS:
            continue

        # Signal 1 — multi-ticker co-occurrence (yt_ only)
        prefix = _video_prefix(spid)
        if not prefix:
            continue
        sibling_set = video_ticker_map.get(prefix, set())
        if len(sibling_set) < 3:
            continue

        # Signal 2 — basket phrasing in the context
        if not _BASKET_PHRASING_RE.search(context):
            continue

        # Signal 3 — NOT a conviction marker for this ticker
        if _has_conviction_marker(context, ticker):
            continue

        flagged.append(_id)
    return flagged


def basket_shoehorn_signals(
    row: tuple,
    video_ticker_map: dict[str, set[str]],
) -> dict:
    """Return per-signal diagnostics for a single basket candidate row.

    Used by scripts/ship_12_audit_phase_a.py to print which of the three
    signals fired for each flagged row. Mirrors the predicate order in
    `_filter_basket_shoehorn` exactly.
    """
    _id, ticker = row[0], (row[1] or "").upper()
    context = row[2] or ""
    spid = row[5] if len(row) > 5 else None
    prefix = _video_prefix(spid)
    siblings = sorted(video_ticker_map.get(prefix, set())) if prefix else []
    return {
        "id": _id,
        "ticker": ticker,
        "source_platform_id": spid,
        "context": context,
        "video_prefix": prefix,
        "sibling_tickers": siblings,
        "signal_1_multi_ticker": prefix is not None and len(siblings) >= 3,
        "signal_2_basket_phrasing": bool(_BASKET_PHRASING_RE.search(context)),
        "signal_3_no_conviction": not _has_conviction_marker(context, ticker),
        "protected": _id in PHASE_A_PROTECTED_IDS,
    }


def _filter_duplicate_source(rows: List[tuple]) -> List[int]:
    """rows: (id, source_platform_id, created_at) ordered by
    source_platform_id, created_at, id. Keeps the first row per
    source_platform_id and flags the rest."""
    flagged = []
    seen: Dict[str, bool] = {}
    for r in rows:
        _id, spid, _created = r[0], r[1], r[2]
        if not spid:
            continue
        if spid in seen:
            flagged.append(_id)
        else:
            seen[spid] = True
    return flagged


def run_audit(conn) -> Dict[str, List[int]]:
    """Read-only audit. Returns {reason: [prediction_id, ...]}.

    Does not write anything. Does not acquire any locks. Safe to run
    against production while the scrapers are live.
    """
    results: Dict[str, List[int]] = {r: [] for r in REASONS}

    results["disclosure_misroute"] = _filter_disclosure_misroute(
        _fetch(conn, _SELECT_DISCLOSURE_CANDIDATES)
    )
    results["invented_timeframe"] = _filter_invented_timeframe(
        _fetch(conn, _SELECT_INVENTED_TIMEFRAME_CANDIDATES)
    )
    results["unresolvable_reference"] = _filter_unresolvable_reference(
        _fetch(conn, _SELECT_UNRESOLVABLE_REF_CANDIDATES)
    )
    # Build the video → ticker-set map ONCE per audit so the basket
    # filter can answer signal-1 (multi-ticker co-occurrence) without
    # re-querying per row.
    video_ticker_map = _build_video_ticker_map(
        _fetch(conn, _SELECT_VIDEO_TICKER_PAIRS)
    )
    results["basket_shoehorn"] = _filter_basket_shoehorn(
        _fetch(conn, _SELECT_BASKET_CANDIDATES),
        video_ticker_map,
    )
    results["duplicate_source"] = _filter_duplicate_source(
        _fetch(conn, _SELECT_DUPLICATE_SOURCE)
    )

    return results


def _compute_overlap(flagged: Dict[str, List[int]]) -> Dict[str, int]:
    sets = {k: set(v) for k, v in flagged.items()}
    overlap = {}
    keys = list(sets.keys())
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            overlap[f"{a}_and_{b}"] = len(sets[a] & sets[b])
    return overlap


def _build_report(flagged: Dict[str, List[int]]) -> dict:
    return {
        "rule_version": RULE_VERSION,
        "generated_at": _dt.datetime.utcnow().isoformat() + "Z",
        "counts": {k: len(v) for k, v in flagged.items()},
        "sample_ids": {k: list(v[:20]) for k, v in flagged.items()},
        "overlap": _compute_overlap(flagged),
    }


def _print_counts(report: dict) -> None:
    print()
    print(f"Ship #12 audit — rule_version {report['rule_version']}")
    print(f"generated_at: {report['generated_at']}")
    print()
    print(f"{'reason':<28} {'count':>10}")
    print("-" * 40)
    total = 0
    for reason in REASONS:
        n = report["counts"][reason]
        total += n
        print(f"{reason:<28} {n:>10,}")
    print("-" * 40)
    print(f"{'TOTAL':<28} {total:>10,}")
    print()
    if report["overlap"]:
        print("Overlap (intersections between reasons):")
        for k, v in report["overlap"].items():
            if v > 0:
                print(f"  {k}: {v}")
        print()


def _connect():
    url = os.environ.get("DATABASE_PUBLIC_URL")
    if not url:
        raise SystemExit(
            "DATABASE_PUBLIC_URL is not set. "
            "Export it before running (monorail.proxy.rlwy.net URL)."
        )
    try:
        import psycopg2
    except ImportError as e:
        raise SystemExit(
            "psycopg2 is required for the production audit. "
            "Install with: pip install psycopg2-binary"
        ) from e
    return psycopg2.connect(url)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ship #12 read-only audit")
    parser.add_argument(
        "--output",
        default=os.path.join(os.path.dirname(__file__), "ship_12_audit_report.json"),
        help="Path for the JSON report file",
    )
    args = parser.parse_args(argv)

    conn = _connect()
    try:
        flagged = run_audit(conn)
    finally:
        conn.close()

    report = _build_report(flagged)
    _print_counts(report)

    with open(args.output, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

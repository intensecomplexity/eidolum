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

RULE_VERSION = "v12.1"

REASONS: Tuple[str, ...] = (
    "disclosure_misroute",
    "invented_timeframe",
    "unresolvable_reference",
    "basket_shoehorn",
    "duplicate_source",
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

# Basket phrases that the extractor force-assigned to a single ticker.
_BASKET_RE = re.compile(
    r"\b(?:semis|semiconductors|banks|miners|airlines|retailers|"
    r"mag\s*7|magnificent\s+seven|faang|the\s+group|the\s+sector|"
    r"the\s+space|all\s+of\s+them|these\s+names|these\s+stocks|"
    r"the\s+basket|the\s+index|small\s+caps|large\s+caps|mid\s+caps|"
    r"growth\s+names|value\s+names|chinese\s+stocks|eu\s+stocks)\b",
    re.IGNORECASE,
)

# Escape hatch: "TICKER specifically" means the speaker DID single out
# that ticker out of a basket — those rows stay clean.
_BASKET_SPECIFIC_RE = re.compile(r"\bspecifically\b", re.IGNORECASE)


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

_SELECT_INVENTED_TIMEFRAME_CANDIDATES = """
SELECT id, ticker, context, exact_quote, quote_context, window_days,
       timeframe_source, created_at
FROM predictions
WHERE window_days = 90
  AND (timeframe_source IS NULL OR timeframe_source <> 'explicit')
  AND excluded_from_training = FALSE
"""

_SELECT_UNRESOLVABLE_REF_CANDIDATES = """
SELECT id, ticker, context, exact_quote, quote_context, created_at
FROM predictions
WHERE context IS NOT NULL
  AND excluded_from_training = FALSE
"""

_SELECT_BASKET_CANDIDATES = """
SELECT id, ticker, context, exact_quote, quote_context, created_at
FROM predictions
WHERE context IS NOT NULL
  AND excluded_from_training = FALSE
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
    """rows: (id, ticker, context, exact_quote, quote_context, window_days,
    timeframe_source, created_at). Flags when source text contains NO
    explicit time unit at all."""
    flagged = []
    for r in rows:
        _id = r[0]
        blob = _source_text((r[2], r[3], r[4]))
        if _EXPLICIT_TIMEFRAME_RE.search(blob):
            continue
        flagged.append(_id)
    return flagged


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


def _filter_basket_shoehorn(rows: List[tuple]) -> List[int]:
    """rows: (id, ticker, context, exact_quote, quote_context, created_at).
    Flags when basket/index phrases appear and the row doesn't
    explicitly single out the ticker with 'specifically'."""
    flagged = []
    for r in rows:
        _id = r[0]
        context = r[2] or ""
        if not _BASKET_RE.search(context):
            continue
        if _BASKET_SPECIFIC_RE.search(context):
            continue
        flagged.append(_id)
    return flagged


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
    results["basket_shoehorn"] = _filter_basket_shoehorn(
        _fetch(conn, _SELECT_BASKET_CANDIDATES)
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

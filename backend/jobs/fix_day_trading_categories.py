"""
One-shot reclassifier for the day_trading miscategorization bug.

Context: the YouTube classifier's METADATA_ENRICHMENT prompt had a
BUCKET MAPPING table that sent any explicit horizon <= 1 day into
timeframe_category='day_trading'. Haiku also defaulted to 1-2 day
horizons when the speaker's language was ambiguous, so ~50 out of 91
day_trading rows were actually earnings plays, macro commentary, or
swing trades misrouted by the numeric fallback.

The prompt has been fixed (day_trading removed from the numeric
bucket mapping — 1-day horizons now fall into swing_trade unless
Haiku explicitly picks day_trading from the signal-phrase table).
This script retroactively reclassifies the existing 91 rows by
sending ONLY the short verbatim quote (not the full transcript) to
Haiku and asking which category best fits. Predictions without a
quote are skipped — there's nothing to classify.

Usage (from backend/):
    python -m jobs.fix_day_trading_categories             # dry run
    python -m jobs.fix_day_trading_categories --apply     # write to DB
    python -m jobs.fix_day_trading_categories --apply --limit 10
    python -m jobs.fix_day_trading_categories --apply --delay 1

Cost: ~91 rows × ~300 input tokens × $1/MTok input + ~5 output
tokens × $5/MTok output ≈ $0.03 per full run. Trivial.
"""
import argparse
import os
import sys
import threading
import time


class FuturesTimeout(Exception):
    """Raised by _run_with_timeout when the wrapped call exceeds timeout_sec."""
    pass


# Allow running as `python -m jobs.fix_day_trading_categories` from backend/.
if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text as sql_text
from database import BgSessionLocal


# ── Constants ─────────────────────────────────────────────────────────────────

TAG = "[fix-daytrading]"

DEFAULT_DELAY = 1.0

# Bounded by wall-clock timeout — Haiku can hang on a flaky connection.
HAIKU_TIMEOUT = 30
HAIKU_MODEL = "claude-haiku-4-5-20251001"
HAIKU_MAX_TOKENS = 20

# The allowed category set this script is willing to WRITE. Pulled from
# the user-supplied prompt category list; every value exists in the
# current production distinct-set for verified_by=youtube_haiku_v1
# (see README of this ship). "structural" is deliberately NOT in this
# set — it exists in the DB but not in the fix prompt, so if Haiku
# returns it we treat it as unknown and skip the row.
_ALLOWED_CATEGORIES: frozenset[str] = frozenset({
    "day_trading",
    "swing_trade",
    "options_short",
    "options_monthly",
    "technical_chart",
    "fundamental_quarterly",
    "earnings_cycle",
    "cyclical_medium",
    "macro_thesis",
    "long_term_fundamental",
})

# Short rewrite prompt. Deliberately framed to bias Haiku toward
# changing the category — the status-quo category is already in
# production and we ONLY call this script to find miscategorizations.
# Even so the final "If day_trading is actually correct, respond with
# day_trading" line keeps the door open for genuine intraday trades.
_REWRITE_SYSTEM = (
    "You are classifying a stock market prediction quote from a YouTube "
    "video. Based ONLY on the quote below, pick the most appropriate "
    "timeframe category. The quote was originally classified as "
    "'day_trading' but may be wrong.\n\n"
    "Categories:\n"
    "- day_trading: explicit same-day trade with intraday price targets "
    "or \"by close today\" language\n"
    "- swing_trade: 2-21 day trade, mentions \"this week\", specific "
    "short-term price levels, technical setups\n"
    "- options_short: options expiring within a week\n"
    "- options_monthly: options expiring within a month\n"
    "- technical_chart: 22-30 day, chart patterns, breakouts, resistance "
    "levels\n"
    "- fundamental_quarterly: mentions earnings, quarterly results, "
    "revenue guidance, next quarter\n"
    "- earnings_cycle: specifically about an upcoming earnings report "
    "within days\n"
    "- cyclical_medium: 3-6 month thesis\n"
    "- macro_thesis: mentions Fed, inflation, interest rates, economy, "
    "currency, multi-month macro narrative\n"
    "- long_term_fundamental: 2+ year thesis, valuation model, long-term "
    "holding\n\n"
    "Respond with ONLY the category name, nothing else. If day_trading "
    "is actually correct, respond with day_trading."
)


# ── Timeout helper (mirror of the one in backfill_youtube_timestamps) ────────

def _run_with_timeout(fn, *args, timeout_sec=None, **kwargs):
    result = [None]
    exc = [None]

    def _target():
        try:
            result[0] = fn(*args, **kwargs)
        except BaseException as e:
            exc[0] = e

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)
    if t.is_alive():
        raise FuturesTimeout(f"{fn.__name__} did not complete within {timeout_sec}s")
    if exc[0] is not None:
        raise exc[0]
    return result[0]


# ── Haiku client ─────────────────────────────────────────────────────────────

_anthropic_client = None


def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        print(f"{TAG} WARNING: ANTHROPIC_API_KEY not set — no reclassification possible", flush=True)
        return None
    try:
        import anthropic
        _anthropic_client = anthropic.Anthropic(api_key=key)
        return _anthropic_client
    except Exception as e:
        print(f"{TAG} WARNING: anthropic client init failed: {e}", flush=True)
        return None


def _ask_haiku_for_category(
    client,
    *,
    ticker: str,
    direction: str,
    inferred_days: int | None,
    quote: str,
) -> tuple[str | None, int, int]:
    """Returns (category_name_or_None, input_tokens, output_tokens)."""
    user_msg = (
        f"Ticker: {ticker}\n"
        f"Direction: {direction}\n"
        f"Current category: day_trading\n"
        f"Current horizon: {inferred_days if inferred_days is not None else '?'} days\n\n"
        f"Quote:\n\"{quote.strip()}\""
    )
    try:
        resp = _run_with_timeout(
            client.messages.create,
            model=HAIKU_MODEL,
            max_tokens=HAIKU_MAX_TOKENS,
            temperature=0,
            system=_REWRITE_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            timeout_sec=HAIKU_TIMEOUT,
        )
    except FuturesTimeout:
        return (None, 0, 0)
    except Exception as e:
        print(f"{TAG}   Haiku error: {type(e).__name__}: {str(e)[:150]}", flush=True)
        return (None, 0, 0)

    text = resp.content[0].text.strip() if resp.content else ""
    usage = resp.usage if hasattr(resp, "usage") else None
    in_tok = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    out_tok = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0

    # Normalize: lower, strip punctuation/quotes, squash whitespace.
    norm = text.lower().strip().strip('"').strip("'").strip(".").strip()
    # Haiku sometimes wraps the answer: "day_trading." → strip that.
    # Take the first whitespace-delimited token if the response drifts.
    first_token = norm.split()[0] if norm else ""
    candidate = first_token.replace("-", "_")

    if candidate in _ALLOWED_CATEGORIES:
        return (candidate, in_tok, out_tok)
    # Haiku replied with something not in the allowed set — treat as
    # indeterminate and skip the row.
    print(
        f"{TAG}   UNEXPECTED category from Haiku: '{text[:60]}' — skipping",
        flush=True,
    )
    return (None, in_tok, out_tok)


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Reclassify existing day_trading YouTube predictions "
                    "by asking Haiku which category best fits the quote.",
    )
    parser.add_argument("--apply", action="store_true",
                        help="Actually write to DB. Default is dry-run.")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process only the first N rows (0 = all).")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                        help=f"Seconds between Haiku calls (default {DEFAULT_DELAY}).")
    args = parser.parse_args(argv)

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"{TAG} Starting day_trading reclassifier ({mode})", flush=True)
    if args.limit:
        print(f"{TAG} Row limit: {args.limit}", flush=True)

    client = _get_anthropic_client()
    if client is None:
        print(f"{TAG} No Haiku client — aborting.")
        return 1

    db = BgSessionLocal()
    try:
        return _run(db, client, apply=args.apply, limit=args.limit, delay=args.delay)
    finally:
        db.close()


def _run(db, client, *, apply: bool, limit: int, delay: float) -> int:
    try:
        db.execute(sql_text("SET statement_timeout = 0"))
        db.commit()
    except Exception as _e:
        print(f"{TAG} WARNING: could not disable statement_timeout: {_e}", flush=True)

    # Query candidates: day_trading, non-excluded, with a usable quote.
    rows = db.execute(sql_text("""
        SELECT id, ticker, direction, source_verbatim_quote,
               conviction_level, inferred_timeframe_days
        FROM predictions
        WHERE verified_by = 'youtube_haiku_v1'
          AND timeframe_category = 'day_trading'
          AND excluded_from_training = FALSE
          AND source_verbatim_quote IS NOT NULL
          AND length(source_verbatim_quote) > 10
        ORDER BY id DESC
    """)).fetchall()

    # Also count the skipped-no-quote set so the user knows the total scope.
    skipped_no_quote = db.execute(sql_text("""
        SELECT COUNT(*) FROM predictions
        WHERE verified_by = 'youtube_haiku_v1'
          AND timeframe_category = 'day_trading'
          AND excluded_from_training = FALSE
          AND (source_verbatim_quote IS NULL OR length(source_verbatim_quote) <= 10)
    """)).scalar() or 0

    if not rows:
        print(f"{TAG} No candidates found.")
        if skipped_no_quote:
            print(f"{TAG}   ({skipped_no_quote} day_trading rows have no quote — untouchable)")
        return 0

    if limit:
        rows = list(rows)[:limit]
    total = len(rows)
    print(f"{TAG} Candidates: {total} rows with a quote "
          f"(+{skipped_no_quote} skipped for missing quote)", flush=True)

    stats: dict = {
        "checked": 0,
        "changed": 0,
        "kept_day_trading": 0,
        "skipped_haiku_unexpected": 0,
        "skipped_haiku_error": 0,
        "from_to": {},
        "input_tokens": 0,
        "output_tokens": 0,
    }

    for i, r in enumerate(rows):
        pid = r.id
        ticker = r.ticker or "?"
        direction = r.direction or "?"
        quote = r.source_verbatim_quote or ""
        inferred_days = r.inferred_timeframe_days

        if i > 0:
            time.sleep(delay)

        new_cat, in_tok, out_tok = _ask_haiku_for_category(
            client,
            ticker=ticker,
            direction=direction,
            inferred_days=inferred_days,
            quote=quote,
        )
        stats["checked"] += 1
        stats["input_tokens"] += in_tok
        stats["output_tokens"] += out_tok

        if new_cat is None:
            # Already logged inside _ask_haiku_for_category for unexpected/error.
            stats["skipped_haiku_error"] += 1
            continue

        if new_cat == "day_trading":
            stats["kept_day_trading"] += 1
            print(
                f"{TAG}   [{i+1}/{total}] id={pid:>7d} {ticker:>6s} "
                f"day_trading → day_trading (keep)",
                flush=True,
            )
            continue

        # Real change: record it and maybe UPDATE
        key = f"day_trading→{new_cat}"
        stats["from_to"][key] = stats["from_to"].get(key, 0) + 1
        stats["changed"] += 1
        print(
            f"{TAG}   [{i+1}/{total}] id={pid:>7d} {ticker:>6s} "
            f"day_trading → {new_cat}",
            flush=True,
        )

        if apply:
            try:
                db.execute(sql_text("""
                    UPDATE predictions
                       SET timeframe_category = :new_cat
                     WHERE id = :id
                       AND timeframe_category = 'day_trading'
                """), {"new_cat": new_cat, "id": pid})
                db.commit()
            except Exception as _uerr:
                print(
                    f"{TAG}   UPDATE failed for id={pid}: "
                    f"{type(_uerr).__name__}: {str(_uerr)[:150]}",
                    flush=True,
                )
                try:
                    db.rollback()
                except Exception:
                    pass

    # ── Summary ──────────────────────────────────────────────────────────
    # Haiku 4.5 input 1.0/MTok, output 5.0/MTok (keep in sync with classifier).
    cost = (
        stats["input_tokens"] * 1.0 / 1_000_000
        + stats["output_tokens"] * 5.0 / 1_000_000
    )
    print(f"\n{TAG} ── Summary ──")
    print(f"{TAG}   Checked:             {stats['checked']}")
    print(f"{TAG}   Changed:             {stats['changed']}")
    print(f"{TAG}   Kept day_trading:    {stats['kept_day_trading']}")
    print(f"{TAG}   Skipped (Haiku err): {stats['skipped_haiku_error']}")
    print(f"{TAG}   No-quote untouched:  {skipped_no_quote}")
    print(f"{TAG}   Haiku tokens:        in={stats['input_tokens']} out={stats['output_tokens']}")
    print(f"{TAG}   Haiku cost:          ${cost:.4f}")
    if stats["from_to"]:
        print(f"{TAG}   Transitions:")
        for k, v in sorted(stats["from_to"].items(), key=lambda x: -x[1]):
            print(f"{TAG}     {k}: {v}")

    if not apply:
        print(f"\n{TAG} DRY RUN — no DB writes. Pass --apply to commit.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
One-shot reclassifier for YouTube predictions with direction='neutral'.

Context: sampling 30 random rows in this category showed ~63% are
actually directional calls where the speaker hedged their language
(Haiku defaulted to neutral rather than picking bullish/bearish),
~23% are not predictions at all (research notes, position disclosures,
news summaries, "I'm watching it" statements), and only ~13% are
genuinely neutral hold recommendations.

This script fixes the backlog the same way fix_day_trading_categories.py
fixed the day_trading miscategorization: send ONLY the short verbatim
quote (no transcript, no extra context) to Haiku with a focused rewrite
prompt, and UPDATE the row based on the response.

Usage (from backend/):
    python -m jobs.fix_neutral_direction             # dry run
    python -m jobs.fix_neutral_direction --apply     # write to DB
    python -m jobs.fix_neutral_direction --apply --limit 10
    python -m jobs.fix_neutral_direction --apply --delay 0.3

Cost: ~263 rows × ~300 input tokens × $1/MTok + ~5 output tokens × $5/MTok
≈ $0.08 per full run. Trivial.

Runs safely in parallel with any other backfill — the UPDATE has a
`AND direction='neutral' AND excluded_from_training=FALSE` guard so a
row that another process already resolved is a no-op here.
"""
import argparse
import os
import sys
import threading
import time


class FuturesTimeout(Exception):
    """Raised by _run_with_timeout when the wrapped call exceeds timeout_sec."""
    pass


# Allow running as `python -m jobs.fix_neutral_direction` from backend/.
if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text as sql_text
from database import BgSessionLocal


# ── Constants ─────────────────────────────────────────────────────────────────

TAG = "[fix-neutral]"

DEFAULT_DELAY = 0.5

HAIKU_TIMEOUT = 30
HAIKU_MODEL = "claude-haiku-4-5-20251001"
HAIKU_MAX_TOKENS = 20

# Exclusion metadata applied when Haiku flags a row as "not_a_prediction".
# Fits the column widths (exclusion_reason=VARCHAR(64),
# exclusion_rule_version=VARCHAR(16)).
_EXCLUSION_REASON = "not_a_prediction"
_EXCLUSION_VERSION = "v15.1"

# Responses we're willing to act on. Anything else is logged as unexpected
# and skipped.
_ALLOWED_RESPONSES: frozenset[str] = frozenset({
    "bullish",
    "bearish",
    "neutral",
    "not_a_prediction",
})

# Rewrite prompt. Deliberately mirrors the user's ship spec so the
# reclassification decisions are reproducible from the commit message
# alone. The four-label menu is the contract — if Haiku drifts we skip.
_REWRITE_SYSTEM = (
    "You are reviewing a stock market prediction quote from a YouTube "
    "video. The quote was labeled 'neutral' direction but may be wrong. "
    "Based ONLY on the quote below, determine what the speaker actually "
    "thinks.\n\n"
    "Respond with ONE of:\n"
    "- bullish (the speaker expects the stock/asset to go up, or "
    "recommends buying, or says it's undervalued)\n"
    "- bearish (the speaker expects the stock/asset to go down, or "
    "recommends selling/avoiding, or says it's overvalued)\n"
    "- neutral (the speaker is genuinely flat, presenting both sides "
    "equally, or giving a hold recommendation)\n"
    "- not_a_prediction (this is a research note, news summary, "
    "position disclosure, tool output, or 'I'm watching this' "
    "statement with no forward call)\n\n"
    "Respond with ONLY the label, nothing else."
)


# ── Timeout helper (mirror of fix_day_trading_categories.py) ─────────────────

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


def _ask_haiku_for_direction(
    client,
    *,
    ticker: str,
    conviction: str | None,
    quote: str,
) -> tuple[str | None, int, int]:
    """Returns (label_or_None, input_tokens, output_tokens)."""
    conv_display = conviction or "unknown"
    user_msg = (
        f"Ticker: {ticker}\n"
        f"Current direction: neutral\n"
        f"Conviction: {conv_display}\n\n"
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

    # Normalize Haiku's response — lower, strip punctuation/quotes.
    norm = text.lower().strip().strip('"').strip("'").strip(".").strip()
    # Take the first whitespace-delimited token if Haiku wraps the answer.
    first_token = norm.split()[0] if norm else ""
    # Haiku sometimes returns "not a prediction" with spaces instead of
    # "not_a_prediction" — accept both by collapsing spaces to underscores
    # across the full normalized string, then picking the first block.
    collapsed = norm.replace(" ", "_").replace("-", "_")
    # Prefer the direct 4-label match on `collapsed` so "not a prediction"
    # resolves correctly; fall back to first_token only if collapsed fails.
    if collapsed in _ALLOWED_RESPONSES:
        return (collapsed, in_tok, out_tok)
    if first_token in _ALLOWED_RESPONSES:
        return (first_token, in_tok, out_tok)

    print(
        f"{TAG}   UNEXPECTED response from Haiku: '{text[:60]}' — skipping",
        flush=True,
    )
    return (None, in_tok, out_tok)


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Reclassify YouTube predictions with direction='neutral' "
                    "by asking Haiku what the speaker actually thinks.",
    )
    parser.add_argument("--apply", action="store_true",
                        help="Actually write to DB. Default is dry-run.")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process only the first N rows (0 = all).")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                        help=f"Seconds between Haiku calls (default {DEFAULT_DELAY}).")
    args = parser.parse_args(argv)

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"{TAG} Starting neutral-direction reclassifier ({mode})", flush=True)
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

    # Query candidates: direction='neutral', non-excluded, with a usable quote.
    rows = db.execute(sql_text("""
        SELECT id, ticker, source_verbatim_quote, conviction_level
        FROM predictions
        WHERE verified_by = 'youtube_haiku_v1'
          AND direction = 'neutral'
          AND excluded_from_training = FALSE
          AND source_verbatim_quote IS NOT NULL
          AND length(source_verbatim_quote) > 10
        ORDER BY id DESC
    """)).fetchall()

    # Count the untouchable subset (no quote) so the summary reflects total scope.
    skipped_no_quote = db.execute(sql_text("""
        SELECT COUNT(*) FROM predictions
        WHERE verified_by = 'youtube_haiku_v1'
          AND direction = 'neutral'
          AND excluded_from_training = FALSE
          AND (source_verbatim_quote IS NULL OR length(source_verbatim_quote) <= 10)
    """)).scalar() or 0

    if not rows:
        print(f"{TAG} No candidates found.")
        if skipped_no_quote:
            print(f"{TAG}   ({skipped_no_quote} neutral rows have no quote — untouchable)")
        return 0

    if limit:
        rows = list(rows)[:limit]
    total = len(rows)
    print(
        f"{TAG} Candidates: {total} rows with a quote "
        f"(+{skipped_no_quote} skipped for missing quote)",
        flush=True,
    )

    stats: dict = {
        "checked": 0,
        "to_bullish": 0,
        "to_bearish": 0,
        "kept_neutral": 0,
        "excluded": 0,
        "skipped_haiku_error": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }

    for i, r in enumerate(rows):
        pid = r.id
        ticker = r.ticker or "?"
        quote = r.source_verbatim_quote or ""
        conviction = r.conviction_level

        if i > 0:
            time.sleep(delay)

        label, in_tok, out_tok = _ask_haiku_for_direction(
            client,
            ticker=ticker,
            conviction=conviction,
            quote=quote,
        )
        stats["checked"] += 1
        stats["input_tokens"] += in_tok
        stats["output_tokens"] += out_tok

        if label is None:
            stats["skipped_haiku_error"] += 1
            continue

        if label == "neutral":
            stats["kept_neutral"] += 1
            print(
                f"{TAG}   [{i+1}/{total}] id={pid:>7d} {ticker:>6s} "
                f"neutral → neutral (keep)",
                flush=True,
            )
            continue

        if label == "bullish":
            stats["to_bullish"] += 1
            print(
                f"{TAG}   [{i+1}/{total}] id={pid:>7d} {ticker:>6s} "
                f"neutral → bullish",
                flush=True,
            )
            if apply:
                _update_direction(db, pid, "bullish")
            continue

        if label == "bearish":
            stats["to_bearish"] += 1
            print(
                f"{TAG}   [{i+1}/{total}] id={pid:>7d} {ticker:>6s} "
                f"neutral → bearish",
                flush=True,
            )
            if apply:
                _update_direction(db, pid, "bearish")
            continue

        if label == "not_a_prediction":
            stats["excluded"] += 1
            print(
                f"{TAG}   [{i+1}/{total}] id={pid:>7d} {ticker:>6s} "
                f"neutral → EXCLUDED (not_a_prediction)",
                flush=True,
            )
            if apply:
                _update_exclusion(db, pid)
            continue

    # ── Summary ──────────────────────────────────────────────────────────
    # Haiku 4.5 input 1.0/MTok, output 5.0/MTok.
    cost = (
        stats["input_tokens"] * 1.0 / 1_000_000
        + stats["output_tokens"] * 5.0 / 1_000_000
    )
    print(f"\n{TAG} ── Summary ──")
    print(f"{TAG}   Checked:             {stats['checked']}")
    print(f"{TAG}   → bullish:           {stats['to_bullish']}")
    print(f"{TAG}   → bearish:           {stats['to_bearish']}")
    print(f"{TAG}   Kept neutral:        {stats['kept_neutral']}")
    print(f"{TAG}   Excluded (not_pred): {stats['excluded']}")
    print(f"{TAG}   Skipped (Haiku err): {stats['skipped_haiku_error']}")
    print(f"{TAG}   No-quote untouched:  {skipped_no_quote}")
    print(f"{TAG}   Haiku tokens:        in={stats['input_tokens']} out={stats['output_tokens']}")
    print(f"{TAG}   Haiku cost:          ${cost:.4f}")

    if not apply:
        print(f"\n{TAG} DRY RUN — no DB writes. Pass --apply to commit.")

    return 0


def _update_direction(db, pid: int, new_dir: str) -> None:
    """Flip direction to bullish/bearish. Guarded so a parallel run can't
    overwrite a previously-resolved row."""
    try:
        db.execute(sql_text("""
            UPDATE predictions
               SET direction = :new_dir
             WHERE id = :id
               AND direction = 'neutral'
               AND excluded_from_training = FALSE
        """), {"new_dir": new_dir, "id": pid})
        db.commit()
    except Exception as _uerr:
        print(
            f"{TAG}   UPDATE failed for id={pid} → {new_dir}: "
            f"{type(_uerr).__name__}: {str(_uerr)[:150]}",
            flush=True,
        )
        try:
            db.rollback()
        except Exception:
            pass


def _update_exclusion(db, pid: int) -> None:
    """Set excluded_from_training=TRUE with the ship's exclusion metadata.
    Guarded so only neutral rows not already excluded get stamped."""
    try:
        db.execute(sql_text("""
            UPDATE predictions
               SET excluded_from_training = TRUE,
                   exclusion_reason = :reason,
                   exclusion_flagged_at = NOW(),
                   exclusion_rule_version = :ver
             WHERE id = :id
               AND direction = 'neutral'
               AND excluded_from_training = FALSE
        """), {
            "reason": _EXCLUSION_REASON,
            "ver": _EXCLUSION_VERSION,
            "id": pid,
        })
        db.commit()
    except Exception as _uerr:
        print(
            f"{TAG}   EXCLUDE UPDATE failed for id={pid}: "
            f"{type(_uerr).__name__}: {str(_uerr)[:150]}",
            flush=True,
        )
        try:
            db.rollback()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())

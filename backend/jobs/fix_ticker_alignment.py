"""
Ticker/quote alignment validator.

The quality audit surfaced at least one prediction where the attached
verbatim quote was about a completely different company (a VICI
Properties quote stamped on LYV).  A model trained on mismatched
ticker/quote pairs learns the wrong associations, so we run one cheap
Haiku pass across the training-ready-with-direction population and
exclude anything the classifier flags as a mismatch.

Usage (from backend/):
    python -m jobs.fix_ticker_alignment                 # dry run
    python -m jobs.fix_ticker_alignment --apply         # write to DB
    python -m jobs.fix_ticker_alignment --apply --limit 30
    python -m jobs.fix_ticker_alignment --apply --delay 0.3

Scope:
    Only the rows that would actually land in the training JSONL are
    scanned (verified_by youtube_haiku_v1, excluded_from_training FALSE,
    direction bullish/bearish, timeframe/conviction/timestamp populated).
    The UPDATE is guarded with `AND excluded_from_training = FALSE`, so
    this job is safe to run alongside other backfill scripts.

What it changes:
    mismatch → excluded_from_training TRUE, exclusion_reason
    'ticker_quote_mismatch', exclusion_rule_version 'v16.4'.
    match / ambiguous → no DB writes (ambiguous rows are logged for
    manual review).
"""
import argparse
import os
import sys
import threading
import time


class FuturesTimeout(Exception):
    """Raised by _run_with_timeout when the wrapped call exceeds timeout_sec."""
    pass


# Allow running as `python -m jobs.fix_ticker_alignment` from backend/.
if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text as sql_text
from database import BgSessionLocal


# ── Constants ─────────────────────────────────────────────────────────────────

TAG = "[ticker-check]"

DEFAULT_DELAY = 0.3

HAIKU_TIMEOUT = 30
HAIKU_MODEL = "claude-haiku-4-5-20251001"
HAIKU_MAX_TOKENS = 12

_EXCLUSION_REASON = "ticker_quote_mismatch"
# v16.4 was the first pass and hit ~75% false positives because the
# prompt had no ETF/crypto wrapper cheat sheet — 214 bad exclusions
# were reverted before the DB was polluted. v16.4a uses the expanded
# prompt and biases uncertainty toward 'ambiguous' instead of
# 'mismatch'. The version bump keeps history cleanly separable.
_EXCLUSION_VERSION = "v16.4a"

_ALLOWED_RESPONSES: frozenset[str] = frozenset({
    "match",
    "mismatch",
    "ambiguous",
})


# ── Timeout helper ───────────────────────────────────────────────────────────

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
        print(f"{TAG} WARNING: ANTHROPIC_API_KEY not set — aborting", flush=True)
        return None
    try:
        import anthropic
        _anthropic_client = anthropic.Anthropic(api_key=key)
        return _anthropic_client
    except Exception as e:
        print(f"{TAG} WARNING: anthropic client init failed: {e}", flush=True)
        return None


def _build_prompt(*, ticker: str, company_name: str | None, quote: str) -> str:
    company_bit = (
        f" ({company_name})"
        if company_name and company_name.strip()
        else ""
    )
    # The first pass of this job ran without the wrapper cheat sheet
    # and hit a ~75% false-positive rate, because Haiku has no
    # built-in knowledge that IBIT is an iShares Bitcoin ETF or that
    # SH is an inverse S&P product. The explicit mapping table below
    # is the fix. It's deliberately verbose — a few extra tokens per
    # row is cheap; wrongly excluding 200+ crypto/ETF predictions is
    # not. The final "when in doubt" rule biases uncertainty toward
    # ambiguous so only unmistakable misalignments get excluded.
    return (
        f"Does this quote discuss the stock ticker {ticker}{company_bit}?\n\n"
        "The quote may reference the company by name, by a common "
        "nickname, or by the underlying asset the ticker tracks. ALL "
        "of these count as a match:\n\n"
        "EQUITIES — company name counts as the ticker:\n"
        "  Apple=AAPL, Tesla=TSLA, Google/Alphabet=GOOGL/GOOG, "
        "Amazon=AMZN, Microsoft=MSFT, Meta/Facebook=META, "
        "Nvidia=NVDA, Netflix=NFLX, PayPal=PYPL, Uber=UBER, "
        "Nike=NKE, Berkshire=BRK.A/BRK.B.\n\n"
        "INDEX / BROAD-MARKET ETFs — 'the market', 'S&P', "
        "'Nasdaq', etc. count as matches:\n"
        "  SPY / VOO / IVV = S&P 500 ('the market', 'the S&P', "
        "'stocks')\n"
        "  QQQ / QQQM = Nasdaq-100 ('the Nasdaq', 'tech', 'the Qs')\n"
        "  DIA = Dow Jones\n"
        "  IWM = Russell 2000 ('small caps')\n"
        "  VTI = total US market\n"
        "  SH = INVERSE S&P (bearish S&P thesis IS a match — the "
        "speaker is betting against the index via SH)\n"
        "  SQQQ / PSQ = inverse / short Nasdaq\n"
        "  SDS = -2x S&P\n\n"
        "BONDS / RATES ETFs:\n"
        "  TLT = 20+ year treasuries ('long bonds', 'duration', "
        "'30-year')\n"
        "  IEF = 7-10 year treasuries\n"
        "  SHY = short-term treasuries\n"
        "  TBT / TMV = inverse / short long-bond (bearish rates)\n"
        "  TIP / SCHP = TIPS, inflation-linked treasuries "
        "('inflation protection', 'real yields')\n"
        "  HYG / JNK = high yield credit ('junk bonds', 'credit')\n"
        "  LQD = investment grade credit\n\n"
        "COMMODITIES / FX ETFs:\n"
        "  GLD / IAU = gold ('gold', 'the yellow metal')\n"
        "  SLV = silver\n"
        "  USO = crude oil ('oil', 'WTI', 'crude')\n"
        "  UNG = natural gas\n"
        "  DBC = broad commodities\n"
        "  UUP = US dollar ('the dollar', 'DXY')\n"
        "  FXE = euro, FXY = yen\n\n"
        "CRYPTO (native + ETF wrappers all count):\n"
        "  BTC / IBIT / FBTC / GBTC = Bitcoin\n"
        "  ETH / ETHA / ETHE / FETH = Ethereum\n"
        "  SOL = Solana\n"
        "  XRP = Ripple / XRP\n"
        "  LINK = Chainlink\n"
        "  LTC = Litecoin\n"
        "  DOGE = Dogecoin\n"
        "  ADA = Cardano\n"
        "  AVAX = Avalanche\n"
        "  DOT = Polkadot\n"
        "  MATIC = Polygon\n\n"
        "SECTOR ETFs — sector name counts:\n"
        "  XLF = financials, XLE = energy, XLK = tech, "
        "XLV = healthcare, XLI = industrials, XLY = consumer disc., "
        "XLP = staples, XLU = utilities, XLRE = real estate, "
        "XLB = materials, XLC = comms.\n"
        "  SMH / SOXX = semiconductors ('semis', 'chips')\n"
        "  KRE / KBE = regional / big banks\n"
        "  XBI / IBB = biotech\n"
        "  ARKK = ARK Innovation ('ARK', 'Cathie Wood')\n\n"
        "VOLATILITY:\n"
        "  VXX / UVXY = VIX / volatility ('the VIX', 'long vol')\n\n"
        f"Quote:\n\"{quote.strip()}\"\n\n"
        f"Ticker under review: {ticker}{company_bit}\n\n"
        "Respond with ONLY one of:\n"
        "- match (the quote is about this ticker / its underlying "
        "asset / the concept it tracks, per the table above)\n"
        "- mismatch (the quote is unmistakably about a DIFFERENT "
        "and SPECIFIC company or asset — e.g. the quote discusses "
        "VICI Properties but the ticker is LYV. Only use mismatch "
        "when you are highly confident and a different specific "
        "name is stated.)\n"
        "- ambiguous (you're not sure, OR the ticker isn't in the "
        "table above and the quote doesn't literally say its "
        "symbol/name, OR the quote is generic commentary that could "
        "apply)\n\n"
        "When in doubt, prefer ambiguous over mismatch. Mismatch "
        "should only fire when the quote clearly names a different "
        "company or asset than the ticker represents."
    )


def _ask_haiku_alignment(
    client,
    *,
    ticker: str,
    company_name: str | None,
    quote: str,
) -> tuple[str | None, int, int]:
    """Returns (label_or_None, input_tokens, output_tokens).

    Label is one of: 'match', 'mismatch', 'ambiguous', or None if Haiku
    timed out / errored / returned an unexpected response.
    """
    user_msg = _build_prompt(ticker=ticker, company_name=company_name, quote=quote)
    try:
        resp = _run_with_timeout(
            client.messages.create,
            model=HAIKU_MODEL,
            max_tokens=HAIKU_MAX_TOKENS,
            temperature=0,
            messages=[{"role": "user", "content": user_msg}],
            timeout_sec=HAIKU_TIMEOUT,
        )
    except FuturesTimeout:
        return (None, 0, 0)
    except Exception as e:
        print(f"{TAG}   Haiku error: {type(e).__name__}: {str(e)[:150]}", flush=True)
        return (None, 0, 0)

    text = resp.content[0].text if resp.content else ""
    usage = resp.usage if hasattr(resp, "usage") else None
    in_tok = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    out_tok = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0

    import re as _re
    norm = _re.sub(r"\s+", " ", text.lower().strip())
    norm = norm.strip('"').strip("'").strip(".").strip()

    # Order matters: 'mismatch' must be checked before 'match' so a
    # reply of "mismatch — ..." doesn't get swallowed by the match branch.
    if norm.startswith("mismatch"):
        return ("mismatch", in_tok, out_tok)
    if norm.startswith("ambiguous"):
        return ("ambiguous", in_tok, out_tok)
    if norm.startswith("match"):
        return ("match", in_tok, out_tok)

    print(
        f"{TAG}   UNEXPECTED response from Haiku: '{text[:80].replace(chr(10), ' ')}' — skipping",
        flush=True,
    )
    return (None, in_tok, out_tok)


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate ticker/quote alignment across training-ready "
                    "predictions. Flags rows where Haiku says the quote "
                    "is about a different company than the stamped ticker.",
    )
    parser.add_argument("--apply", action="store_true",
                        help="Actually write to DB. Default is dry-run.")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process only the first N rows (0 = all).")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                        help=f"Seconds between Haiku calls (default {DEFAULT_DELAY}).")
    args = parser.parse_args(argv)

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"{TAG} Starting ticker alignment check ({mode})", flush=True)
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

    # LEFT JOIN ticker_sectors so Haiku gets the company name when we
    # have one cached — makes the match/mismatch decision more reliable
    # for tickers that rarely appear verbatim in speech (e.g. BRK.B,
    # GOOGL).  Rows without a cached name still get scanned; Haiku just
    # sees the bare ticker.
    rows = db.execute(sql_text("""
        SELECT p.id,
               p.ticker,
               p.source_verbatim_quote,
               ts.company_name
          FROM predictions p
          LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker
         WHERE p.verified_by = 'youtube_haiku_v1'
           AND p.excluded_from_training = FALSE
           AND p.timeframe_category IS NOT NULL
           AND p.source_verbatim_quote IS NOT NULL
           AND p.source_timestamp_seconds IS NOT NULL
           AND p.conviction_level IS NOT NULL
           AND p.inferred_timeframe_days IS NOT NULL
           AND p.direction IN ('bullish','bearish')
         ORDER BY p.id DESC
    """)).fetchall()

    if not rows:
        print(f"{TAG} No candidates found.")
        return 0

    if limit:
        rows = list(rows)[:limit]
    total = len(rows)
    print(f"{TAG} Candidates: {total} training-ready rows", flush=True)

    stats: dict = {
        "checked": 0,
        "match": 0,
        "mismatch": 0,
        "ambiguous": 0,
        "skipped_haiku_error": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    ambiguous_ids: list[int] = []
    mismatch_ids: list[int] = []

    for i, r in enumerate(rows):
        pid = r.id
        ticker = r.ticker or "?"
        quote = r.source_verbatim_quote or ""
        company_name = getattr(r, "company_name", None)

        if i > 0:
            time.sleep(delay)

        label, in_tok, out_tok = _ask_haiku_alignment(
            client,
            ticker=ticker,
            company_name=company_name,
            quote=quote,
        )
        stats["checked"] += 1
        stats["input_tokens"] += in_tok
        stats["output_tokens"] += out_tok

        if label is None:
            stats["skipped_haiku_error"] += 1
            continue

        if label == "match":
            stats["match"] += 1
            # Keep log terse — one line per row only every 50 for the
            # happy path so the log isn't 3900 lines of noise.
            if (i + 1) % 50 == 0 or i < 5:
                print(
                    f"{TAG} id={pid:>7d} {ticker:>6s} \u2713 match "
                    f"[{i+1}/{total}]",
                    flush=True,
                )
            continue

        if label == "ambiguous":
            stats["ambiguous"] += 1
            ambiguous_ids.append(pid)
            print(
                f"{TAG} id={pid:>7d} {ticker:>6s} ? ambiguous — kept, "
                f"review suggested",
                flush=True,
            )
            continue

        # label == 'mismatch'
        stats["mismatch"] += 1
        mismatch_ids.append(pid)
        print(
            f"{TAG} id={pid:>7d} {ticker:>6s} \u2717 MISMATCH — excluded",
            flush=True,
        )
        if apply:
            _update_exclusion(db, pid)

    # ── Summary ──────────────────────────────────────────────────────────
    cost = (
        stats["input_tokens"] * 1.0 / 1_000_000
        + stats["output_tokens"] * 5.0 / 1_000_000
    )
    pct_mismatch = stats["mismatch"] * 100 / max(stats["checked"], 1)
    print(f"\n{TAG} ── Summary ──")
    print(f"{TAG}   Scanned:             {stats['checked']}")
    print(f"{TAG}   Match (kept):        {stats['match']}")
    print(f"{TAG}   Mismatch (excluded): {stats['mismatch']}  ({pct_mismatch:.1f}%)")
    print(f"{TAG}   Ambiguous (kept):    {stats['ambiguous']}")
    print(f"{TAG}   Skipped (Haiku err): {stats['skipped_haiku_error']}")
    print(f"{TAG}   Haiku tokens:        in={stats['input_tokens']} out={stats['output_tokens']}")
    print(f"{TAG}   Haiku cost:          ${cost:.4f}")

    if ambiguous_ids:
        # Print the full list once at the end so a reviewer can copy/paste
        # them into a manual audit without having to re-grep the log.
        preview = ", ".join(str(x) for x in ambiguous_ids[:50])
        more = "" if len(ambiguous_ids) <= 50 else f" … (+{len(ambiguous_ids) - 50} more)"
        print(f"{TAG}   Ambiguous ids:       {preview}{more}")

    if not apply:
        if mismatch_ids:
            preview = ", ".join(str(x) for x in mismatch_ids[:50])
            more = "" if len(mismatch_ids) <= 50 else f" … (+{len(mismatch_ids) - 50} more)"
            print(f"{TAG}   Would-exclude ids:   {preview}{more}")
        print(f"\n{TAG} DRY RUN — no DB writes. Pass --apply to commit.")

    return 0


def _update_exclusion(db, pid: int) -> None:
    try:
        db.execute(sql_text("""
            UPDATE predictions
               SET excluded_from_training = TRUE,
                   exclusion_reason = :reason,
                   exclusion_flagged_at = NOW(),
                   exclusion_rule_version = :ver
             WHERE id = :id
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

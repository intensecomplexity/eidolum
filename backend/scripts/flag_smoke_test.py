#!/usr/bin/env python3
"""Flag smoke test harness for the 11 Eidolum YouTube ship flags.

Runs jobs.youtube_classifier.classify_video against a canned per-flag
transcript fixture designed to trigger exactly one extractor, then
checks the returned prediction dicts for the flag's signature field.

Dry-run only. No DB writes. Reads live flag state from prod via a
read-only SQLAlchemy session (DATABASE_PUBLIC_URL). Every flag must be
ON in prod for its test to be meaningful — the harness prints a warning
and still runs otherwise.

Usage:
    export ANTHROPIC_API_KEY=...
    export DATABASE_PUBLIC_URL=postgresql://...
    python backend/scripts/flag_smoke_test.py --all
    python backend/scripts/flag_smoke_test.py --flag pair_call_extraction

The harness is intentionally a read-only sibling of the real pipeline:
- Imports classify_video directly (no scheduler, no dedupe stage).
- Passes a prod DB session so classify_video's feature_flags reads hit
  the same config rows the real worker uses.
- Never calls _insert_prediction / _route_to_disclosure_table, so
  predictions never reach the DB. Even in the classify_video path the
  only DB interaction is the 11 feature_flags SELECTs.

Cost budget: ~11 Haiku calls with short (<400 char) canned transcripts.
Estimated ~100K input tokens (with ephemeral prompt cache kicking in
after call 1) and ~11K output. Well under $0.20.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


def _fatal(msg: str, code: int = 2) -> None:
    print(f"FATAL: {msg}", file=sys.stderr)
    sys.exit(code)


if not os.getenv("ANTHROPIC_API_KEY"):
    _fatal("ANTHROPIC_API_KEY not set in env")

DB_URL = os.getenv("DATABASE_PUBLIC_URL") or os.getenv("DATABASE_URL")
if not DB_URL:
    _fatal("DATABASE_PUBLIC_URL (or DATABASE_URL) not set in env")


from sqlalchemy import create_engine, text as sql_text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

_engine = create_engine(DB_URL, pool_pre_ping=True)
_Session = sessionmaker(bind=_engine)


from jobs.youtube_classifier import classify_video  # noqa: E402


# ─── Fixtures ────────────────────────────────────────────────────────────────
#
# Each entry:
#   title        — fake video title (influences only logging)
#   transcript   — canned passage designed to trigger exactly one extractor
#   signature    — predicate(list[pred_dict]) -> bool
#   description  — human-readable "what this should produce" for the report
#
# Signatures lean on the `derived_from` marker (and `_kind` / `_derived_from`
# on the post-validator dicts where relevant) because that's what each ship's
# instruction block teaches Haiku to stamp. target_revisions uses the
# `is_revision` flag per its block. ranked_list_extraction uses list_rank.

FIXTURES: dict[str, dict] = {
    "ranked_list_extraction": {
        "title": "My Top 5 Stocks for 2026",
        "transcript": (
            "Here are my top 5 picks for 2026, in order. Number one is NVIDIA, "
            "ticker NVDA, my highest conviction name. Number two is AMD. Number "
            "three is Taiwan Semi, TSM. Number four is Apple, AAPL. And number "
            "five is Microsoft. These are my five biggest positions going into "
            "the new year."
        ),
        "signature": lambda preds: any(
            ("list_rank" in p) or ("list_id" in p) for p in preds
        ),
        "description": "Ranked-list ticker_calls with list_id + list_rank fields.",
    },
    "target_revisions": {
        "title": "Updating My NVDA Target",
        "transcript": (
            "Quick update on my NVIDIA call. Last month I said NVDA was going to "
            "two hundred dollars over the next six months. I'm raising my target "
            "from two hundred to two hundred and forty. The Blackwell ramp is "
            "ahead of schedule and the guide was stronger than I expected."
        ),
        "signature": lambda preds: any(p.get("is_revision") is True for p in preds),
        "description": "Prediction with is_revision=true + previous_target + revision_direction.",
    },
    "options_position_extraction": {
        "title": "My AAPL Options Trade",
        "transcript": (
            "I'm buying two hundred dollar calls on Apple expiring in June. "
            "Bullish setup into WWDC. I also loaded up on some TSLA puts this "
            "week — this stock is way overvalued, I expect a pullback before "
            "the next earnings print."
        ),
        "signature": lambda preds: any(
            str(p.get("derived_from") or "").lower() == "options_position" for p in preds
        ),
        "description": "ticker_call rows with derived_from=options_position.",
    },
    "earnings_call_extraction": {
        "title": "NVDA Earnings Preview",
        "transcript": (
            "NVIDIA reports next Wednesday. I think they beat consensus by a "
            "wide margin and the stock pops ten percent post earnings. I'm "
            "long into the print. AAPL reports next Thursday and I expect a "
            "miss on services growth — looking for a five percent drop."
        ),
        "signature": lambda preds: any(
            str(p.get("derived_from") or "").lower() == "earnings_call"
            or str(p.get("event_type") or "").lower() == "earnings"
            for p in preds
        ),
        "description": "ticker_call rows with event_type=earnings + derived_from=earnings_call.",
    },
    "macro_call_extraction": {
        "title": "Macro Outlook 2026",
        "transcript": (
            "The dollar is going to strengthen throughout 2026 as the Fed holds. "
            "I'm also bullish gold — gold is headed to three thousand dollars "
            "an ounce. And I think inflation is coming back, so TIPS are the trade."
        ),
        "signature": lambda preds: any(
            str(p.get("derived_from") or "").lower() == "macro_call"
            or p.get("concept") for p in preds
        ),
        "description": "macro_call rows with concept field + derived_from=macro_call.",
    },
    "pair_call_extraction": {
        "title": "Pair Trade Idea",
        "transcript": (
            "My highest conviction pair right now is long NVIDIA, short Intel. "
            "NVDA keeps taking share from INTC in data center and the margin "
            "gap is going to widen through twenty twenty six. Putting on the "
            "spread with a six month horizon."
        ),
        "signature": lambda preds: any(
            str(p.get("derived_from") or "").lower() == "pair_call"
            or p.get("_kind") == "pair_call"
            or (p.get("pair_long_ticker") and p.get("pair_short_ticker"))
            for p in preds
        ),
        "description": "pair_call rows with pair_long_ticker + pair_short_ticker.",
    },
    "binary_event_extraction": {
        "title": "Fed and FDA Outlook",
        "transcript": (
            "The Fed is going to cut rates by fifty basis points at the March "
            "FOMC meeting. And I think the FDA will approve the Eli Lilly "
            "obesity drug by the end of Q3."
        ),
        "signature": lambda preds: any(
            str(p.get("derived_from") or "").lower() == "binary_event_call"
            or (p.get("expected_outcome_text") and p.get("event_deadline"))
            for p in preds
        ),
        "description": "binary_event_call rows with event_type + expected_outcome_text + event_deadline.",
    },
    "metric_forecast_extraction": {
        "title": "Earnings Numbers and CPI",
        "transcript": (
            "NVIDIA is going to report five dollars and twenty cents EPS next "
            "Wednesday. And CPI is going to print three point two percent next "
            "month — core CPI comes in at three point one."
        ),
        "signature": lambda preds: any(
            str(p.get("derived_from") or "").lower() == "metric_forecast_call"
            or p.get("metric_type")
            for p in preds
        ),
        "description": "metric_forecast_call rows with metric_type + metric_target + metric_release_date.",
    },
    "conditional_call_extraction": {
        "title": "IF/THEN Setups — conditional trades",
        "transcript": (
            "Here is a key conditional setup. If NVDA holds the one hundred "
            "and eighty dollar level on a daily close, the stock runs to two "
            "hundred and twenty dollars by summer 2026. That is my conditional "
            "long trade. Separately, if AAPL breaks below one hundred and "
            "seventy on a daily close, I expect it to drop to one hundred and "
            "fifty dollars over the next three months. IF trigger THEN outcome "
            "is the framework here."
        ),
        "signature": lambda preds: any(
            str(p.get("derived_from") or "").lower() == "conditional_call"
            or p.get("trigger_condition")
            or p.get("trigger_type")
            for p in preds
        ),
        "description": "conditional_call rows with trigger_condition + trigger_type + trigger_* columns.",
    },
    "disclosure_extraction": {
        "title": "Portfolio Update",
        "transcript": (
            "Quick portfolio update. We continue to hold our long term position "
            "in Arista Networks, ticker ANET. We trimmed our META position at "
            "five hundred and twenty dollars last week after the big run. And "
            "we added to TSLA this week, starter position."
        ),
        "signature": lambda preds: any(
            str(p.get("derived_from") or "").lower() == "disclosure"
            or p.get("action") in {"hold", "add", "trim", "exit", "buy", "starter"}
            for p in preds
        ),
        "description": "disclosures table rows (routed via derived_from=disclosure + action).",
    },
    "regime_call_extraction": {
        "title": "Market Regime Outlook",
        "transcript": (
            "We are still in a bull market. I do not see a market top until "
            "late 2026 at the earliest. The broader trend for SPY and for "
            "small caps is higher through the rest of this year."
        ),
        "signature": lambda preds: any(
            str(p.get("derived_from") or "").lower() == "regime_call"
            or p.get("regime_type")
            for p in preds
        ),
        "description": "regime_call rows with regime_type + regime_instrument.",
    },
}


# ─── Runner ─────────────────────────────────────────────────────────────────

def _flag_state(db, config_key: str) -> bool:
    try:
        row = db.execute(
            sql_text("SELECT value FROM config WHERE key=:k"), {"k": config_key}
        ).fetchone()
        if not row:
            return False
        return str(row[0]).strip().lower() == "true"
    except Exception:
        return False


_FLAG_TO_CONFIG = {
    "ranked_list_extraction": "ENABLE_RANKED_LIST_EXTRACTION",
    "target_revisions": "ENABLE_TARGET_REVISIONS",
    "options_position_extraction": "ENABLE_OPTIONS_POSITION_EXTRACTION",
    "earnings_call_extraction": "ENABLE_EARNINGS_CALL_EXTRACTION",
    "macro_call_extraction": "ENABLE_MACRO_CALL_EXTRACTION",
    "pair_call_extraction": "ENABLE_PAIR_CALL_EXTRACTION",
    "binary_event_extraction": "ENABLE_BINARY_EVENT_EXTRACTION",
    "metric_forecast_extraction": "ENABLE_METRIC_FORECAST_EXTRACTION",
    "conditional_call_extraction": "ENABLE_CONDITIONAL_CALL_EXTRACTION",
    "disclosure_extraction": "ENABLE_DISCLOSURE_EXTRACTION",
    "regime_call_extraction": "ENABLE_REGIME_CALL_EXTRACTION",
}


def run_flag(flag_name: str) -> dict:
    fixture = FIXTURES[flag_name]
    config_key = _FLAG_TO_CONFIG[flag_name]

    db = _Session()
    try:
        flag_on = _flag_state(db, config_key)
        if not flag_on:
            print(
                f"  [WARN] {config_key} is OFF in prod — extraction block will "
                f"not be appended and this test will FAIL by design."
            )
        t0 = time.time()
        preds, telem = classify_video(
            channel_name="SmokeTest",
            title=fixture["title"],
            publish_date="2026-04-12",
            transcript=fixture["transcript"],
            video_id=f"smoke-{flag_name[:16]}",
            db=db,
        )
        elapsed_ms = int((time.time() - t0) * 1000)
    finally:
        db.close()

    sig_ok = bool(fixture["signature"](preds))
    error = telem.get("error")

    return {
        "flag": flag_name,
        "config_key": config_key,
        "flag_on_in_prod": flag_on,
        "verdict": "PASS" if (sig_ok and not error) else "FAIL",
        "elapsed_ms": elapsed_ms,
        "n_preds_raw": telem.get("predictions_raw", 0),
        "n_preds_validated": len(preds),
        "input_tokens": telem.get("input_tokens", 0),
        "output_tokens": telem.get("output_tokens", 0),
        "error": error,
        "preds": preds,
        "description": fixture["description"],
    }


def _summary_line(r: dict) -> str:
    v = r["verdict"]
    icon = "PASS" if v == "PASS" else "FAIL"
    err = f" error={r['error']}" if r.get("error") else ""
    return (
        f"  [{icon}] {r['flag']:32s} preds={r['n_preds_validated']:2d} "
        f"in={r['input_tokens']:6d} out={r['output_tokens']:4d} "
        f"{r['elapsed_ms']:5d}ms{err}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--flag", help="Run a single flag by name")
    ap.add_argument("--all", action="store_true", help="Run all 11 flags")
    ap.add_argument(
        "--json-out",
        help="Write full per-flag results (including predictions) to this path",
    )
    args = ap.parse_args()

    if not (args.all or args.flag):
        ap.error("one of --all or --flag is required")
    if args.flag and args.flag not in FIXTURES:
        ap.error(
            f"unknown flag: {args.flag}. known: {', '.join(FIXTURES.keys())}"
        )

    flags = list(FIXTURES) if args.all else [args.flag]
    results = []

    for idx, flag in enumerate(flags, 1):
        print(f"\n=== [{idx}/{len(flags)}] {flag} ===", flush=True)
        try:
            r = run_flag(flag)
        except Exception as e:
            r = {
                "flag": flag,
                "config_key": _FLAG_TO_CONFIG.get(flag, "?"),
                "flag_on_in_prod": None,
                "verdict": "FAIL",
                "elapsed_ms": 0,
                "n_preds_raw": 0,
                "n_preds_validated": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "error": f"harness_exception: {type(e).__name__}: {e}",
                "preds": [],
                "description": FIXTURES.get(flag, {}).get("description", ""),
            }
        results.append(r)
        # Trim preds for console output but keep count
        brief = {k: v for k, v in r.items() if k != "preds"}
        brief["first_pred"] = r["preds"][0] if r["preds"] else None
        print(json.dumps(brief, indent=2, default=str), flush=True)

    print("\n" + "=" * 70)
    passes = sum(1 for r in results if r["verdict"] == "PASS")
    fails = [r for r in results if r["verdict"] == "FAIL"]
    print(f"SUMMARY: {passes}/{len(results)} PASS")
    print("-" * 70)
    for r in results:
        print(_summary_line(r))
    if fails:
        print("\nFAIL LIST:")
        for r in fails:
            print(f"  - {r['flag']}: {r['error'] or 'signature not present'}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(results, indent=2, default=str))
        print(f"\nFull JSON results written to {args.json_out}")

    return 0 if passes == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

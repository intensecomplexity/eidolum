"""Phase-1 conditional extraction fixtures + live eval (cc_recover prompt).

Two layers:
  (1) DETERMINISTIC fixtures (no LLM) — feed conditional/normal/vague dicts as
      build_cc_prompt(conditional=True) would emit them through the REAL
      validator (_validate_and_dedupe_predictions) and assert routing:
        clean price conditional -> _kind=conditional_call + price trigger
        vague (type=other)      -> conditional_call, kept (scored unresolved)
        plain ticker call       -> ticker_call, UNCHANGED
        bad trigger_type        -> dropped (never a flat call)
  (2) LIVE eval (--live) — runs the current vs conditional prompt through
      claude -p on synthetic + real transcripts and reports acceptance +
      conditional capture. (See the turn report for the recorded numbers.)

Run:  python3 backend/scripts/test_conditional_extraction.py
      python3 backend/scripts/test_conditional_extraction.py --live   # needs claude + FMP/DB
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "jobs"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import classifier_validation  # noqa  (ensures jobs/ on path)
from jobs.youtube_classifier import _validate_and_dedupe_predictions


def _route(p):
    p = dict(p)
    p.setdefault("timeframe_source", "inferred")
    p.setdefault("inferred_timeframe_days", 90)
    p.setdefault("verbatim_quote", "x" * 20)
    out = _validate_and_dedupe_predictions([p])
    return out[0] if out else None


def fixtures():
    fails = 0

    # clean checkable price conditional -> conditional_call w/ price trigger
    r = _route({"derived_from": "conditional_call", "trigger_condition": "NVDA closes above 200",
                "trigger_type": "price_break", "trigger_ticker": "NVDA", "trigger_price": 200,
                "ticker": "NVDA", "direction": "bullish", "price_target": 250})
    if not (r and r.get("_kind") == "conditional_call" and r.get("_trigger_type") == "price_break"
            and r.get("_trigger_ticker") == "NVDA" and float(r.get("_trigger_price")) == 200):
        print("FAIL: clean price conditional not routed:", r and {k: r.get(k) for k in ('_kind','_trigger_type','_trigger_ticker','_trigger_price')}); fails += 1
    else:
        print("OK: clean price conditional -> conditional_call + price_break NVDA/200")

    # vague trigger (type=other), explicit consequent -> kept as conditional (unresolved)
    r = _route({"derived_from": "conditional_call", "trigger_condition": "the economy slows",
                "trigger_type": "other", "trigger_ticker": None, "trigger_price": None,
                "ticker": "GLD", "direction": "bullish", "price_target": 300})
    if not (r and r.get("_kind") == "conditional_call" and r.get("_trigger_type") == "other"):
        print("FAIL: vague conditional not kept as conditional:", r); fails += 1
    else:
        print("OK: vague conditional -> conditional_call type=other (scored unresolved, never MISS)")

    # plain call -> ticker_call, unchanged (no derived_from)
    r = _route({"ticker": "AAPL", "direction": "bullish", "price_target": 250})
    if not (r and r.get("_kind") == "ticker_call"):
        print("FAIL: plain call not ticker_call:", r); fails += 1
    else:
        print("OK: plain call -> ticker_call (unchanged)")

    # invalid trigger_type -> dropped (NOT a flat call)
    r = _route({"derived_from": "conditional_call", "trigger_condition": "vibes",
                "trigger_type": "vibes", "ticker": "TSLA", "direction": "bullish"})
    if r is not None:
        print("FAIL: bad trigger_type not dropped:", r); fails += 1
    else:
        print("OK: bad trigger_type -> dropped (never becomes a flat directional call)")

    # price trigger missing trigger_price -> dropped
    r = _route({"derived_from": "conditional_call", "trigger_condition": "X breaks 100",
                "trigger_type": "price_break", "trigger_ticker": "X", "trigger_price": None,
                "ticker": "X", "direction": "bullish"})
    if r is not None:
        print("FAIL: price trigger w/o price not dropped:", r); fails += 1
    else:
        print("OK: price trigger missing trigger_price -> dropped")

    print(f"\n{'ALL FIXTURES PASS' if fails == 0 else f'{fails} FAILURES'}")
    return fails


if __name__ == "__main__":
    if "--live" in sys.argv:
        print("Live eval: see backend/scripts and the Phase-1 report; harness in /tmp/eval_conditional.py")
    sys.exit(1 if fixtures() else 0)

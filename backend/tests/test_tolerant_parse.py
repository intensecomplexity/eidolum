"""Tests for _parse_classifier_output_tolerant — salvaging prediction
objects from malformed Qwen classifier output.

Run:  python3 tests/test_tolerant_parse.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("CLASSIFIER_BASE_URL", "https://dummy.invalid")
os.environ.setdefault("CF_ACCESS_CLIENT_ID", "dummy")
os.environ.setdefault("CF_ACCESS_CLIENT_SECRET", "dummy")


def main():
    from jobs.youtube_classifier import _parse_classifier_output_tolerant as parse

    P = '{"ticker": "AAPL", "direction": "bullish", "source_verbatim_quote": "Apple up"}'
    Q = '{"ticker": "TSLA", "direction": "bearish", "source_verbatim_quote": "Tesla down"}'
    fails = []

    def check(name, raw, want_n, want_mode, want_total=None):
        preds, meta = parse(raw)
        ok = (len(preds) == want_n and meta["mode"] == want_mode
              and (want_total is None or meta.get("total") == want_total))
        tag = "OK  " if ok else "FAIL"
        print(f"  [{tag}] {name}: got {len(preds)} preds, mode={meta['mode']} "
              f"(want {want_n}, {want_mode})")
        if not ok:
            fails.append(name)

    # 1. clean valid JSON array -> 2/2, mode clean
    check("clean array", f"[{P}, {Q}]", 2, "clean")
    # 2. junk prefix -> stripped and parsed -> 2/2, recovered
    check("junk prefix", f"Here are the predictions: [{P}, {Q}]", 2, "recovered")
    # 3. one malformed object in the middle -> 2/3, recovered
    check("bad middle object",
          f'[{P}, {{"ticker": "BAD", "direction":}}, {Q}]', 2, "recovered", want_total=3)
    # 4. truncated mid-string -> 0, failed
    check("truncated mid-string", '[{"ticker": "AAPL", "context": "the', 0, "failed")
    # 5. completely empty -> 0, failed
    check("empty", "", 0, "failed")
    # 6. dry-run-style: one complete object then a truncated one (prompt
    #    text bled into the quote) -> salvage the complete one.
    check("dry-run style partial",
          f'[{P}, {{"ticker": "CRBS", "direction": "bearish", '
          f'"source_verbatim_quote": "Video title: **WARNING** The',
          1, "recovered")
    # bonus — single clean object (not array) wrapped to a list
    check("single clean dict", P, 1, "clean")

    if fails:
        print(f"FAIL: {fails}")
        return 1
    print("PASS: all 7 tolerant-parse fixtures")
    return 0


if __name__ == "__main__":
    sys.exit(main())

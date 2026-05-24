"""Unit tests for the first-distinctive-token anchor in
jobs.timestamp_matcher._match_word_level.

Run directly:
  cd backend && python3 jobs/tests/test_timestamp_anchor.py

Or with pytest:
  cd backend && python3 -m pytest jobs/tests/test_timestamp_anchor.py -q
"""
from __future__ import annotations

import os
import sys

# Allow `import jobs.timestamp_matcher` whether the test is invoked from
# /backend or /backend/jobs/tests.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from jobs.timestamp_matcher import match_quote_to_timestamp  # noqa: E402


def _build_mu_transcript() -> dict:
    """Hand-built fixture matching the BxA_Y71fDkw (Chip Stock Investor MU)
    transcript shape. The auto-ASR mis-transcribed 'Micron' as 'Microlin'
    at idx 0; the next true 'Micron' occurrence lands at ~12.7s (second
    speaker repeating the topic). The matcher's job is to anchor on the
    first distinctive quote token inside the winning window."""
    raw_words = [
        ("Microlin", 80),
        (" just", 800),
        (" had", 1040),
        (" a", 1280),
        (" banger", 1600),
        (" of", 2000),
        (" a", 2160),
        (" quarter.", 2320),
        (">> Yeah,", 2960),
        (" they", 3200),
        (" sure", 3360),
        (" did.", 3600),
        (" It", 3840),
        (" was", 4080),
        (" really", 4240),
        (" good.", 4480),
        ("Although", 5200),
        (" maybe", 6160),
        (" we", 6480),
        (" should", 6720),
        (" say", 6960),
        (" expected", 7200),
        (" to", 7600),
        (" be", 7760),
        (" really", 7920),
        (" good.", 8160),
        (" They", 8400),
        (" just", 8640),
        (" booked", 8880),
        (" up", 9200),
        (" all", 9440),
        (" their", 9680),
        (" 2026", 9920),
        (" capacity.", 10880),
        # Second speaker — auto-ASR got 'Micron' right this time.
        (">> Micron", 12719),
        (" had", 13200),
        (" record", 13440),
        (" revenue", 13680),
        (" at", 13920),
        (" 13.6", 14160),
        (" billion.", 14640),
    ]
    return {
        "words": [{"text": t, "start_ms": s} for t, s in raw_words],
        "segments": [
            {"start_ms": 80, "duration_ms": 2880, "text":
                "Microlin just had a banger of a quarter."},
            {"start_ms": 2960, "duration_ms": 2240, "text":
                ">> Yeah, they sure did. It was really good."},
            {"start_ms": 5200, "duration_ms": 2719, "text":
                "Although maybe we should say expected to"},
            {"start_ms": 7919, "duration_ms": 2961, "text":
                "be really good. They just booked up all"},
            {"start_ms": 10880, "duration_ms": 1839, "text":
                "their 2026 capacity."},
            {"start_ms": 12719, "duration_ms": 2000, "text":
                ">> Micron had record revenue at 13.6 billion."},
        ],
        "has_word_level": True,
    }


def _build_tight_transcript() -> dict:
    """Control fixture: the quote literally starts at idx 0 with the
    correct lead distinctive token. Anchor must return 0 seconds."""
    raw_words = [
        ("Apple", 0),
        (" is", 200),
        (" going", 400),
        (" up", 700),
        (" this", 900),
        (" quarter.", 1100),
        (" Tesla", 1500),
        (" is", 1800),
        (" not.", 2000),
    ]
    return {
        "words": [{"text": t, "start_ms": s} for t, s in raw_words],
        "segments": [
            {"start_ms": 0, "duration_ms": 1100, "text":
                "Apple is going up this quarter."},
            {"start_ms": 1500, "duration_ms": 500, "text":
                " Tesla is not."},
        ],
        "has_word_level": True,
    }


def test_mu_misanchor_fixed() -> None:
    """The bug: matcher returned ts=1 (window's left edge at ' just'@800ms)
    because the winning Jaccard-1.0 window stretched far enough to capture
    'micron' at idx 34 (~12.7s). With the new anchor, ts must point at the
    first distinctive quote token inside that window — namely 'micron' at
    12.7s (or 'banger' at 1.6s if 'micron' is missed)."""
    transcript = _build_mu_transcript()
    quote = ("Micron just had a banger of a quarter. Yeah, they sure did. "
             "It was really good. Although maybe we should say expected to be "
             "really good. They just booked up all their 2026 capacity.")
    seconds, method, conf = match_quote_to_timestamp(
        quote, transcript, enable_two_pass=False, video_id="BxA_Y71fDkw",
    )
    print(f"  MU case: seconds={seconds} method={method} conf={conf}")
    assert method == "word_level", f"expected word_level path, got {method}"
    # Pre-fix: returned 1. Post-fix: must point at the distinctive token's
    # natural position. The first distinctive lead from the quote in token
    # order is 'micron' (after stripping stopwords like 'just','had','a').
    # 'micron' lands at idx 34, t=12719ms → 13 seconds.
    assert seconds is not None, "matcher returned no timestamp"
    assert seconds >= 12, (
        f"expected seconds >= 12 (true position of distinctive token), "
        f"got {seconds}"
    )


def test_tight_match_no_regression() -> None:
    """A tight match where the quote literally starts at idx 0 with the
    correct distinctive lead token. New anchor must return 0 — same as
    the legacy window-edge behavior, no regression."""
    transcript = _build_tight_transcript()
    quote = "Apple is going up this quarter"
    seconds, method, conf = match_quote_to_timestamp(
        quote, transcript, enable_two_pass=False,
    )
    print(f"  Tight case: seconds={seconds} method={method} conf={conf}")
    assert method == "word_level", f"expected word_level path, got {method}"
    assert seconds == 0, f"expected 0, got {seconds}"


def main() -> int:
    failed = 0
    for fn in (test_mu_misanchor_fixed, test_tight_match_no_regression):
        try:
            print(f"\n{fn.__name__}:")
            fn()
            print(f"  PASS")
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{'OK' if failed == 0 else 'FAIL'}: {failed} failure(s)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

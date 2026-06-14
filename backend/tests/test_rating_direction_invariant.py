"""Invariant: a BULLISH or BEARISH analyst rating must NEVER be stored as
direction='neutral'. This is the regression guard for the 2026-06-14
"Maintains/Reiterates Buy -> neutral" mislabel bug (massive_benzinga).

The destination RATING determines stance, independent of the action verb:
  Buy-family   -> bullish (or None when a maintains/reiterates reaffirmation
                  with no PT change is deliberately SKIPPED — that is allowed;
                  it must NOT become neutral)
  Hold-family  -> neutral
  Sell-family  -> bearish (or None on a skipped reaffirmation)

Forward behavior (skipping no-PT reaffirmations) is intentionally preserved —
this test only forbids the neutral mislabel, not the skip.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jobs.massive_benzinga import _get_direction

BULL = ["buy", "strong buy", "outperform", "sector outperform", "market outperform",
        "overweight", "accumulate", "positive", "add", "top pick"]
BEAR = ["sell", "strong sell", "underperform", "sector underperform", "underweight",
        "reduce", "negative"]
NEUTRAL = ["hold", "neutral", "market perform", "equal weight", "sector perform",
           "peer perform", "market weight"]
VERBS = ["maintains", "reiterates", "initiates", "upgrades", "downgrades", "resumes", "assumes"]
PTS = [("100", "100"), ("110", "100"), ("90", "100"), ("", ""), ("100", "")]


def test_bullish_rating_never_neutral():
    for rating in BULL:
        for verb in VERBS:
            for pt_c, pt_p in PTS:
                d = _get_direction(verb, rating, pt_c, pt_p)
                assert d in ("bullish", None), (
                    f"BULL rating '{rating}' via '{verb}' (PT {pt_c}/{pt_p}) returned {d!r}; "
                    f"must be 'bullish' or None, NEVER 'neutral'/'bearish'")


def test_bearish_rating_never_neutral():
    for rating in BEAR:
        for verb in VERBS:
            for pt_c, pt_p in PTS:
                d = _get_direction(verb, rating, pt_c, pt_p)
                assert d in ("bearish", None), (
                    f"BEAR rating '{rating}' via '{verb}' (PT {pt_c}/{pt_p}) returned {d!r}; "
                    f"must be 'bearish' or None, NEVER 'neutral'/'bullish'")


def test_neutral_rating_is_neutral_or_skipped():
    for rating in NEUTRAL:
        for verb in VERBS:
            d = _get_direction(verb, rating, "100", "100")
            assert d in ("neutral", None), (
                f"NEUTRAL rating '{rating}' via '{verb}' returned {d!r}; must be 'neutral' or None")


def test_named_verb_rating_combos():
    # The specific cases from the audit: the rating, not the verb, sets stance.
    assert _get_direction("maintains", "buy", "110", "100") == "bullish"
    assert _get_direction("reiterates", "outperform", "200", "150") == "bullish"
    assert _get_direction("maintains", "hold", "100", "100") == "neutral"
    assert _get_direction("maintains", "sell", "40", "50") == "bearish"
    assert _get_direction("downgrades", "hold", "100", "120") == "neutral"  # downgrade-to-hold is neutral, not bearish


if __name__ == "__main__":
    test_bullish_rating_never_neutral()
    test_bearish_rating_never_neutral()
    test_neutral_rating_is_neutral_or_skipped()
    test_named_verb_rating_combos()
    print("all invariant tests passed")

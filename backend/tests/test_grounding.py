"""Unit tests for backend/classifiers/grounding.py — pure function,
no DB access, no fixtures beyond a hand-built alias_map."""
import pytest

from classifiers.grounding import (
    classify,
    GROUNDING_EXPLICIT,
    GROUNDING_IMPLICIT,
    GROUNDING_INFERRED,
    GROUNDING_NO_WINDOW,
)


# A small, hand-built alias_map that covers the patterns we care
# about: multi-word aliases, short ambiguous tickers, two candidates
# both present so first-match-by-length can win.
ALIAS_MAP = {
    "SMH":  {"semiconductors", "semis", "chip stocks", "chips"},
    "XBI":  {"biotech", "biotech stocks"},
    "NVDA": {"nvidia"},
    "BA":   {"boeing"},
    "PANW": {"palo alto", "palo alto networks"},
    "GLD":  {"gold"},
    "MO":   {"altria"},
}


def test_explicit_match():
    gt, term = classify("SMH", "SMH looks strong here", ALIAS_MAP)
    assert gt == GROUNDING_EXPLICIT
    assert term == "SMH"


def test_explicit_with_dollar_prefix_on_ticker_input():
    # Ticker input normalises away a leading "$".
    gt, term = classify("$SMH", "SMH is ripping", ALIAS_MAP)
    assert gt == GROUNDING_EXPLICIT
    assert term == "SMH"


def test_alias_match_semis():
    gt, term = classify(
        "SMH", "semiconductors are going up next quarter", ALIAS_MAP,
    )
    assert gt == GROUNDING_IMPLICIT
    assert term == "semiconductors"


def test_alias_match_biotech_stocks_multi_word():
    gt, term = classify(
        "XBI", "biotech stocks finally bottoming", ALIAS_MAP,
    )
    assert gt == GROUNDING_IMPLICIT
    # Longest-match-first: "biotech stocks" wins over "biotech".
    assert term == "biotech stocks"


def test_alias_multi_word_longest_wins_over_shorter():
    # Window contains both "palo alto" and "palo alto networks" via
    # the full phrase; the longer alias should win because it's more
    # specific.
    gt, term = classify(
        "PANW",
        "I think palo alto networks still has upside",
        ALIAS_MAP,
    )
    assert gt == GROUNDING_IMPLICIT
    assert term == "palo alto networks"


def test_inferred_when_nothing_matches():
    gt, term = classify(
        "NVDA", "the stock market is going to crash", ALIAS_MAP,
    )
    assert gt == GROUNDING_INFERRED
    assert term is None


def test_word_boundary_blocks_ba_inside_baylor():
    # Critical — "BA" must not match inside "Baylor" or "base".
    gt, term = classify(
        "BA",
        "We visited Baylor and came back to base camp.",
        ALIAS_MAP,
    )
    assert gt == GROUNDING_INFERRED
    assert term is None


def test_word_boundary_blocks_ba_inside_abandoned():
    gt, term = classify(
        "BA", "The project was abandoned yesterday.", ALIAS_MAP,
    )
    assert gt == GROUNDING_INFERRED
    assert term is None


def test_word_boundary_allows_ba_as_whole_word():
    # With a real mention, BA should match.
    gt, term = classify(
        "BA", "BA has a big backlog of 737 orders.", ALIAS_MAP,
    )
    assert gt == GROUNDING_EXPLICIT
    assert term == "BA"


def test_alias_boeing_word_boundary():
    gt, term = classify(
        "BA", "boeing is trading near the 52-week low", ALIAS_MAP,
    )
    assert gt == GROUNDING_IMPLICIT
    assert term == "boeing"


def test_empty_window_returns_no_window_text():
    gt, term = classify("NVDA", "", ALIAS_MAP)
    assert gt == GROUNDING_NO_WINDOW
    assert term is None


def test_none_window_returns_no_window_text():
    gt, term = classify("NVDA", None, ALIAS_MAP)
    assert gt == GROUNDING_NO_WINDOW
    assert term is None


def test_whitespace_only_window_returns_no_window_text():
    gt, term = classify("NVDA", "   \n\t  ", ALIAS_MAP)
    assert gt == GROUNDING_NO_WINDOW
    assert term is None


def test_case_insensitive_explicit():
    gt, term = classify("NVDA", "nvda is crushing earnings", ALIAS_MAP)
    assert gt == GROUNDING_EXPLICIT
    assert term == "NVDA"


def test_case_insensitive_alias():
    gt, term = classify("NVDA", "NVIDIA is crushing earnings", ALIAS_MAP)
    assert gt == GROUNDING_IMPLICIT
    assert term == "nvidia"


def test_mixed_explicit_beats_alias_when_both_present():
    # If the ticker symbol itself appears, the classifier should
    # return 'explicit' and never fall through to the alias path —
    # rule-2 ticker check comes before rule-3 alias check.
    gt, term = classify(
        "NVDA", "NVDA — nvidia earnings tomorrow", ALIAS_MAP,
    )
    assert gt == GROUNDING_EXPLICIT
    assert term == "NVDA"


def test_multiple_alias_candidates_first_by_length_wins():
    # Both "chips" and "chip stocks" are defined for SMH. "chip
    # stocks" is longer, so if present it should win; else "chips".
    gt, term = classify(
        "SMH", "chip stocks are expensive here", ALIAS_MAP,
    )
    assert gt == GROUNDING_IMPLICIT
    assert term == "chip stocks"

    gt, term = classify(
        "SMH", "chips are expensive here", ALIAS_MAP,
    )
    assert gt == GROUNDING_IMPLICIT
    assert term == "chips"


def test_unknown_ticker_returns_inferred_when_text_present():
    # No entry in alias_map for ZZZZ and symbol doesn't appear.
    gt, term = classify(
        "ZZZZ", "the market is choppy today", ALIAS_MAP,
    )
    assert gt == GROUNDING_INFERRED
    assert term is None


def test_empty_ticker_with_text_returns_inferred():
    gt, term = classify("", "some text here", ALIAS_MAP)
    assert gt == GROUNDING_INFERRED
    assert term is None


def test_none_ticker_with_text_returns_inferred():
    gt, term = classify(None, "some text here", ALIAS_MAP)
    assert gt == GROUNDING_INFERRED
    assert term is None


def test_alias_surrounded_by_punctuation_matches():
    # Word-boundary anchors treat punctuation as boundaries.
    gt, term = classify(
        "NVDA", "I own (nvidia) and love it.", ALIAS_MAP,
    )
    assert gt == GROUNDING_IMPLICIT
    assert term == "nvidia"


def test_two_letter_ticker_mo_inside_common_word_does_not_match():
    # "MO" must not match "mommy", "tomorrow", "motion".
    gt, term = classify(
        "MO",
        "tomorrow my mommy says we're going to the park",
        ALIAS_MAP,
    )
    assert gt == GROUNDING_INFERRED
    assert term is None


def test_two_letter_ticker_mo_as_whole_word_matches():
    gt, term = classify(
        "MO", "MO has raised its dividend for 50 years.", ALIAS_MAP,
    )
    assert gt == GROUNDING_EXPLICIT
    assert term == "MO"

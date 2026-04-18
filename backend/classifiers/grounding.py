"""Grounding classifier — tells whether a prediction's ticker was
actually mentioned in its source window (explicit), implied via an
alias the speaker used (implicit_alias), or produced by the LLM
without any in-text backing (inferred).

The classifier is a pure function — no DB access, no I/O, no mutable
module state — so it can be unit-tested exhaustively and re-used from
both the backfill job and the live-extraction pipeline.

Contract:
    classify(ticker, window_text, alias_map) -> (grounding_type, matched_term)

    grounding_type:
        'no_window_text'  — window_text is None / empty / whitespace-only
        'explicit'        — ticker symbol appears as a whole word (case
                            insensitive) in window_text
        'implicit_alias'  — some alias in alias_map[ticker] appears as a
                            whole word (case insensitive) in window_text
        'inferred'        — window_text is non-empty but neither ticker
                            nor any alias appears as a whole word

    matched_term:
        the actual substring that produced the non-'inferred',
        non-'no_window_text' classification. For 'explicit' this is
        the ticker (normalized upper-case). For 'implicit_alias' it's
        the alias string as stored in alias_map. NULL otherwise.

Rules (checked in order, first hit wins):
    1. empty/None window_text → ('no_window_text', None)
    2. explicit ticker match → ('explicit', <ticker>)
    3. implicit alias match  → ('implicit_alias', <alias>)
    4. no match              → ('inferred', None)

Word-boundary matching uses Python's `\\b` regex anchor, which splits
on `\\w` transitions. That keeps "BA" from matching inside "Bay",
"base", or "Baylor", and "MO" from matching "mommy" or "motion".
Spaces inside multi-word aliases are preserved — "gold miners" is
still matched as a single run with `\\b` anchors at each end.
"""
from __future__ import annotations

import re
from typing import Iterable, Mapping, Optional

# Valid grounding_type values (kept in sync with the DB column comment
# in 0013_grounding_type.sql).
GROUNDING_EXPLICIT = "explicit"
GROUNDING_IMPLICIT = "implicit_alias"
GROUNDING_INFERRED = "inferred"
GROUNDING_NO_WINDOW = "no_window_text"

VALID_GROUNDING_TYPES = frozenset({
    GROUNDING_EXPLICIT,
    GROUNDING_IMPLICIT,
    GROUNDING_INFERRED,
    GROUNDING_NO_WINDOW,
})


def _whole_word_search(text_lower: str, needle_lower: str) -> Optional[str]:
    """Return the exact slice of text that matched, or None. Text is
    assumed already lower-cased; needle is too. Uses `\\b` on both
    ends so "BA" doesn't match inside "Baylor" or "base"."""
    if not needle_lower:
        return None
    pattern = r"\b" + re.escape(needle_lower) + r"\b"
    m = re.search(pattern, text_lower)
    return m.group(0) if m else None


def classify(
    ticker: Optional[str],
    window_text: Optional[str],
    alias_map: Mapping[str, Iterable[str]],
) -> tuple[str, Optional[str]]:
    """See module docstring."""
    # Rule 1 — no_window_text when the window is empty / whitespace-only.
    if not window_text or not isinstance(window_text, str) \
            or not window_text.strip():
        return (GROUNDING_NO_WINDOW, None)

    # Normalise inputs. Tickers normalise to upper, window + aliases
    # lower-cased for the case-insensitive match.
    if not ticker or not isinstance(ticker, str):
        # No ticker to look up — treat as inferred (we have text but
        # nothing to anchor on).
        return (GROUNDING_INFERRED, None)
    ticker_up = ticker.strip().upper().lstrip("$")
    text_lower = window_text.lower()

    # Rule 2 — explicit ticker match (ticker symbol appears as a
    # whole word).
    if ticker_up:
        hit = _whole_word_search(text_lower, ticker_up.lower())
        if hit is not None:
            return (GROUNDING_EXPLICIT, ticker_up)

    # Rule 3 — implicit alias match. Iterate in a stable order so
    # "first match wins" is deterministic and test-friendly.
    aliases = alias_map.get(ticker_up) or alias_map.get(ticker) or ()
    # Sorted by (length desc, alias asc) so a longer, more-specific
    # alias wins over a substring alias when both appear in the text
    # (e.g. "palo alto networks" before "palo alto"). Length tiebreak
    # is alphabetical for determinism.
    ordered = sorted(aliases, key=lambda a: (-len(a or ""), a or ""))
    for alias in ordered:
        if not alias or not isinstance(alias, str):
            continue
        alias_lower = alias.strip().lower()
        if not alias_lower:
            continue
        hit = _whole_word_search(text_lower, alias_lower)
        if hit is not None:
            return (GROUNDING_IMPLICIT, alias)

    # Rule 4 — neither anchored in the text.
    return (GROUNDING_INFERRED, None)

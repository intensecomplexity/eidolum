"""
Source-timestamp matcher — resolves a verbatim quote from Haiku to the
exact second in a YouTube video where the forecaster said it.

Ship #9. Four-path hybrid:
  A. word_level  — normalized Jaccard over a sliding window of word-level
                   JSON3 ASR data. Highest precision (~word-accurate).
  B. fuzzy_match — difflib.SequenceMatcher ratio over segment-level text.
                   Works when word-level isn't available (manual captions,
                   JSON3 endpoint refused).
  C. two_pass    — a second cheap Haiku call that picks the best-matching
                   segment from a numbered candidate list. Only invoked
                   when A and B both fail AND anthropic client is available.
  D. unknown     — all three failed; caller stores source_timestamp_seconds=NULL
                   and increments the failed counter. Prediction still inserts.

Thread-safety: the Anthropic client is lazily created per-process and
cached in a module-level global. No locks needed since it's thread-safe
per the Anthropic SDK docs. Call made in Path C is bounded by max_tokens=50
so even repeated fallbacks don't blow up the token budget.

Cost ceiling: Path C fires at most once per prediction that falls through
A and B. At ~200 input tokens + 20 output tokens per call on Haiku 4.5
that's ~$0.00025 per fallback — so 10,000 fallback calls would cost $2.50.
If >5% of predictions need Path C we'll see it in the admin
timestamp-diagnostics endpoint and tune the thresholds or the prompt.
"""
from __future__ import annotations

import logging
import os
import re
from difflib import SequenceMatcher
from typing import Optional, Tuple

log = logging.getLogger(__name__)

# Thresholds for Path A and Path B. Tuned on a small sample; see the
# admin /api/admin/timestamp-diagnostics endpoint for empirical numbers
# once the flag is flipped on.
_WORD_LEVEL_THRESHOLD = 0.70   # Jaccard on normalized word tokens
_FUZZY_SEGMENT_THRESHOLD = 0.60  # SequenceMatcher ratio on segment text

# Two-pass Haiku settings. Cheap enough that we can afford to fire per
# fallback; the prompt is tiny and the response is a single integer or
# "none".
_TWO_PASS_MODEL = "claude-haiku-4-5-20251001"
_TWO_PASS_MAX_TOKENS = 50
_TWO_PASS_CANDIDATES = 5  # how many segments to present to Haiku

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")

# Lazy Anthropic client (shared per-process).
_anthropic_client = None


def _get_anthropic_client():
    """Lazy client — only constructed when Path C is actually invoked.
    Returns None when ANTHROPIC_API_KEY is missing, the SDK is not
    importable, or construction fails; Path C callers must handle None."""
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None
    try:
        import anthropic  # lazy
        _anthropic_client = anthropic.Anthropic(api_key=key)
        return _anthropic_client
    except Exception as e:
        log.warning("[TS-MATCH] anthropic client init failed: %s", e)
        return None


def _normalize_tokens(text: str) -> list[str]:
    """Normalize a string to a list of lowercase alphanumeric tokens.
    Used by both Path A (word-level) and Path B input preparation.
    Preserves token ORDER so the caller can still slide a window."""
    if not text:
        return []
    t = text.lower()
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    return [tok for tok in t.split(" ") if tok]


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _match_word_level(
    quote_tokens: list[str],
    words: list[dict],
) -> Optional[Tuple[int, float]]:
    """Slide a window the length of quote_tokens across the word-level
    ASR list, computing a Jaccard-over-ordered-tokens for each position.
    Returns (start_second, similarity) for the best match above
    _WORD_LEVEL_THRESHOLD, or None if nothing clears the bar.

    Path A.
    """
    if not quote_tokens or not words:
        return None
    qlen = len(quote_tokens)
    qset = set(quote_tokens)
    best_score = 0.0
    best_start_ms: Optional[int] = None

    # Pre-normalize every word in the transcript once.
    normed_words = []
    for w in words:
        toks = _normalize_tokens(w.get("text") or "")
        if toks:
            # A JSON3 "seg" is usually one token (e.g. "welcome", " to",
            # " the"), but may occasionally contain a contraction like
            # "don't" that normalizes to two. Preserve all tokens for
            # matching but anchor the timestamp on the seg's start_ms.
            for t in toks:
                normed_words.append((t, int(w.get("start_ms") or 0)))
    if len(normed_words) < max(qlen // 2, 3):
        return None

    # Sliding window. A narrow window width (qlen) would miss cases
    # where Haiku shortens the quote slightly or uses different word
    # boundaries ("two fifty" vs "twofifty"). Allow ±30% stretch.
    min_w = max(3, int(qlen * 0.7))
    max_w = max(qlen, int(qlen * 1.3))
    # Stride 1 is fine — qlen is small (10-30) and normed_words fits
    # in memory. For a 30-minute auto-ASR video that's ~5000 tokens,
    # so ~5000 * 20 window sizes = 100K comparisons. Well within budget.
    for start in range(len(normed_words)):
        # Try the canonical width first (most common match shape),
        # then fall back to the stretched widths if it looks close.
        for width in (qlen, min_w, max_w):
            end = start + width
            if end > len(normed_words):
                continue
            window_tokens = [t for (t, _s) in normed_words[start:end]]
            wset = set(window_tokens)
            sim = _jaccard(qset, wset)
            if sim > best_score:
                best_score = sim
                best_start_ms = normed_words[start][1]
                if sim >= 0.98:
                    break
        if best_score >= 0.98:
            break

    if best_start_ms is None or best_score < _WORD_LEVEL_THRESHOLD:
        return None
    return (int(round(best_start_ms / 1000)), float(best_score))


def _match_fuzzy_segment(
    quote: str,
    segments: list[dict],
) -> Optional[Tuple[int, float]]:
    """difflib.SequenceMatcher ratio per segment, normalized. Returns
    (start_second, ratio) for the best segment above
    _FUZZY_SEGMENT_THRESHOLD, or None.

    Path B. Works on both manual and auto captions since it only
    needs segment text.
    """
    if not quote or not segments:
        return None
    quote_n = " ".join(_normalize_tokens(quote))
    if not quote_n:
        return None
    best_ratio = 0.0
    best_ms: Optional[int] = None
    for seg in segments:
        seg_text = seg.get("text") or ""
        seg_n = " ".join(_normalize_tokens(seg_text))
        if not seg_n:
            continue
        ratio = SequenceMatcher(None, quote_n, seg_n).quick_ratio()
        if ratio < _FUZZY_SEGMENT_THRESHOLD:
            continue
        # Only compute the full ratio (slower) if quick_ratio passed.
        real = SequenceMatcher(None, quote_n, seg_n).ratio()
        if real > best_ratio:
            best_ratio = real
            best_ms = int(seg.get("start_ms") or 0)
            if real >= 0.98:
                break
    if best_ms is None or best_ratio < _FUZZY_SEGMENT_THRESHOLD:
        return None
    return (int(round(best_ms / 1000)), float(best_ratio))


def _match_two_pass(
    quote: str,
    segments: list[dict],
) -> Optional[Tuple[int, float]]:
    """Path C: pick the top-N candidate segments by any cheap similarity,
    show them to Haiku in a numbered list, and ask Haiku to pick the
    best match. Returns (start_second, confidence) or None.

    Uses a tiny second Haiku call bounded to max_tokens=50. Skipped
    silently when the client can't be constructed (missing API key,
    SDK not installed, etc).
    """
    if not quote or not segments:
        return None
    client = _get_anthropic_client()
    if client is None:
        return None

    # Rank all segments by quick SequenceMatcher and keep the top N.
    quote_n = " ".join(_normalize_tokens(quote))
    scored: list[tuple[float, dict]] = []
    for seg in segments:
        seg_n = " ".join(_normalize_tokens(seg.get("text") or ""))
        if not seg_n:
            continue
        q = SequenceMatcher(None, quote_n, seg_n).quick_ratio()
        scored.append((q, seg))
    scored.sort(key=lambda t: -t[0])
    candidates = scored[: _TWO_PASS_CANDIDATES]
    if not candidates:
        return None

    # Build the prompt. Numbered list so Haiku just emits "3" or "none".
    lines = []
    for i, (_score, seg) in enumerate(candidates, start=1):
        seg_text = (seg.get("text") or "").strip().replace("\n", " ")
        lines.append(f"{i}. {seg_text[:200]}")
    candidate_block = "\n".join(lines)

    system_prompt = (
        "You are a transcript alignment assistant. You will see a target "
        "quote and a numbered list of candidate transcript segments. "
        "Pick the segment number that BEST contains the target quote. "
        "Reply with ONLY the number (e.g. '3'). Reply with 'none' if no "
        "segment contains the target quote."
    )
    user_prompt = (
        f"Target quote: {quote.strip()[:400]}\n\n"
        f"Candidate segments:\n{candidate_block}\n\n"
        "Best match number:"
    )

    try:
        resp = client.messages.create(
            model=_TWO_PASS_MODEL,
            max_tokens=_TWO_PASS_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        content = resp.content[0].text.strip() if resp.content else ""
    except Exception as e:
        log.info("[TS-MATCH] two-pass Haiku call failed: %s", e)
        return None

    # Parse the response — expect a bare digit or "none".
    low = content.lower().strip().strip(".")
    if low == "none" or not low:
        return None
    # Extract first integer in the response.
    m = re.search(r"\d+", low)
    if not m:
        return None
    try:
        idx = int(m.group(0))
    except ValueError:
        return None
    if idx < 1 or idx > len(candidates):
        return None
    chosen = candidates[idx - 1][1]
    start_ms = int(chosen.get("start_ms") or 0)
    # Confidence: reuse the quick_ratio of the chosen candidate as a
    # floor. If the candidate was clearly the best match by that metric
    # Haiku is likely right. Clamp to [0.60, 0.95] since we never saw
    # the full segment text.
    base = float(candidates[idx - 1][0])
    confidence = max(0.60, min(0.95, base + 0.10))
    return (int(round(start_ms / 1000)), confidence)


def match_quote_to_timestamp(
    verbatim_quote: Optional[str],
    transcript_data: Optional[dict],
    *,
    enable_two_pass: bool = True,
) -> Tuple[Optional[int], str, float]:
    """Resolve a verbatim quote to (seconds, method, confidence).

    Returns:
      (seconds, 'word_level',  sim)  when Path A matches
      (seconds, 'fuzzy_match', sim)  when Path B matches
      (seconds, 'two_pass',    conf) when Path C matches
      (None,    'unknown',     0.0)  when all paths fail

    Guaranteed to NEVER raise: any internal failure falls through to
    'unknown' so the caller can still insert the prediction with
    source_timestamp_seconds=NULL.

    When `enable_two_pass=False` (used by unit tests and for situations
    where the Anthropic client would be unhappy) Path C is skipped.
    """
    try:
        if not verbatim_quote or not isinstance(verbatim_quote, str):
            return (None, "unknown", 0.0)
        if not transcript_data or not isinstance(transcript_data, dict):
            return (None, "unknown", 0.0)

        # Path A: word-level Jaccard
        if transcript_data.get("has_word_level") and transcript_data.get("words"):
            quote_tokens = _normalize_tokens(verbatim_quote)
            a_result = _match_word_level(
                quote_tokens, transcript_data["words"]
            )
            if a_result is not None:
                seconds, sim = a_result
                return (seconds, "word_level", round(sim, 3))

        segments = transcript_data.get("segments") or []

        # Path B: fuzzy SequenceMatcher on segments
        b_result = _match_fuzzy_segment(verbatim_quote, segments)
        if b_result is not None:
            seconds, ratio = b_result
            return (seconds, "fuzzy_match", round(ratio, 3))

        # Path C: two-pass Haiku
        if enable_two_pass and segments:
            c_result = _match_two_pass(verbatim_quote, segments)
            if c_result is not None:
                seconds, confidence = c_result
                return (seconds, "two_pass", round(confidence, 3))

        # Path D: give up
        return (None, "unknown", 0.0)
    except Exception as e:
        log.info("[TS-MATCH] match_quote_to_timestamp failed: %s", e)
        return (None, "unknown", 0.0)

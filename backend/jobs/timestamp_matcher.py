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

# ── Contraction expansion (used by aggressive normalization) ──────────────
#
# Applied in two groups on already-lowercased text BEFORE punctuation is
# stripped, so apostrophes are still present when we match on them.
# Biases ambiguous suffixes ('s, 'd) toward their most common financial-
# transcript meaning: "tesla's up" → "tesla is up" (not possessive),
# "we'd buy" → "we would buy" (not "we had"). Occasional false expansions
# add consistent noise to both sides (quote and transcript) so they still
# match each other.

_APOSTROPHE_SUBS: tuple[tuple[str, str], ...] = (
    (r"n['\u2019]t\b", " not"),
    (r"['\u2019]ll\b", " will"),
    (r"['\u2019]re\b", " are"),
    (r"['\u2019]ve\b", " have"),
    (r"['\u2019]m\b", " am"),
    (r"['\u2019]s\b", " is"),
    (r"['\u2019]d\b", " would"),
)

_WRITTEN_SUBS: tuple[tuple[str, str], ...] = (
    (r"\bgonna\b", "going to"),
    (r"\bwanna\b", "want to"),
    (r"\bgotta\b", "got to"),
    (r"\bkinda\b", "kind of"),
    (r"\bsorta\b", "sort of"),
    (r"\boughta\b", "ought to"),
    (r"\bhafta\b", "have to"),
    (r"\blemme\b", "let me"),
    (r"\bgimme\b", "give me"),
    (r"\bdunno\b", "do not know"),
    (r"\bya\b", "you"),
)

_APOSTROPHE_PATS = tuple((re.compile(pat), sub) for pat, sub in _APOSTROPHE_SUBS)
_WRITTEN_PATS = tuple((re.compile(pat), sub) for pat, sub in _WRITTEN_SUBS)

# ── Key-phrase anchor constants ────────────────────────────────────────────
#
# Used by Path F (_match_key_phrase_anchor) to find segments that share a
# ticker symbol + numeric anchor with the quote. The blacklist filters
# common short all-caps words that look like tickers but aren't.

_TICKER_DOLLAR_RE = re.compile(r"\$([A-Z]{1,5})\b")
_TICKER_BARE_RE = re.compile(r"\b([A-Z]{2,5})\b")
_NUMBER_RE = re.compile(r"\$?\d{2,}(?:,\d{3})*(?:\.\d+)?")

_TICKER_BLACKLIST: frozenset[str] = frozenset({
    "I", "A", "IT", "IS", "AM", "PM", "OK", "THE", "BUT", "NOT", "AND",
    "OR", "TO", "IF", "IN", "ON", "OF", "AT", "BE", "SO", "NO", "US",
    "UK", "EU", "CEO", "IPO", "CFO", "CFA", "ETF", "ETFS", "FAQ", "FED",
    "FDA", "EPS", "YOY", "QOQ", "MOM", "YTD", "QTD", "MTD", "PE", "PEG",
    "GDP", "CPI", "PPI", "ISM", "PMI", "DIY", "GM", "WTI", "RSI", "ATH",
    "ATL", "TLDR", "FYI", "AKA", "BTW", "IMO", "IMHO",
})

# Lazy Anthropic client (shared per-process).
_anthropic_client = None


def _expand_contractions(text: str) -> str:
    """Expand English contractions on already-lowercased text. Runs all
    apostrophe-form substitutions first (n't, 'll, 're, 've, 'm, 's, 'd)
    then written-form ones (gonna → going to, etc.). Returns the modified
    text — punctuation stripping happens later."""
    for pat, sub in _APOSTROPHE_PATS:
        text = pat.sub(sub, text)
    for pat, sub in _WRITTEN_PATS:
        text = pat.sub(sub, text)
    return text


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


def _normalize_tokens(text: str, *, aggressive: bool = False) -> list[str]:
    """Normalize a string to a list of lowercase alphanumeric tokens.
    Used by both Path A (word-level) and Path B input preparation.
    Preserves token ORDER so the caller can still slide a window.

    When aggressive=True, runs _expand_contractions before punctuation
    stripping so "gonna" → "going to" and "can't" → "can not" match
    the same tokens regardless of which form the transcript uses. The
    default (False) preserves the byte-for-byte behavior used by the
    existing Path A / Path B matchers."""
    if not text:
        return []
    t = text.lower()
    if aggressive:
        t = _expand_contractions(t)
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
    *,
    aggressive: bool = False,
    use_overlap_ratio: bool = False,
    threshold: float = _WORD_LEVEL_THRESHOLD,
) -> Optional[Tuple[int, float]]:
    """Slide a window the length of quote_tokens across the word-level
    ASR list, computing a similarity score for each position. Returns
    (start_second, similarity) for the best match above `threshold`,
    or None if nothing clears the bar.

    Path A (default): Jaccard similarity over non-aggressively-normalized
    tokens. Existing behavior — byte-for-byte preserved when called with
    default kwargs.

    New variants (Ship: fuzzy matcher):
      - aggressive=True → transcript words are re-normalized with
        contraction expansion, matching the same normalization applied
        to quote_tokens by the caller. Rescues "gonna" vs "going to" and
        "can't" vs "can not" mismatches.
      - use_overlap_ratio=True → similarity is |qset ∩ wset| / |qset|
        instead of Jaccard. Asymmetric: filler words in the window no
        longer drag the score down. Best for cases where the transcript
        has lots of disfluencies around the target phrase.
    """
    if not quote_tokens or not words:
        return None
    qlen = len(quote_tokens)
    qset = set(quote_tokens)
    qset_len = len(qset)
    best_score = 0.0
    best_start_ms: Optional[int] = None

    # Pre-normalize every word in the transcript once. When aggressive,
    # the caller expects contraction expansion to apply to both sides.
    normed_words = []
    for w in words:
        toks = _normalize_tokens(w.get("text") or "", aggressive=aggressive)
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
    # boundaries ("two fifty" vs "twofifty"). Allow ±30% stretch for
    # the Jaccard path. The overlap-ratio path allows wider windows
    # (up to 2x) since extra tokens don't hurt the score.
    min_w = max(3, int(qlen * 0.7))
    if use_overlap_ratio:
        widths: tuple[int, ...] = (qlen, min_w, max(qlen, int(qlen * 2)))
    else:
        widths = (qlen, min_w, max(qlen, int(qlen * 1.3)))
    # Stride 1 is fine — qlen is small (10-30) and normed_words fits
    # in memory. For a 30-minute auto-ASR video that's ~5000 tokens,
    # so ~5000 * 20 window sizes = 100K comparisons. Well within budget.
    for start in range(len(normed_words)):
        # Try the canonical width first (most common match shape),
        # then fall back to the stretched widths if it looks close.
        for width in widths:
            end = start + width
            if end > len(normed_words):
                continue
            window_tokens = [t for (t, _s) in normed_words[start:end]]
            wset = set(window_tokens)
            if use_overlap_ratio:
                # |qset ∩ wset| / |qset| — asymmetric, tolerates filler.
                sim = len(qset & wset) / qset_len if qset_len else 0.0
            else:
                sim = _jaccard(qset, wset)
            if sim > best_score:
                best_score = sim
                best_start_ms = normed_words[start][1]
                if sim >= 0.98:
                    break
        if best_score >= 0.98:
            break

    if best_start_ms is None or best_score < threshold:
        return None
    return (int(round(best_start_ms / 1000)), float(best_score))


def _match_fuzzy_segment(
    quote: str,
    segments: list[dict],
    *,
    aggressive: bool = False,
) -> Optional[Tuple[int, float]]:
    """difflib.SequenceMatcher ratio per segment, normalized. Returns
    (start_second, ratio) for the best segment above
    _FUZZY_SEGMENT_THRESHOLD, or None.

    Path B. Works on both manual and auto captions since it only
    needs segment text. When aggressive=True, contractions are
    expanded on both sides before the ratio is computed.
    """
    if not quote or not segments:
        return None
    quote_n = " ".join(_normalize_tokens(quote, aggressive=aggressive))
    if not quote_n:
        return None
    best_ratio = 0.0
    best_ms: Optional[int] = None
    for seg in segments:
        seg_text = seg.get("text") or ""
        seg_n = " ".join(_normalize_tokens(seg_text, aggressive=aggressive))
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


def _match_segment_overlap(
    quote_tokens: list[str],
    segments: list[dict],
    *,
    threshold: float = 0.50,
) -> Optional[Tuple[int, float]]:
    """Dynamic multi-segment overlap matcher. For each start segment,
    incrementally combine adjacent segments (up to a span width scaled
    to the quote length) and score each resulting union against the
    quote token set. Returns the best (start_second, ratio) above
    `threshold` or None.

    Used by Path segment_overlap when the video has no JSON3 word-level
    data. Auto-caption segments are typically 5-8 words; a long quote
    (30+ distinct tokens) needs 4-6 segments combined to reach any
    meaningful overlap. The span width `max_span` is derived from the
    quote's token count so short quotes don't bloat the search and
    long quotes still have a chance of covering their content.

    Ties are won by the shortest span starting at the earliest
    position (single segment > adjacent pair > triple, etc.), which
    keeps precision as high as possible while still rescuing long
    multi-segment spans. Caller is expected to pass aggressive-
    normalized quote_tokens.
    """
    if not quote_tokens or not segments:
        return None
    qset = set(quote_tokens)
    qlen = len(qset)
    if qlen == 0:
        return None

    # Pre-tokenize each segment once.
    seg_data: list[tuple[set[str], int]] = []
    for seg in segments:
        toks = _normalize_tokens(seg.get("text") or "", aggressive=True)
        seg_data.append((set(toks), int(seg.get("start_ms") or 0)))
    n = len(seg_data)
    if n == 0:
        return None

    # Span width: assume auto-caption segments carry ~5 tokens each on
    # average, so need ceil(qlen / 4) segments to comfortably cover a
    # quote's distinct tokens. Add a small safety margin, clamp to the
    # transcript length, and never go below 2 (we always want to try
    # at least adjacent pairs).
    max_span = max(2, min(n, (qlen // 4) + 2))

    best_ratio = 0.0
    best_ms: Optional[int] = None

    # For each start position, incrementally grow the combined token
    # set and score at every span width from 1 up to max_span. Using
    # strict > means shorter spans win ties, so we anchor on the
    # tightest possible segment when multiple widths score equally.
    for i in range(n):
        combined: set[str] = set()
        end = min(i + max_span, n)
        for j in range(i, end):
            combined = combined | seg_data[j][0]
            if not combined:
                continue
            ratio = len(qset & combined) / qlen
            if ratio > best_ratio:
                best_ratio = ratio
                best_ms = seg_data[i][1]
                # Early out: perfect overlap, no need to keep scanning.
                if best_ratio >= 0.98:
                    return (int(round(best_ms / 1000)), float(best_ratio))

    if best_ms is None or best_ratio < threshold:
        return None
    return (int(round(best_ms / 1000)), float(best_ratio))


def _match_key_phrase_anchor(
    quote: str,
    segments: list[dict],
) -> Optional[Tuple[int, float]]:
    """Path F: last-resort anchoring on ticker symbols and numeric
    phrases shared between the quote and a transcript segment. Useful
    when every fuzzy match fails because Haiku heavily paraphrased the
    quote — but the concrete anchors (ticker + price target) usually
    survive both sides.

    Extracts $-prefixed tickers, bare 2-5 letter all-caps tickers
    (minus a blacklist of common English abbreviations), and numeric
    values of at least 2 digits from the quote. Scans segments for
    ones that contain BOTH at least one ticker AND at least one
    numeric anchor from the quote (case-insensitive, comma-insensitive).
    Returns the segment with the highest anchor overlap count with
    confidence 0.55-0.80 scaled by overlap size.

    Returns None when the quote carries no anchors (common case — a
    qualitative regime call with no ticker or dollar amount) or no
    segment contains a matching pair.
    """
    if not quote or not segments:
        return None

    # Extract tickers from the quote (preserve original case for match)
    dollar_tickers = set(_TICKER_DOLLAR_RE.findall(quote))
    bare_tickers = {
        t for t in _TICKER_BARE_RE.findall(quote)
        if t not in _TICKER_BLACKLIST
    }
    tickers = dollar_tickers | bare_tickers
    if not tickers:
        return None

    # Extract numeric anchors (2+ digits, optionally with $, commas, decimal)
    number_matches = _NUMBER_RE.findall(quote)
    # Normalize: strip $, strip commas, keep as strings for substring matching
    numbers: set[str] = set()
    for n in number_matches:
        stripped = n.lstrip("$").replace(",", "")
        if stripped:
            numbers.add(stripped)
    if not numbers:
        return None

    best_score = 0
    best_ms: Optional[int] = None
    for seg in segments:
        seg_text = (seg.get("text") or "")
        if not seg_text:
            continue
        seg_upper = seg_text.upper()
        seg_digits = seg_text.replace(",", "")
        # Ticker must appear as a whole word in the segment to avoid
        # accidental substring hits (e.g. "IBM" inside "WAYBILLIBMESS").
        matched_tickers = sum(
            1 for t in tickers
            if re.search(rf"\b\$?{re.escape(t)}\b", seg_upper)
        )
        if matched_tickers == 0:
            continue
        matched_numbers = sum(1 for n in numbers if n in seg_digits)
        if matched_numbers == 0:
            continue
        score = matched_tickers + matched_numbers
        if score > best_score:
            best_score = score
            best_ms = int(seg.get("start_ms") or 0)

    if best_ms is None:
        return None
    # Confidence scales with anchor density but never exceeds 0.80.
    # A quote that shares 1 ticker + 1 number with a segment earns 0.60;
    # 2+2 earns 0.72; 3+3 earns 0.80.
    confidence = min(0.80, 0.50 + 0.05 * best_score)
    return (int(round(best_ms / 1000)), float(confidence))


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

    Tries each strategy in order; returns the first match.

    Existing paths (byte-for-byte preserved):
      (seconds, 'word_level',   sim) — Path A, Jaccard on word-level JSON3
      (seconds, 'fuzzy_match',  sim) — Path B, SequenceMatcher on segments
      (seconds, 'two_pass',    conf) — Path C, Haiku picks best candidate

    New fallback paths (Ship: fuzzy matcher):
      (seconds, 'normalized_overlap', sim)  — Path A with aggressive
          contraction expansion + overlap ratio metric (filler-tolerant)
          over the word-level ASR list
      (seconds, 'segment_overlap',    sim)  — same overlap logic but
          over paragraph-level segments converted to pseudo-words
          (used when the video has no JSON3 word-level data)
      (seconds, 'normalized_fuzzy',   sim)  — Path B with aggressive
          contraction expansion
      (seconds, 'key_phrase_anchor', conf) — Path F, anchors the quote
          to a segment by shared ticker + numeric anchor

    (None, 'unknown', 0.0) when every path fails.

    Guaranteed to NEVER raise: any internal failure falls through to
    'unknown' so the caller can still insert the prediction with
    source_timestamp_seconds=NULL (or reject it via the training
    completeness gate).

    When `enable_two_pass=False` (used by unit tests and for situations
    where the Anthropic client would be unhappy) Path C is skipped.
    """
    try:
        if not verbatim_quote or not isinstance(verbatim_quote, str):
            return (None, "unknown", 0.0)
        if not transcript_data or not isinstance(transcript_data, dict):
            return (None, "unknown", 0.0)

        has_words = bool(
            transcript_data.get("has_word_level")
            and transcript_data.get("words")
        )
        segments = transcript_data.get("segments") or []

        # ── Path A: existing word-level Jaccard (non-aggressive) ─────────
        if has_words:
            quote_tokens = _normalize_tokens(verbatim_quote)
            a_result = _match_word_level(
                quote_tokens, transcript_data["words"]
            )
            if a_result is not None:
                seconds, sim = a_result
                return (seconds, "word_level", round(sim, 3))

        # ── Path B: existing fuzzy SequenceMatcher on segments ──────────
        b_result = _match_fuzzy_segment(verbatim_quote, segments)
        if b_result is not None:
            seconds, ratio = b_result
            return (seconds, "fuzzy_match", round(ratio, 3))

        # ── NEW FALLBACK PATHS ───────────────────────────────────────────
        # Aggressive normalization of the quote (contractions expanded).
        # Computed once and reused by the remaining paths.
        quote_tokens_agg = _normalize_tokens(verbatim_quote, aggressive=True)

        # Path A-overlap (word-level): |qset ∩ wset| / |qset| with
        # aggressive norm on both sides. Rescues contraction/filler
        # mismatches that Jaccard penalized.
        if has_words:
            a2_result = _match_word_level(
                quote_tokens_agg, transcript_data["words"],
                aggressive=True, use_overlap_ratio=True,
            )
            if a2_result is not None:
                seconds, sim = a2_result
                return (seconds, "normalized_overlap", round(sim, 3))

        # Path segment_overlap: per-segment overlap ratio for videos
        # with no JSON3 word-level data. Uses _match_segment_overlap
        # which scores each segment (and adjacent pairs) directly
        # instead of sliding over a flat pseudo-word list — a flat
        # slide can tie across the right and wrong segments and pick
        # the wrong one, while per-segment scoring unambiguously
        # picks the best segment.
        if segments:
            a3_result = _match_segment_overlap(
                quote_tokens_agg, segments, threshold=0.55,
            )
            if a3_result is not None:
                seconds, sim = a3_result
                return (seconds, "segment_overlap", round(sim, 3))

        # Path B-aggressive: SequenceMatcher with contraction expansion.
        # Niche — only helps when the quote fits mostly in one segment
        # and differs only by contraction form.
        b2_result = _match_fuzzy_segment(
            verbatim_quote, segments, aggressive=True,
        )
        if b2_result is not None:
            seconds, ratio = b2_result
            return (seconds, "normalized_fuzzy", round(ratio, 3))

        # Path F: key-phrase anchor on tickers + numeric values. Last
        # stdlib-only resort before the API fallback.
        f_result = _match_key_phrase_anchor(verbatim_quote, segments)
        if f_result is not None:
            seconds, confidence = f_result
            return (seconds, "key_phrase_anchor", round(confidence, 3))

        # ── Path C: existing two-pass Haiku (API call, slow) ────────────
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

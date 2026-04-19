"""Fuzzy-match audit — Haiku "inferred" predictions vs cached transcripts.

Goal: for every Haiku-era prediction the grounding sweep left in the
`inferred` bucket (no ticker/alias found in the ±60s window), decide
whether the stored `source_verbatim_quote` actually appears in the
video transcript or was hallucinated.

Cache-only (53%) scope:
  - quotes come from predictions.source_verbatim_quote
  - transcripts come from video_transcripts (flat-text blob per video)
  - ±60s window is NOT reconstructible from the cache (segments not
    stored); we use the full cached transcript as a STRICT superset
    of any ±60s window, so any row flagged FAKE here is guaranteed
    FAKE in the stricter ±60s-window test too
  - 47% of videos aren't cached — those rows get `NEEDS_REFETCH`
    and skip the three fuzzy scores

Read-only. No DB writes. No network. No API calls. rapidfuzz if
available, stdlib difflib fallback.

Run:
    DATABASE_URL=... python3 backend/scripts/fuzzy_match_haiku_inferred.py
"""
from __future__ import annotations

import csv
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import psycopg2  # noqa: E402

try:
    from rapidfuzz import fuzz as _fuzz
    _HAS_RAPIDFUZZ = True
except ImportError:
    from difflib import SequenceMatcher as _SeqMatcher
    _HAS_RAPIDFUZZ = False


# ── Inputs / outputs ───────────────────────────────────────────────────────
CSV_IN = Path("audit/grounding_wide_window_sweep_2026-04-18.csv")
CSV_OUT = Path("audit/fuzzy_match_haiku_inferred_2026-04-19.csv")
MD_OUT = Path("audit/fuzzy_match_haiku_inferred_2026-04-19.md")

# Basic English stopwords — removed before token_overlap so "the" /
# "a" / "is" don't inflate the score when both quote and window are
# English prose.
STOPWORDS = set("""
the a an is are was were be been being have has had do does did will would
could should may might must can cannot
of in on at by for to from with as and or but not no if so than then into
that this these those it its there here their his her our your my his
i you we they he she me him us them
yes yeah oh uh um really just like so such also even very much many any
""".split())


def _normalize_tokens(s: str) -> list[str]:
    """lowercase + strip punctuation → list of word-tokens."""
    if not s:
        return []
    return re.sub(r"[^\w\s]+", " ", s.lower()).split()


def _token_overlap(quote_tokens: list[str], window_tokens: list[str]) -> float:
    """% of unique quote tokens (minus stopwords) that appear in window."""
    q = set(quote_tokens) - STOPWORDS
    w = set(window_tokens) - STOPWORDS
    if not q:
        return 0.0
    return len(q & w) / len(q)


def _sequence_ratio(quote_norm: str, window_norm: str) -> float:
    """0..1 similarity of quote against any substring of window.

    rapidfuzz.fuzz.partial_ratio is SIMD-fast and returns 0-100 —
    exactly the "find quote inside window" semantics we need. The
    difflib fallback uses find_longest_match / len(quote) as a
    reasonable proxy."""
    if not quote_norm or not window_norm:
        return 0.0
    if _HAS_RAPIDFUZZ:
        return _fuzz.partial_ratio(quote_norm, window_norm) / 100.0
    sm = _SeqMatcher(None, quote_norm, window_norm, autojunk=False)
    lm = sm.find_longest_match(0, len(quote_norm), 0, len(window_norm))
    return lm.size / max(1, len(quote_norm))


def _longest_ngram(quote_tokens: list[str], window_tokens: list[str]) -> int:
    """Longest run of consecutive tokens from quote that appears
    anywhere in window. Uses space-bounded substring search so the
    underlying check is C-level `in`."""
    if not quote_tokens or not window_tokens:
        return 0
    window_str = " " + " ".join(window_tokens) + " "
    longest = 0
    for i in range(len(quote_tokens)):
        j = i + longest + 1  # try only runs longer than the current best
        while j <= len(quote_tokens):
            needle = " " + " ".join(quote_tokens[i:j]) + " "
            if needle in window_str:
                longest = j - i
                j += 1
            else:
                break  # extension failed; longer runs from this i also fail
    return longest


def _bucket(token_ov: float, seq_ratio: float, ngram: int,
            quote_word_count: int) -> str:
    if quote_word_count < 4:
        return "TOO_SHORT"
    if token_ov >= 0.70 or seq_ratio >= 0.60 or ngram >= 5:
        return "REAL"
    if token_ov < 0.20 and seq_ratio < 0.25 and ngram < 3:
        return "FAKE"
    return "AMBIGUOUS"


def main() -> int:
    print(f"fuzzy-match-audit  library={'rapidfuzz' if _HAS_RAPIDFUZZ else 'difflib'}")

    # ── Load sweep CSV → inferred ids ─────────────────────────────
    with CSV_IN.open() as f:
        sweep_rows = list(csv.DictReader(f))
    inferred_ids = [int(r["id"]) for r in sweep_rows
                    if r["final_type"] == "inferred" and r["id"].isdigit()]
    print(f"inferred rows in sweep CSV: {len(inferred_ids):,}")

    # ── Join to DB for quote + video_id + channel + generating_model ─
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("""
        SELECT p.id,
               p.ticker,
               p.direction,
               p.source_verbatim_quote,
               substring(p.source_platform_id FROM 4 FOR 11) AS vid,
               p.generating_model,
               f.name AS channel
        FROM predictions p
        LEFT JOIN forecasters f ON f.id = p.forecaster_id
        WHERE p.id = ANY(%s)
          AND p.generating_model = 'haiku'
    """, (inferred_ids,))
    rows = cur.fetchall()
    print(f"Haiku-inferred rows: {len(rows):,}")

    # ── Pull cached transcripts ───────────────────────────────────
    need_vids = list({r[4] for r in rows if r[4]})
    cur.execute(
        "SELECT video_id, transcript_text FROM video_transcripts "
        "WHERE video_id = ANY(%s)",
        (need_vids,),
    )
    transcripts: dict[str, str] = {r[0]: (r[1] or "") for r in cur.fetchall()}
    cur.close()
    conn.close()
    print(f"cached transcripts: {len(transcripts):,} / {len(need_vids):,} "
          f"videos ({100*len(transcripts)/len(need_vids) if need_vids else 0:.1f}%)")

    # Pre-tokenize every cached transcript once (avoid re-normalising
    # inside the per-row loop).
    tx_tokens: dict[str, list[str]] = {
        vid: _normalize_tokens(t) for vid, t in transcripts.items()
    }
    tx_norm: dict[str, str] = {vid: " ".join(tx_tokens[vid]) for vid in tx_tokens}

    # ── Score every row ─────────────────────────────────────────────
    out_rows = []
    bucket_counts: Counter = Counter()
    for pid, ticker, direction, quote, vid, gm, channel in rows:
        quote_text = (quote or "").strip()
        q_tokens = _normalize_tokens(quote_text)
        q_words = len(q_tokens)
        if vid not in transcripts:
            out_rows.append({
                "id": pid, "ticker": ticker, "direction": direction or "",
                "video_id": vid or "", "channel": channel or "",
                "generating_model": gm or "",
                "quote_word_count": q_words,
                "token_overlap": "", "sequence_ratio": "", "longest_ngram": "",
                "bucket": "NEEDS_REFETCH",
                "quote_preview": quote_text[:80].replace("\n", " "),
            })
            bucket_counts["NEEDS_REFETCH"] += 1
            continue

        w_tokens = tx_tokens[vid]
        w_norm = tx_norm[vid]
        tok_ov = round(_token_overlap(q_tokens, w_tokens), 4)
        q_norm = " ".join(q_tokens)
        seq_r = round(_sequence_ratio(q_norm, w_norm), 4)
        ngram = _longest_ngram(q_tokens, w_tokens)
        b = _bucket(tok_ov, seq_r, ngram, q_words)
        out_rows.append({
            "id": pid, "ticker": ticker, "direction": direction or "",
            "video_id": vid, "channel": channel or "",
            "generating_model": gm or "",
            "quote_word_count": q_words,
            "token_overlap": tok_ov, "sequence_ratio": seq_r,
            "longest_ngram": ngram, "bucket": b,
            "quote_preview": quote_text[:80].replace("\n", " "),
        })
        bucket_counts[b] += 1

    # ── Write CSV ─────────────────────────────────────────────────
    CSV_OUT.parent.mkdir(exist_ok=True)
    fieldnames = [
        "id", "ticker", "direction", "video_id", "channel",
        "generating_model", "quote_word_count",
        "token_overlap", "sequence_ratio", "longest_ngram",
        "bucket", "quote_preview",
    ]
    with CSV_OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    print(f"csv → {CSV_OUT} ({CSV_OUT.stat().st_size:,} bytes)")

    # ── Aggregates for MD ─────────────────────────────────────────
    total = len(out_rows)
    all_buckets = ("REAL", "FAKE", "AMBIGUOUS", "TOO_SHORT", "NEEDS_REFETCH")
    bucket_tickers = {b: Counter() for b in all_buckets}
    bucket_channels = {b: Counter() for b in all_buckets}
    bucket_samples: dict[str, list[dict]] = {b: [] for b in all_buckets}
    for r in out_rows:
        b = r["bucket"]
        bucket_tickers[b][r["ticker"]] += 1
        if r["channel"]:
            bucket_channels[b][r["channel"]] += 1
        if len(bucket_samples[b]) < 10:
            bucket_samples[b].append(r)

    # ── Headline to stdout ────────────────────────────────────────
    print()
    print("=" * 68)
    print("  HEADLINE — Haiku-inferred fuzzy-match audit (53% coverage)")
    print("=" * 68)
    print(f"  Total analyzed:  {total:,}")
    for b in all_buckets:
        n = bucket_counts[b]
        pct = 100 * n / total if total else 0
        print(f"  {b:<15}  {n:>6,}  ({pct:5.1f}%)")
    print()
    print("  Top 5 channels with most FAKE predictions:")
    for ch, n in bucket_channels["FAKE"].most_common(5):
        print(f"    {ch:<40}  {n:>3}")
    print()
    print("  Top 5 tickers with most FAKE predictions:")
    for t, n in bucket_tickers["FAKE"].most_common(5):
        print(f"    {t:<8}  {n:>3}")

    # ── Write markdown ────────────────────────────────────────────
    lines = []
    lines.append("# Fuzzy-Match Audit — Haiku Inferred Predictions (2026-04-19)")
    lines.append("")
    lines.append("**Cache-only coverage (53%).** `NEEDS_REFETCH` rows flagged for a "
                 "future audit once segment-aware transcripts are stored.")
    lines.append("")
    lines.append(f"- Scoring library: `{'rapidfuzz' if _HAS_RAPIDFUZZ else 'difflib (stdlib fallback)'}`")
    lines.append(f"- Source CSV: `{CSV_IN}`")
    lines.append(f"- Window text: full cached transcript from `video_transcripts` "
                 "(strict superset of any ±60 s window — so every FAKE "
                 "here is guaranteed FAKE under the stricter windowed test)")
    lines.append(f"- Inferred rows in grounding sweep: {len(inferred_ids):,}")
    lines.append(f"- Haiku-inferred target: {total:,}")
    lines.append(f"- Cached videos: {len(transcripts):,} / {len(need_vids):,} unique videos needed")
    lines.append("")
    lines.append("## Bucket rules")
    lines.append("")
    lines.append("- `TOO_SHORT`: quote has < 4 tokens (unreliable to fuzzy-match)")
    lines.append("- `REAL`: token_overlap ≥ 70% OR sequence_ratio ≥ 0.60 OR longest_ngram ≥ 5 words")
    lines.append("- `FAKE`: token_overlap < 20% AND sequence_ratio < 0.25 AND longest_ngram < 3 words")
    lines.append("- `AMBIGUOUS`: everything else (paraphrase / partial match — flag for LLM judge later)")
    lines.append("- `NEEDS_REFETCH`: video transcript not in local cache")
    lines.append("")
    lines.append("## Bucket counts")
    lines.append("")
    lines.append("| bucket | count | % |")
    lines.append("|---|---:|---:|")
    for b in all_buckets:
        n = bucket_counts[b]
        pct = 100 * n / total if total else 0
        lines.append(f"| `{b}` | {n:,} | {pct:.1f}% |")
    lines.append(f"| **total** | **{total:,}** | 100.0% |")
    lines.append("")

    # Score distribution summary on scored rows (exclude NEEDS_REFETCH)
    scored_rows = [r for r in out_rows if r["bucket"] != "NEEDS_REFETCH"]
    if scored_rows:
        tok_vals = sorted(r["token_overlap"] for r in scored_rows)
        seq_vals = sorted(r["sequence_ratio"] for r in scored_rows)
        ng_vals = sorted(r["longest_ngram"] for r in scored_rows)
        def pct(xs, p):
            if not xs: return 0
            k = max(0, min(len(xs) - 1, int(round(p * (len(xs) - 1)))))
            return xs[k]
        lines.append("## Score distributions (scored rows only)")
        lines.append("")
        lines.append("| percentile | token_overlap | sequence_ratio | longest_ngram |")
        lines.append("|---:|---:|---:|---:|")
        for p in (0.1, 0.25, 0.5, 0.75, 0.9, 0.95):
            lines.append(f"| p{int(p*100)} | {pct(tok_vals, p):.2f} | "
                         f"{pct(seq_vals, p):.2f} | {pct(ng_vals, p)} |")
        lines.append("")

    lines.append("## Top 10 channels — FAKE")
    lines.append("")
    lines.append("| channel | count |")
    lines.append("|---|---:|")
    for ch, n in bucket_channels["FAKE"].most_common(10):
        lines.append(f"| {ch} | {n} |")
    lines.append("")
    lines.append("## Top 10 tickers — FAKE")
    lines.append("")
    lines.append("| ticker | count |")
    lines.append("|---|---:|")
    for t, n in bucket_tickers["FAKE"].most_common(10):
        lines.append(f"| `{t}` | {n} |")
    lines.append("")

    for b in ("FAKE", "AMBIGUOUS", "REAL", "TOO_SHORT", "NEEDS_REFETCH"):
        lines.append(f"## 10 samples — {b}")
        lines.append("")
        if not bucket_samples[b]:
            lines.append("_(none)_")
            lines.append("")
            continue
        lines.append("| id | ticker | channel | tok_ov | seq_r | ngram | words | quote |")
        lines.append("|---:|---|---|---:|---:|---:|---:|---|")
        for s in bucket_samples[b]:
            ch_short = (s["channel"] or "")[:20]
            qp = s["quote_preview"]
            lines.append(
                f"| {s['id']} | `{s['ticker']}` | {ch_short} | "
                f"{s['token_overlap']} | {s['sequence_ratio']} | "
                f"{s['longest_ngram']} | {s['quote_word_count']} | "
                f"{qp!r} |"
            )
        lines.append("")

    MD_OUT.write_text("\n".join(lines))
    print(f"md  → {MD_OUT} ({MD_OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

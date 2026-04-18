"""Narrow-quote hypothesis test.

Claim under test: rows with NVDA/TSLA/META/AAPL/GOOGL/MSFT that landed
in the grounding classifier's `inferred` bucket mostly contain the
company name in the ±60s transcript window around the stored
timestamp, but not in the narrow `source_verbatim_quote` the classifier
sees. If true, much of the 40.8% inferred rate is narrow-quote false
negatives, not real hallucinations.

Usage (must inherit webshare proxy env vars):
    railway run python3 backend/scripts/narrow_quote_hypothesis_test.py
"""
from __future__ import annotations

import os
import sys
import time
import random
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import psycopg2  # noqa: E402
from classifiers.grounding import (  # noqa: E402
    classify,
    GROUNDING_EXPLICIT,
    GROUNDING_IMPLICIT,
    GROUNDING_INFERRED,
    GROUNDING_NO_WINDOW,
)

TEST_TICKERS = ("NVDA", "TSLA", "META", "AAPL", "GOOGL", "MSFT")
SAMPLE_SIZE = 30
WINDOW_SEC = 60
FETCH_SLEEP = 0.4
MAX_BACKOFF = 30.0
SEED = "2026_04_18_narrow_quote_test"
REPORT_PATH = Path("audit/narrow_quote_hypothesis_test_2026-04-18.md")


def _extract_video_id(spid: str | None) -> str | None:
    if not spid or not isinstance(spid, str) or not spid.startswith("yt_"):
        return None
    cand = spid[3:3 + 11]
    return cand if len(cand) == 11 else None


def _build_company_alias_map(cur) -> dict[str, set[str]]:
    cur.execute(
        "SELECT ticker, alias FROM company_name_aliases WHERE ticker = ANY(%s)",
        (list(TEST_TICKERS),),
    )
    out: dict[str, set[str]] = {t: set() for t in TEST_TICKERS}
    for t, a in cur.fetchall():
        if t and a:
            out.setdefault(t.strip().upper(), set()).add(a.strip().lower())
    return out


def _fetch_candidates(cur) -> list:
    # psycopg2 format-substitutes '%s', so literal '%' inside the SQL
    # must be doubled to '%%'.
    cur.execute(
        r"""
        SELECT id, ticker, source_timestamp_seconds, source_platform_id,
               source_verbatim_quote
        FROM predictions
        WHERE source_platform_id LIKE E'yt\\_%%' ESCAPE E'\\'
          AND ticker = ANY(%s)
          AND source_timestamp_seconds IS NOT NULL
          AND source_verbatim_quote IS NOT NULL
        """,
        (list(TEST_TICKERS),),
    )
    return cur.fetchall()


def _fetch_transcript_with_backoff(video_id: str) -> dict:
    """fetch_transcript_with_timestamps but with exponential backoff
    on transient failures so a temporary rate-limit doesn't wipe the
    whole batch."""
    from jobs.youtube_classifier import fetch_transcript_with_timestamps
    backoff = FETCH_SLEEP
    while True:
        try:
            r = fetch_transcript_with_timestamps(video_id)
        except Exception as e:
            r = {"status": f"exception:{type(e).__name__}", "text": "",
                 "segments": []}
        status = (r or {}).get("status") or ""
        if status == "ok":
            return r
        # Retry once on rate-limit-ish errors.
        if "429" in status or "rate" in status.lower():
            if backoff > MAX_BACKOFF:
                return r
            time.sleep(backoff)
            backoff *= 2
            continue
        return r


def _window_text(segments: list, ts: int) -> str:
    """Concatenate every segment whose start_ms/1000 is in
    (ts - WINDOW_SEC, ts + WINDOW_SEC)."""
    lo_ms = (ts - WINDOW_SEC) * 1000
    hi_ms = (ts + WINDOW_SEC) * 1000
    parts = []
    for s in segments or []:
        start_ms = s.get("start_ms") if isinstance(s, dict) else None
        if start_ms is None:
            continue
        if lo_ms < start_ms < hi_ms:
            txt = s.get("text") or ""
            if txt.strip():
                parts.append(txt.strip())
    return " ".join(parts)


def main() -> int:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    alias_map = _build_company_alias_map(cur)
    print(f"[narrow-quote-test] alias_map (company-only):")
    for t in TEST_TICKERS:
        print(f"    {t}: {sorted(alias_map[t])}")

    candidates = _fetch_candidates(cur)
    print(f"[narrow-quote-test] raw candidates (all 6 tickers, has-ts+quote): {len(candidates)}")

    inferred_pop = []
    for pid, tk, ts, spid, vq in candidates:
        gt, _ = classify(tk, vq, alias_map)
        if gt == GROUNDING_INFERRED:
            inferred_pop.append((pid, tk, ts, spid, vq))
    print(f"[narrow-quote-test] inferred-bucket (company-only classifier): {len(inferred_pop)}")

    random.seed(SEED)
    sample = random.sample(inferred_pop, min(SAMPLE_SIZE, len(inferred_pop)))
    print(f"[narrow-quote-test] seed={SEED!r} sampled={len(sample)}")

    buckets = {"A": [], "B": [], "C": [], "D": []}
    for i, (pid, tk, ts, spid, vq) in enumerate(sample, 1):
        video_id = _extract_video_id(spid)
        if not video_id:
            print(f"  [{i:02d}/{len(sample)}] id={pid} ticker={tk} ts={ts} — "
                  f"bad spid {spid!r}, skipping as D")
            buckets["D"].append((pid, tk, ts, spid, vq, "bad_spid", ""))
            continue

        print(f"  [{i:02d}/{len(sample)}] id={pid} ticker={tk} ts={ts} video={video_id} …", end="", flush=True)
        r = _fetch_transcript_with_backoff(video_id)
        status = (r or {}).get("status") or ""
        segments = (r or {}).get("segments") or []
        if status != "ok" or not segments:
            print(f" status={status!r}")
            buckets["D"].append((pid, tk, ts, spid, vq, status, ""))
            time.sleep(FETCH_SLEEP)
            continue

        wide_text = _window_text(segments, int(ts or 0))
        narrow_gt, narrow_term = classify(tk, vq, alias_map)
        wide_gt, wide_term = classify(tk, wide_text, alias_map)

        narrow_hit = narrow_gt in (GROUNDING_EXPLICIT, GROUNDING_IMPLICIT)
        wide_hit = wide_gt in (GROUNDING_EXPLICIT, GROUNDING_IMPLICIT)

        if narrow_hit:
            # Self-consistency bug — our population filter said
            # narrow was inferred. Capture it for audit.
            buckets["C"].append((pid, tk, ts, spid, vq, narrow_term, wide_text))
            print(f" C narrow_hit={narrow_term!r}")
        elif wide_hit:
            buckets["A"].append((pid, tk, ts, spid, vq, wide_term, wide_text))
            print(f" A wide_hit={wide_term!r}")
        else:
            buckets["B"].append((pid, tk, ts, spid, vq, None, wide_text))
            print(f" B name-absent")

        time.sleep(FETCH_SLEEP)

    # ── Summary ─────────────────────────────────────────────────────
    total = sum(len(v) for v in buckets.values())
    a = len(buckets["A"])
    b = len(buckets["B"])
    c = len(buckets["C"])
    d = len(buckets["D"])
    print()
    print("HYPOTHESIS TEST RESULTS (N={})".format(total))
    print("-" * 30)
    print(f"A (narrow-quote false negative): {a}/{total} ({a*100//max(1,total)}%)")
    print(f"B (genuine name-absent):         {b}/{total} ({b*100//max(1,total)}%)")
    print(f"C (classifier bug):              {c}/{total}")
    print(f"D (no transcript):               {d}/{total}")
    print()
    if a > 20:
        print("CONFIRMED — narrow quote is driving the false-positive inferred rate.")
    elif b > 15:
        print("WEAK — most 'inferred' rows are genuinely name-absent.")
    else:
        print("PARTIAL — narrow quote is one factor among several.")

    # ── Bucket B detail ────────────────────────────────────────────
    if buckets["B"]:
        print()
        print("=" * 72)
        print(f" Bucket B detail ({len(buckets['B'])} rows — genuine name-absent)")
        print("=" * 72)
        for pid, tk, ts, spid, vq, _term, wide in buckets["B"]:
            print(f"\nid={pid} ticker={tk} stored_ts={ts} spid={spid}")
            print(f"  source_verbatim_quote:")
            print(f"    {vq!r}")
            print(f"  ±{WINDOW_SEC}s window:")
            print(f"    {wide or '(empty)'}")

    # ── Markdown report ───────────────────────────────────────────
    lines = []
    lines.append("# Narrow-Quote Hypothesis Test — 2026-04-18")
    lines.append("")
    lines.append(f"Claim under test: rows for {', '.join(TEST_TICKERS)} that land in the grounding classifier's `inferred` bucket mostly contain the company name in the ±{WINDOW_SEC}s transcript window around `source_timestamp_seconds`, but not in the narrow `source_verbatim_quote`. If true, the 40.8% inferred figure is inflated by narrow-quote false negatives, not real hallucinations.")
    lines.append("")
    lines.append(f"- sample size: `N={total}` (target {SAMPLE_SIZE})")
    lines.append(f"- population (inferred, company-only alias map): `{len(inferred_pop)}` rows")
    lines.append(f"- seed: `{SEED}`")
    lines.append(f"- transcript fetch: `fetch_transcript_with_timestamps` with {FETCH_SLEEP}s inter-request delay")
    lines.append(f"- window: `(stored_ts - {WINDOW_SEC}, stored_ts + {WINDOW_SEC})` seconds, strict")
    lines.append(f"- alias map (company-only): ")
    for t in TEST_TICKERS:
        lines.append(f"    - `{t}`: {{{', '.join(sorted(alias_map[t])) or '(none)'}}}")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append(f"| bucket | description | count | % |")
    lines.append(f"|---|---|---:|---:|")
    lines.append(f"| A | narrow-quote false negative (wide hit, narrow miss) | {a} | {a*100//max(1,total)}% |")
    lines.append(f"| B | genuine name-absent (wide miss, narrow miss) | {b} | {b*100//max(1,total)}% |")
    lines.append(f"| C | classifier bug (narrow hit — should be empty) | {c} | {c*100//max(1,total)}% |")
    lines.append(f"| D | no transcript | {d} | {d*100//max(1,total)}% |")
    lines.append("")
    if a > 20:
        verdict = "**CONFIRMED** — narrow quote is driving the false-positive inferred rate."
    elif b > 15:
        verdict = "**WEAK** — most `inferred` rows are genuinely name-absent."
    else:
        verdict = "**PARTIAL** — narrow quote is one factor among several."
    lines.append(f"**Verdict:** {verdict}")
    lines.append("")

    lines.append("## Bucket A detail (narrow-quote false negatives)")
    lines.append("")
    if not buckets["A"]:
        lines.append("_(none)_")
    for pid, tk, ts, spid, vq, term, wide in buckets["A"]:
        lines.append(f"### id={pid} ticker=`{tk}` stored_ts={ts} matched=`{term}`")
        lines.append(f"`spid`: `{spid}`")
        lines.append("")
        lines.append("**source_verbatim_quote (narrow):**")
        lines.append(f"> {(vq or '_(NULL)_')}")
        lines.append("")
        lines.append(f"**±{WINDOW_SEC}s window (wide):**")
        lines.append(f"> {wide or '_(empty)_'}")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## Bucket B detail (genuine name-absent rows)")
    lines.append("")
    if not buckets["B"]:
        lines.append("_(none)_")
    for pid, tk, ts, spid, vq, _term, wide in buckets["B"]:
        lines.append(f"### id={pid} ticker=`{tk}` stored_ts={ts}")
        lines.append(f"`spid`: `{spid}`")
        lines.append("")
        lines.append("**source_verbatim_quote (narrow):**")
        lines.append(f"> {(vq or '_(NULL)_')}")
        lines.append("")
        lines.append(f"**±{WINDOW_SEC}s window (wide):**")
        lines.append(f"> {wide or '_(empty)_'}")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## Bucket D detail (no transcript)")
    lines.append("")
    if not buckets["D"]:
        lines.append("_(none)_")
    for pid, tk, ts, spid, vq, status, _wide in buckets["D"]:
        lines.append(f"- id={pid} ticker=`{tk}` ts={ts} status=`{status}` spid=`{spid}`")
    lines.append("")

    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines))
    print()
    print(f"[narrow-quote-test] report → {REPORT_PATH} ({REPORT_PATH.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

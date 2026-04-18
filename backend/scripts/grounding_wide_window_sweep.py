"""Grounding wide-window sweep.

Re-classify YouTube-sourced predictions whose current grounding bucket
is 'inferred' by reading the ±N-second transcript window around
source_timestamp_seconds instead of the narrow source_verbatim_quote.
Narrow-quote hypothesis test (commit c79dbad) showed ~70% of inferred
big-tech rows are narrow-quote false negatives.

Dry-run by default — prints before/after bucket counts, dumps a CSV of
every proposed (id, old, new, matched_term), and writes nothing to the
predictions table. --apply wraps UPDATEs in 500-row COMMIT batches and
is gated by `grounding_type IS NULL` so re-runs can't double-write.

Invariants asserted at start and end:
  1. md5 of every HAIKU_SYSTEM / YOUTUBE_HAIKU_* string constant in
     backend.jobs.youtube_classifier must not change.
  2. WEBSHARE_PROXY_USERNAME must be populated. We explicitly check
     for the EBSHARE_... typo that's currently living in Railway vars
     so it can never silently cause datacenter-IP blocks.

Usage:
    # dry run (writes nothing)
    DATABASE_URL=... WEBSHARE_PROXY_USERNAME=... WEBSHARE_PROXY_PASSWORD=... \\
      python3 backend/scripts/grounding_wide_window_sweep.py

    # dry run, only the first 50 videos
    ... --video-limit 50

    # apply after approval (500-row batches, idempotent via IS NULL)
    ... --apply
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import psycopg2  # noqa: E402

from classifiers.grounding import (  # noqa: E402
    classify,
    GROUNDING_EXPLICIT,
    GROUNDING_IMPLICIT,
    GROUNDING_INFERRED,
    GROUNDING_NO_WINDOW,
)

log = logging.getLogger(__name__)
TAG = "[grounding-sweep]"

DEFAULT_WINDOW_SEC = 60
DEFAULT_FETCH_DELAY = 0.4
DEFAULT_APPLY_BATCH = 500
MAX_BACKOFF_SEC = 30.0
UNRECOVERABLE_RETRY_DAYS = 30

REPORT_DIR = Path("audit")
CSV_PATH = REPORT_DIR / "grounding_wide_window_sweep_2026-04-18.csv"
SUMMARY_PATH = REPORT_DIR / "grounding_wide_window_sweep_2026-04-18.md"


# ─── Guardrail 1: Haiku prompt integrity ───────────────────────────────────

_HAIKU_CONST_RE = re.compile(r"^(HAIKU_SYSTEM|YOUTUBE_HAIKU_[A-Z_]+)$")


def haiku_fingerprints() -> dict[str, str]:
    """md5 every HAIKU_SYSTEM / YOUTUBE_HAIKU_* string constant in
    jobs.youtube_classifier. Returns {name: md5_hex}. Excludes
    non-string constants like token-count integers so the guardrail
    is robust against benign tweaks to tokens-per-call limits."""
    import jobs.youtube_classifier as yt
    out: dict[str, str] = {}
    for name in dir(yt):
        if not _HAIKU_CONST_RE.match(name):
            continue
        val = getattr(yt, name, None)
        if not isinstance(val, str):
            continue
        out[name] = hashlib.md5(val.encode("utf-8")).hexdigest()
    return out


# ─── Guardrail 2: Webshare env ─────────────────────────────────────────────

def assert_webshare_env() -> None:
    """Verify WEBSHARE_PROXY_USERNAME is set and isn't the typo'd
    EBSHARE_... copy that's known to live in the Railway vars table."""
    u = os.environ.get("WEBSHARE_PROXY_USERNAME", "").strip()
    p = os.environ.get("WEBSHARE_PROXY_PASSWORD", "").strip()
    if not u or not p:
        bad_u = os.environ.get("EBSHARE_PROXY_USERNAME", "").strip()
        if bad_u:
            raise SystemExit(
                f"{TAG} FATAL: WEBSHARE_PROXY_USERNAME is blank but "
                "EBSHARE_PROXY_USERNAME is set (Railway typo). Fix the "
                "env var name before re-running — datacenter IPs are "
                "blocked."
            )
        raise SystemExit(
            f"{TAG} FATAL: WEBSHARE_PROXY_USERNAME / ...PASSWORD not set. "
            "Transcript fetches will be datacenter-IP-blocked."
        )


# ─── Transcript helpers ────────────────────────────────────────────────────

def _extract_video_id(spid: str | None) -> str | None:
    """yt_{11chars}_... → video_id, else None."""
    if not spid or not isinstance(spid, str) or not spid.startswith("yt_"):
        return None
    cand = spid[3:3 + 11]
    return cand if len(cand) == 11 else None


def _fetch_with_backoff(video_id: str, delay: float) -> dict:
    """fetch_transcript_with_timestamps with an exponential backoff on
    rate-limit-shaped errors. Returns the helper's dict verbatim."""
    from jobs.youtube_classifier import fetch_transcript_with_timestamps
    backoff = delay
    while True:
        try:
            r = fetch_transcript_with_timestamps(video_id)
        except Exception as e:
            r = {"status": f"exception:{type(e).__name__}",
                 "text": "", "segments": []}
        status = (r or {}).get("status") or ""
        if status == "ok":
            return r
        if "429" in status or "rate" in status.lower():
            if backoff > MAX_BACKOFF_SEC:
                return r
            time.sleep(backoff)
            backoff *= 2
            continue
        return r


def _window_text(segments: list, ts: int, window_sec: int) -> str:
    lo_ms = (ts - window_sec) * 1000
    hi_ms = (ts + window_sec) * 1000
    parts = []
    for s in segments or []:
        start_ms = s.get("start_ms") if isinstance(s, dict) else None
        if start_ms is None:
            continue
        if lo_ms < start_ms < hi_ms:
            txt = (s.get("text") or "").strip()
            if txt:
                parts.append(txt)
    return " ".join(parts)


# ─── Alias map + unrecoverable cache ──────────────────────────────────────

def build_alias_map(cur) -> dict[str, set[str]]:
    """Merge all three alias tables into one ticker → {aliases} map."""
    am: dict[str, set[str]] = {}

    cur.execute("SELECT etf_ticker, alias FROM sector_etf_aliases")
    for etf, alias in cur.fetchall():
        if etf and alias:
            am.setdefault(etf.strip().upper(), set()).add(alias.strip().lower())

    cur.execute(
        "SELECT primary_etf, secondary_etfs, aliases FROM macro_concept_aliases"
    )
    for primary, secondaries, aliases_csv in cur.fetchall():
        if not aliases_csv:
            continue
        aliases = {a.strip().lower() for a in aliases_csv.split(",") if a.strip()}
        etfs: set[str] = set()
        if primary:
            etfs.add(primary.strip().upper())
        if secondaries:
            for s in secondaries.split(","):
                if s.strip():
                    etfs.add(s.strip().upper())
        for etf in etfs:
            am.setdefault(etf, set()).update(aliases)

    cur.execute("SELECT ticker, alias FROM company_name_aliases")
    for t, a in cur.fetchall():
        if t and a:
            am.setdefault(t.strip().upper(), set()).add(a.strip().lower())
    return am


def load_unrecoverable(cur) -> set[str]:
    """Video IDs known to be unfetchable; skip them on retry for
    UNRECOVERABLE_RETRY_DAYS."""
    try:
        cur.execute(f"""
            SELECT video_id FROM youtube_backfill_unrecoverable
            WHERE last_attempted_at > NOW() - INTERVAL '{int(UNRECOVERABLE_RETRY_DAYS)} days'
        """)
        return {r[0] for r in cur.fetchall() if r[0]}
    except Exception:
        # Table doesn't exist yet — nothing to skip.
        return set()


def mark_unrecoverable(cur, conn, video_id: str, reason: str) -> None:
    try:
        cur.execute("""
            INSERT INTO youtube_backfill_unrecoverable
              (video_id, reason, last_attempted_at, attempt_count)
            VALUES (%s, %s, NOW(), 1)
            ON CONFLICT (video_id) DO UPDATE SET
              reason = EXCLUDED.reason,
              last_attempted_at = NOW(),
              attempt_count = youtube_backfill_unrecoverable.attempt_count + 1
        """, (video_id, (reason or "unknown")[:200]))
        conn.commit()
    except Exception as e:
        log.warning("%s mark_unrecoverable(%s): %s", TAG, video_id, e)
        try:
            conn.rollback()
        except Exception:
            pass


# ─── Core sweep ────────────────────────────────────────────────────────────

def run(
    *,
    window_sec: int,
    fetch_delay: float,
    video_limit: int | None,
    apply_mode: bool,
    apply_batch: int,
) -> int:
    assert_webshare_env()
    pre_fp = haiku_fingerprints()
    print(f"{TAG} haiku_fingerprints count={len(pre_fp)}")

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    try:
        alias_map = build_alias_map(cur)
        total_aliases = sum(len(v) for v in alias_map.values())
        print(f"{TAG} alias_map: {len(alias_map)} tickers, {total_aliases} entries")

        unrecoverable = load_unrecoverable(cur)
        print(f"{TAG} unrecoverable skip-list: {len(unrecoverable)} video_ids")

        # ── Pull population ────────────────────────────────────────
        # yt_ rows with a stamped timestamp and a non-null narrow quote.
        # source_verbatim_quote IS NULL rows are out-of-scope for this
        # ship (caller can run a follow-up that treats them the same way).
        cur.execute(r"""
            SELECT id, ticker, source_timestamp_seconds, source_platform_id,
                   source_verbatim_quote, grounding_type
            FROM predictions
            WHERE source_platform_id LIKE E'yt\\_%%' ESCAPE E'\\'
              AND source_timestamp_seconds IS NOT NULL
              AND source_verbatim_quote IS NOT NULL
        """)
        rows = cur.fetchall()
        print(f"{TAG} population: {len(rows):,} yt_ rows with ts+verbatim")

        # ── Narrow-classify every row (baseline) ──────────────────
        narrow = {}
        baseline = Counter()
        for pid, ticker, ts, spid, vq, cur_gt in rows:
            gt, term = classify(ticker, vq, alias_map)
            narrow[pid] = {
                "ticker": ticker, "ts": ts, "spid": spid, "vq": vq,
                "narrow_type": gt, "narrow_term": term,
                "current_grounding": cur_gt,
            }
            baseline[gt] += 1
        print(f"{TAG} narrow baseline: " + ", ".join(
            f"{k}={baseline[k]:,}" for k in (
                GROUNDING_EXPLICIT, GROUNDING_IMPLICIT,
                GROUNDING_INFERRED, GROUNDING_NO_WINDOW,
            )
        ))

        inferred_ids = [pid for pid, v in narrow.items()
                        if v["narrow_type"] == GROUNDING_INFERRED]
        print(f"{TAG} inferred to re-resolve: {len(inferred_ids):,}")

        # Group inferred rows by video_id so each transcript is fetched
        # exactly once per cycle.
        by_video: dict[str, list[int]] = defaultdict(list)
        bad_spid = []
        for pid in inferred_ids:
            vid = _extract_video_id(narrow[pid]["spid"])
            if not vid:
                bad_spid.append(pid)
                continue
            by_video[vid].append(pid)
        print(f"{TAG} unique videos to fetch: {len(by_video):,} "
              f"(bad_spid={len(bad_spid)})")

        if video_limit is not None:
            keys = sorted(by_video.keys())[:video_limit]
            by_video = {k: by_video[k] for k in keys}
            print(f"{TAG} --video-limit={video_limit} → processing {len(by_video)} videos")

        # ── Fetch transcripts + wide-window re-classify ───────────
        wide = {}  # pid → {wide_type, wide_term, wide_len, wide_status}
        stats = Counter()
        stats["videos_total"] = len(by_video)

        for i, (vid, pids) in enumerate(sorted(by_video.items()), 1):
            if vid in unrecoverable:
                stats["videos_skipped_unrecoverable"] += 1
                for pid in pids:
                    wide[pid] = {
                        "wide_type": narrow[pid]["narrow_type"],
                        "wide_term": narrow[pid]["narrow_term"],
                        "wide_len": 0,
                        "wide_status": "skipped_unrecoverable",
                    }
                continue

            if i % 50 == 0 or i == 1:
                print(f"{TAG}   [{i}/{len(by_video)}] {vid} "
                      f"(preds={len(pids)})")
            r = _fetch_with_backoff(vid, fetch_delay)
            status = (r or {}).get("status") or "unknown"
            segments = (r or {}).get("segments") or []
            if status != "ok" or not segments:
                stats["videos_transcript_failed"] += 1
                mark_unrecoverable(cur, conn, vid, status)
                for pid in pids:
                    wide[pid] = {
                        "wide_type": narrow[pid]["narrow_type"],
                        "wide_term": narrow[pid]["narrow_term"],
                        "wide_len": 0,
                        "wide_status": f"fetch:{status}",
                    }
                time.sleep(fetch_delay)
                continue

            stats["videos_fetched_ok"] += 1
            for pid in pids:
                ts = int(narrow[pid]["ts"] or 0)
                wtext = _window_text(segments, ts, window_sec)
                wt_len = len(wtext)
                if not wtext:
                    wide[pid] = {
                        "wide_type": narrow[pid]["narrow_type"],
                        "wide_term": narrow[pid]["narrow_term"],
                        "wide_len": 0,
                        "wide_status": "empty_window",
                    }
                    continue
                ticker = narrow[pid]["ticker"]
                gt, term = classify(ticker, wtext, alias_map)
                wide[pid] = {
                    "wide_type": gt, "wide_term": term,
                    "wide_len": wt_len, "wide_status": "ok",
                }
            time.sleep(fetch_delay)

        # ── Aggregate: final proposed grounding_type per row ──────
        final_type: dict[int, str] = {}
        final_term: dict[int, str | None] = {}
        changed = Counter()
        for pid, n in narrow.items():
            if n["narrow_type"] != GROUNDING_INFERRED:
                # narrow classification wins — wide-window only applied
                # to inferred rows per spec
                final_type[pid] = n["narrow_type"]
                final_term[pid] = n["narrow_term"]
                continue
            w = wide.get(pid)
            if w is None:
                final_type[pid] = n["narrow_type"]
                final_term[pid] = n["narrow_term"]
                continue
            final_type[pid] = w["wide_type"]
            final_term[pid] = w["wide_term"]
            if w["wide_type"] != GROUNDING_INFERRED:
                changed[w["wide_type"]] += 1

        after = Counter(final_type.values())

        # ── Print report ──────────────────────────────────────────
        print()
        print("=" * 72)
        print(f"  Wide-window sweep — before/after buckets")
        print("=" * 72)
        for k in (GROUNDING_EXPLICIT, GROUNDING_IMPLICIT,
                  GROUNDING_INFERRED, GROUNDING_NO_WINDOW):
            before = baseline[k]
            a = after[k]
            delta = a - before
            sign = f"{delta:+,}" if delta else "(no change)"
            print(f"  {k:<18} {before:>8,} → {a:>8,}   {sign}")
        print(f"  {'─' * 44}")
        print(f"  moved from inferred: {sum(changed.values()):,}")
        for k in (GROUNDING_EXPLICIT, GROUNDING_IMPLICIT, GROUNDING_NO_WINDOW):
            if changed[k]:
                print(f"    → {k}: {changed[k]:,}")
        print()
        print(f"  transcript fetches: ok={stats['videos_fetched_ok']:,} "
              f"failed={stats['videos_transcript_failed']:,} "
              f"unrecoverable_skipped={stats['videos_skipped_unrecoverable']:,}")

        # Top terms that fired on the wide window (that weren't hitting
        # in the narrow quote — the "aha" terms).
        wide_term_counts = Counter()
        for pid, w in wide.items():
            if w["wide_type"] in (GROUNDING_EXPLICIT, GROUNDING_IMPLICIT) \
                    and w["wide_status"] == "ok":
                wide_term_counts[w["wide_term"]] += 1
        print()
        print("  Top wide-window match terms (newly hitting):")
        for term, cnt in wide_term_counts.most_common(15):
            print(f"    {term:<30} {cnt:>5,}")

        # Top tickers moved out of inferred
        ticker_moved = Counter()
        for pid in inferred_ids:
            if final_type[pid] != GROUNDING_INFERRED:
                ticker_moved[narrow[pid]["ticker"]] += 1
        print()
        print("  Top tickers moved out of inferred:")
        for tk, cnt in ticker_moved.most_common(15):
            print(f"    {tk:<10} {cnt:>5,}")

        # Top tickers STILL inferred
        ticker_stuck = Counter()
        for pid in inferred_ids:
            if final_type[pid] == GROUNDING_INFERRED:
                ticker_stuck[narrow[pid]["ticker"]] += 1
        print()
        print("  Top tickers STILL inferred after wide-window:")
        for tk, cnt in ticker_stuck.most_common(15):
            print(f"    {tk:<10} {cnt:>5,}")

        # ── Write CSV ─────────────────────────────────────────────
        REPORT_DIR.mkdir(exist_ok=True)
        with CSV_PATH.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "id", "ticker", "stored_ts", "spid",
                "current_grounding_type",
                "narrow_type", "narrow_term",
                "final_type", "final_term",
                "wide_status", "wide_len",
                "narrow_len",
            ])
            for pid, n in narrow.items():
                ww = wide.get(pid) or {}
                w.writerow([
                    pid, n["ticker"], n["ts"], n["spid"],
                    n["current_grounding"] or "",
                    n["narrow_type"], n["narrow_term"] or "",
                    final_type[pid], final_term[pid] or "",
                    ww.get("wide_status") or "",
                    ww.get("wide_len") or 0,
                    len(n["vq"] or ""),
                ])
        print()
        print(f"  csv → {CSV_PATH} ({CSV_PATH.stat().st_size:,} bytes)")

        # ── Write markdown summary ────────────────────────────────
        mlines = []
        mlines.append("# Grounding Wide-Window Sweep — 2026-04-18")
        mlines.append("")
        mlines.append(f"- population: `{len(rows):,}` yt_ rows with ts + verbatim")
        mlines.append(f"- narrow-inferred target: `{len(inferred_ids):,}` rows")
        mlines.append(f"- unique videos: `{len(by_video):,}`")
        mlines.append(f"- window: ±`{window_sec}s` around source_timestamp_seconds")
        mlines.append(f"- fetch delay: `{fetch_delay}s` (exponential backoff on rate limits)")
        mlines.append(f"- unrecoverable skip-list: `{len(unrecoverable)}` videos "
                      f"(retry cooldown `{UNRECOVERABLE_RETRY_DAYS}d`)")
        mlines.append(f"- apply mode: `{apply_mode}` (batch `{apply_batch}`)")
        mlines.append("")
        mlines.append("## Before → after")
        mlines.append("")
        mlines.append("| bucket | before | after | delta |")
        mlines.append("|---|---:|---:|---:|")
        for k in (GROUNDING_EXPLICIT, GROUNDING_IMPLICIT,
                  GROUNDING_INFERRED, GROUNDING_NO_WINDOW):
            before = baseline[k]
            a = after[k]
            mlines.append(f"| `{k}` | {before:,} | {a:,} | {a-before:+,} |")
        mlines.append("")
        mlines.append(f"Moved from `inferred`: **{sum(changed.values()):,}** rows "
                      f"(→ `explicit` {changed[GROUNDING_EXPLICIT]:,}, "
                      f"→ `implicit_alias` {changed[GROUNDING_IMPLICIT]:,}, "
                      f"→ `no_window_text` {changed[GROUNDING_NO_WINDOW]:,})")
        mlines.append("")
        mlines.append(f"Transcript fetches: `ok={stats['videos_fetched_ok']:,}`, "
                      f"`failed={stats['videos_transcript_failed']:,}`, "
                      f"`unrecoverable_skipped={stats['videos_skipped_unrecoverable']:,}`.")
        mlines.append("")
        mlines.append("## Top wide-window match terms (newly hitting)")
        mlines.append("")
        mlines.append("| term | count |")
        mlines.append("|---|---:|")
        for term, cnt in wide_term_counts.most_common(30):
            mlines.append(f"| `{term}` | {cnt:,} |")
        mlines.append("")
        mlines.append("## Tickers moved out of inferred")
        mlines.append("")
        mlines.append("| ticker | count |")
        mlines.append("|---|---:|")
        for tk, cnt in ticker_moved.most_common(30):
            mlines.append(f"| `{tk}` | {cnt:,} |")
        mlines.append("")
        mlines.append("## Tickers still inferred after wide-window")
        mlines.append("")
        mlines.append("| ticker | count |")
        mlines.append("|---|---:|")
        for tk, cnt in ticker_stuck.most_common(30):
            mlines.append(f"| `{tk}` | {cnt:,} |")
        mlines.append("")
        mlines.append(f"CSV of every row's proposed classification: `{CSV_PATH}`")
        mlines.append("")
        SUMMARY_PATH.write_text("\n".join(mlines))
        print(f"  markdown → {SUMMARY_PATH} ({SUMMARY_PATH.stat().st_size:,} bytes)")

        # ── Apply mode ────────────────────────────────────────────
        if apply_mode:
            print()
            print(f"{TAG} --apply ON — writing grounding_type / _matched_term")
            print(f"{TAG} guard: UPDATE ... WHERE grounding_type IS NULL "
                  f"(idempotent resume)")
            batch: list[tuple[int, str, str | None]] = []
            total_updated = 0
            for pid in sorted(narrow.keys()):
                batch.append((pid, final_type[pid], final_term[pid]))
                if len(batch) >= apply_batch:
                    total_updated += _apply_batch(cur, conn, batch)
                    batch = []
            if batch:
                total_updated += _apply_batch(cur, conn, batch)
            print(f"{TAG} apply complete — {total_updated:,} rows written")
        else:
            print()
            print(f"{TAG} dry-run — no DB writes. Re-run with --apply after review.")

        # ── Verify Haiku md5 guard ────────────────────────────────
        post_fp = haiku_fingerprints()
        if pre_fp != post_fp:
            diff = {k: (pre_fp.get(k), post_fp.get(k))
                    for k in set(pre_fp) | set(post_fp)
                    if pre_fp.get(k) != post_fp.get(k)}
            raise SystemExit(
                f"{TAG} FATAL: Haiku prompt constants changed during "
                f"the run: {diff}"
            )
        print(f"{TAG} Haiku prompt md5 guard OK ({len(post_fp)} constants unchanged)")
        return 0
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


def _apply_batch(cur, conn, batch: list[tuple[int, str, str | None]]) -> int:
    """Write one batch, single transaction. Returns rowcount of the
    applied updates. Each row is its own statement because
    grounding_type varies per row; grouping by value would add
    complexity without meaningful speedup at these volumes."""
    applied = 0
    try:
        for pid, gt, term in batch:
            cur.execute("""
                UPDATE predictions
                SET grounding_type = %s,
                    grounding_matched_term = %s
                WHERE id = %s
                  AND grounding_type IS NULL
            """, (gt, (term or None), int(pid)))
            applied += cur.rowcount or 0
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.warning("%s batch failed (%d rows): %s", TAG, len(batch), e)
    return applied


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--window-sec", type=int, default=DEFAULT_WINDOW_SEC)
    parser.add_argument("--delay", type=float, default=DEFAULT_FETCH_DELAY,
                        help="seconds between transcript fetches")
    parser.add_argument("--video-limit", type=int, default=None,
                        help="process only the first N videos (debug)")
    parser.add_argument("--apply", action="store_true",
                        help="write grounding_type to predictions (default: dry-run)")
    parser.add_argument("--apply-batch", type=int, default=DEFAULT_APPLY_BATCH)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if not args.verbose else logging.DEBUG,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return run(
        window_sec=args.window_sec,
        fetch_delay=args.delay,
        video_limit=args.video_limit,
        apply_mode=args.apply,
        apply_batch=args.apply_batch,
    )


if __name__ == "__main__":
    sys.exit(main())

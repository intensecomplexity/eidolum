"""Recall fixture for the Haiku pre-filter in cc_recover_classifier_errors.py.

Samples videos with KNOWN ground truth from the recovery checkpoint:
  - positives: result.status == ok_inserted   (Sonnet found >=1 prediction)
  - negatives: result.status == ok_no_predictions
fetches their persisted transcripts, runs the ACTUAL prefilter prompt+runner
(imported from the worker — no copy drift), and reports:
  - recall      = of true-prediction videos, fraction Haiku passes to Sonnet
                  (MUST be >= ~0.95 to ship — a false 'no' drops predictions)
  - skip rate   = of empty videos, fraction Haiku screens out (the savings)

Usage:
  DATABASE_PUBLIC_URL=... python3 haiku_prefilter_eval.py [n_per_class=40]
"""
from __future__ import annotations

import json
import os
import sys

import psycopg2

sys.argv = [sys.argv[0]]  # keep the worker's argv-parsing import-safe
import cc_recover_classifier_errors as ccr  # noqa: E402

CKPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "_artifacts", "_recovery_checkpoint.json")
BATCH_CHARS = 90_000


def sample_ids(n: int) -> tuple[list, list]:
    d = json.load(open(CKPT))
    done = [v for v in d["videos"] if v["status"] == "done" and v.get("result")]
    done.sort(key=lambda v: v.get("attempted_at") or "", reverse=True)
    pos = [v["video_id"] for v in done
           if v["result"].get("status") == "ok_inserted"][: n * 2]
    neg = [v["video_id"] for v in done
           if v["result"].get("status") == "ok_no_predictions"][: n * 2]
    return pos, neg


def fetch_transcripts(ids: list, n: int, cur) -> dict:
    cur.execute(
        """SELECT video_id, transcript_text FROM video_transcripts
           WHERE video_id = ANY(%s) AND length(transcript_text) > 200""",
        (ids,),
    )
    by_id = dict(cur.fetchall())
    return {vid: by_id[vid] for vid in ids if vid in by_id}  # keep recency order


def screen(transcripts: dict) -> dict:
    """Char-budget batches through the real prefilter, fail_open=False."""
    verdicts: dict = {}
    batch: dict = {}
    chars = 0

    def flush():
        nonlocal batch, chars
        if not batch:
            return
        out = ccr.run_cc_prefilter(batch, fail_open=False)
        if out is None:
            print(f"  RETRY: prefilter call failed for batch of {len(batch)}")
            out = ccr.run_cc_prefilter(batch, fail_open=False)
            if out is None:
                raise SystemExit("prefilter failed twice — fix before trusting eval")
        verdicts.update(out)
        print(f"  screened {len(verdicts)} videos...", flush=True)
        batch, chars = {}, 0

    for vid, text in transcripts.items():
        if batch and chars + len(text) > BATCH_CHARS:
            flush()
        batch[vid] = text
        chars += len(text)
    flush()
    return verdicts


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    url = os.environ.get("DATABASE_PUBLIC_URL")
    if not url:
        raise SystemExit("set DATABASE_PUBLIC_URL")
    conn = psycopg2.connect(url, connect_timeout=10)
    cur = conn.cursor()

    pos_ids, neg_ids = sample_ids(n)
    pos = dict(list(fetch_transcripts(pos_ids, n, cur).items())[:n])
    neg = dict(list(fetch_transcripts(neg_ids, n, cur).items())[:n])
    conn.close()
    print(f"sample: {len(pos)} known-prediction, {len(neg)} known-empty")

    print("screening POSITIVES (must pass to Sonnet)...")
    pv = screen(pos)
    print("screening NEGATIVES (skipping these is the savings)...")
    nv = screen(neg)

    tp = sum(1 for v in pv.values() if v)        # correctly sent to Sonnet
    fn = [vid for vid, v in pv.items() if not v]  # DROPPED real predictions
    tn = sum(1 for v in nv.values() if not v)    # correctly skipped
    fp = sum(1 for v in nv.values() if v)        # wasted Sonnet calls

    recall = tp / max(1, len(pv))
    skip_rate = tn / max(1, len(nv))
    print("\n=== RESULTS ===")
    print(f"recall (prediction videos passed to Sonnet): {tp}/{len(pv)} = {recall:.1%}")
    print(f"skip rate (empty videos screened out):       {tn}/{len(nv)} = {skip_rate:.1%}")
    print(f"false negatives (real predictions DROPPED):  {fn or 'none'}")
    print(f"false positives (wasted Sonnet calls):       {fp}/{len(nv)}")
    verdict = "SHIP" if recall >= 0.95 else "DO NOT SHIP — loosen the prompt"
    print(f"verdict: {verdict}")
    out = os.path.join(os.path.dirname(CKPT), "haiku_prefilter_eval_results.json")
    json.dump({"positives": pv, "negatives": nv, "recall": recall,
               "skip_rate": skip_rate, "false_negatives": fn}, open(out, "w"), indent=1)
    print(f"verdicts saved: {out}")


if __name__ == "__main__":
    main()

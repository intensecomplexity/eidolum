"""Population requote pass — TRANSCRIPT FETCH + PERSIST (2026-06-21).

For every distinct video in the cohort:
  - if a timed transcript is already cached at /tmp/heal/timed/<vid>.json, reuse it;
  - else live-fetch via fetch_transcript_with_timestamps (Webshare proxy) with
    backoff and write the {segments,text} cache file (status=ok only);
  - persist_transcript(db, vid, text) on every vid that has text — idempotent
    (ON CONFLICT DO NOTHING, first-capture-wins, never overwrites/deletes).

Checkpointed/resumable: a video with a cache file is skipped on re-run. Writes a
small fetch ledger to requote_pop_fetch_2026_06_21.json. Persist uses SessionLocal,
so run with DATABASE_URL pointed at the PUBLIC proxy.

Run:
  DATABASE_PUBLIC_URL=...  DATABASE_URL="$DATABASE_PUBLIC_URL" \
  WEBSHARE_PROXY_USERNAME=... WEBSHARE_PROXY_PASSWORD=... \
  python3 backend/scripts/requote_pop_fetch_2026_06_21.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

HERE = os.path.dirname(os.path.abspath(__file__))
COHORT = os.path.join(HERE, "requote_pop_cohort_2026_06_21.json")
LEDGER = os.path.join(HERE, "requote_pop_fetch_2026_06_21.json")
TIMED_DIR = "/tmp/heal/timed"
FETCH_SLEEP = 5
MAX_BACKOFF = 80


def fetch_with_backoff(video_id):
    from jobs.youtube_classifier import fetch_transcript_with_timestamps
    backoff = FETCH_SLEEP
    while True:
        try:
            r = fetch_transcript_with_timestamps(video_id)
        except Exception as e:
            r = {"status": f"exception:{type(e).__name__}", "text": "", "segments": []}
        status = (r or {}).get("status") or ""
        if status == "ok":
            return r
        if "429" in status or "rate" in status.lower():
            if backoff > MAX_BACKOFF:
                return r
            time.sleep(backoff)
            backoff *= 2
            continue
        return r


def main():
    os.makedirs(TIMED_DIR, exist_ok=True)
    cohort = json.load(open(COHORT))["rows"]
    vids = sorted({r["vid"] for r in cohort if r["vid"]})
    print(f"distinct cohort videos: {len(vids)}")

    from database import SessionLocal
    from jobs.video_transcript_store import persist_transcript

    cached = fetched = persisted = transient = terminal = 0
    ledger = {}
    db = SessionLocal()
    for i, vid in enumerate(vids, 1):
        path = f"{TIMED_DIR}/{vid}.json"
        text = None
        if os.path.exists(path):
            cached += 1
            try:
                text = (json.load(open(path)) or {}).get("text") or ""
            except Exception:
                text = ""
            ledger[vid] = "cached"
        else:
            r = fetch_with_backoff(vid)
            st = (r or {}).get("status") or "unknown"
            if st == "ok" and (r.get("segments") or r.get("text")):
                json.dump({"segments": r.get("segments") or [], "text": r.get("text") or ""},
                          open(path, "w"))
                text = r.get("text") or ""
                fetched += 1
                ledger[vid] = "fetched"
                print(f"  [{i}/{len(vids)}] fetched {vid} ({len(r.get('segments') or [])} segs)", flush=True)
            else:
                ledger[vid] = f"fail:{st}"
                if any(k in st for k in ("transcripts_disabled", "video_unavailable",
                                          "no_transcript", "empty_transcript")):
                    terminal += 1
                else:
                    transient += 1
                print(f"  [{i}/{len(vids)}] FAIL {vid}: {st}", flush=True)
            time.sleep(FETCH_SLEEP)
        # persist (idempotent) whenever we have text
        if text and text.strip():
            try:
                persist_transcript(db, vid, text, transcript_format="text")
                persisted += 1
            except Exception as e:
                print(f"    persist warn {vid}: {str(e)[:80]}", flush=True)
    try:
        db.close()
    except Exception:
        pass

    json.dump({"generated": "2026-06-21", "videos": len(vids), "cached": cached,
               "fetched": fetched, "persisted": persisted, "transient": transient,
               "terminal": terminal, "ledger": ledger}, open(LEDGER, "w"), indent=0)
    print(f"\nDONE  videos={len(vids)} cached={cached} fetched={fetched} "
          f"persisted={persisted} transient={transient} terminal={terminal}")


if __name__ == "__main__":
    main()

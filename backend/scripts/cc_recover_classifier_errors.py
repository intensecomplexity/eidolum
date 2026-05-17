#!/usr/bin/env python3
"""Recover YouTube videos stuck at transcript_status='classifier_error' by
re-classifying them with Claude Code's own model (headless `claude -p`).

Why this exists
---------------
~11k `youtube_videos` rows sit at transcript_status='classifier_error':
the transcript fetched fine but the Pavilion/Qwen classifier crashed or
timed out before extracting predictions. Pavilion can't catch up (model
doesn't fit on GPU). This script does what dozens of manual Cowork
windows would do — it drives `claude -p` (headless Claude Code, billed to
the CC subscription, NOT the Anthropic API) as the classifier.

Architecture
------------
This is a standalone, resumable process — NOT a Claude Code Task subagent
(a `railway run python` process cannot call the Agent tool). Each batch is
classified by shelling out to `claude -p --output-format json`, which is a
fresh-context CC invocation per batch == the "subagent" the spec wants.

Per batch (<=20 videos / <=300k transcript chars):
  1. Live re-fetch each transcript via fetch_transcript_with_timestamps
     (the production path). NOTE: video_transcripts stores plain text
     only — no per-segment timing — so a live fetch is mandatory for the
     timestamp hard gate to resolve. Stored text alone => 0 inserts.
  2. One `claude -p` call classifies every good transcript in the batch.
  3. Each video is run through the *production* `_process_one_video`
     path, with `classify_video` / `fetch_transcript*` monkeypatched to
     serve this batch's cached CC result + cached transcript. That reuses
     the real insert routing, dedup, timestamp hard gate, validation
     gate (shadow), forecaster resolution — zero reimplementation.
  4. Freshly inserted predictions get generating_model tagged.
  5. youtube_videos.transcript_status updated via _record_processed_video.

Resumability: checkpoint at _artifacts/_recovery_checkpoint.json, written
after every video's DB commit. A video is marked 'done' ONLY after its
write commits. Re-run the same command to resume after Ctrl-C / crash.

Usage:
  railway run -s <service> python backend/scripts/cc_recover_classifier_errors.py --limit 3
  railway run -s <service> python backend/scripts/cc_recover_classifier_errors.py
"""
import os
import re
import sys
import json
import time
import shutil
import signal
import subprocess
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Paths ───────────────────────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ARTIFACTS_DIR = os.path.join(_SCRIPT_DIR, "_artifacts")
CHECKPOINT = os.path.join(ARTIFACTS_DIR, "_recovery_checkpoint.json")
PROGRESS_LOG = os.path.join(ARTIFACTS_DIR, "recovery_progress.log")
IDS_FILE = os.path.join(ARTIFACTS_DIR, "2026-05-17-classifier-error-recovery-ids.txt")
CC_CWD = "/tmp/cc_recovery_cwd"  # empty dir => `claude -p` finds no repo CLAUDE.md

# ── Tuning ──────────────────────────────────────────────────────────────────
GENERATING_MODEL = "cc_sonnet_recovery_2026_05_17"  # cohort tag — DO NOT CHANGE
MAX_BATCH_VIDEOS = 10              # ~9-min `claude -p` call; 20 ran ~20min+
MAX_BATCH_CHARS = 220_000          # ~55k input tokens — safe inside Sonnet ctx
CONSECUTIVE_FAILURE_ABORT = 5      # abort after N consecutive CC-level failures
MAX_VIDEO_ATTEMPTS = 5             # give up on a video after N failed attempts
PROGRESS_EVERY = 200               # videos between progress snapshots
CLAUDE_TIMEOUT = 1800              # seconds per `claude -p` call (30min headroom)
USAGE_LIMIT_BACKOFF = 1800         # seconds to sleep when CC usage-limited
CLAUDE_MODEL = "sonnet"
TRANSCRIPT_FETCH_PACING = 2.0      # seconds between live YouTube transcript fetches
BATCH_PACING = 15.0                # seconds between batches

# Terminal transcript_status values — nothing more to do, mark the video done.
# Anything else (classifier_error, transient "error: ..." network/anti-bot
# blocks, cc_classify_missing) is RETRIABLE: leave the video pending so a
# later loop / re-run picks it up. A transient YouTube block must never be
# treated as terminal — that silently drops recoverable videos.
TERMINAL_STATUSES = {
    "ok_inserted", "ok_no_predictions", "no_transcript", "transcripts_disabled",
    "video_unavailable", "empty_transcript", "library_missing", "no_video_id",
}

# Qwen-variant -> canonical field names the validator expects. Mirrors the
# _QWEN_FIELD_MAP inside _classify_video_qwen so CC output is normalized
# identically to the production classifier path.
_FIELD_MAP = {
    "reasoning_quote": "verbatim_quote",
    "source_verbatim_quote": "verbatim_quote",
    "quote": "verbatim_quote",
    "target_price": "price_target",
    "conviction": "conviction_level",
    "timeframe": "timeframe_category",
    "timeframe_days": "inferred_timeframe_days",
}

_stop = {"flag": False}
# Per-batch caches the monkeypatched fetch/classify functions read from.
_TRANSCRIPT_CACHE: dict = {}
_PRED_CACHE: dict = {}


def _handle_sigterm(signum, frame):
    _stop["flag"] = True
    _log("[recover] stop signal received — finishing current video then exiting")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        with open(PROGRESS_LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── Checkpoint ──────────────────────────────────────────────────────────────
def load_checkpoint() -> dict | None:
    if os.path.exists(CHECKPOINT):
        try:
            with open(CHECKPOINT) as f:
                return json.load(f)
        except Exception as e:
            _log(f"[recover] checkpoint unreadable ({e}) — refusing to overwrite, abort")
            raise
    return None


def save_checkpoint(cp: dict) -> None:
    cp["updated_at"] = _now()
    tmp = CHECKPOINT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cp, f)
    os.replace(tmp, CHECKPOINT)


def init_checkpoint(db) -> dict:
    from sqlalchemy import text as sql_text
    rows = db.execute(sql_text("""
        SELECT youtube_video_id
        FROM youtube_videos
        WHERE transcript_status = 'classifier_error'
        ORDER BY publish_date DESC NULLS LAST
    """)).fetchall()
    cp = {
        "created_at": _now(),
        "updated_at": _now(),
        "total": len(rows),
        "videos": [
            {"video_id": r[0], "status": "pending", "attempts": 0,
             "attempted_at": None, "result": None}
            for r in rows
        ],
    }
    save_checkpoint(cp)
    _log(f"[recover] checkpoint initialized: {len(rows)} classifier_error videos")
    return cp


# ── CC classifier (`claude -p` headless) ────────────────────────────────────
def _claude_bin() -> str:
    return os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "claude"


def _subprocess_env() -> dict:
    """Env for `claude -p` with API-routing vars scrubbed so it bills the
    CC subscription (OAuth login) and never the Anthropic API. Rule 1."""
    env = dict(os.environ)
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
              "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
              "AWS_BEARER_TOKEN_BEDROCK"):
        env.pop(k, None)
    return env


def build_cc_prompt(transcripts: dict) -> str:
    """transcripts: {video_id: transcript_text}."""
    blocks = []
    for vid, text in transcripts.items():
        blocks.append(f'--- VIDEO {vid} ---\n{text}')
    body = "\n\n".join(blocks)
    return f"""You are classifying stock predictions from YouTube finance video transcripts. Return JSON only — no prose, no markdown fences.

For each video, extract every valid stock prediction. A valid prediction has ALL of:
- ticker: a real US-tradable symbol (e.g. AAPL, TSLA, NVDA). NOT macro words (MACRO, SPY500), NOT indices described loosely.
- direction: "bullish" or "bearish" — NEVER "neutral" (a non-directional call is not a prediction; drop it).
- forward-looking language ("I think", "will", "target", "by Q3", "headed to").
- verbatim_quote: the exact words spoken, ~30-150 chars, copied byte-for-byte from the transcript. It MUST be an exact substring of the transcript text — it is matched against transcript timing. Do not paraphrase or fix grammar.

EVERY prediction object MUST also carry these three fields (predictions missing any of them are discarded downstream):
- timeframe_days: integer 1-2000 — the horizon the call should play out over. If the speaker states one ("by Friday", "this quarter", "by year end"), convert it to days. If they give none, infer a sensible default from the call's nature (a chart/swing setup ≈ 21, an earnings call ≈ 90, a long-term thesis ≈ 365). Never 0, never null.
- timeframe_category: pick the row whose upper bound is the smallest value >= timeframe_days:
    <=7 -> "options_short" ; <=21 -> "swing_trade" ; <=30 -> "technical_chart" ;
    <=90 -> "fundamental_quarterly" ; <=180 -> "cyclical_medium" ;
    <=730 -> "macro_thesis" ; >730 -> "long_term_fundamental"
- conviction_level: one of exactly "strong" (emphatic, high-confidence), "moderate" (a normal call), "hedged" ("might", "could", "if X then"), "hypothetical" (a speculative what-if scenario), "unknown" (tone unclear).
- price_target: a number if the speaker names one, otherwise null.

REJECT (do not emit) predictions that are:
- Past-tense reporting ("revenue grew 40%", "missed estimates")
- Ad reads ("sponsored by", "use code", "brought to you by")
- Pronoun-only context ("they're going up" without naming the company)
- Wrong-ticker attribution (ticker named but context is a different company)
- Contradictory pairs (same video bullish AND bearish on the same ticker — drop both)
- Hallucinated / made-up tickers

For a video with no valid predictions, return an entry with "predictions": [].
Return an entry for EVERY video listed below, even if empty.

Output — a JSON array, exactly this shape, nothing else:
[
  {{
    "video_id": "<the id from the --- VIDEO <id> --- header>",
    "predictions": [
      {{"ticker": "AAPL", "direction": "bullish", "price_target": 250, "timeframe_days": 90, "timeframe_category": "fundamental_quarterly", "conviction_level": "moderate", "verbatim_quote": "<exact transcript words>"}}
    ]
  }}
]

VIDEOS TO CLASSIFY:

{body}
"""


def _extract_json_array(s: str):
    """Tolerant: parse a JSON array of {video_id, predictions} entries."""
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s).strip()
    try:
        v = json.loads(s)
        if isinstance(v, list):
            return v
        if isinstance(v, dict) and "predictions" in v:
            return [v]
    except Exception:
        pass
    m = re.search(r"\[.*\]", s, re.DOTALL)
    if m:
        try:
            v = json.loads(m.group(0))
            if isinstance(v, list):
                return v
        except Exception:
            pass
    return None


def run_cc_classifier(prompt: str) -> tuple[list | None, str | None]:
    """Run one `claude -p` classification. Returns (entries, error).

    On CC usage-limit, sleeps and retries indefinitely (limits reset) —
    a usage-limit pause is never reported as a failure. Returns (None, tag)
    only on a genuine error the caller should count toward the abort guard.
    """
    cmd = [
        _claude_bin(), "-p",
        "--output-format", "json",
        "--model", CLAUDE_MODEL,
        "--strict-mcp-config",        # ignore all MCP servers — faster startup
        "--no-session-persistence",   # don't litter session files
    ]
    env = _subprocess_env()
    while True:
        if _stop["flag"]:
            return None, "stopped"
        t0 = time.time()
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True,
                cwd=CC_CWD, env=env, timeout=CLAUDE_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return None, f"claude_timeout_{CLAUDE_TIMEOUT}s"
        latency = time.time() - t0
        blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
        low = blob.lower()
        if ("usage limit" in low or "rate limit" in low
                or "limit reached" in low or "limit will reset" in low):
            _log(f"[recover] CC usage limit hit — sleeping {USAGE_LIMIT_BACKOFF}s "
                 f"then retrying this batch")
            for _ in range(USAGE_LIMIT_BACKOFF // 10):
                if _stop["flag"]:
                    return None, "stopped"
                time.sleep(10)
            continue
        if proc.returncode != 0:
            return None, f"claude_exit_{proc.returncode}: {(proc.stderr or '')[:200]}"
        # Unwrap the --output-format json envelope.
        try:
            env_obj = json.loads(proc.stdout)
        except Exception as e:
            return None, f"claude_envelope_unparseable: {e}: {(proc.stdout or '')[:200]}"
        if env_obj.get("is_error"):
            return None, f"claude_is_error: {str(env_obj.get('result'))[:200]}"
        result_text = env_obj.get("result") or ""
        entries = _extract_json_array(result_text)
        if entries is None:
            return None, f"cc_output_unparseable: {result_text[:200]}"
        run_cc_classifier.last_latency = latency  # type: ignore[attr-defined]
        return entries, None


# ── Monkeypatch shims — make _process_one_video use this batch's caches ─────
def _shim_fetch_rich(video_id: str) -> dict:
    return _TRANSCRIPT_CACHE.get(video_id) or {
        "text": "", "lang": None, "status": "no_transcript",
        "segments": [], "words": None, "has_word_level": False,
        "is_generated": False, "fetched_at": datetime.utcnow(),
    }


def _shim_fetch_plain(video_id: str) -> tuple:
    d = _TRANSCRIPT_CACHE.get(video_id) or {}
    return (d.get("text") or None), (d.get("status") or "no_transcript")


def _shim_classify_video(channel_name, title, publish_date, transcript,
                         video_id=None, db=None, lang=None):
    """Drop-in for classify_video — serves this batch's cached CC result.
    Normalizes + validates exactly as _classify_video_qwen does."""
    from jobs.youtube_classifier import (
        _validate_and_dedupe_predictions, MAX_PREDICTIONS_PER_VIDEO,
    )
    telem = {
        "chunks": 0, "input_tokens": 0, "output_tokens": 0, "cache_create": 0,
        "cache_read": 0, "estimated_cost_usd": 0.0, "haiku_retries": 0,
        "predictions_raw": 0, "predictions_validated": 0, "rejections": [],
        "prompt_variant": "cc_sonnet_recovery", "last_status": None,
    }
    if video_id not in _PRED_CACHE:
        # CC never returned this video (batch failed / omitted it). Leave it
        # as classifier_error so the next loop iteration retries it. Rule 5.
        telem["error"] = "cc_classify_missing: video absent from CC batch result"
        return [], telem
    raw = _PRED_CACHE.get(video_id) or []
    norm = []
    for p in raw:
        if not isinstance(p, dict):
            continue
        for src, dst in _FIELD_MAP.items():
            if src in p and dst not in p:
                p[dst] = p[src]
        if "timeframe_source" not in p:
            p["timeframe_source"] = "inferred"
        norm.append(p)
    telem["predictions_raw"] = len(norm)
    valid = _validate_and_dedupe_predictions(norm)
    if len(valid) > MAX_PREDICTIONS_PER_VIDEO:
        valid = valid[:MAX_PREDICTIONS_PER_VIDEO]
    telem["predictions_validated"] = len(valid)
    return valid, telem


def install_monkeypatches() -> None:
    import jobs.youtube_channel_monitor as ycm
    ycm.fetch_transcript_with_timestamps = _shim_fetch_rich
    ycm.fetch_transcript = _shim_fetch_plain
    ycm.classify_video = _shim_classify_video


# ── Main ────────────────────────────────────────────────────────────────────
def main() -> int:
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    os.makedirs(CC_CWD, exist_ok=True)

    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    from sqlalchemy import create_engine, text as sql_text
    from sqlalchemy.orm import sessionmaker
    from jobs.youtube_channel_monitor import _process_one_video, _record_processed_video

    install_monkeypatches()

    # Own engine, statement_timeout disabled — the candidate scan is large.
    # RECOVERY_DATABASE_URL lets a local run point at the Railway public
    # proxy host (postgres.railway.internal isn't resolvable off-network);
    # it survives `railway run`, which would otherwise override DATABASE_URL.
    db_url = os.environ.get("RECOVERY_DATABASE_URL") or os.environ["DATABASE_URL"]
    engine = create_engine(
        db_url,
        connect_args={"options": "-c statement_timeout=0"},
        pool_pre_ping=True,
    )
    db = sessionmaker(bind=engine)()

    cp = load_checkpoint()
    if cp is None:
        cp = init_checkpoint(db)
    else:
        done = sum(1 for v in cp["videos"] if v["status"] == "done")
        _log(f"[recover] resuming: {done}/{cp['total']} done, "
             f"{cp['total'] - done} pending")

    # Video metadata + channel id map (re-queried each run, not checkpointed).
    # Keyed by the checkpoint's video_ids — NOT by transcript_status. A
    # retried video's status may have flipped to a transient "error: ..."
    # value, which would drop it from a status-filtered query and strand it.
    all_ids = [v["video_id"] for v in cp["videos"]]
    meta = {
        r[0]: {"channel_name": r[1], "title": r[2] or "",
               "description": r[3] or "", "publish": r[4]}
        for r in db.execute(sql_text(
            "SELECT youtube_video_id, channel_name, title, description, "
            "publish_date FROM youtube_videos "
            "WHERE youtube_video_id = ANY(:ids)"
        ), {"ids": all_ids}).fetchall()
    }
    chan_id = {
        r[0]: r[1] for r in db.execute(sql_text(
            "SELECT channel_name, youtube_channel_id FROM youtube_channels"
        )).fetchall()
    }

    by_id = {v["video_id"]: v for v in cp["videos"]}
    start = time.time()
    consecutive_failures = 0
    batches_run = 0
    cc_latencies: list[float] = []
    inserted_total = 0
    processed_since_log = 0
    processed_this_run = 0

    def pending_videos():
        return [v for v in cp["videos"]
                if v["status"] == "pending"
                and v["video_id"] in meta
                and v["attempts"] < MAX_VIDEO_ATTEMPTS]

    while True:
        if _stop["flag"]:
            _log("[recover] stop flag set — exiting cleanly; re-run to resume")
            break

        pend = pending_videos()
        if not pend:
            break

        # Build a batch bounded by video count (and, after fetch, by total
        # transcript chars). --limit caps the whole run to one small batch.
        if limit is not None:
            pend = pend[:limit]
        batch = pend[:MAX_BATCH_VIDEOS]
        batch_ids = [v["video_id"] for v in batch]

        # ── 1. Live re-fetch transcripts (the REAL functions) ──────────────
        from jobs.youtube_classifier import fetch_transcript_with_timestamps
        _TRANSCRIPT_CACHE.clear()
        _PRED_CACHE.clear()
        for vid in batch_ids:
            if _stop["flag"]:
                break
            try:
                _TRANSCRIPT_CACHE[vid] = fetch_transcript_with_timestamps(vid)
            except Exception as e:
                _TRANSCRIPT_CACHE[vid] = {
                    "text": "", "lang": None,
                    "status": f"error: {type(e).__name__}",
                    "segments": [], "words": None, "has_word_level": False,
                    "is_generated": False, "fetched_at": datetime.utcnow(),
                }
            # Pace the live fetches — hammering YouTube back-to-back trips
            # Google's /sorry anti-bot block even through the proxy.
            time.sleep(TRANSCRIPT_FETCH_PACING)

        # Trim the batch to a char budget — classify only good transcripts.
        good: dict = {}
        chars = 0
        for vid in batch_ids:
            d = _TRANSCRIPT_CACHE.get(vid) or {}
            if d.get("status") == "ok" and d.get("text"):
                t = d["text"]
                if good and chars + len(t) > MAX_BATCH_CHARS:
                    break  # defer the rest of this batch to the next loop
                good[vid] = t
                chars += len(t)

        # ── 2. Classify the good transcripts via `claude -p` ───────────────
        if good:
            entries, err = run_cc_classifier(build_cc_prompt(good))
            if err == "stopped":
                _log("[recover] stopped during classification — exiting cleanly")
                break
            if err:
                consecutive_failures += 1
                _log(f"[recover] CC classify failed for batch {batch_ids[0]}.. "
                     f"({consecutive_failures}/{CONSECUTIVE_FAILURE_ABORT}): {err}")
                if consecutive_failures >= CONSECUTIVE_FAILURE_ABORT:
                    _log("[recover] ABORT: 5 consecutive CC failures — investigate. "
                         "Re-run to resume once resolved.")
                    break
                continue  # leave batch pending; next iteration retries it
            consecutive_failures = 0
            batches_run += 1
            if getattr(run_cc_classifier, "last_latency", None):
                cc_latencies.append(run_cc_classifier.last_latency)
            for ent in entries or []:
                if isinstance(ent, dict) and ent.get("video_id"):
                    _PRED_CACHE[ent["video_id"]] = ent.get("predictions") or []

        # ── 3-5. Run each video through the production path ───────────────
        # Only videos whose transcript made it into `good` were classified;
        # the rest stay pending (char-budget deferral) or get a transcript
        # status (fetch failure). A video classified but absent from
        # _PRED_CACHE stays classifier_error and is retried.
        process_ids = list(good.keys()) + [
            vid for vid in batch_ids
            if (_TRANSCRIPT_CACHE.get(vid) or {}).get("status") != "ok"
        ]
        for vid in process_ids:
            if _stop["flag"]:
                break
            v = by_id[vid]
            m = meta[vid]
            publish_str = m["publish"].isoformat() if m["publish"] else ""
            v["attempts"] += 1
            v["attempted_at"] = _now()
            try:
                inserted, tchars, status = _process_one_video(
                    db, m["channel_name"], chan_id.get(m["channel_name"]),
                    vid, m["title"], publish_str, defaultdict(int),
                )
                _record_processed_video(
                    db, vid, m["channel_name"], m["title"],
                    m["description"], publish_str, status, tchars, inserted,
                )
                new_ids = []
                if inserted > 0:
                    rows = db.execute(sql_text(
                        "UPDATE predictions SET generating_model = :gm "
                        "WHERE transcript_video_id = :vid "
                        "AND generating_model IS NULL RETURNING id"
                    ), {"gm": GENERATING_MODEL, "vid": vid[:11]}).fetchall()
                    new_ids = [r[0] for r in rows]
                db.commit()
            except Exception as e:
                try:
                    db.rollback()
                except Exception:
                    pass
                _log(f"[recover] exception on video={vid}: {type(e).__name__}: {e}")
                # Leave pending unless attempts exhausted.
                if v["attempts"] >= MAX_VIDEO_ATTEMPTS:
                    v["status"] = "done"
                    v["result"] = {"inserted": 0, "error": f"exhausted: {type(e).__name__}"}
                save_checkpoint(cp)
                continue

            if new_ids:
                with open(IDS_FILE, "a") as f:
                    for pid in new_ids:
                        f.write(f"{pid}\n")

            if status in TERMINAL_STATUSES:
                v["status"] = "done"
                v["result"] = {"inserted": inserted, "status": status}
                inserted_total += inserted
                processed_since_log += 1
                processed_this_run += 1
            elif v["attempts"] >= MAX_VIDEO_ATTEMPTS:
                # Retriable (classifier_error / transient transcript block)
                # but out of attempts — mark done so the run can finish.
                v["status"] = "done"
                v["result"] = {"inserted": inserted, "status": f"{status[:60]}|exhausted"}
                processed_since_log += 1
            # else: retriable with attempts left — leave pending for next loop.
            save_checkpoint(cp)
            _log(f"[recover] video={vid} -> {status}, {inserted} preds "
                 f"(attempt {v['attempts']})")

            if processed_since_log >= PROGRESS_EVERY:
                log_progress(cp, start, batches_run, cc_latencies,
                             inserted_total, consecutive_failures)
                processed_since_log = 0

        if limit is not None:
            _log(f"[recover] --limit {limit} reached — stopping")
            break
        if not _stop["flag"]:
            time.sleep(BATCH_PACING)

    log_progress(cp, start, batches_run, cc_latencies, inserted_total,
                 consecutive_failures, final=True)
    db.close()
    return 0


def log_progress(cp, start, batches_run, cc_latencies, inserted_total,
                 consecutive_failures, final=False):
    done = [v for v in cp["videos"] if v["status"] == "done"]
    n_done = len(done)
    n_pending = cp["total"] - n_done
    inserted_rows = [v for v in done
                     if (v.get("result") or {}).get("status") == "ok_inserted"]
    no_pred = [v for v in done
               if (v.get("result") or {}).get("status") == "ok_no_predictions"]
    still_err = [v for v in done
                 if (v.get("result") or {}).get("status")
                 not in ("ok_inserted", "ok_no_predictions")]
    elapsed = time.time() - start
    avg_lat = sum(cc_latencies) / len(cc_latencies) if cc_latencies else 0.0
    rate = (n_done / elapsed) if elapsed > 0 else 0  # videos/sec this run
    eta_h = (n_pending / rate / 3600) if rate > 0 else 0
    yield_rate = (inserted_total / n_done) if n_done else 0.0

    if final:
        _log("=" * 60)
        _log(f"=== CLASSIFIER ERROR RECOVERY {'COMPLETE' if n_pending == 0 else 'PAUSED'} "
             f"@ {_now()} ===")
    else:
        _log(f"=== RECOVERY PROGRESS @ {_now()} ===")
    _log(f"  Total videos:            {cp['total']}")
    _log(f"  Done:                    {n_done} ({100*n_done/max(cp['total'],1):.1f}%)")
    _log(f"  Pending:                 {n_pending}")
    _log(f"    - ok_inserted:         {len(inserted_rows)}")
    _log(f"    - ok_no_predictions:   {len(no_pred)}")
    _log(f"    - no-data / exhausted: {len(still_err)} (no transcript, dead video, or retries spent)")
    _log(f"  Predictions inserted:    {inserted_total}")
    _log(f"  Yield (preds/done):      {yield_rate:.2f}")
    _log(f"  CC batches run:          {batches_run}")
    _log(f"  Avg CC latency:          {avg_lat:.0f}s")
    _log(f"  Consecutive failures:    {consecutive_failures}")
    _log(f"  ETA at current rate:     {eta_h:.1f}h")
    _log(f"  generating_model tag:    {GENERATING_MODEL}")
    if final:
        _log("=" * 60)


if __name__ == "__main__":
    sys.exit(main())

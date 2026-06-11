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


def _resolve_checkpoint_path() -> str:
    """--checkpoint-path <file> selects this worker's checkpoint. Default is
    the original single-worker file, so existing invocations are unchanged.
    Parallel workers each pass their own (_recovery_checkpoint_a.json, ...)."""
    if "--checkpoint-path" in sys.argv:
        return os.path.abspath(sys.argv[sys.argv.index("--checkpoint-path") + 1])
    return os.path.join(ARTIFACTS_DIR, "_recovery_checkpoint.json")


CHECKPOINT = _resolve_checkpoint_path()
# Per-worker suffix from the checkpoint filename: _recovery_checkpoint_a.json
# -> "_a"; _recovery_checkpoint.json -> "". Keeps progress/ids/run logs
# separate so parallel workers never clobber each other.
_cp_base = os.path.basename(CHECKPOINT)
_SUFFIX = ""
if _cp_base.startswith("_recovery_checkpoint") and _cp_base.endswith(".json"):
    _SUFFIX = _cp_base[len("_recovery_checkpoint"):-len(".json")]
PROGRESS_LOG = os.path.join(ARTIFACTS_DIR, f"recovery_progress{_SUFFIX}.log")
IDS_FILE = os.path.join(
    ARTIFACTS_DIR, f"2026-05-17-classifier-error-recovery-ids{_SUFFIX}.txt")
CC_CWD = f"/tmp/cc_recovery_cwd{_SUFFIX}"  # empty dir => `claude -p` finds no CLAUDE.md

# ── Tuning ──────────────────────────────────────────────────────────────────
GENERATING_MODEL = "cc_sonnet_recovery_2026_05_17"  # cohort tag — DO NOT CHANGE
MAX_BATCH_VIDEOS = 4               # smaller `claude -p` generation: a full 10-video
                                   # batch of multi-stock videos pushed claude past the
                                   # 1800s timeout (2026-06-09); 4 keeps calls well under
MAX_BATCH_CHARS = 90_000           # ~22k input tokens — bounds per-call generation len
CONSECUTIVE_FAILURE_ABORT = 5      # abort after N consecutive CC-level failures
MAX_VIDEO_ATTEMPTS = 20            # give up on a video after N failed attempts
                                   # (raised 5->20 alongside FETCH_TIMEOUT 120->30 so
                                   # per-video fetch budget stays 30*20=600s == old
                                   # 120*5: a degraded proxy can't exhaust+lose videos
                                   # any faster, but each batch churns 4x quicker)
PROGRESS_EVERY = 200               # videos between progress snapshots
CLAUDE_TIMEOUT = 1800              # seconds per `claude -p` call (30min headroom)
USAGE_LIMIT_BACKOFF = 1800         # seconds to sleep when CC usage-limited
CLAUDE_MODEL = "sonnet"
PREFILTER_MODEL = "haiku"          # cheap yes/no screen before the Sonnet call —
                                   # ~74% of videos have zero predictions; skipping
                                   # Sonnet for them is the Max-budget win
PREFILTER_ENABLED = (os.environ.get("RECOVERY_PREFILTER", "on").lower()
                     in ("on", "true", "1", "yes"))  # kill switch: RECOVERY_PREFILTER=off
TRANSCRIPT_FETCH_PACING = 4.0      # seconds between live YouTube transcript fetches —
                                   # 4s/worker keeps the aggregate ~2s across the 2
                                   # parallel workers (avoids the /sorry anti-bot block)
BATCH_PACING = 15.0                # seconds between batches
FETCH_TIMEOUT = 30                 # hard cap (s) on one live transcript fetch —
                                   # youtube_transcript_api has no socket timeout.
                                   # 30s = ~4x a healthy fetch (~7s observed); a
                                   # degraded proxy fails fast instead of burning
                                   # 120s/video. See MAX_VIDEO_ATTEMPTS (budget held).

# ── Continuous / live-queue mode ────────────────────────────────────────────
IDLE_POLL_SECONDS = 300            # when no classifier_error videos are ready,
                                   # idle this long then re-query (never exit)
EXHAUSTED_BACKOFF_HOURS = 12       # a video that hit MAX_VIDEO_ATTEMPTS is held
                                   # out of the live queue this long, then becomes
                                   # eligible again — so a permanently-failing
                                   # video can't starve the rest yet isn't
                                   # abandoned forever (in case it was transient)

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

# Connect-args shared by the initial engine and every rebuild after a
# mid-run password rotation. Kept in one place so the rebuilt engine is
# byte-for-byte identical to the original (TCP keepalives + connect_timeout
# + statement_timeout=0 across multi-minute `claude -p` idle gaps).
_ENGINE_CONNECT_ARGS = {
    "options": "-c statement_timeout=0",
    "connect_timeout": 30,
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 5,
}
# Holds the live engine so the rotation-recovery path can dispose the stale
# one. {"engine": Engine, "session": Session}.
_DB = {"engine": None, "session": None}
DB_REBUILD_MAX = 6          # max engine rebuilds for one write before giving up
DB_REBUILD_BACKOFF = 20     # seconds between rebuild attempts (let rotation settle)


class _HollowWrite(Exception):
    """Raised when a commit reports success but the expected row is absent —
    the signature of an OperationalError swallowed by the prod insert path
    during a credential rotation."""


def _current_db_url() -> str:
    """Resolve the DB URL FRESH from the environment on every call. After a
    Railway password rotation, the launching shell's env is stale, but a
    re-read of RECOVERY_DATABASE_URL / DATABASE_URL picks up a value that an
    operator (or a future auto-refresh hook) has exported into this process.
    Re-reading is the cheap, dependency-free option vs shelling out to
    `railway variables -s Postgres --json` (which needs the Railway CLI +
    network + correct linked service and can itself hang)."""
    return os.environ.get("RECOVERY_DATABASE_URL") or os.environ["DATABASE_URL"]


def _build_engine_and_session():
    """(Re)create the engine + session from the CURRENT env URL. Disposes any
    previous engine first so rotated-out connections aren't leaked."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    old = _DB.get("engine")
    if old is not None:
        try:
            old.dispose()
        except Exception:
            pass
    engine = create_engine(
        _current_db_url(),
        connect_args=dict(_ENGINE_CONNECT_ARGS),
        pool_pre_ping=True,
        pool_recycle=600,
    )
    session = sessionmaker(bind=engine)()
    _DB["engine"] = engine
    _DB["session"] = session
    return engine, session


def _is_auth_failure(exc: Exception) -> bool:
    """True if exc is (or wraps) a Postgres password-auth failure — the
    signature of a mid-run credential rotation. Matches on message text so it
    catches the error whether it surfaces as a bare psycopg2.OperationalError
    or wrapped in sqlalchemy.exc.OperationalError."""
    from sqlalchemy.exc import OperationalError as SAOperationalError
    msg = str(getattr(exc, "orig", exc)) + " " + str(exc)
    low = msg.lower()
    looks_auth = (
        "password authentication failed" in low
        or "authentication failed for user" in low
    )
    is_op = isinstance(exc, SAOperationalError)
    try:
        import psycopg2
        is_op = is_op or isinstance(getattr(exc, "orig", exc), psycopg2.OperationalError)
    except Exception:
        pass
    return looks_auth and is_op


def _rebuild_session_after_rotation(label: str):
    """Re-read the env URL, rebuild the engine/session, return the new session.
    Sleeps a short backoff first so a still-in-flight rotation can settle."""
    _log(f"[recover] {label}: password auth failed — rotation suspected; "
         f"re-reading env URL and rebuilding engine in {DB_REBUILD_BACKOFF}s")
    for _ in range(DB_REBUILD_BACKOFF // 5):
        if _stop["flag"]:
            break
        time.sleep(5)
    _, session = _build_engine_and_session()
    return session


def _handle_sigterm(signum, frame):
    _stop["flag"] = True
    _log("[recover] stop signal received — finishing current video then exiting")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _within_hours(iso_str, hours: float) -> bool:
    """True if iso_str (an _now() timestamp) is within `hours` of now. None or
    unparseable => False (treated as 'not recent', so the video is eligible)."""
    if not iso_str:
        return False
    try:
        ts = datetime.fromisoformat(iso_str)
    except Exception:
        return False
    return (datetime.now(timezone.utc) - ts).total_seconds() < hours * 3600


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


# Phase-1 conditional-call extraction block (eval-gated; injected only when
# build_cc_prompt(conditional=True)). The downstream validator branch requires
# trigger_type in this exact set and demands trigger_ticker+trigger_price for
# the price_* types — kept in sync here.
_CONDITIONAL_BLOCK = """
CONDITIONAL CALLS ("if <trigger> then <call>"): when a directional call on a ticker is CONTINGENT on a separate trigger event firing first — "if NVDA breaks 200 it runs to 250", "as long as SPY holds 450, semis stay bullish", "if the Fed cuts, small caps rip", "if it breaks that low it undercuts" — DO NOT emit it as a flat prediction. A flat MISS for a call whose trigger never fired is wrong. Emit it as a conditional with a STRUCTURED trigger. Keep the normal outcome fields (ticker, direction, price_target, timeframe_days, timeframe_category, conviction_level, verbatim_quote) and ADD:
- "derived_from": "conditional_call"
- "trigger_condition": the precondition in plain words ("NVDA closes above 200", "Fed cuts 50bps")
- "trigger_type": exactly one of —
    "price_break"  : a ticker crossing a level ("if X breaks/closes above/below $N"). REQUIRES trigger_ticker + a positive trigger_price.
    "price_hold"   : a ticker staying above/below a level ("as long as X holds $N"). REQUIRES trigger_ticker + a positive trigger_price.
    "fed_decision" : a Fed rate cut or hike.
    "economic_data": a macro print (CPI, jobs, GDP, a rate level).
    "market_event" : an index or commodity level, or a market event ("if oil tops $100", "if VIX > 40", "if a recession hits").
    "other"        : a real but NON-numeric trigger you cannot reduce to a checkable number ("if the economy slows", "if tariffs go up", "if foreign steel gets cheaper"). Keep it — it will be scored unresolved, NEVER a hit or miss.
- "trigger_ticker": the watched symbol (price_break/price_hold only; null otherwise). For an index/VIX/commodity use market_event, not price_break.
- "trigger_price": the numeric threshold (price_break/price_hold only; null otherwise).
- "trigger_deadline": ISO date (YYYY-MM-DD) the trigger must fire by if stated, else null.

Conditional rules:
- The OUTCOME side MUST be an EXPLICIT directional call on a named ticker. If the consequent direction is itself only inferred from sector/mechanism talk, REJECT it — the inferred-direction rule still applies; do not invent a direction.
- A vague trigger with an EXPLICIT consequent → capture as conditional with trigger_type "other" (scored unresolved). NEVER downgrade a conditional into a flat directional call.
- A flat, non-contingent call stays a normal prediction (no derived_from)."""

_CONDITIONAL_EXAMPLE = """,
      {{"derived_from": "conditional_call", "trigger_condition": "NVDA closes above 200", "trigger_type": "price_break", "trigger_ticker": "NVDA", "trigger_price": 200, "trigger_deadline": null, "ticker": "NVDA", "direction": "bullish", "price_target": 250, "timeframe_days": 90, "timeframe_category": "fundamental_quarterly", "conviction_level": "moderate", "verbatim_quote": "if NVDA breaks 200 it runs to 250"}},
      {{"derived_from": "conditional_call", "trigger_condition": "tariffs on imported steel rise", "trigger_type": "other", "trigger_ticker": null, "trigger_price": null, "trigger_deadline": null, "ticker": "CLF", "direction": "bullish", "price_target": null, "timeframe_days": 180, "timeframe_category": "cyclical_medium", "conviction_level": "moderate", "verbatim_quote": "if tariffs go up Cleveland Cliffs is a winner"}}"""


def build_cc_prompt(transcripts: dict, conditional: bool = False) -> str:
    """transcripts: {video_id: transcript_text}.

    conditional=False (default) is the CURRENT live prompt, byte-for-byte.
    conditional=True adds the conditional_call extraction block + schema
    example — the Phase-1 candidate, eval-gated. Held out of the live loop
    (build_cc_prompt(good)) until sign-off; the swap is flipping this arg.
    The downstream pipeline (validator conditional_call branch ->
    _kind/_trigger_* -> insert_youtube_conditional_prediction -> evaluator
    trigger scoring) is already wired, so this prompt change is sufficient.
    """
    blocks = []
    for vid, text in transcripts.items():
        blocks.append(f'--- VIDEO {vid} ---\n{text}')
    body = "\n\n".join(blocks)
    _cond_rules = _CONDITIONAL_BLOCK if conditional else ""
    _cond_example = _CONDITIONAL_EXAMPLE if conditional else ""
    return f"""You are classifying stock predictions from YouTube finance video transcripts. Return JSON only — no prose, no markdown fences.

For each video, extract every valid stock prediction. A valid prediction has ALL of:
- ticker: a real, exchange-listed symbol from ANY market worldwide, OR a real cryptocurrency. Keep every genuine call regardless of country. Storage convention (so non-US is never confused with a US ticker): US stocks bare (AAPL, TSLA, NVDA); non-US stocks take the Yahoo-Finance exchange suffix — London .L (BARC.L), Toronto .TO (SHOP.TO), Hong Kong .HK (0700.HK), Australia .AX (BHP.AX), Frankfurt .DE/.F, Paris .PA, Swiss .SW, Tokyo .T, Amsterdam .AS, India NSE .NS (RELIANCE.NS), BSE .BO; crypto bare (BTC, ETH, SOL, XRP). The symbol MUST be real — NOT macro words (MACRO, SPY500), NOT loosely-described indices, NOT hallucinated/invented symbols.
- direction: "bullish" or "bearish" — NEVER "neutral" (a non-directional call is not a prediction; drop it).
- forward-looking language ("I think", "will", "target", "by Q3", "headed to").
- verbatim_quote: the exact words spoken, copied byte-for-byte from the transcript — an exact substring (it is matched against transcript timing to resolve the source timestamp). Copy as many words as the prediction spans; there is NO minimum and NO maximum length — never drop a real prediction for being short. Include enough words to locate it uniquely in the transcript. Do not paraphrase or fix grammar.

EVERY prediction object MUST also carry these three fields (predictions missing any of them are discarded downstream):
- timeframe_days: integer 1-2000 — the horizon the call should play out over. If the speaker states one ("by Friday", "this quarter", "by year end"), convert it to days. If they give none, infer a sensible default from the call's nature (a chart/swing setup ≈ 21, an earnings call ≈ 90, a long-term thesis ≈ 365). Never 0, never null.
- timeframe_category: pick the row whose upper bound is the smallest value >= timeframe_days:
    <=7 -> "options_short" ; <=21 -> "swing_trade" ; <=30 -> "technical_chart" ;
    <=90 -> "fundamental_quarterly" ; <=180 -> "cyclical_medium" ;
    <=730 -> "macro_thesis" ; >730 -> "long_term_fundamental"
- conviction_level: one of exactly "strong" (emphatic, high-confidence), "moderate" (a normal call), "hedged" ("might", "could", "if X then"), "hypothetical" (a speculative what-if scenario), "unknown" (tone unclear).
- price_target: a number if the speaker names one, otherwise null.

REJECT (do not emit) predictions that are:
- Past-tense reporting ("revenue grew 40%", "missed estimates", "benefited from", "was up") — history is not a prediction, even when it explains a mechanism that could continue
- Inferred direction: a direction you derived from general sector/industry/mechanism talk (tariff mechanics, rate effects, commodity cycles) rather than the speaker explicitly making a forward call on the named ticker. Require an explicit call on THAT ticker — "I think X drops", "bearish on X", "X will...", or a price target for X. Sector/tariff mechanics alone is NOT a prediction.
- Ad reads ("sponsored by", "use code", "brought to you by")
- Pronoun-only context ("they're going up" without naming the company)
- Wrong-ticker attribution (ticker named but context is a different company)
- Contradictory pairs (same video bullish AND bearish on the same ticker — drop both)
- Hallucinated / made-up tickers
{_cond_rules}
For a video with no valid predictions, return an entry with "predictions": [].
Return an entry for EVERY video listed below, even if empty.

Output — a JSON array, exactly this shape, nothing else:
[
  {{
    "video_id": "<the id from the --- VIDEO <id> --- header>",
    "predictions": [
      {{"ticker": "AAPL", "direction": "bullish", "price_target": 250, "timeframe_days": 90, "timeframe_category": "fundamental_quarterly", "conviction_level": "moderate", "verbatim_quote": "<exact transcript words>"}},
      {{"ticker": "BTC", "direction": "bullish", "price_target": 100000, "timeframe_days": 180, "timeframe_category": "cyclical_medium", "conviction_level": "strong", "verbatim_quote": "<exact transcript words>"}},
      {{"ticker": "BARC.L", "direction": "bearish", "price_target": null, "timeframe_days": 30, "timeframe_category": "technical_chart", "conviction_level": "moderate", "verbatim_quote": "<exact transcript words>"}}{_cond_example}
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


def _run_cc_text(prompt: str, model: str) -> tuple[str | None, str | None]:
    """Run one `claude -p` call and return (result_text, error).

    On CC usage-limit, sleeps and retries indefinitely (limits reset) —
    a usage-limit pause is never reported as a failure. Returns (None, tag)
    only on a genuine error the caller should handle.
    """
    cmd = [
        _claude_bin(), "-p",
        "--output-format", "json",
        "--model", model,
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
            _log(f"[recover] CC usage limit hit ({model}) — sleeping "
                 f"{USAGE_LIMIT_BACKOFF}s then retrying this batch")
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
        _run_cc_text.last_latency = latency  # type: ignore[attr-defined]
        return env_obj.get("result") or "", None


def run_cc_classifier(prompt: str) -> tuple[list | None, str | None]:
    """Run one `claude -p` Sonnet classification. Returns (entries, error)."""
    result_text, err = _run_cc_text(prompt, CLAUDE_MODEL)
    if err:
        return None, err
    entries = _extract_json_array(result_text)
    if entries is None:
        return None, f"cc_output_unparseable: {result_text[:200]}"
    run_cc_classifier.last_latency = _run_cc_text.last_latency  # type: ignore[attr-defined]
    return entries, None


# ── Haiku pre-filter — cheap yes/no screen before the Sonnet extraction ─────
def build_prefilter_prompt(transcripts: dict) -> str:
    """transcripts: {video_id: transcript_text}. Tuned for HIGH RECALL —
    a false 'no' drops a real prediction forever; a false 'yes' just costs
    one Sonnet call. When in doubt the screen must say yes."""
    blocks = []
    for vid, text in transcripts.items():
        blocks.append(f'--- VIDEO {vid} ---\n{text}')
    body = "\n\n".join(blocks)
    return f"""You are a cheap HIGH-RECALL screen in front of a careful prediction extractor. For EACH video below answer ONE question: might this transcript contain ANY forward-looking view on a SPECIFIC named stock, company, ETF, or cryptocurrency — its future price, value, growth, or whether to buy/sell/hold/avoid it?

Count ALL of these as "yes":
- explicit directional calls ("I think X goes up", "bearish on Y") and ANY price target, fair-value estimate, or upside/downside scenario ("the middle ground shows us 244", "$300 by 2027")
- HEDGED or soft calls ("might be a good buy", "could see upside", "I'd consider adding")
- buy/sell/hold/avoid/accumulate/trim statements, including the speaker's own actions ("I'm still buying Nvidia")
- valuation or thesis statements implying future direction ("it's undervalued here", "the hypergrowth days are over", "it's a mature business now")
- company names count even without ticker symbols; ONE such statement anywhere in the video is enough
Your job is NOT to judge whether a call is high-quality or explicit enough — the extractor downstream applies the strict rules. Your ONLY failure mode is missing a video that had a call. If there is ANY chance, or the transcript is garbled or ambiguous, answer "yes".

Answer "no" ONLY when you are confident the ENTIRE video contains nothing of the above — e.g. pure news recaps with no opinion, personal-finance/budgeting education, tutorials, interviews with zero asset views, pure backward-looking performance reviews with no view on the future, or ads.

Output ONLY a JSON object mapping every video id to "yes" or "no", nothing else:
{{"<video_id>": "yes", "<video_id_2>": "no"}}
Every one of the {len(transcripts)} video ids MUST appear exactly once.

VIDEOS TO SCREEN:

{body}
"""


def run_cc_prefilter(transcripts: dict, fail_open: bool = True) -> dict | None:
    """Haiku screen over {video_id: text}. Returns {video_id: bool} where True
    means SEND TO SONNET. FAIL-OPEN by design: on any error, unparseable
    output, or a missing id, that video goes to Sonnet — recall over savings.
    With fail_open=False (eval harness) returns None on error instead."""
    all_yes = {vid: True for vid in transcripts}
    result_text, err = _run_cc_text(build_prefilter_prompt(transcripts),
                                    PREFILTER_MODEL)
    if err:
        _log(f"[recover] prefilter error ({err}) — "
             f"{'failing open, full batch to Sonnet' if fail_open else 'eval abort'}")
        return all_yes if fail_open else None
    s = (result_text or "").strip()
    s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
    s = re.sub(r"\n?```\s*$", "", s).strip()
    try:
        # raw_decode: parse the FIRST JSON object and ignore trailing prose —
        # Haiku sometimes appends "**Reasoning:** ..." after the verdict dict.
        verdicts, _ = json.JSONDecoder().raw_decode(s[s.index("{"):])
        assert isinstance(verdicts, dict)
    except Exception as e:
        _log(f"[recover] prefilter output unparseable ({e}) — "
             f"{'failing open' if fail_open else 'eval abort'}: {s[:150]}")
        return all_yes if fail_open else None
    out = {}
    for vid in transcripts:
        v = str(verdicts.get(vid, "yes")).strip().lower()  # missing id -> yes
        out[vid] = (v != "no")
    return out


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


# ── Live transcript fetch with a hard timeout ───────────────────────────────
class _FetchTimeout(Exception):
    pass


def _alarm_handler(signum, frame):
    raise _FetchTimeout(f"transcript fetch exceeded {FETCH_TIMEOUT}s")


def fetch_transcript_guarded(video_id: str) -> dict:
    """fetch_transcript_with_timestamps wrapped in a SIGALRM hard timeout.
    youtube_transcript_api's HTTP calls carry no socket timeout — a single
    stalled Webshare/YouTube connection would otherwise hang the whole run
    indefinitely (observed: 70min frozen with the process idle at 0% CPU).
    On timeout, raises _FetchTimeout — the caller records it as a retriable
    'error: ...' status so the video is retried, not lost."""
    from jobs.youtube_classifier import fetch_transcript_with_timestamps
    prev = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(FETCH_TIMEOUT)
    try:
        return fetch_transcript_with_timestamps(video_id)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prev)


# ── Main ────────────────────────────────────────────────────────────────────
def main() -> int:
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    os.makedirs(CC_CWD, exist_ok=True)

    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    from sqlalchemy import text as sql_text
    from jobs.youtube_channel_monitor import _process_one_video, _record_processed_video

    install_monkeypatches()

    # Own engine, statement_timeout disabled — the candidate scan is large.
    # RECOVERY_DATABASE_URL lets a local run point at the Railway public
    # proxy host (postgres.railway.internal isn't resolvable off-network);
    # it survives `railway run`, which would otherwise override DATABASE_URL.
    # The engine is built via _build_engine_and_session so the same code path
    # can rebuild it from a freshly-read env URL after a mid-run password
    # rotation (TCP keepalives + connect_timeout + pool_recycle live in
    # _ENGINE_CONNECT_ARGS — the run idles its DB connection across
    # multi-minute `claude -p` calls; without them the Railway public proxy
    # silently drops it, observed SSL-closed errors).
    engine, db = _build_engine_and_session()

    cp = load_checkpoint()
    if cp is None:
        cp = init_checkpoint(db)
    else:
        done = sum(1 for v in cp["videos"] if v["status"] == "done")
        _log(f"[recover] continuous mode: checkpoint tracks {len(cp['videos'])} "
             f"videos ({done} historically done); the work queue is now the LIVE "
             f"classifier_error set (random order), not the checkpoint")

    # The work QUEUE is the LIVE DB set (transcript_status='classifier_error'),
    # queried fresh and in RANDOM order each batch so old backlog and freshly
    # discovered videos interleave — the run never "drains all old first" and
    # never finishes. The checkpoint (cp["videos"]) is now an ATTEMPT-TRACKING /
    # telemetry store keyed by video_id, NOT the queue: a successfully
    # reclassified video leaves classifier_error and is naturally excluded by
    # the live query, so a stale checkpoint can never re-add a done video.
    by_id = {v["video_id"]: v for v in cp["videos"]}
    start = time.time()
    consecutive_failures = 0
    batches_run = 0
    cc_latencies: list[float] = []
    inserted_total = 0
    processed_since_log = 0
    processed_this_run = 0
    q_lim = MAX_BATCH_VIDEOS if limit is None else max(1, min(limit, MAX_BATCH_VIDEOS))

    while True:
        if _stop["flag"]:
            _log("[recover] stop flag set — exiting cleanly")
            break

        # Hold out videos that hit MAX_VIDEO_ATTEMPTS within the backoff window
        # so a permanently-failing video can't starve the queue; after the
        # window it becomes eligible again in case the failure was transient.
        excl = [vid for vid, v in by_id.items()
                if v["attempts"] >= MAX_VIDEO_ATTEMPTS
                and _within_hours(v.get("attempted_at"), EXHAUSTED_BACKOFF_HOURS)]

        # Live + RANDOM queue (skip the exclusion clause when empty so an empty
        # array can't trip "cannot determine type of empty array").
        q = ("SELECT youtube_video_id FROM youtube_videos "
             "WHERE transcript_status = 'classifier_error' ")
        params = {"lim": q_lim}
        if excl:
            q += "AND NOT (youtube_video_id = ANY(:excl)) "
            params["excl"] = excl
        q += "ORDER BY RANDOM() LIMIT :lim"
        batch_ids = [r[0] for r in db.execute(sql_text(q), params).fetchall()]

        # CONTINUOUS: never exit on an empty set — idle + re-poll. Only the stop
        # flag (watchdog STOP-file / SIGTERM) ends the run.
        if not batch_ids:
            _log(f"[recover] idle: 0 classifier_error videos ready "
                 f"({len(excl)} held out as exhausted); re-poll in {IDLE_POLL_SECONDS}s")
            for _ in range(max(1, IDLE_POLL_SECONDS // 5)):
                if _stop["flag"]:
                    break
                time.sleep(5)
            continue

        # Track an attempt record for every (possibly brand-new) id.
        for vid in batch_ids:
            if vid not in by_id:
                rec = {"video_id": vid, "status": "pending", "attempts": 0,
                       "attempted_at": None, "result": None}
                cp["videos"].append(rec)
                by_id[vid] = rec
        cp["total"] = len(cp["videos"])   # keep log_progress telemetry sane

        # Per-batch metadata + channel map — re-queried live so newly discovered
        # videos and channels resolve (these are NOT fixed at startup anymore).
        meta = {
            r[0]: {"channel_name": r[1], "title": r[2] or "",
                   "description": r[3] or "", "publish": r[4]}
            for r in db.execute(sql_text(
                "SELECT youtube_video_id, channel_name, title, description, "
                "publish_date FROM youtube_videos "
                "WHERE youtube_video_id = ANY(:ids)"
            ), {"ids": batch_ids}).fetchall()
        }
        chan_id = {
            r[0]: r[1] for r in db.execute(sql_text(
                "SELECT channel_name, youtube_channel_id FROM youtube_channels"
            )).fetchall()
        }
        batch = [by_id[vid] for vid in batch_ids if vid in meta]
        batch_ids = [v["video_id"] for v in batch]
        if not batch_ids:
            continue

        # ── 1. Live re-fetch transcripts (real fetch, hard-timeout-guarded) ─
        _TRANSCRIPT_CACHE.clear()
        _PRED_CACHE.clear()
        for vid in batch_ids:
            if _stop["flag"]:
                break
            try:
                _TRANSCRIPT_CACHE[vid] = fetch_transcript_guarded(vid)
            except Exception as e:
                _TRANSCRIPT_CACHE[vid] = {
                    "text": "", "lang": None,
                    "status": f"error: {type(e).__name__}",
                    "segments": [], "words": None, "has_word_level": False,
                    "is_generated": False, "fetched_at": datetime.utcnow(),
                }
            # Persist the transcript the moment it's fetched, BEFORE
            # classification — so re-fetching the classifier_error backlog
            # saves the text and this is the LAST time we ever pay the proxy
            # for it. Idempotent (first capture wins); never raises.
            _d = _TRANSCRIPT_CACHE.get(vid) or {}
            if _d.get("status") == "ok" and _d.get("text"):
                try:
                    from jobs.video_transcript_store import persist_transcript
                    _m = meta.get(vid, {})
                    persist_transcript(
                        db, vid, _d["text"],
                        transcript_format="json3",
                        channel_name=_m.get("channel_name"),
                        video_title=_m.get("title"),
                        video_publish_date=_m.get("publish"),
                    )
                except Exception as _pe:
                    _log(f"[recover] transcript persist failed for {vid}: {_pe}")
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

        # ── 1.5 Haiku pre-filter: skip Sonnet for prediction-free videos ───
        # A "no" verdict short-circuits to ok_no_predictions via the normal
        # production path (_PRED_CACHE[vid] = [] == classified, zero preds).
        # Fail-open: any prefilter error sends the full batch to Sonnet.
        prefilter_skipped: list = []
        if good and PREFILTER_ENABLED and not _stop["flag"]:
            verdicts = run_cc_prefilter(good)
            for vid, send in (verdicts or {}).items():
                if not send:
                    _PRED_CACHE[vid] = []
                    prefilter_skipped.append(vid)
                    good.pop(vid, None)
            if verdicts:
                _log(f"[recover] prefilter: {len(prefilter_skipped)}/"
                     f"{len(verdicts)} screened out (no prediction) — "
                     f"Sonnet sees {len(good)}")

        # ── 2. Classify the good transcripts via `claude -p` ───────────────
        if good:
            # conditional=True LIVE since 2026-06-11 (Phase-1 sign-off): "if X
            # then Y" calls now extract as conditional_call (structured trigger)
            # instead of a flat directional call — the CLF/steel false-MISS fix.
            # Eval: 50 transcripts / ~45 channels, acceptance parity (7==7,
            # 11==11), 0 spurious conditionals, no real normal-call regression
            # (the one AMZN drop was LLM noise — live drops it too). conditional=
            # False stays byte-identical for an instant rollback.
            entries, err = run_cc_classifier(build_cc_prompt(good, conditional=True))
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
        process_ids = list(good.keys()) + prefilter_skipped + [
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
            # Rotation-resilient write: try the full write+commit; on a
            # password-auth failure (rotation) rebuild the engine from a
            # freshly-read env URL and retry the SAME video. A write that
            # never persists must NOT mark the video done — it stays
            # pending/retry so the data isn't silently lost ("hollow-done").
            write_ok = False
            auth_blocked = False   # True => failure was a rotation, don't burn the attempt
            last_exc = None
            rebuilds = 0
            while True:
                if _stop["flag"]:
                    break
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
                    # _process_one_video / _record_processed_video swallow
                    # OperationalError internally (shared prod code) and
                    # rollback, so a rotation can make them return a clean
                    # status while NOTHING persisted. The youtube_videos row
                    # ALWAYS pre-exists (these are existing classifier_error
                    # rows), so an absence check is useless — instead verify
                    # transcript_status was actually re-stamped to the status
                    # we just wrote. If it still reads the old value (e.g. it
                    # is still 'classifier_error'), the UPDATE was rolled back
                    # inside the swallow and the write was hollow.
                    persisted = db.execute(sql_text(
                        "SELECT transcript_status FROM youtube_videos "
                        "WHERE youtube_video_id = :vid"
                    ), {"vid": vid}).fetchone()
                    got = persisted[0] if persisted else None
                    if persisted is None or got != status:
                        raise _HollowWrite(
                            f"hollow_write: transcript_status did not persist "
                            f"(want {status!r}, got {got!r}) — write swallowed "
                            "inside prod code, likely password rotation"
                        )
                    write_ok = True
                    break
                except Exception as e:
                    last_exc = e
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    # A hollow write is the fingerprint of a rotation whose
                    # OperationalError was swallowed deeper down: the prod
                    # insert path caught it, rolled back, and returned a clean
                    # status, so nothing persisted. Treat it like an auth
                    # failure — refund the attempt and rebuild the engine.
                    if _is_auth_failure(e) or isinstance(e, _HollowWrite):
                        auth_blocked = True
                        if rebuilds < DB_REBUILD_MAX:
                            rebuilds += 1
                            db = _rebuild_session_after_rotation(
                                f"video={vid} (rebuild {rebuilds}/{DB_REBUILD_MAX})")
                            continue  # retry this video on the fresh session
                    _log(f"[recover] exception on video={vid}: {type(e).__name__}: {e}")
                    break

            if not write_ok:
                if auth_blocked:
                    # Failure was a password rotation, not a bad video. Refund
                    # the attempt and leave the video pending so a later loop /
                    # re-run retries it once credentials are fresh. NEVER mark
                    # done here — marking-done-on-swallowed-write was the
                    # data-loss bug that lost ~188 videos.
                    v["attempts"] -= 1
                    save_checkpoint(cp)
                    if _stop["flag"]:
                        break
                    continue
                # Genuine (non-auth) DB error or hollow write. Keep the attempt
                # so a permanently-broken video can eventually exhaust and let
                # the run finish — but only mark done once attempts are spent.
                if v["attempts"] >= MAX_VIDEO_ATTEMPTS:
                    v["status"] = "done"
                    v["result"] = {
                        "inserted": 0,
                        "error": f"exhausted: {type(last_exc).__name__ if last_exc else 'unknown'}",
                    }
                save_checkpoint(cp)
                if _stop["flag"]:
                    break
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

#!/usr/bin/env python3
"""Build a clean, labeled JSONL corpus to fine-tune a replacement for the
Haiku/Sonnet YouTube+X prediction classifier (2026-06-21).

WHAT THIS IS (and is NOT)
-------------------------
The live classifier's job is: given a chunk of a YouTube transcript or a tweet
and a candidate ticker the speaker mentioned, decide whether there is a genuine
forward directional *prediction* on that ticker and, if so, extract its
structured form (direction / target / timeframe / conviction). This script
distills that decision into a supervised corpus:

    input   = source context (YouTube transcript window OR full tweet)
              + the candidate ticker + source kind   (NO stored fields -> no
              answer leakage; the model must read the context itself)
    output  = {"decision":"predict", ticker, direction, target, timeframe,
               conviction}                       (a valid call)
              OR {"decision":"reject", "reject_reason": <class>}

Labels are *silver*: produced per-row by `claude -p` (Sonnet primary, Haiku
fallback when Sonnet hits a usage limit) auditing the stored row against the
source. They are NOT human gold. The honesty check (`build` stage) measures
silver-vs-gold agreement on the 200 human-labeled rows in `gt_gold`
(2026-06-21) and prints the circularity caveats. See LABELS.md (emitted by the
`build` stage).

SCOPE: train/val cover YouTube + X only — the surfaces the LLM classifier
actually runs on. `article` rows (97.6% of the visible table) are Benzinga's
structured analyst-rating feed, not LLM-classified free text, and gold is 0%
article; a small capped article stratum is included only for source coverage
and is kept OUT of train/val (separate file). The 200 gold ids are EXCLUDED
from the corpus so they remain a pristine external benchmark.

LOCKED RULES (Nimrod, honored verbatim in the judge prompt):
  * a bare directional stance ("I like X", "X is a buy", "bullish X") is VALID
    even with no price target;
  * conditionals ("if/when ... then ...") are ACCEPTED as valid;
  * a hedged / low-conviction musing is NOT a prediction even if it names a
    number;
  * a vague preference with no gradeable claim ("great company") is a REJECT;
  * a wrong stored *target* alone does NOT invalidate a real call.

Resumable + checkpointed at every stage. Stages:

  sample   draw the deterministic stratified sample (seeded) + the 200 gold
           overlap ids, build each row's model-input text, write worklist.jsonl
  judge    per-row `claude -p` silver judge -> append silver_labels.jsonl
           (ThreadPool, resumes from the checkpoint, never overwrites)
  build    format train/val/gold_overlap JSONL, 90/10 stratified split, compute
           silver-vs-gold agreement, write stats.json + LABELS.md
  all      sample -> judge -> build

Run (DB url is the Postgres service DATABASE_PUBLIC_URL):
  DATABASE_PUBLIC_URL=... python3 finetune_corpus_builder.py all
  # or stage by stage; judge can be re-run to resume after an interrupt.
"""
from __future__ import annotations
import argparse, hashlib, json, os, random, re, subprocess, sys, threading, time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
GOLD_JSONL = os.path.join(
    HERE, "..", "groundtruth_2026_06_16", "gold_verdicts_200.jsonl"
)
WORKLIST = os.path.join(HERE, "worklist.jsonl")
SILVER = os.path.join(HERE, "silver_labels.jsonl")
TRAIN = os.path.join(HERE, "train.jsonl")
VAL = os.path.join(HERE, "val.jsonl")
GOLD_OVERLAP = os.path.join(HERE, "gold_overlap.jsonl")
STATS = os.path.join(HERE, "stats.json")
LABELS_MD = os.path.join(HERE, "LABELS.md")

SEED = 20260621
WINDOW = 3000            # chars of transcript context centered on the quote
PRIMARY = os.environ.get("SILVER_PRIMARY", "sonnet")
FALLBACK = os.environ.get("SILVER_FALLBACK", "haiku")
WORKERS = int(os.environ.get("SILVER_WORKERS", "20"))

# Per-(source x category) target sample sizes. Small YouTube categories are
# taken whole ("all"); ticker_call strata are capped. Article is capped low and
# routed OUT of train/val.
TARGETS = {
    ("youtube", "ticker_call"): 2500,
    ("youtube", "macro_call"): "all",
    ("youtube", "sector_call"): "all",
    ("youtube", "regime_call"): "all",
    ("youtube", "metric_forecast_call"): "all",
    ("youtube", "conditional_call"): "all",
    ("youtube", "pair_call"): "all",
    ("youtube", "binary_event_call"): "all",
    ("x", "ticker_call"): 2000,
    ("article", "ticker_call"): 200,   # coverage stratum, kept out of train/val
}

VISIBLE = """NOT (p.source_type='youtube' AND p.source_timestamp_seconds IS NULL)
 AND (p.conviction_level NOT IN ('hedged','hypothetical') OR p.conviction_level IS NULL)
 AND COALESCE(p.is_reported_speech,FALSE)=FALSE
 AND COALESCE(p.is_ambiguous_symbol,FALSE)=FALSE
 AND COALESCE(p.is_weak_basket_call,FALSE)=FALSE
 AND COALESCE(p.is_holding_disclosure,FALSE)=FALSE
 AND COALESCE(p.is_no_claim,FALSE)=FALSE"""

VERDICTS = {"OK", "conditional", "not_a_prediction", "hedged", "holding",
            "reported_speech", "wrong_ticker", "chart_commentary",
            "direction_mismatch", "target_error"}

# stored timeframe_category -> coarse learnable bucket
TF_BUCKET = {
    "day_trading": "short", "options_short": "short", "options_monthly": "short",
    "swing_trade": "short", "technical_chart": "short", "earnings_cycle": "short",
    "fundamental_quarterly": "medium", "cyclical_medium": "medium",
    "macro_thesis": "long", "long_term_fundamental": "long", "structural": "long",
}


def db():
    import psycopg2
    url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("need DATABASE_PUBLIC_URL (Postgres service public url)")
    return psycopg2.connect(url)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


# ---------------------------------------------------------------- sample stage
def gold_ids() -> list[int]:
    return [json.loads(l)["id"] for l in open(GOLD_JSONL) if l.strip()]


def transcript_window(transcript: str, quote: str) -> str:
    """~WINDOW chars of transcript centered on the stored quote; head fallback."""
    if not transcript:
        return ""
    if len(transcript) <= WINDOW:
        return transcript
    q = norm(quote)[:60]
    i = norm(transcript).find(q) if len(q) >= 12 else -1
    if i >= 0:
        lo = max(0, i - WINDOW // 2)
        return transcript[lo:lo + WINDOW]
    return transcript[:WINDOW]


def build_input(r: dict) -> tuple[str, str]:
    """Return (input_kind, model_input_text) for one row. Leak-free: contains
    only the source context + candidate ticker + source kind."""
    st = r["source_type"]
    tk = r["ticker"]
    if st == "youtube":
        win = transcript_window(r.get("transcript") or "", r.get("verbatim") or "")
        if len(win) >= 80:
            kind = "yt_transcript_window"
            body = win
        else:
            kind = "yt_quote_only"
            body = " ".join(x for x in [r.get("source_title"), r.get("verbatim"),
                                        r.get("exact_quote"), r.get("context")] if x)[:1500]
        head = (f"SOURCE: YouTube earnings/markets video transcript (auto-captioned; "
                f"expect ASR noise).\nCANDIDATE TICKER: {tk}\n\nTRANSCRIPT:\n")
        return kind, head + "---\n" + body + "\n---"
    if st == "x":
        body = (r.get("verbatim") or r.get("exact_quote") or r.get("context") or "")[:1500]
        head = f"SOURCE: a single tweet (X/Twitter).\nCANDIDATE TICKER: {tk}\n\nTWEET:\n"
        return "x_tweet", head + "---\n" + body + "\n---"
    # article (analyst-rating feed)
    body = (r.get("context") or r.get("exact_quote") or "")[:600]
    head = f"SOURCE: an analyst rating note.\nCANDIDATE TICKER: {tk}\n\nNOTE:\n"
    return "article_note", head + "---\n" + body + "\n---"


SAMPLE_COLS = """p.id, p.ticker, p.source_type, p.prediction_category, p.direction,
 p.target_price, p.conviction_level, p.timeframe_category, p.inferred_timeframe_days,
 p.call_type, p.source_title, p.context, p.exact_quote, p.source_verbatim_quote,
 p.transcript_video_id"""


def row_from_record(rec, transcript=None) -> dict:
    (pid, tk, st, cat, direction, target, conv, tfcat, tfdays, ctype,
     title, ctx, exq, verb, tvid) = rec
    return {
        "id": pid, "ticker": tk, "source_type": st, "prediction_category": cat,
        "stored_direction": direction, "stored_target": float(target) if target is not None else None,
        "stored_conviction": conv, "stored_timeframe_category": tfcat,
        "stored_timeframe_days": tfdays, "call_type": ctype,
        "source_title": title, "context": ctx, "exact_quote": exq,
        "verbatim": verb, "transcript_video_id": tvid, "transcript": transcript,
    }


def stage_sample():
    conn = db()
    cur = conn.cursor()
    gids = set(gold_ids())
    rng = random.Random(SEED)
    worklist: dict[int, dict] = {}

    def fetch_ids(source, cat, limit):
        # deterministic pseudo-random ordering by salted md5(id); excludes gold ids
        lim = "" if limit == "all" else f"LIMIT {int(limit)}"
        cur.execute(f"""
            SELECT p.id FROM predictions p
            WHERE {VISIBLE} AND p.source_type=%s AND p.prediction_category=%s
              AND p.id <> ALL(%s)
            ORDER BY md5(p.id::text || '{SEED}') {lim}
        """, (source, cat, list(gids)))
        return [r[0] for r in cur.fetchall()]

    picked: dict[int, tuple] = {}   # id -> (source, cat, role)
    for (source, cat), limit in TARGETS.items():
        ids = fetch_ids(source, cat, limit)
        for i in ids:
            picked[i] = (source, cat, "corpus")
        print(f"  sampled {source}/{cat}: {len(ids)} (target {limit})", flush=True)

    # gold overlap: judge all 200 with the same silver judge (NOT in train/val)
    for gi in gids:
        picked[gi] = (None, None, "gold_overlap")
    print(f"  + gold overlap ids: {len(gids)}", flush=True)

    # hydrate every picked id with its fields + transcript (single pass)
    all_ids = list(picked.keys())
    print(f"  hydrating {len(all_ids)} rows ...", flush=True)
    CHUNK = 1000
    recs: dict[int, tuple] = {}
    for k in range(0, len(all_ids), CHUNK):
        batch = all_ids[k:k + CHUNK]
        cur.execute(f"SELECT {SAMPLE_COLS} FROM predictions p WHERE p.id = ANY(%s)", (batch,))
        for rec in cur.fetchall():
            recs[rec[0]] = rec
    # transcripts for the youtube rows in one join
    yt_vids = {recs[i][14] for i in all_ids if i in recs and recs[i][2] == "youtube" and recs[i][14]}
    tmap: dict[str, str] = {}
    if yt_vids:
        vids = list(yt_vids)
        for k in range(0, len(vids), CHUNK):
            b = vids[k:k + CHUNK]
            cur.execute("SELECT video_id, transcript_text FROM video_transcripts WHERE video_id = ANY(%s)", (b,))
            for vid, txt in cur.fetchall():
                if vid not in tmap or len(txt or "") > len(tmap[vid] or ""):
                    tmap[vid] = txt
    print(f"  transcripts joined: {len(tmap)} / {len(yt_vids)} yt videos", flush=True)

    n_missing = 0
    for i in all_ids:
        if i not in recs:
            n_missing += 1
            continue
        rec = recs[i]
        source, cat, role = picked[i]
        r = row_from_record(rec, transcript=tmap.get(rec[14]))
        kind, model_input = build_input(r)
        worklist[i] = {
            "id": i, "role": role, "in_gold": i in gids,
            "source_type": r["source_type"], "prediction_category": r["prediction_category"],
            "ticker": r["ticker"], "input_kind": kind, "model_input": model_input,
            # stored hints for the judge only (NOT placed in the training input):
            "stored_direction": r["stored_direction"], "stored_target": r["stored_target"],
            "stored_conviction": r["stored_conviction"],
            "stored_timeframe_category": r["stored_timeframe_category"],
            "quote": (r["verbatim"] or r["exact_quote"] or r["context"] or "")[:500],
        }
    if n_missing:
        print(f"  WARN {n_missing} picked ids not found in predictions", flush=True)

    with open(WORKLIST, "w") as f:
        for i in sorted(worklist):
            f.write(json.dumps(worklist[i]) + "\n")
    roles = Counter(w["role"] for w in worklist.values())
    print(f"WORKLIST written: {len(worklist)} rows -> {WORKLIST}  roles={dict(roles)}", flush=True)
    conn.close()


# ----------------------------------------------------------------- judge stage
JUDGE_PROMPT = '''You are auditing ONE stored stock-prediction row against its source.
The SOURCE TEXT below is the ground truth — NOT the stored fields.

Candidate ticker: {ticker}
Stored (may be wrong — for your reference only): direction={direction}  target={target}  quote="{quote}"

{input}

Decide, for the CANDIDATE TICKER only, using these LOCKED RULES:
- A bare directional STANCE ("I like {ticker}", "{ticker} is a buy", "I'm bullish {ticker}",
  "avoid {ticker}") IS a valid prediction even with NO price target.
- A CONDITIONAL call ("if/when X then {ticker} ...") IS accepted as valid.
- A HEDGED / low-conviction musing ("maybe", "could", "not sure, but", "a little") is NOT a
  prediction even if it names a number.
- A vague PREFERENCE with no gradeable claim ("great company", "I like the management") with no
  direction is NOT a prediction (reject).
- A wrong stored TARGET alone does NOT make a real call invalid.
- A passive HOLDING disclosure ("I own/hold {ticker}"), REPORTED speech ("analysts expect"),
  pure CHART commentary (levels/support with no committed direction), or a call about a DIFFERENT
  company are all NOT valid for {ticker}.

Set "valid": true ONLY if there is a genuine forward directional call on {ticker} whose direction
you can state from the source. Otherwise "valid": false.

Choose ONE "verdict":
  OK | conditional | not_a_prediction | hedged | holding | reported_speech | wrong_ticker |
  chart_commentary | direction_mismatch | target_error
(direction_mismatch = a real call but opposite to the stored direction -> valid=false;
 target_error = a real valid call but the stored target is wrong -> valid=true, give corrected target or null.)

If valid, also extract from the SOURCE:
  direction: "bullish" | "bearish" | "neutral"
  target: a number (price target) or null
  timeframe: "short" | "medium" | "long" | null
  conviction: "strong" | "moderate" | "low" | "conditional" | null

Ignore ASR garble. Reply with ONLY a JSON object, no prose:
{{"valid": <bool>, "verdict": "<one>", "direction": "<or null>", "target": <number or null>,
 "timeframe": "<or null>", "conviction": "<or null>", "why": "<=16 words"}}'''


def clean_env():
    return {k: v for k, v in os.environ.items()
            if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN")}


# A real subscription usage-cap latches the run to Haiku (it stays hit for the
# rest of the reset window). A transient overload only triggers a per-row
# fallback — it must NOT permanently downgrade the whole run.
CAP_SIGNALS = ("usage limit", "limit reached", "limit will reset", "/upgrade",
               "out of credit", "insufficient credit", "quota exceeded")
TRANSIENT_SIGNALS = ("overloaded", "rate limit", "rate_limit", "429", "529",
                     "too many requests", "service unavailable")
_sonnet_blocked = threading.Event()   # latched only on a real usage cap
_lock = threading.Lock()
_done = set()
_n = [0]


def call_claude(model: str, prompt: str):
    """Return (parsed_json | None, signal) where signal in {'', 'cap', 'transient'}."""
    try:
        cp = subprocess.run(["claude", "-p", "--model", model, prompt],
                            capture_output=True, text=True, timeout=300,
                            cwd="/tmp", env=clean_env(), stdin=subprocess.DEVNULL)
    except Exception:
        return None, "transient"
    out, err = cp.stdout or "", cp.stderr or ""
    blob = (out + " " + err).lower()
    signal = ""
    if any(s in blob for s in CAP_SIGNALS):
        signal = "cap"
    elif cp.returncode != 0 and any(s in blob for s in TRANSIENT_SIGNALS):
        signal = "transient"
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None, signal
    try:
        return json.loads(m.group(0)), signal
    except Exception:
        return None, signal


def judge_row(w: dict) -> dict:
    prompt = JUDGE_PROMPT.format(
        ticker=w["ticker"], direction=w.get("stored_direction"),
        target=w.get("stored_target"), quote=(w.get("quote") or "")[:300],
        input=w["model_input"])
    used = None
    parsed = None
    # primary (unless the run is latched to fallback), then fallback
    order = [FALLBACK] if _sonnet_blocked.is_set() and PRIMARY == "sonnet" else [PRIMARY, FALLBACK]
    for model in order:
        for _ in range(2):
            parsed, signal = call_claude(model, prompt)
            if parsed and (parsed.get("verdict") in VERDICTS or "valid" in parsed):
                used = model
                break
            if signal == "cap" and model == PRIMARY == "sonnet":
                _sonnet_blocked.set()   # latch the whole run to Haiku
                break                   # stop retrying Sonnet, drop to fallback
        if parsed and used:
            break
    if not parsed or not used:
        return {"id": w["id"], "role": w["role"], "judge_model": "none",
                "verdict": "ERROR", "valid": None, "why": "judge_failed"}
    v = parsed.get("verdict")
    v = v if v in VERDICTS else "other"
    valid = bool(parsed.get("valid"))
    if v in ("OK", "conditional", "target_error"):
        valid = True
    if v in ("not_a_prediction", "hedged", "holding", "reported_speech",
             "wrong_ticker", "chart_commentary", "direction_mismatch"):
        valid = False
    return {
        "id": w["id"], "role": w["role"], "judge_model": used,
        "verdict": v, "valid": valid,
        "direction": parsed.get("direction"), "target": parsed.get("target"),
        "timeframe": parsed.get("timeframe"), "conviction": parsed.get("conviction"),
        "why": (parsed.get("why") or "")[:120],
    }


def stage_judge():
    rows = [json.loads(l) for l in open(WORKLIST) if l.strip()]
    if os.path.exists(SILVER):
        for l in open(SILVER):
            try:
                o = json.loads(l)
                if o.get("verdict") in VERDICTS or o.get("verdict") == "other":
                    _done.add(o["id"])
            except Exception:
                pass
    todo = [w for w in rows if w["id"] not in _done]
    # Shuffle (seeded) so judging progress is balanced across sources. The
    # worklist is id-sorted and article rows have the lowest ids, so without
    # this the run would judge all article rows first and YouTube (the core)
    # last — an interrupted run would then have zero YouTube labels.
    random.Random(SEED).shuffle(todo)
    print(f"judge: {len(todo)} to do ({len(_done)} already), workers={WORKERS}, "
          f"primary={PRIMARY} fallback={FALLBACK}", flush=True)

    def work(w):
        res = judge_row(w)
        with _lock:
            with open(SILVER, "a") as f:
                f.write(json.dumps(res) + "\n")
            _n[0] += 1
            n = _n[0]
        if n % 50 == 0 or res["verdict"] == "ERROR":
            blk = " [sonnet-blocked->haiku]" if _sonnet_blocked.is_set() else ""
            print(f"  [{n}/{len(todo)}] id={res['id']} {res['judge_model']} "
                  f"{res['verdict']} valid={res['valid']}{blk}", flush=True)

    with ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(work, todo))
    print("JUDGE STAGE DONE", flush=True)


# ----------------------------------------------------------------- build stage
INSTRUCTION = (
    "You classify whether a financial speaker makes a genuine forward directional "
    "prediction about a specific candidate ticker, and if so extract its structured "
    "form. Input: a YouTube transcript window or a tweet, plus the candidate ticker. "
    "Rules: a bare directional stance (\"I like X\", \"X is a buy\") is a valid "
    "prediction even with no target; conditionals are accepted; a hedged/low-conviction "
    "musing is NOT a prediction even with a number; a vague preference with no gradeable "
    "claim is not a prediction; holdings disclosures, reported speech, pure chart "
    "commentary, and calls about a different company are not valid for this ticker. "
    "Respond with ONLY JSON: either "
    "{\"decision\":\"predict\",\"ticker\":..,\"direction\":\"bullish|bearish|neutral\","
    "\"target\":<number|null>,\"timeframe\":\"short|medium|long|null\","
    "\"conviction\":\"strong|moderate|low|conditional|null\"} or "
    "{\"decision\":\"reject\",\"reject_reason\":<class>}."
)


def output_json(w: dict, lab: dict) -> dict:
    if lab.get("valid"):
        tf = lab.get("timeframe")
        if tf not in ("short", "medium", "long"):
            tf = TF_BUCKET.get(w.get("stored_timeframe_category") or "", None)
        conv = lab.get("conviction")
        if conv not in ("strong", "moderate", "low", "conditional"):
            conv = w.get("stored_conviction") if w.get("stored_conviction") in ("strong", "moderate", "low") else None
        if lab.get("verdict") == "conditional" and not conv:
            conv = "conditional"
        direction = lab.get("direction")
        if direction not in ("bullish", "bearish", "neutral"):
            direction = w.get("stored_direction")
        tgt = lab.get("target")
        if isinstance(tgt, str):
            try:
                tgt = float(re.sub(r"[^0-9.]", "", tgt))
            except Exception:
                tgt = None
        return {"decision": "predict", "ticker": w["ticker"], "direction": direction,
                "target": tgt, "timeframe": tf, "conviction": conv}
    return {"decision": "reject", "reject_reason": lab.get("verdict", "not_a_prediction")}


def corpus_record(w: dict, lab: dict) -> dict:
    out = output_json(w, lab)
    return {
        "messages": [
            {"role": "system", "content": INSTRUCTION},
            {"role": "user", "content": w["model_input"]},
            {"role": "assistant", "content": json.dumps(out, separators=(",", ":"))},
        ],
        "meta": {
            "id": w["id"], "source": w["source_type"],
            "category": w["prediction_category"], "input_kind": w["input_kind"],
            "silver_verdict": lab.get("verdict"), "silver_valid": lab.get("valid"),
            "judge_model": lab.get("judge_model"), "decision": out["decision"],
            "in_gold": w.get("in_gold", False),
        },
    }


def stage_build():
    wl = {w["id"]: w for w in (json.loads(l) for l in open(WORKLIST) if l.strip())}
    labs = {}
    for l in open(SILVER):
        try:
            o = json.loads(l)
            labs[o["id"]] = o   # last write wins (resume-safe)
        except Exception:
            pass

    gold = {}
    for l in open(GOLD_JSONL):
        if l.strip():
            o = json.loads(l)
            gold[o["id"]] = o   # {id, gold_verdict, gold_valid, haiku_verdict}

    corpus, gold_rows, errors = [], [], 0
    for pid, w in wl.items():
        lab = labs.get(pid)
        if not lab or lab.get("verdict") == "ERROR":
            errors += 1
            continue
        if w["role"] == "gold_overlap":
            gold_rows.append((w, lab))
        elif w["source_type"] in ("youtube", "x"):
            corpus.append(corpus_record(w, lab))
        else:  # article coverage stratum -> separate, kept out of train/val
            corpus.append({**corpus_record(w, lab), "_article": True})

    train_pool = [r for r in corpus if not r.get("_article")]
    article_pool = [{k: v for k, v in r.items() if k != "_article"} for r in corpus if r.get("_article")]

    # 90/10 stratified split by (source, decision)
    rng = random.Random(SEED)
    strata = defaultdict(list)
    for r in train_pool:
        strata[(r["meta"]["source"], r["meta"]["decision"])].append(r)
    train, val = [], []
    for key, items in strata.items():
        rng.shuffle(items)
        k = max(1, round(len(items) * 0.10)) if len(items) >= 10 else 0
        val.extend(items[:k])
        train.extend(items[k:])
    rng.shuffle(train)
    rng.shuffle(val)

    # ---- silver-vs-gold agreement on the 200 overlap (the honesty check) ----
    pair = []  # (silver_valid, gold_valid, silver_verdict, gold_verdict, source)
    for w, lab in gold_rows:
        g = gold.get(w["id"])
        if g is None or lab.get("valid") is None:
            continue
        pair.append((bool(lab["valid"]), bool(g["gold_valid"]),
                     lab.get("verdict"), g.get("gold_verdict"), w["source_type"]))
    n_pair = len(pair)
    agree = sum(1 for p in pair if p[0] == p[1])
    tp = sum(1 for p in pair if p[0] and p[1])      # silver valid & gold valid
    fp = sum(1 for p in pair if p[0] and not p[1])  # silver valid, gold invalid
    fn = sum(1 for p in pair if not p[0] and p[1])  # silver invalid, gold valid
    tn = sum(1 for p in pair if not p[0] and not p[1])
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    # cohen's kappa (validity, binary)
    po = agree / n_pair if n_pair else 0.0
    ps = (tp + fp) / n_pair if n_pair else 0.0   # silver-valid rate
    pg = (tp + fn) / n_pair if n_pair else 0.0   # gold-valid rate
    pe = ps * pg + (1 - ps) * (1 - pg)
    kappa = (po - pe) / (1 - pe) if (1 - pe) else 0.0
    by_src = {}
    for s in ("youtube", "x"):
        sub = [p for p in pair if p[4] == s]
        by_src[s] = {"n": len(sub),
                     "agreement": round(sum(1 for p in sub if p[0] == p[1]) / len(sub), 4) if sub else None}
    # WHERE silver disagrees with gold (the diagnostic): false-OK = silver said
    # valid but the human said invalid (the damaging direction — non-predictions
    # passed as calls); false-reject = silver killed a human-valid call.
    false_ok = dict(Counter(p[2] for p in pair if p[0] and not p[1]))
    false_reject = dict(Counter(p[2] for p in pair if not p[0] and p[1]))

    # ---- clean human-labeled gold seed (200 rows, GOLD labels as targets) ----
    # Highest-quality data available: validity is human. For valid rows the
    # structured fields come from the stored row (gold OK => the row is
    # correctly represented). NOT for honest evaluation of any judge tuned on
    # this set — see the contamination caveat in LABELS.md.
    gold_seed = []
    for gid, g in gold.items():
        w = wl.get(gid)
        if not w:
            continue
        if g.get("gold_valid"):
            tf = TF_BUCKET.get(w.get("stored_timeframe_category") or "", None)
            conv = w.get("stored_conviction") if w.get("stored_conviction") in ("strong", "moderate", "low") else None
            if g.get("gold_verdict") == "conditional":
                conv = "conditional"
            out = {"decision": "predict", "ticker": w["ticker"],
                   "direction": w.get("stored_direction"), "target": w.get("stored_target"),
                   "timeframe": tf, "conviction": conv}
        else:
            reason = "wrong_direction" if g.get("gold_verdict") == "wrong_direction" else "not_a_prediction"
            out = {"decision": "reject", "reject_reason": reason}
        gold_seed.append({
            "messages": [
                {"role": "system", "content": INSTRUCTION},
                {"role": "user", "content": w["model_input"]},
                {"role": "assistant", "content": json.dumps(out, separators=(",", ":"))},
            ],
            "meta": {"id": gid, "source": w["source_type"], "label_source": "human_gold",
                     "gold_verdict": g.get("gold_verdict"), "decision": out["decision"]},
        })

    # write corpus files
    def dump(path, rows):
        with open(path, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    dump(TRAIN, train)
    dump(VAL, val)
    dump(os.path.join(HERE, "article_holdout.jsonl"), article_pool)
    dump(os.path.join(HERE, "gold_human_seed.jsonl"), gold_seed)
    # gold_overlap: full record + gold for auditing
    with open(GOLD_OVERLAP, "w") as f:
        for w, lab in gold_rows:
            g = gold.get(w["id"], {})
            f.write(json.dumps({
                "id": w["id"], "source": w["source_type"],
                "silver_verdict": lab.get("verdict"), "silver_valid": lab.get("valid"),
                "gold_verdict": g.get("gold_verdict"), "gold_valid": g.get("gold_valid"),
                "haiku_verdict": g.get("haiku_verdict"), "judge_model": lab.get("judge_model"),
            }) + "\n")

    # distributions
    def dist(rows, field):
        return dict(Counter(r["meta"][field] for r in rows))
    decision_dist = dict(Counter(r["meta"]["decision"] for r in train_pool))
    verdict_dist = dict(Counter(r["meta"]["silver_verdict"] for r in train_pool))
    source_dist = dict(Counter(r["meta"]["source"] for r in train_pool))
    judge_dist = dict(Counter(r["meta"]["judge_model"] for r in train_pool))
    reject_reasons = dict(Counter(r["meta"]["silver_verdict"] for r in train_pool
                                  if r["meta"]["decision"] == "reject"))

    stats = {
        "built_from_worklist": len(wl),
        "labeled_ok": len(wl) - errors, "judge_errors": errors,
        "corpus_yt_x": len(train_pool), "article_holdout": len(article_pool),
        "gold_human_seed": len(gold_seed),
        "train": len(train), "val": len(val), "gold_overlap": len(gold_rows),
        "decision_dist": decision_dist, "verdict_dist": verdict_dist,
        "source_dist": source_dist, "judge_model_dist": judge_dist,
        "reject_reason_dist": reject_reasons,
        "train_decision": dist(train, "decision"), "val_decision": dist(val, "decision"),
        "silver_vs_gold": {
            "n": n_pair, "agreement": round(po, 4), "kappa": round(kappa, 4),
            "silver_precision_vs_gold": round(prec, 4),
            "silver_recall_vs_gold": round(rec, 4),
            "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
            "silver_valid_rate": round(ps, 4), "gold_valid_rate": round(pg, 4),
            "by_source": by_src,
            "false_ok_by_silver_verdict": false_ok,
            "false_reject_by_silver_verdict": false_reject,
        },
    }
    with open(STATS, "w") as f:
        json.dump(stats, f, indent=2)
    write_labels_md(stats)
    print(json.dumps(stats, indent=2), flush=True)
    print(f"\nWROTE: {TRAIN} {VAL} {GOLD_OVERLAP} {STATS} {LABELS_MD}", flush=True)


def write_labels_md(s: dict):
    sg = s["silver_vs_gold"]
    md = f"""# Fine-tune corpus — labels & honesty check (2026-06-21)

Replacement for the Haiku/Sonnet **YouTube + X** prediction classifier. Built by
`finetune_corpus_builder.py` (committed). Data files (`*.jsonl`) are NOT committed —
they live here and in Drive `eidolum.prompts/`.

## Task framing (per-candidate)
- **input**: a YouTube transcript window (~{WINDOW} chars, centered on the stored quote)
  or a full tweet, plus the **candidate ticker**. No stored fields are placed in the
  input, so there is no answer leakage — the model must read the source.
- **output**: `{{"decision":"predict",ticker,direction,target,timeframe,conviction}}`
  for a genuine forward call, else `{{"decision":"reject","reject_reason":<class>}}`.
- Labels are **silver** (`claude -p`, primary `{PRIMARY}` / fallback `{FALLBACK}`),
  honoring Nimrod's locked rules (hedged→reject even with a number; conditionals
  accepted; vague-preference→reject; bare stance→valid; wrong target alone ≠ invalid).

## Counts
- worklist rows: **{s['built_from_worklist']}**  (judge errors dropped: {s['judge_errors']})
- YouTube+X corpus: **{s['corpus_yt_x']}**  → train **{s['train']}** / val **{s['val']}** (90/10 stratified by source×decision)
- article coverage holdout (kept OUT of train/val): **{s['article_holdout']}**
- gold overlap judged (NOT in train/val): **{s['gold_overlap']}**
- **`gold_human_seed.jsonl`**: **{s['gold_human_seed']}** rows with HUMAN-gold validity labels (the
  cleanest data here; see contamination caveat #6 before using to evaluate).

## Files
- `train.jsonl` / `val.jsonl` — the silver corpus (YouTube+X), chat-format messages + meta.
- `gold_human_seed.jsonl` — 200 human-labeled rows, same format (highest quality).
- `gold_overlap.jsonl` — per-row silver vs gold for the honesty check.
- `article_holdout.jsonl` — labeled article stratum, excluded from train/val.
- `silver_labels.jsonl` / `worklist.jsonl` — raw judge checkpoint + sampled inputs.
- `stats.json` — every number below, machine-readable.

## Type distribution (train+val pool)
- decision: `{s['decision_dist']}`
- source: `{s['source_dist']}`
- silver verdict: `{s['verdict_dist']}`
- reject reasons: `{s['reject_reason_dist']}`
- judge model used: `{s['judge_model_dist']}`

## Silver-vs-gold agreement (the honesty check, n={sg['n']})
| metric | value |
|---|---|
| validity agreement | **{sg['agreement']*100:.1f}%** |
| Cohen's κ (validity) | {sg['kappa']:.3f} |
| silver precision vs gold | {sg['silver_precision_vs_gold']*100:.1f}% |
| silver recall vs gold | {sg['silver_recall_vs_gold']*100:.1f}% |
| confusion (tp/fp/fn/tn) | {sg['confusion']} |
| silver valid-rate / gold valid-rate | {sg['silver_valid_rate']*100:.1f}% / {sg['gold_valid_rate']*100:.1f}% |
| by source | {sg['by_source']} |

**Where silver disagrees with gold:**
- **false-OK** (silver said valid, human said INVALID — the damaging direction):
  `{sg['false_ok_by_silver_verdict']}`
- false-reject (silver killed a human-valid call): `{sg['false_reject_by_silver_verdict']}`

**HEADLINE (honest):** silver-vs-gold validity agreement ≈ **{sg['agreement']*100:.0f}%**, vs the
**Haiku bar of 61.5%** (GOLD_FINDINGS.md). The silver Sonnet judge **reproduces the same
false-OK bias gold exposed in Haiku** — it passes non-predictions (holdings, DCF/intrinsic-value
computations, "I'd buy only if it dropped to $X" soft stances) as OK. Recall vs gold is high but
precision is low: the judge rarely kills a real call, but it over-accepts. **This corpus is a
baseline, not training-grade as-is** — fine-tuning on it would bake in the over-accept bias.

## Path to training-grade (non-circular)
1. A stricter v2 judge that requires a *committed forward directional call* (reject pure
   valuation/ownership/conditional-interest). Faithful to the locked rules, not fit to gold.
2. Human adjudication of the **OK bucket** (the weak spot: where false-OKs concentrate).
3. **Validate any v2 judge on a FRESH human gold sample** — the current 200 are now "seen"
   (this analysis read their disagreements), so re-scoring v2 on them would be circular.
4. Use `gold_human_seed.jsonl` (200 human-labeled) as a high-quality anchor / few-shot set.

## Circularity / bias caveats (read before training)
1. **Accepted-only negatives.** The corpus is drawn from *visible* predictions —
   rows the existing classifier already ACCEPTED. The "reject" examples are only the
   subset the silver judge flags among accepted rows; the corpus contains **no true
   upstream negatives** (transcript spans the old classifier correctly skipped). A
   model trained here learns the *per-candidate accept/reject + extraction* decision,
   NOT raw span detection from scratch.
2. **Silver is an LLM distilling an LLM.** Labels come from Sonnet/Haiku, so corpus
   quality is capped by the agreement number above. Training on it reproduces the
   judge's biases, not ground truth.
3. **Shared-lineage inflation.** The silver judge shares rule lineage with the
   classifier that produced the rows; agreement may overstate correctness where both
   share a blind spot (e.g. false-OK non-predictions — the very leak gold exposed:
   the Haiku OK bucket was only 46% gold-valid).
4. **Single human labeler** defines gold; the 200 are stratified (raw 39.5% valid),
   and the dominant class CI is wide. Treat the agreement % as directional, not exact.
5. **Article excluded** from train/val by design (structured analyst feed, not
   transcript classification, 0% of gold). Included only as a labeled coverage holdout.
6. **`gold_human_seed.jsonl` is for training/anchoring, NOT for evaluating a judge tuned on
   this work.** Its structured fields (direction/target/timeframe) are the *stored* values
   (human labeled only validity), so they carry the original classifier's extraction, not gold.

## Provenance
- visibility filter = the live `yt_visible_filter` + all six hide-flags (defaults ON).
- deterministic seeded sample (`SEED={SEED}`, `ORDER BY md5(id||seed)`), gold-200 ids excluded.
- gold source: `gt_gold` table + `groundtruth_2026_06_16/gold_verdicts_200.jsonl`.
"""
    with open(LABELS_MD, "w") as f:
        f.write(md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["sample", "judge", "build", "all"])
    a = ap.parse_args()
    if a.stage in ("sample", "all"):
        print("== SAMPLE ==", flush=True); stage_sample()
    if a.stage in ("judge", "all"):
        print("== JUDGE ==", flush=True); stage_judge()
    if a.stage in ("build", "all"):
        print("== BUILD ==", flush=True); stage_build()


if __name__ == "__main__":
    main()

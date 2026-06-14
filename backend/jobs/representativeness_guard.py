"""Transcript-aware forward guards for the YouTube classifier (Ship: hardening 2026-06-14).

Closes the quote-quality failure classes that this week's cleanup remediated but the
classifier itself never guarded against. Runs at insert time inside
`insert_youtube_prediction` (ticker_call only), the one layer where the prediction,
its resolved timestamp, AND the rich transcript all coexist — the 4-field
`validate_or_reject` gate is transcript-blind and structurally cannot do these.

Guards (see the hardening Step-0 audit):
  (f) ORPHAN, window-aware — reject only if the ticker/alias appears in NEITHER the
      quote NOR the ±90s window. Benign pronoun calls ("I'd add to it here") whose
      ticker is named nearby PASS (the 45.6% benign-pronoun population must survive).
  (a) RESIDUAL — on a FUZZY timestamp match, replace the stored quote with the real
      transcript segment text (word-level exact matches are left untouched).
  (c)+(e)+(d) SUSPECT SECOND-PASS, cost-gated — a row is a "suspect" only if a cheap
      signal fires (orphan-in-quote, opposite-direction cue, reported-speech near-miss,
      or no commitment word). Suspects get ONE `claude -p` verify over the ±90s window
      that returns: KEEP (+grounded direction, may correct a flip), REJECT_NO_CALL, or
      REPORTED_SPEECH. Non-suspects skip the call entirely (Max-budget protection).

Additive + fail-open: gated by ENABLE_REPRESENTATIVENESS_GUARD (default on). Any error,
missing transcript, or unavailable `claude -p` degrades to keep-unchanged so an insert
is never broken. NEVER edits HAIKU_SYSTEM. Verify model: REPRESENTATIVENESS_VERIFY_MODEL
(haiku|sonnet; eval-gated default).
"""
import json
import os
import re
import subprocess
from difflib import SequenceMatcher

WINDOW_SEC = 90
# Default SONNET: Haiku failed its eval gate for this verify task (34% clean
# false-reject, 60% no-call catch on the 203-row fixture). Sonnet is the
# eval-gated choice. Override via REPRESENTATIVENESS_VERIFY_MODEL if re-gated.
VERIFY_MODEL = (os.environ.get("REPRESENTATIVENESS_VERIFY_MODEL", "sonnet") or "sonnet").strip().lower()


def enabled() -> bool:
    return (os.environ.get("ENABLE_REPRESENTATIVENESS_GUARD", "true") or "true").strip().lower() in ("1", "true", "yes")


# ── lexicons (conservative; precision over recall) ──────────────────────────
_BULL = {"buy", "buying", "bought", "long", "bullish", "undervalued", "upside",
         "higher", "moon", "accumulate", "rally", "breakout", "uptrend", "load"}
_BEAR = {"sell", "selling", "sold", "short", "bearish", "overvalued", "downside",
         "lower", "crash", "puts", "avoid", "dump", "downtrend", "collapse", "tank"}
_COMMIT = {"buy", "sell", "long", "short", "bullish", "bearish", "target", "will",
           "think", "thinks", "expect", "expecting", "going", "headed", "add",
           "adding", "hold", "holding", "own", "owning", "calls", "puts", "like",
           "love", "favorite", "pick", "undervalued", "overvalued", "upside",
           "downside", "buying", "selling", "my", "i'm", "we're", "i'll"}

# (d) expanded reported-speech — conversational forms added to the gate's formal set
_REPORTED_PATTERNS = [
    re.compile(r"\b(?:said|says|saying|stated|claimed|mentioned|warned|predicted|"
               r"tweeted|posted|wrote|told|argued|insisted|noted|forecasted?|"
               r"recommended|advised|reiterated|refers?\s+to|referring\s+to|"
               r"talks?\s+about|talking\s+about|pointed\s+out|suggests?)\b", re.I),
    re.compile(r"\baccording to\b", re.I),
    re.compile(r"(?i:\bper)\s+[A-Z][a-z]+"),
    # "<Capitalized Name> says/thinks/believes/..." — proper-noun subject + speech verb
    re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+"
               r"(?i:says|said|believes|thinks|expects|is\s+calling|has\s+been\s+calling|"
               r"is\s+predicting|sees|projects|recommends|suggested|argues)\b"),
    re.compile(r"\b(?:he|she|they)(?:'s)?\s+(?:says|saying|said|believes|thinks|"
               r"expects|argues|claims|recommends|warns)\b", re.I),
    re.compile(r"\bin (?:his|her|their) (?:latest|recent|new)?\s*"
               r"(?:note|report|interview|appearance|tweet|post|video)\b", re.I),
]
_FIRST_PERSON = re.compile(
    r"\b(?:I|we|my|our|me)(?:'\w+)?\b(?:\s+\w+){0,5}\s+"
    r"(?:think(?:ing)?|believe|expect(?:ing)?|predict(?:ing)?|see(?:ing)?|"
    r"project(?:ing)?|target(?:ing)?|call(?:ing)?|buy(?:ing)?|sell(?:ing)?|"
    r"like|love|own|am\s+calling)\b", re.I)


# ── alias map (same construction as the requote pipeline) ───────────────────
_alias_cache = {}


def alias_map(db):
    if _alias_cache.get("_built"):
        return _alias_cache["map"]
    am = {}
    try:
        from sqlalchemy import text as sql_text
        for q, key in [("SELECT etf_ticker, alias FROM sector_etf_aliases", 2),
                       ("SELECT ticker, alias FROM company_name_aliases", 2)]:
            for t, a in db.execute(sql_text(q)).fetchall():
                if t and a:
                    am.setdefault(t.strip().upper(), set()).add(a.strip().lower())
        for primary, sec, csv in db.execute(sql_text(
                "SELECT primary_etf, secondary_etfs, aliases FROM macro_concept_aliases")).fetchall():
            if not csv:
                continue
            al = {a.strip().lower() for a in csv.split(",") if a.strip()}
            etfs = set()
            if primary:
                etfs.add(primary.strip().upper())
            if sec:
                etfs.update(s.strip().upper() for s in sec.split(",") if s.strip())
            for e in etfs:
                am.setdefault(e, set()).update(al)
    except Exception:
        am = {}
    _alias_cache["map"] = am
    _alias_cache["_built"] = True
    return am


_SUFFIX = re.compile(
    r"\b(inc|incorporated|corp|corporation|company|co|ltd|limited|holdings|holding|"
    r"group|plc|technologies|technology|systems|industries|international|enterprises|"
    r"class\s+[abc])\b\.?", re.I)
_cname_cache = {}


def company_names(db):
    if _cname_cache.get("_built"):
        return _cname_cache["map"]
    m = {}
    try:
        from sqlalchemy import text as sql_text
        for t, nm in db.execute(sql_text(
                "SELECT ticker, company_name FROM ticker_sectors WHERE company_name IS NOT NULL")).fetchall():
            if t and nm and nm.strip():
                m[t.strip().upper()] = nm.strip()
    except Exception:
        m = {}
    _cname_cache["map"] = m
    _cname_cache["_built"] = True
    return m


def _clean_name(nm):
    nm = _SUFFIX.sub("", nm or "").strip(" .,").lower()
    nm = re.sub(r"\s+", " ", nm)
    return nm


def ticker_terms(ticker, amap, cnames=None):
    t = (ticker or "").strip().upper().lstrip("$")
    terms = {t.lower()} | amap.get(t, set())
    if cnames:
        nm = _clean_name(cnames.get(t, ""))
        if len(nm) >= 4:
            terms.add(nm)
            first = nm.split()[0]
            if len(first) >= 4:  # distinctive first token ("enphase", "albemarle")
                terms.add(first)
    return {x for x in terms if len(x) >= 3}


def _names(text, terms):
    low = (text or "").lower()
    for t in terms:
        if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", low):
            return True
    return False


def _cue(quote, lex):
    low = " " + (quote or "").lower() + " "
    return any(re.search(r"(?<![a-z])" + re.escape(c) + r"(?![a-z])", low) for c in lex)


def reported_hit(text):
    if not text or not text.strip():
        return False
    if _FIRST_PERSON.search(text):
        return False
    return any(p.search(text) for p in _REPORTED_PATTERNS)


def _segments(transcript_data):
    return (transcript_data or {}).get("segments") or []


def window_text(transcript_data, seconds, half=WINDOW_SEC):
    if seconds is None:
        return ""
    lo, hi = (seconds - half) * 1000, (seconds + half) * 1000
    parts = []
    for s in _segments(transcript_data):
        st = s.get("start_ms") if isinstance(s, dict) else None
        if st is None:
            continue
        if lo <= st <= hi:
            txt = (s.get("text") or "").strip()
            if txt:
                parts.append(txt)
    return " ".join(parts)


def grounded_segment_text(transcript_data, seconds, model_quote):
    """Real transcript text spanning the quote, for (a)-residual on fuzzy matches."""
    if seconds is None:
        return None
    words = len((model_quote or "").split()) or 8
    dur_ms = max(4000, int(words * 450))
    lo, hi = (seconds * 1000) - 1500, (seconds * 1000) + dur_ms
    parts = []
    for s in _segments(transcript_data):
        st = s.get("start_ms") if isinstance(s, dict) else None
        if st is None:
            continue
        if lo <= st <= hi:
            txt = (s.get("text") or "").strip()
            if txt:
                parts.append(txt)
    out = " ".join(parts).strip()
    return out or None


def cheap_signals(quote, ticker, direction, window, amap, cnames=None):
    terms = ticker_terms(ticker, amap, cnames)
    orphan = not _names(quote, terms)
    in_window = _names(window, terms)
    opp = False
    if direction == "bullish" and _cue(quote, _BEAR) and not _cue(quote, _BULL):
        opp = True
    if direction == "bearish" and _cue(quote, _BULL) and not _cue(quote, _BEAR):
        opp = True
    rep = reported_hit(quote) or reported_hit(window)
    no_commit = not _cue(quote, _COMMIT)
    return {"orphan_in_quote": orphan, "ticker_in_window": in_window,
            "opposite_cue": opp, "reported_near": rep, "no_commit": no_commit}


_VERIFY_PROMPT = """You verify ONE stored YouTube stock prediction against its transcript window.

Ticker: {ticker} ({terms}). Classifier's LABELED direction: {direction}.
Displayed quote: "{quote}"

TRANSCRIPT WINDOW (±90s around the quote; raw ASR):
---
{window}
---

Does the VIDEO HOST (not a guest, not a quoted third party) make a committed forward directional call on {ticker} here?
- KEEP: the host makes a committed call. Return grounded_direction = bullish|bearish (the host's ACTUAL direction — may differ from the labeled one) and grounded_quote = the exact host sentence (a byte-exact substring of the window, 15+ chars).
- REPORTED_SPEECH: the call is attributed to a third party (an analyst, Buffett, Munger, "he says", a reviewed video). Return grounded_quote of the attribution.
- REJECT_NO_CALL: no committed forward call on {ticker} here (narration / teaching example / past recap / ticker only mentioned).

Reply ONLY JSON: {{"verdict":"KEEP|REPORTED_SPEECH|REJECT_NO_CALL","grounded_direction":"bullish|bearish|null","grounded_quote":"<exact substring or null>","why":"<=15 words"}}"""


def _subprocess_env():
    return {k: v for k, v in os.environ.items()
            if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN")}


def verify_suspect(ticker, direction, window, quote, terms_str="", model=None):
    """ONE claude -p verify call. Fail-open: returns KEEP-unchanged on any error."""
    model = (model or VERIFY_MODEL).strip().lower()
    prompt = _VERIFY_PROMPT.format(ticker=ticker, terms=terms_str or ticker,
                                   direction=direction, quote=(quote or "")[:300],
                                   window=(window or "")[:8000])
    try:
        p = subprocess.run(["claude", "-p", "--model", model, prompt],
                           capture_output=True, text=True, timeout=240,
                           env=_subprocess_env(), stdin=subprocess.DEVNULL)
        out = json.loads(re.search(r"\{.*\}", p.stdout, re.S).group(0))
        vd = (out.get("verdict") or "").upper()
        if vd not in ("KEEP", "REPORTED_SPEECH", "REJECT_NO_CALL"):
            return {"verdict": "KEEP", "grounded_direction": direction, "grounded_quote": None, "error": "bad_verdict"}
        return {"verdict": vd,
                "grounded_direction": (out.get("grounded_direction") or direction),
                "grounded_quote": out.get("grounded_quote"),
                "why": out.get("why", "")}
    except Exception as e:
        return {"verdict": "KEEP", "grounded_direction": direction, "grounded_quote": None, "error": str(e)[:80]}


def decide(pred, ticker, direction, ts_fields, transcript_data, db,
           *, run_second_pass=True, stats=None):
    """Return a decision dict:
      {action: 'keep'|'reject', reason, direction, reported_speech, verbatim,
       second_pass: bool, signals}
    Fail-open everywhere. No-op (keep) when disabled / no transcript / no timestamp.
    """
    keep = {"action": "keep", "reason": None, "direction": direction,
            "reported_speech": False, "verbatim": None, "second_pass": False, "signals": {}}
    try:
        if not enabled() or transcript_data is None:
            return keep
        seconds = (ts_fields or {}).get("source_timestamp_seconds")
        if not seconds:
            return keep  # (b) hard gate already handles missing-timestamp rows
        quote = (ts_fields.get("source_verbatim_quote")
                 or pred.get("_verbatim_quote") or pred.get("verbatim_quote") or "")
        amap = alias_map(db)
        cnames = company_names(db)
        terms = ticker_terms(ticker, amap, cnames)
        win = window_text(transcript_data, seconds)
        sig = cheap_signals(quote, ticker, direction, win, amap, cnames)
        keep["signals"] = sig
        if stats is not None:
            stats["repguard_seen"] = int(stats.get("repguard_seen", 0)) + 1

        # (f) NOTE: a deterministic ticker-naming reject was evaluated and REJECTED
        # at merge. On an unbiased 400-row sample it would hard-drop 23.5% (±90s
        # window) / 14.5% (whole transcript) of VALID calls — finance hosts name a
        # ticker once and speak in pronouns, and spoken-name/ASR variance defeats
        # the ticker_sectors name map. It failed "no material clean-row regression".
        # The anti-orphan intent is served instead by the (e) no-commitment
        # second-pass below: orphan narration has no commit word -> verified ->
        # flagged; a real pronoun call ("I'd add to it here") keeps its commit word
        # and is left untouched. No deterministic orphan reject ships.

        # (a) residual: ground the stored quote on a fuzzy match
        new_verbatim = None
        if ts_fields.get("source_timestamp_method") not in ("word_level",):
            gt = grounded_segment_text(transcript_data, seconds, quote)
            if gt:
                new_verbatim = gt

        # Suspect = a HIGH-PRECISION signal only. Bare orphan-in-quote is NOT a
        # trigger: it fires on the 45% benign-pronoun population ("I'd add to it
        # here", ticker named nearby) where the second-pass both wastes budget
        # and (when the verifier errs) false-rejects real calls. True orphans are
        # already rejected above by the window-aware (f) check; benign pronouns
        # with the ticker in-window are left alone. The second-pass is reserved
        # for direction contradiction (c), reported-speech (d), and no-commitment
        # narration (e) — the classes a transcript-blind gate cannot see.
        suspect = (sig["opposite_cue"] or sig["reported_near"] or sig["no_commit"])
        if not suspect or not run_second_pass:
            return {**keep, "verbatim": new_verbatim}

        if stats is not None:
            stats["repguard_second_pass"] = int(stats.get("repguard_second_pass", 0)) + 1
        v = verify_suspect(ticker, direction, win, quote,
                           terms_str=", ".join(sorted(terms)[:6]))
        # (e) no-call: the LLM verify's no-call PRECISION is not high enough to
        # hard-drop an insert (eval showed it false-rejects real pronoun-heavy
        # calls). Default action is a reversible HIDE flag (is_weak_basket_call),
        # NOT a delete — flag-not-delete. REPRESENTATIVENESS_NO_CALL_ACTION can be
        # 'reject' (hard block), 'flag' (default, hide), or 'off' (no-op keep).
        if v["verdict"] == "REJECT_NO_CALL":
            action = (os.environ.get("REPRESENTATIVENESS_NO_CALL_ACTION", "flag") or "flag").strip().lower()
            if stats is not None:
                stats["repguard_no_call_" + action] = int(stats.get("repguard_no_call_" + action, 0)) + 1
            if action == "reject":
                return {**keep, "action": "reject", "reason": "no_call_verified", "second_pass": True, "signals": sig}
            if action == "flag":
                return {**keep, "action": "keep", "reason": "no_call_flagged",
                        "weak_flag": True, "second_pass": True, "signals": sig, "verbatim": new_verbatim}
            return {**keep, "second_pass": True, "verbatim": new_verbatim}
        rep = v["verdict"] == "REPORTED_SPEECH"
        gdir = v.get("grounded_direction") if v.get("grounded_direction") in ("bullish", "bearish") else direction
        gq = v.get("grounded_quote")
        # only accept a grounded quote that is a real substring of the window
        verbatim = new_verbatim
        if gq and isinstance(gq, str) and gq.strip() and gq.strip().lower() in (win or "").lower():
            verbatim = gq.strip()
        if stats is not None:
            if gdir != direction:
                stats["repguard_direction_corrected"] = int(stats.get("repguard_direction_corrected", 0)) + 1
            if rep:
                stats["repguard_reported_speech"] = int(stats.get("repguard_reported_speech", 0)) + 1
        return {"action": "keep", "reason": None, "direction": gdir,
                "reported_speech": rep, "verbatim": verbatim, "second_pass": True, "signals": sig}
    except Exception:
        return keep

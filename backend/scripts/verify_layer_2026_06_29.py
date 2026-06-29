"""Cost-gated LLM verify layer (2026-06-29). Handles the ANCHORED junk the deterministic
reject_judge can't safely catch + the 168 deferred reported/hedged suspects. Deterministic
SUSPECT gate (cheap) -> one claude -p Sonnet verify per suspect (locked rubric) -> reject
ONLY confirmed junk. Flag-not-delete, reversible. EVAL-GATE on gt_gold before any apply.

Suspect = still-visible youtube/x row matching a pattern the verify should adjudicate:
  reported  : mentions analyst/firm/rank (incl. own-thesis-that-mentions-one -> verify KEEPs)
  hedged    : a hedge phrase in the quote (incl. rhetorical -> verify KEEPs)
  dir_mismatch: stored direction contradicts the quote's directional cue
  conditional : "if/when/as long as" gating structure
  vague_year  : the only number-anchor is a bare 20xx year (no $ / % / level)
Everything numeric+directional+committed that matches NONE is auto-KEPT (no LLM call).
"""
import os, re, sys, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.reject_rules_judge_2026_06_29 import REPORTED, HEDGE, has_anchor
from jobs.representativeness_guard import _BULL, _BEAR, _cue, _COND_RX, _FIRST_PERSON

VERIFY_MODEL = os.environ.get("VERIFY_LAYER_MODEL", "sonnet")
_YEAR = re.compile(r"\b20\d\d\b")
_DOLLAR_PCT = re.compile(r"\$\s?\d|\d+\s?%")


def suspect_kinds(row):
    """Return the set of suspect patterns this still-visible row matches (cost-gate)."""
    q = row.get("quote") or ""
    d = (row.get("direction") or "").strip().lower()
    kinds = []
    if REPORTED.search(q):
        kinds.append("reported")
    if HEDGE.search(q):
        kinds.append("hedged")
    if d == "bullish" and _cue(q, _BEAR) and not _cue(q, _BULL): kinds.append("dir_mismatch")
    if d == "bearish" and _cue(q, _BULL) and not _cue(q, _BEAR): kinds.append("dir_mismatch")
    if _COND_RX.search(q):
        kinds.append("conditional")
    if has_anchor(q) and _YEAR.search(q) and not _DOLLAR_PCT.search(q) and not re.search(r"\b\d{2,}\b", _YEAR.sub("", q)):
        kinds.append("vague_year")
    return kinds


_RUBRIC = """You are the final quality gate for a stored stock prediction shown to users. Decide KEEP or REJECT
using the LOCKED rules. Bias: when in doubt, KEEP — a wrongly-hidden real call is the worst outcome.

Ticker: {ticker}. Stored direction: {direction}.
Stored quote: "{quote}"

REJECT only if the quote is clearly one of:
  - ANALYST/THIRD-PARTY RELAY: the call is attributed to an analyst/firm/rank/another person and the speaker
    adds NO own conviction ("Citizens initiated coverage", "Wall St target 29", "he says"). BUT an OWN thesis
    that merely MENTIONS an analyst/target is KEEP ("I'm bullish; analysts also see upside").
  - REAL HEDGE / NO-CONVICTION: an explicitly hedged musing with no committed view ("could go either way",
    "who knows", "maybe, maybe not"). A RHETORICAL phrase is KEEP ("no idea why people sleep on it", "50/50"
    used for market share, a confident call that happens to contain a soft word).
  - WRONG / NON-COMMITTED DIRECTION: no committed SINGLE forward direction on {ticker} (calls both ways, or
    only narrates/teaches/recaps, or the stored direction plainly contradicts the quote).
  - NOT A GRADEABLE CALL: a conditional whose call does not stand on its own, a target mentioned only in
    passing (a P/E, market cap, someone else's level), or vague commentary with no real forward call.

KEEP if: a committed forward directional call with a real number/level or timeframe; an OPERATIONAL claim
(revenue/FCF/EPS/margin + value); an own thesis (even if it cites an analyst); a rhetorical soft phrase.

Reply ONLY JSON: {{"verdict":"KEEP|REJECT","reason":"analyst_relay|real_hedge|wrong_direction|not_gradeable|own_call|operational|committed","why":"<=15 words"}}"""


def _env():
    return {k: v for k, v in os.environ.items()
            if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")}


def verify(row, model=None):
    """One claude -p verify. Fail-open KEEP (never hide on error). -> (verdict, reason, why)."""
    model = model or VERIFY_MODEL
    prompt = _RUBRIC.format(ticker=row.get("ticker"), direction=row.get("direction"),
                            quote=(row.get("quote") or "")[:1200])
    try:
        p = subprocess.run(["claude", "-p", "--model", model, prompt], capture_output=True, text=True,
                           timeout=240, env=_env(), cwd="/tmp", stdin=subprocess.DEVNULL)
        low = (p.stdout + p.stderr).lower()
        if '"api_error_status":429' in low or "usage limit" in low:
            return ("KEEP", "ratelimit", "")   # caller may retry; never hide
        out = json.loads(re.search(r"\{.*\}", p.stdout, re.S).group(0))
        vd = (out.get("verdict") or "").upper().strip()
        if vd not in ("KEEP", "REJECT"):
            return ("KEEP", "bad_verdict", "")
        return (vd, out.get("reason", ""), out.get("why", ""))
    except Exception as e:
        return ("KEEP", "error", str(e)[:60])


VIS_YTX = ("source_type IN ('youtube','x') AND COALESCE(claim_type,'price')<>'operational' "
           "AND NOT (source_type='youtube' AND source_timestamp_seconds IS NULL) "
           "AND (conviction_level NOT IN ('hedged','hypothetical') OR conviction_level IS NULL) "
           "AND COALESCE(is_reported_speech,FALSE)=FALSE AND COALESCE(is_ambiguous_symbol,FALSE)=FALSE "
           "AND COALESCE(is_weak_basket_call,FALSE)=FALSE AND COALESCE(is_holding_disclosure,FALSE)=FALSE "
           "AND COALESCE(is_no_claim,FALSE)=FALSE AND COALESCE(is_no_gradeable_claim,FALSE)=FALSE")


if __name__ == "__main__":
    import collections
    from database import BgSessionLocal
    from sqlalchemy import text as sql
    db = BgSessionLocal()
    rows = db.execute(sql(f"""SELECT id, ticker, direction,
       COALESCE(NULLIF(source_verbatim_quote,''),exact_quote,context,'') quote
       FROM predictions WHERE {VIS_YTX}""")).mappings().all()
    by = collections.Counter(); suspects = 0
    for r in rows:
        k = suspect_kinds(dict(r))
        if k:
            suspects += 1
            for x in k: by[x] += 1
    print(f"still-visible YT+X non-operational: {len(rows)}")
    print(f"SUSPECTS (get an LLM call): {suspects}  ({100*suspects/len(rows):.1f}%)")
    print(f"by kind (rows may match >1): {dict(by)}")

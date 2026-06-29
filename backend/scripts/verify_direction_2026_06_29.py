"""Direction-correction layer (2026-06-29). Fixes rows whose stored bull/bear direction
CONTRADICTS the quote, so real calls score correctly (fix, don't hide). MUTATES scoring ->
maximal conservatism: flip ONLY unambiguous, high-confidence contradictions; default no-flip.
EVAL-GATE on gt_gold first (false-flip MUST be ~0 — a wrong flip corrupts a real score).

Candidate = dir_mismatch suspect (stored direction contradicts the quote's directional cue),
still-visible YT+X. One claude -p Sonnet judge per candidate. claude -p on Max.
"""
import os, re, sys, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODEL = os.environ.get("DIR_MODEL", "sonnet")

_RUBRIC = """Determine the TRUE forward direction the SPEAKER expresses ON the ticker {ticker} in this quote.

Stored direction (may be wrong): {direction}
Quote: "{quote}"

Output the speaker's actual directional view ON {ticker}: bullish (expects up / buy / long / undervalued),
bearish (expects down / sell / short / avoid / overvalued), or neutral (no clear single direction).

Then CLASSIFY vs the stored direction:
  CONFIRMED_CONTRADICTION: the quote UNAMBIGUOUSLY expresses the OPPOSITE of the stored direction on {ticker}
    — e.g. stored bullish but the speaker is shorting / says it crashes / says avoid; stored bearish but the
    speaker is buying / says it rips. Use ONLY when you are highly confident the stored direction is simply wrong.
  AGREES: the quote's direction matches the stored direction.
  AMBIGUOUS: mixed/both-ways, unclear, neutral, about a DIFFERENT ticker, or you cannot tell with confidence.

CRITICAL — do NOT infer direction from a bare PRICE LEVEL / target / fair-value number ("to $0.30",
"worth $620", "fair value $X", "PT $X"). Whether a level implies up or down depends on the CURRENT price,
which you usually do NOT have — so a level is NEVER a confirmed contradiction (-> AMBIGUOUS). Base
CONFIRMED_CONTRADICTION ONLY on an EXPLICIT directional word/stance on {ticker} that plainly opposes the
stored direction: buy/sell, long/short, bullish/bearish, "going up/down", crash/rip, avoid, "I'm shorting",
undervalued/overvalued. ("undervalued"=bullish, "overvalued"=bearish.)

DECISIVE BIAS — a wrong flip corrupts a real forecaster score (worse than doing nothing). When there is ANY
plausible reading under which the stored direction is defensible, choose AGREES or AMBIGUOUS — NOT
CONFIRMED_CONTRADICTION. Confirm a contradiction only for a clear, explicit opposite directional STANCE on {ticker}.

Reply ONLY JSON: {{"true_direction":"bullish|bearish|neutral","classification":"CONFIRMED_CONTRADICTION|AGREES|AMBIGUOUS","confidence":"high|medium|low","evidence":"<exact phrase>","why":"<=15 words"}}"""


def _env():
    return {k: v for k, v in os.environ.items()
            if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")}


def judge(row, model=None):
    """-> dict {true_direction, classification, confidence, evidence, why}. Fail-open AGREES."""
    model = model or MODEL
    prompt = _RUBRIC.format(ticker=row.get("ticker"), direction=row.get("direction"),
                            quote=(row.get("quote") or "")[:1200])
    try:
        p = subprocess.run(["claude", "-p", "--model", model, prompt], capture_output=True, text=True,
                           timeout=240, env=_env(), cwd="/tmp", stdin=subprocess.DEVNULL)
        low = (p.stdout + p.stderr).lower()
        if '"api_error_status":429' in low or "usage limit" in low:
            return {"classification": "AGREES", "confidence": "low", "reason": "ratelimit"}
        out = json.loads(re.search(r"\{.*\}", p.stdout, re.S).group(0))
        return out
    except Exception as e:
        return {"classification": "AGREES", "confidence": "low", "reason": "error:" + str(e)[:50]}


def should_flip(row, j):
    """Flip ONLY a high-confidence unambiguous contradiction to a real bull/bear direction."""
    td = (j.get("true_direction") or "").lower()
    return (j.get("classification") == "CONFIRMED_CONTRADICTION"
            and (j.get("confidence") or "").lower() == "high"
            and td in ("bullish", "bearish")
            and td != (row.get("direction") or "").lower())

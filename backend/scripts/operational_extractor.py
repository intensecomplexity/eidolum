"""Operational-claim extractor (PHASE 2) — tags a single (ticker, quote) as a PRICE
prediction or an OPERATIONAL prediction about a company's reported financials, and for
operational claims pulls {metric, metric_kind, target_value, target_period, direction}.

Runs headless `claude -p` (Sonnet) billed to the Max plan (API-routing env scrubbed,
empty cwd so no CLAUDE.md leaks in) — the SAME invocation cc_recover_classifier_errors.py
uses. This is a STANDALONE re-extraction pass: it does NOT modify the live price-extraction
prompt (build_cc_prompt), so price extraction cannot regress. It only ADDS the operational
tag, used by the backfill (PHASE 5) and the eval gate.

Output JSON per call:
  {"claim_type":"price"|"operational"|"not_a_prediction",
   "metric": <revenue|free_cash_flow|eps_diluted|net_income|gross_margin|operating_margin|net_margin|null>,
   "metric_kind":"absolute"|"growth_pct"|"cagr"|"direction"|null,
   "target_value": <number|null>, "target_period": <"FY2027"|"Q2-2026"|"+5y"|null>,
   "direction":"bullish"|"bearish"|null}
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time

_CWD = tempfile.mkdtemp(prefix="op_extract_cwd_")  # empty => claude -p finds no CLAUDE.md


def _claude_bin() -> str:
    return os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "claude"


def _subprocess_env() -> dict:
    env = dict(os.environ)
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
              "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "AWS_BEARER_TOKEN_BEDROCK"):
        env.pop(k, None)
    return env


PROMPT = """You classify ONE stock-related statement, for the TICKER given, as a PRICE
prediction or an OPERATIONAL prediction about the company's reported financials. Return
STRICT JSON only — no prose, no markdown.

PRICE = any claim about the STOCK's price / return / chart: a price target, "% upside",
entry-stop-target levels, "goes higher / lower", a fair value PER SHARE, a buy price.
Tag these claim_type="price" (this engine does not grade them here).

OPERATIONAL = a forward claim about the company's REPORTED FINANCIAL metric, one of:
  revenue | free_cash_flow | eps_diluted | net_income | gross_margin | operating_margin | net_margin
with a specific target. metric_kind:
  absolute   - a level: "FCF reaches $133B", "revenue of $50B", "net margin of 25%"
  growth_pct - a single-period % change: "revenue up 90-110%", "grows 30%", "double" (=100)
  cagr       - an annualised multi-year rate: "10-12% revenue CAGR through 2027"
  direction  - only up/down, no number: "cash flows decline next quarter"

target_value units: dollars IN FULL (133 billion -> 133000000000); percentages as plain
numbers (90-110% -> use the midpoint 100; "double" -> 100; "triple" -> 200); a margin level
as its percent (25% -> 25); null for metric_kind="direction". For a RANGE use the midpoint.
target_period: "FY2027" / "Q2-2026"; if only a relative horizon is given use "+Ny"
("over the next 5 years" -> "+5y", "next year" -> "+1y").

RULES
- claim_type="operational" ONLY if it names/implies one of the 7 metrics AND gives a target
  (a number, or a clear up/down for metric_kind=direction).
- A stock price / return / chart-level claim is "price" even when fundamentals are the
  rationale ("services margin 75%, so it hits $250" -> price; the $250 is the claim).
- COMPANY GUIDANCE about its OWN financial metric counts as operational even when the speaker
  relays it ("management guided revenue up 30%", "they expect FCF to double", "Bill said we're
  confident revenue more than doubles next year") -> extract it; the company's own outlook is
  exactly what we grade against reported actuals.
- EXCLUDE as "not_a_prediction" only: (i) a STOCK-PRICE target attributed to anyone — incl. a
  CEO or analyst price target like "$45-55 a share" (that is a price, NOT one of the 7 metrics);
  (ii) a sell-side ANALYST/FIRM metric estimate the speaker merely repeats without endorsing.
- Vague operational talk with no metric+value ("great margins", "I like the business",
  "undervalued") -> "not_a_prediction".
- direction: set "direction":"bearish" for decline/fall/drop, "bullish" for grow/rise/expand.

Return exactly:
{"claim_type":"...","metric":...,"metric_kind":...,"target_value":...,"target_period":...,"direction":...}

TICKER: __TICKER__
STATEMENT: __QUOTE__
"""


def _run_claude(prompt: str, model: str = "sonnet", timeout: int = 300):
    cmd = [_claude_bin(), "-p", "--output-format", "json", "--model", model,
           "--strict-mcp-config", "--no-session-persistence"]
    env = _subprocess_env()
    for _attempt in range(3):
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                                  cwd=_CWD, env=env, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, f"timeout_{timeout}s"
        low = ((proc.stdout or "") + (proc.stderr or "")).lower()
        if '"api_error_status":429' in low or "usage limit" in low or "limit reached" in low:
            time.sleep(60)
            continue
        if proc.returncode != 0:
            return None, f"claude_exit_{proc.returncode}: {(proc.stderr or '')[:200]}"
        try:
            env_obj = json.loads(proc.stdout)
        except Exception as e:
            return None, f"envelope_unparseable: {e}"
        if env_obj.get("is_error"):
            return None, f"is_error: {str(env_obj.get('result'))[:200]}"
        return env_obj.get("result") or "", None
    return None, "retries_exhausted"


def _parse(text: str):
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s).strip()
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def extract_operational(ticker: str, quote: str, model: str = "sonnet"):
    """Return the parsed extraction dict (with an '_error' key on failure)."""
    prompt = PROMPT.replace("__TICKER__", str(ticker)).replace("__QUOTE__", (quote or "").strip()[:1500])
    text, err = _run_claude(prompt, model=model)
    if err:
        return {"_error": err}
    obj = _parse(text)
    if obj is None:
        return {"_error": "unparseable", "_raw": (text or "")[:200]}
    obj.setdefault("claim_type", None)
    return obj

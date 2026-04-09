"""
Groq Layer 3 classifier eval.

Runs a set of pre-labeled tweets through Groq llama-3.3-70b-versatile
and reports accuracy vs ground truth. Uses the Groq free tier.

Usage:
    railway run python3 backend/scripts/groq_layer3_eval.py

Requires: GROQ_API_KEY env var (set in Railway worker env).

This script does NOT touch the production X scraper. It is a one-shot
manual eval, never imported by worker.py, never scheduled. Reads its
testset from backend/scripts/groq_layer3_testset.json (gitignored)
and writes results to backend/scripts/groq_layer3_eval_results.json
(also gitignored).
"""
import json
import os
import time
from pathlib import Path

import httpx

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"

# Sanity check — presence only, never print the value
if not GROQ_API_KEY:
    raise SystemExit("GROQ_API_KEY missing from env")
print(f"[groq-eval] GROQ_API_KEY present (len={len(GROQ_API_KEY)})")

# Concise prompt — Groq Llama 3.3 70B is smart enough to handle a short
# spec. Target ~600 tokens; Haiku's prompt is ~3,630 tokens.
GROQ_SYSTEM = """You are classifying tweets from financial Twitter for Eidolum, a prediction accountability platform.

Your job: decide if a tweet contains a TESTABLE prediction about a stock, crypto, sector, or the broader market, and if so, extract the key fields.

ACCEPT as prediction:
- Ticker + direction: "$NVDA going to $200 by EOY", "AAPL looks weak here"
- Position disclosure: "I'm long SITM", "just added to my GLW position"
- Target hit: "$GLW hit my $160 target, taking profits" (still a prediction — retrospective accept)
- Sector calls with clear direction: "semiconductors are going to crash", "banks will rally into earnings"
- Macro calls with market impact: "recession coming in Q3, shorting SPY"
- Analyst rating changes / price targets / Buy/Sell calls on a named ticker
- Options flow / dark pool signals on a named ticker with strike or direction

REJECT:
- Pure commentary without direction: "interesting chart on NVDA"
- Political/geopolitical news with no market angle: "Trump meets Netanyahu"
- Questions: "is $TSLA a buy here?"
- Retweets/quote tweets with no added view
- Emoji-only, greetings, "gm", "gn", jokes
- Chart screenshots with only "watching this" or similar
- News reports with no directional claim about a tradeable instrument

When a tweet is borderline, LEAN TOWARD ACCEPTING if there's a clear ticker AND a clear direction — better to over-catch than miss real calls.

Output STRICT JSON only. No prose before or after. Schema:
{
  "is_prediction": true|false,
  "ticker_or_sector": "NVDA"|"semiconductors"|null,
  "direction": "bullish"|"bearish"|"neutral"|null,
  "target_price": 200.0|null,
  "timeframe": "1d"|"1w"|"1m"|"3m"|"6m"|"1y"|null,
  "confidence": "high"|"medium"|"low",
  "reasoning": "one sentence why"
}"""


def classify(tweet_text: str) -> dict:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": GROQ_SYSTEM},
            {"role": "user", "content": tweet_text},
        ],
        "temperature": 0.1,
        "max_tokens": 300,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(GROQ_URL, json=payload, headers=headers)

    if resp.status_code != 200:
        return {
            "_success": False,
            "_error": f"http_{resp.status_code}",
            "_body": resp.text[:500],
        }

    data = resp.json()
    usage = data.get("usage", {})
    content = None
    try:
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        parsed["_success"] = True
        parsed["_tokens_in"] = usage.get("prompt_tokens", 0)
        parsed["_tokens_out"] = usage.get("completion_tokens", 0)
        return parsed
    except (KeyError, json.JSONDecodeError, TypeError) as e:
        return {
            "_success": False,
            "_error": f"parse_error: {e}",
            "_raw": (content or "no content")[:500],
        }


def main():
    testset_path = Path(__file__).parent / "groq_layer3_testset.json"
    if not testset_path.exists():
        raise SystemExit(f"testset not found at {testset_path}")

    with testset_path.open() as f:
        testset = json.load(f)

    print(f"[groq-eval] loaded {len(testset)} labeled tweets")
    print(f"[groq-eval] model: {MODEL}")
    print(f"[groq-eval] starting eval...\n")

    results = []
    correct_accept = 0
    correct_reject = 0
    false_accept = 0   # Groq said yes, we said no
    false_reject = 0   # Groq said no, we said yes
    errors = 0
    total_tokens_in = 0
    total_tokens_out = 0
    start = time.time()

    for i, row in enumerate(testset, 1):
        text = row["text"]
        expected = row["expected_is_prediction"]
        handle = row.get("handle", "?")

        result = classify(text)

        actual = None
        if not result.get("_success"):
            errors += 1
            verdict = "ERROR"
        else:
            actual = bool(result.get("is_prediction", False))
            total_tokens_in += result.get("_tokens_in", 0)
            total_tokens_out += result.get("_tokens_out", 0)

            if expected and actual:
                correct_accept += 1
                verdict = "OK ACCEPT"
            elif not expected and not actual:
                correct_reject += 1
                verdict = "OK REJECT"
            elif expected and not actual:
                false_reject += 1
                verdict = "X FALSE REJECT"
            else:
                false_accept += 1
                verdict = "X FALSE ACCEPT"

        print(f"--- {i}/{len(testset)} --- @{handle}")
        print(f"tweet: {text[:200]}")
        print(f"expected: is_pred={expected}")
        if result.get("_success"):
            print(
                f"groq:     is_pred={actual} "
                f"ticker={result.get('ticker_or_sector')} "
                f"dir={result.get('direction')} "
                f"target={result.get('target_price')} "
                f"tf={result.get('timeframe')}"
            )
            print(f"reason:   {(result.get('reasoning') or '')[:160]}")
        else:
            print(f"groq:     {result.get('_error')}")
            if result.get("_raw"):
                print(f"raw:      {result.get('_raw')[:200]}")
            if result.get("_body"):
                print(f"body:     {result.get('_body')[:200]}")
        print(f"verdict:  {verdict}\n")

        results.append({
            "tweet_id": row.get("tweet_id"),
            "handle": handle,
            "expected": expected,
            "actual": actual,
            "verdict": verdict,
            "groq_response": result,
        })

        # Modest pacing for the free tier — 30 req/min budget on most Groq tiers.
        time.sleep(0.5)

    elapsed = time.time() - start
    total = len(testset)
    correct = correct_accept + correct_reject
    accuracy = (correct / total * 100) if total else 0

    print("=" * 60)
    print(f"GROQ LAYER 3 EVAL RESULTS - {MODEL}")
    print("=" * 60)
    print(f"Total tweets:      {total}")
    print(f"Correct accepts:   {correct_accept}")
    print(f"Correct rejects:   {correct_reject}")
    print(f"False accepts:     {false_accept}  (Groq said yes, truth=no)")
    print(f"False rejects:     {false_reject}  (Groq said no, truth=yes)")
    print(f"Errors:            {errors}")
    print(f"Accuracy:          {accuracy:.1f}% ({correct}/{total})")
    print()
    print(f"Tokens:            {total_tokens_in} in / {total_tokens_out} out")
    print(f"Elapsed:           {elapsed:.1f}s  (avg {elapsed/total:.2f}s/tweet)")
    print()
    # Cost estimate for comparison. Groq Llama 3.3 70B paid tier:
    #   ~$0.59/M input, ~$0.79/M output
    est_cost = (
        (total_tokens_in * 0.59 / 1_000_000)
        + (total_tokens_out * 0.79 / 1_000_000)
    )
    print(f"Est paid-tier cost for this run: ${est_cost:.6f}  (FREE on free tier)")
    print()

    # Save full results for review
    results_path = Path(__file__).parent / "groq_layer3_eval_results.json"
    with results_path.open("w") as f:
        json.dump({
            "model": MODEL,
            "total": total,
            "correct_accept": correct_accept,
            "correct_reject": correct_reject,
            "false_accept": false_accept,
            "false_reject": false_reject,
            "errors": errors,
            "accuracy_pct": accuracy,
            "tokens_in": total_tokens_in,
            "tokens_out": total_tokens_out,
            "elapsed_sec": elapsed,
            "results": results,
        }, f, indent=2)
    print(f"Full results saved to {results_path}")


if __name__ == "__main__":
    main()

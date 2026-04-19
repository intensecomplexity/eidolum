"""LLM-judge audit — Sonnet decides whether each Haiku `inferred` row
is real attribution (quote really about that ticker) or mis-attribution
(real transcript text, but wrong ticker tag).

Context: fuzzy-match audit (commit 7db3894) proved Haiku doesn't
fabricate quote prose — 1,250 / 1,250 cached rows pass as extractive.
What remains is to test whether the ticker attached to each quote is
the ticker the speaker was actually talking about.

Per-row flow:
  1. Load the row (id, ticker, direction, video_id, quote).
  2. Fetch the full transcript from `video_transcripts`.
  3. Locate the quote's char offset in the transcript. Exact substring
     first; rapidfuzz.partial_ratio_alignment as fallback if the
     normalizer differs. Take ±600 chars as the local context window.
  4. Look up company_name from ticker_sectors.
  5. Build the judge prompt; call Sonnet 4.6 with JSON-only response.
  6. Append to CSV immediately (flush per row). Accumulate cost.

Safety controls:
  - DRY RUN FIRST via --limit 5. Full run requires --limit 1250
    (or omit the flag after --go-past-dry).
  - Preflight: one tiny test call; abort if Anthropic returns
    "credit balance is too low".
  - Hard spend cap: abort if running USD cost exceeds $20.
  - Resume: if CSV already has rows, skip ids already scored.
  - Incremental flush per row.
  - Model: claude-sonnet-4-6 (falls through to -4-5 if not available).

Usage:
    # dry run — 5 rows, pause at end
    DATABASE_URL=... ANTHROPIC_API_KEY=... \\
      python3 backend/scripts/llm_judge_haiku_inferred.py --limit 5

    # full run after approval
    DATABASE_URL=... ANTHROPIC_API_KEY=... \\
      python3 backend/scripts/llm_judge_haiku_inferred.py --limit 10000
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import psycopg2  # noqa: E402

try:
    import anthropic
except ImportError:
    print("ERROR: pip install anthropic", file=sys.stderr)
    sys.exit(2)

try:
    from rapidfuzz import fuzz as _rf_fuzz
except ImportError:
    _rf_fuzz = None


# ── Config ────────────────────────────────────────────────────────────────
CSV_IN = Path("audit/fuzzy_match_haiku_inferred_2026-04-19.csv")
CSV_OUT = Path("audit/llm_judge_haiku_inferred_2026-04-19.csv")
MD_OUT = Path("audit/llm_judge_haiku_inferred_2026-04-19.md")

MODEL_PRIMARY = "claude-sonnet-4-6"
MODEL_FALLBACK = "claude-sonnet-4-5"
# Sonnet 4 family pricing (standard, no prompt cache): $3/M input, $15/M output.
# Will use response.usage to bill accurately.
SONNET_INPUT_PER_MTOK = 3.0
SONNET_OUTPUT_PER_MTOK = 15.0

HARD_SPEND_CAP_USD = 20.0
CREDIT_PREFLIGHT_MIN = 0.0  # preflight is a tiny call; cap abort is the ceiling

WINDOW_CHARS = 600
MAX_OUTPUT_TOKENS = 300
BACKOFF_BASE_S = 2.0
BACKOFF_MAX_S = 30.0

JUDGE_SYSTEM = (
    "You are auditing financial prediction extractions. The extraction "
    "system sometimes copies a real sentence from a transcript but tags "
    "it to the wrong stock ticker. Your job: decide if the quoted "
    "sentence, in its surrounding context, is actually talking about "
    "the specified ticker. Be skeptical. A quote that discusses "
    "markets/sectors/themes broadly but never mentions this specific "
    "company or its products is MIS_ATTRIBUTION. A quote that does "
    "reference this company (by name, ticker, subsidiary, product, CEO) "
    "— even indirectly — is REAL_ATTRIBUTION. If genuinely ambiguous, "
    "say UNCERTAIN."
)


# ── Helpers ───────────────────────────────────────────────────────────────

def build_user_prompt(ticker: str, company: str | None, direction: str,
                      quote: str, window: str) -> str:
    company_part = f" ({company})" if company else ""
    return (
        f"TICKER: {ticker}{company_part}\n"
        f"PREDICTED DIRECTION: {(direction or 'unknown').upper()}\n"
        f"EXTRACTED QUOTE: \"{quote}\"\n\n"
        f"SURROUNDING TRANSCRIPT CONTEXT (\u00b1{WINDOW_CHARS} chars around the quote):\n"
        f"\"\"\"\n{window}\n\"\"\"\n\n"
        f"Question: Is the extracted quote actually about "
        f"{ticker}{company_part} in this context, or is it a "
        f"mis-attribution (real quote, wrong ticker)?\n"
        f"Respond with JSON only: "
        f'{{"verdict": "REAL_ATTRIBUTION" | "MIS_ATTRIBUTION" | "UNCERTAIN", '
        f'"confidence": 0.0-1.0, "reason": "one sentence"}}'
    )


def locate_quote_window(quote: str, transcript: str) -> tuple[str, int]:
    """Return (context_window_text, char_idx_in_transcript).
    char_idx = -1 if the quote couldn't be located at all."""
    if not transcript or not quote:
        return (transcript[: 2 * WINDOW_CHARS], -1)

    # Exact substring
    idx = transcript.find(quote)
    # Case-insensitive substring
    if idx < 0:
        idx = transcript.lower().find(quote.lower())
    # Fuzzy via rapidfuzz alignment
    if idx < 0 and _rf_fuzz is not None:
        try:
            al = _rf_fuzz.partial_ratio_alignment(quote, transcript)
            if al is not None and getattr(al, "score", 0) >= 70:
                idx = al.dest_start
        except Exception:
            pass

    if idx < 0:
        # Fallback: beginning of transcript (rare — fuzzy audit said
        # every REAL row has ≥6-word contiguous match)
        return (transcript[: 2 * WINDOW_CHARS], -1)

    start = max(0, idx - WINDOW_CHARS)
    end = min(len(transcript), idx + len(quote) + WINDOW_CHARS)
    return (transcript[start:end], idx)


def parse_verdict_json(text: str) -> dict:
    """Parse Sonnet's JSON response. Falls back to {} on error —
    caller decides how to treat that."""
    t = (text or "").strip()
    # strip markdown fences
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if t.endswith("```"):
            t = t[:-3].strip()
    try:
        d = json.loads(t)
    except Exception:
        # Best-effort: find the first {...} block
        m = re.search(r"\{.*?\}", t, re.DOTALL)
        if m:
            try:
                d = json.loads(m.group(0))
            except Exception:
                d = {}
        else:
            d = {}
    return d if isinstance(d, dict) else {}


def preflight_credit(client, model: str) -> str:
    """Make one tiny call. If it 400s with 'credit balance is too low'
    or any auth / model error, abort. Returns the working model id."""
    for m in (model, MODEL_FALLBACK):
        try:
            r = client.messages.create(
                model=m,
                max_tokens=4,
                temperature=0,
                system="Reply with one word.",
                messages=[{"role": "user", "content": "ping"}],
            )
            in_tok = getattr(r.usage, "input_tokens", 0)
            out_tok = getattr(r.usage, "output_tokens", 0)
            print(f"[preflight] model={m} ok  in={in_tok} out={out_tok}")
            return m
        except anthropic.BadRequestError as e:
            msg = str(e)
            if "credit balance is too low" in msg.lower():
                print(f"[preflight] FATAL: Anthropic credit balance too low. "
                      f"Abort.\n  {msg}", file=sys.stderr)
                sys.exit(3)
            if "model" in msg.lower() and m == MODEL_PRIMARY:
                print(f"[preflight] primary model {MODEL_PRIMARY} rejected, "
                      f"falling back to {MODEL_FALLBACK}: {msg}")
                continue
            print(f"[preflight] FATAL: {msg}", file=sys.stderr)
            sys.exit(3)
        except Exception as e:
            print(f"[preflight] FATAL: {type(e).__name__}: {e}",
                  file=sys.stderr)
            sys.exit(3)
    print("[preflight] FATAL: no model available", file=sys.stderr)
    sys.exit(3)


def call_judge(client, model: str, ticker: str, company: str | None,
               direction: str, quote: str, window: str) -> tuple[dict, int, int]:
    """Returns (parsed_json, input_tokens, output_tokens). Retries on
    429 with exponential backoff. Any other error raises."""
    user_prompt = build_user_prompt(ticker, company, direction, quote, window)
    backoff = BACKOFF_BASE_S
    for attempt in range(5):
        try:
            r = client.messages.create(
                model=model,
                max_tokens=MAX_OUTPUT_TOKENS,
                temperature=0,
                system=JUDGE_SYSTEM,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = r.content[0].text if r.content else ""
            in_tok = getattr(r.usage, "input_tokens", 0)
            out_tok = getattr(r.usage, "output_tokens", 0)
            return parse_verdict_json(text), in_tok, out_tok
        except anthropic.RateLimitError as e:
            if attempt == 4:
                raise
            sleep_s = min(BACKOFF_MAX_S, backoff)
            print(f"  [429] backoff {sleep_s}s (attempt {attempt+1}/5): {e}",
                  file=sys.stderr)
            time.sleep(sleep_s)
            backoff *= 2
    raise RuntimeError("unreachable")


# ── Main ──────────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5,
                        help="max rows to process this run "
                             "(default 5 = dry-run)")
    parser.add_argument("--spend-cap", type=float, default=HARD_SPEND_CAP_USD)
    parser.add_argument("--model", default=MODEL_PRIMARY)
    args = parser.parse_args(argv)

    # ── Inputs ────────────────────────────────────────────────────
    if not CSV_IN.exists():
        print(f"[FATAL] missing input CSV: {CSV_IN}", file=sys.stderr)
        return 2
    with CSV_IN.open() as f:
        in_rows = [r for r in csv.DictReader(f)
                   if r.get("bucket") == "REAL"]
    print(f"[load] REAL-bucket rows in fuzzy-match CSV: {len(in_rows):,}")

    # Resume: collect already-scored ids
    done_ids: set[int] = set()
    existing_cost_usd = 0.0
    if CSV_OUT.exists() and CSV_OUT.stat().st_size > 0:
        with CSV_OUT.open() as f:
            for r in csv.DictReader(f):
                try:
                    done_ids.add(int(r["prediction_id"]))
                    existing_cost_usd += float(r.get("call_cost_usd") or 0)
                except Exception:
                    pass
        print(f"[resume] {len(done_ids):,} rows already in {CSV_OUT} "
              f"(accrued cost ${existing_cost_usd:.4f})")

    todo = [r for r in in_rows if int(r["id"]) not in done_ids][: args.limit]
    if not todo:
        print("[nothing to do] all requested rows already scored")
        return 0
    print(f"[plan] scoring {len(todo)} rows this invocation "
          f"(limit={args.limit}, resume-skipped={len(in_rows)-len(todo)-len(done_ids)})")

    # ── DB + transcripts ─────────────────────────────────────────
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    pids = [int(r["id"]) for r in todo]
    cur.execute("""
        SELECT p.id, p.ticker, p.direction,
               p.source_verbatim_quote,
               substring(p.source_platform_id FROM 4 FOR 11) AS vid,
               ts.company_name
        FROM predictions p
        LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker
        WHERE p.id = ANY(%s)
    """, (pids,))
    pred_by_id = {r[0]: r for r in cur.fetchall()}
    vids = list({pred_by_id[pid][4] for pid in pids if pid in pred_by_id and pred_by_id[pid][4]})
    cur.execute(
        "SELECT video_id, transcript_text FROM video_transcripts "
        "WHERE video_id = ANY(%s)",
        (vids,),
    )
    tx_by_vid = {r[0]: (r[1] or "") for r in cur.fetchall()}
    cur.close()
    conn.close()
    print(f"[load] predictions={len(pred_by_id)}  "
          f"cached_transcripts={len(tx_by_vid)}/{len(vids)}")

    # ── Anthropic client + preflight ─────────────────────────────
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("[FATAL] ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 2
    client = anthropic.Anthropic(api_key=api_key)
    model = preflight_credit(client, args.model)

    # ── Output CSV (append mode if resuming) ─────────────────────
    CSV_OUT.parent.mkdir(exist_ok=True)
    write_header = not (CSV_OUT.exists() and CSV_OUT.stat().st_size > 0)
    out_f = CSV_OUT.open("a" if not write_header else "w", newline="")
    out_fields = [
        "prediction_id", "ticker", "direction", "video_id", "company_name",
        "quote", "verdict", "confidence", "reason",
        "input_tokens", "output_tokens", "call_cost_usd",
        "quote_located", "run_at",
    ]
    out_w = csv.DictWriter(out_f, fieldnames=out_fields)
    if write_header:
        out_w.writeheader()
        out_f.flush()

    # ── Loop ─────────────────────────────────────────────────────
    running_cost = existing_cost_usd
    verdicts = Counter()
    scored = 0
    t0 = time.time()
    try:
        for row in todo:
            pid = int(row["id"])
            rec = pred_by_id.get(pid)
            if rec is None:
                print(f"  [{pid}] MISSING from predictions — skipping")
                continue
            _, ticker, direction, quote, vid, company = rec
            transcript = tx_by_vid.get(vid, "")
            if not transcript:
                print(f"  [{pid}] no cached transcript for {vid} — skipping")
                continue
            window, q_idx = locate_quote_window(quote, transcript)

            # Spend-cap check BEFORE the call
            if running_cost >= args.spend_cap:
                print(f"[abort] running cost ${running_cost:.4f} >= cap "
                      f"${args.spend_cap}", file=sys.stderr)
                break

            try:
                verdict, in_tok, out_tok = call_judge(
                    client, model, ticker, company, direction or "",
                    quote, window,
                )
            except Exception as e:
                print(f"  [{pid}] call error: {type(e).__name__}: {e}",
                      file=sys.stderr)
                continue

            call_cost = (in_tok * SONNET_INPUT_PER_MTOK
                         + out_tok * SONNET_OUTPUT_PER_MTOK) / 1_000_000
            running_cost += call_cost

            verdict_label = verdict.get("verdict") or "PARSE_FAIL"
            verdicts[verdict_label] += 1

            out_w.writerow({
                "prediction_id": pid,
                "ticker": ticker or "",
                "direction": direction or "",
                "video_id": vid or "",
                "company_name": company or "",
                "quote": quote or "",
                "verdict": verdict_label,
                "confidence": verdict.get("confidence") or "",
                "reason": (verdict.get("reason") or "").strip(),
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "call_cost_usd": round(call_cost, 6),
                "quote_located": q_idx >= 0,
                "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                        time.gmtime()),
            })
            out_f.flush()
            scored += 1

            elapsed = time.time() - t0
            rate = scored / max(1.0, elapsed)
            print(f"  [{scored}/{len(todo)}]  id={pid}  ticker={ticker}  "
                  f"-> {verdict_label}  conf={verdict.get('confidence')}  "
                  f"tokens={in_tok}/{out_tok}  cost=${call_cost:.4f}  "
                  f"total=${running_cost:.4f}  "
                  f"rate={rate:.2f}/s", flush=True)

            # Every 100 rows: print the cap status
            if scored % 100 == 0:
                remaining_budget = args.spend_cap - running_cost
                print(f"  [cap-check] running=${running_cost:.4f}  "
                      f"cap=${args.spend_cap}  remaining=${remaining_budget:.4f}")
    finally:
        out_f.close()

    elapsed = time.time() - t0
    print()
    print("=" * 68)
    print(f"  run complete  scored={scored}  "
          f"elapsed={elapsed:.1f}s  cost=${running_cost:.4f}")
    print("=" * 68)
    for v, n in verdicts.most_common():
        print(f"  {v:<20}  {n:>5}")
    print(f"\n  csv → {CSV_OUT}  ({CSV_OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

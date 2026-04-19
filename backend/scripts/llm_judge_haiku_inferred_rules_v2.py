"""LLM-judge re-audit v2 — Nimrod's attribution rules.

Re-scores the 437 non-REAL rows from commit c11012e under rules that
explicitly accept thematic / sector / commodity / implicit / conditional
attribution as REAL, not ambiguous.

Three verdicts:
  REAL_ATTRIBUTION — matches any of Cat 1-5 (theme / sector / commodity
                     ETF / implicit reference / conditional)
  RETAG            — subject is correct at the sector/theme level, but
                     the ticker is a narrow individual stock instead
                     of the sector ETF. suggested_ticker = ETF symbol
  MIS_ATTRIBUTION  — no thematic, sector, commodity, or implicit link;
                     speaker is discussing something else entirely

Structurally identical to llm_judge_haiku_inferred.py (commit c11012e):
subprocess-free, rapidfuzz quote-locator, psycopg2 transcript load,
incremental CSV flush, resume-safe, spend-cap gated, preflight call.

Usage:
    # dry run (5 rows)
    DATABASE_URL=... ANTHROPIC_API_KEY=... \\
      python3 backend/scripts/llm_judge_haiku_inferred_rules_v2.py --limit 5

    # full pass
    DATABASE_URL=... ANTHROPIC_API_KEY=... \\
      python3 backend/scripts/llm_judge_haiku_inferred_rules_v2.py --limit 10000
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
CSV_IN = Path("audit/llm_judge_haiku_inferred_2026-04-19.csv")
CSV_OUT = Path("audit/llm_judge_haiku_inferred_rules_v2_2026-04-19.csv")
MD_OUT = Path("audit/llm_judge_haiku_inferred_rules_v2_2026-04-19.md")

MODEL_PRIMARY = "claude-sonnet-4-6"
MODEL_FALLBACK = "claude-sonnet-4-5"
SONNET_INPUT_PER_MTOK = 3.0
SONNET_OUTPUT_PER_MTOK = 15.0

HARD_SPEND_CAP_USD = 10.0

WINDOW_CHARS = 600
MAX_OUTPUT_TOKENS = 300
BACKOFF_BASE_S = 2.0
BACKOFF_MAX_S = 30.0


JUDGE_SYSTEM = (
    "You are auditing financial prediction attributions. The "
    "extraction system sometimes attaches a quote to a ticker that's "
    "a reasonable thematic, sector, or implicit proxy for what the "
    "speaker said — that is REAL, not a mistake. Your job is to "
    "distinguish three cases:\n\n"
    "REAL_ATTRIBUTION — the ticker fits under any of these patterns:\n"
    "  - Theme ETF for a theme ('tech rally' -> QQQ)\n"
    "  - Sector ETF for a sector ('banks look strong' -> XLF)\n"
    "  - Commodity/currency/macro ETF for that asset "
    "('gold' -> GLD, 'dollar' -> UUP, 'oil' -> USO)\n"
    "  - Implicit reference to the specific company "
    "('iPhone maker' -> AAPL, 'Musk's car company' -> TSLA)\n"
    "  - Conditional / hypothetical prediction about the ticker "
    "('if X, NVDA rallies' -> NVDA)\n\n"
    "RETAG — the speaker discussed a sector or theme, but the ticker "
    "is a narrow individual stock instead of the sector ETF. Output "
    "the recommended sector ETF as suggested_ticker.\n\n"
    "MIS_ATTRIBUTION — the ticker has no thematic, sector, commodity, "
    "or implicit link to the quote. The speaker is discussing "
    "something else entirely.\n\n"
    "Conditionals, hypotheticals, and 'could' / 'might' / 'if' phrasing "
    "are all VALID predictions — not grounds for ambiguity.\n\n"
    "Reference ETF mapping for RETAG suggestions:\n"
    "  Semiconductors SMH, Biotech IBB, Financials/banks XLF, "
    "Energy XLE, Broad tech QQQ or XLK, Healthcare XLV, REITs VNQ, "
    "Defense ITA, Consumer discretionary XLY, Consumer staples XLP, "
    "Industrials XLI, Materials XLB, Utilities XLU, Communications XLC, "
    "Homebuilders ITB, Gold miners GDX, Oil & gas explorers XOP, "
    "Gold GLD, Silver SLV, Oil USO, Dollar UUP, Bitcoin IBIT, "
    "Long treasuries TLT, TIPS TIP, Emerging markets EEM, China FXI, "
    "Inverse S&P SH."
)


def build_user_prompt(ticker: str, company: str | None, direction: str,
                      quote: str, window: str) -> str:
    company_part = f" ({company})" if company else ""
    return (
        f"TICKER: {ticker}{company_part}\n"
        f"PREDICTED DIRECTION: {(direction or 'unknown').upper()}\n"
        f'EXTRACTED QUOTE: "{quote}"\n\n'
        f"SURROUNDING CONTEXT (±{WINDOW_CHARS} chars):\n"
        f'"""\n{window}\n"""\n\n'
        f"Classify under the rules. Respond with JSON only:\n"
        f'{{"verdict": "REAL_ATTRIBUTION" | "RETAG" | "MIS_ATTRIBUTION", '
        f'"suggested_ticker": "SYMBOL or null", '
        f'"confidence": 0.0-1.0, '
        f'"reason": "one sentence citing which rule applies"}}'
    )


def locate_quote_window(quote: str, transcript: str) -> tuple[str, int]:
    if not transcript or not quote:
        return (transcript[: 2 * WINDOW_CHARS], -1)
    idx = transcript.find(quote)
    if idx < 0:
        idx = transcript.lower().find(quote.lower())
    if idx < 0 and _rf_fuzz is not None:
        try:
            al = _rf_fuzz.partial_ratio_alignment(quote, transcript)
            if al is not None and getattr(al, "score", 0) >= 70:
                idx = al.dest_start
        except Exception:
            pass
    if idx < 0:
        return (transcript[: 2 * WINDOW_CHARS], -1)
    start = max(0, idx - WINDOW_CHARS)
    end = min(len(transcript), idx + len(quote) + WINDOW_CHARS)
    return (transcript[start:end], idx)


def parse_verdict_json(text: str) -> dict:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if t.endswith("```"):
            t = t[:-3].strip()
    try:
        d = json.loads(t)
    except Exception:
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
    for m in (model, MODEL_FALLBACK):
        try:
            r = client.messages.create(
                model=m, max_tokens=4, temperature=0,
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
                print(f"[preflight] FATAL: Anthropic credit balance too low.\n  {msg}", file=sys.stderr)
                sys.exit(3)
            if "model" in msg.lower() and m == MODEL_PRIMARY:
                print(f"[preflight] primary {MODEL_PRIMARY} rejected, falling back: {msg}")
                continue
            print(f"[preflight] FATAL: {msg}", file=sys.stderr)
            sys.exit(3)
        except Exception as e:
            print(f"[preflight] FATAL: {type(e).__name__}: {e}", file=sys.stderr)
            sys.exit(3)
    print("[preflight] FATAL: no model available", file=sys.stderr)
    sys.exit(3)


def call_judge(client, model: str, ticker: str, company: str | None,
               direction: str, quote: str, window: str) -> tuple[dict, int, int]:
    user_prompt = build_user_prompt(ticker, company, direction, quote, window)
    backoff = BACKOFF_BASE_S
    for attempt in range(5):
        try:
            r = client.messages.create(
                model=model, max_tokens=MAX_OUTPUT_TOKENS, temperature=0,
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


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5,
                        help="max rows to process this run (default 5 = dry-run)")
    parser.add_argument("--spend-cap", type=float, default=HARD_SPEND_CAP_USD)
    parser.add_argument("--model", default=MODEL_PRIMARY)
    args = parser.parse_args(argv)

    # ── Load v1 judge CSV, filter to non-REAL ────────────────────
    if not CSV_IN.exists():
        print(f"[FATAL] missing input CSV: {CSV_IN}", file=sys.stderr)
        return 2
    with CSV_IN.open() as f:
        v1_rows = list(csv.DictReader(f))
    non_real = [r for r in v1_rows
                if r.get("verdict") in ("MIS_ATTRIBUTION", "UNCERTAIN")]
    print(f"[load] v1 rows total: {len(v1_rows):,}  "
          f"non-REAL (to re-score): {len(non_real):,}")

    # Resume from output CSV
    done_ids: set[int] = set()
    existing_cost = 0.0
    if CSV_OUT.exists() and CSV_OUT.stat().st_size > 0:
        with CSV_OUT.open() as f:
            for r in csv.DictReader(f):
                try:
                    done_ids.add(int(r["prediction_id"]))
                    existing_cost += float(r.get("call_cost_usd") or 0)
                except Exception:
                    pass
        print(f"[resume] {len(done_ids):,} rows already scored "
              f"(accrued cost ${existing_cost:.4f})")

    todo = [r for r in non_real
            if int(r["prediction_id"]) not in done_ids][: args.limit]
    if not todo:
        print("[nothing to do] all requested rows already scored")
        return 0
    print(f"[plan] scoring {len(todo)} rows this invocation (limit={args.limit})")

    # ── Pull transcripts + company names ─────────────────────────
    pids = [int(r["prediction_id"]) for r in todo]
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("""
        SELECT p.id,
               substring(p.source_platform_id FROM 4 FOR 11) AS vid,
               ts.company_name
        FROM predictions p
        LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker
        WHERE p.id = ANY(%s)
    """, (pids,))
    db_meta = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    vids = list({db_meta[pid][0] for pid in pids
                 if pid in db_meta and db_meta[pid][0]})
    cur.execute(
        "SELECT video_id, transcript_text FROM video_transcripts "
        "WHERE video_id = ANY(%s)", (vids,),
    )
    tx_by_vid = {r[0]: (r[1] or "") for r in cur.fetchall()}
    cur.close()
    conn.close()
    print(f"[load] predictions={len(db_meta)}  "
          f"cached_transcripts={len(tx_by_vid)}/{len(vids)}")

    # ── Anthropic client + preflight ─────────────────────────────
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("[FATAL] ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 2
    client = anthropic.Anthropic(api_key=api_key)
    model = preflight_credit(client, args.model)

    # ── Output CSV ───────────────────────────────────────────────
    CSV_OUT.parent.mkdir(exist_ok=True)
    write_header = not (CSV_OUT.exists() and CSV_OUT.stat().st_size > 0)
    out_f = CSV_OUT.open("a" if not write_header else "w", newline="")
    out_fields = [
        "prediction_id", "ticker", "direction", "video_id", "company_name",
        "quote",
        "v1_verdict", "v1_confidence", "v1_reason",
        "v2_verdict", "v2_confidence", "v2_reason", "v2_suggested_ticker",
        "input_tokens", "output_tokens", "call_cost_usd",
        "quote_located", "run_at",
    ]
    out_w = csv.DictWriter(out_f, fieldnames=out_fields)
    if write_header:
        out_w.writeheader()
        out_f.flush()

    # ── Loop ─────────────────────────────────────────────────────
    running_cost = existing_cost
    verdicts = Counter()
    scored = 0
    t0 = time.time()
    try:
        for row in todo:
            pid = int(row["prediction_id"])
            meta = db_meta.get(pid)
            if meta is None:
                print(f"  [{pid}] missing from predictions — skip")
                continue
            vid, company = meta
            transcript = tx_by_vid.get(vid, "")
            if not transcript:
                print(f"  [{pid}] no cached transcript for {vid} — skip")
                continue
            quote = row["quote"] or ""
            ticker = row["ticker"]
            direction = row["direction"]
            window, q_idx = locate_quote_window(quote, transcript)

            if running_cost >= args.spend_cap:
                print(f"[abort] running cost ${running_cost:.4f} >= cap "
                      f"${args.spend_cap}", file=sys.stderr)
                break

            try:
                verdict, in_tok, out_tok = call_judge(
                    client, model, ticker, company, direction, quote, window,
                )
            except Exception as e:
                print(f"  [{pid}] call error: {type(e).__name__}: {e}",
                      file=sys.stderr)
                continue

            cost = (in_tok * SONNET_INPUT_PER_MTOK
                    + out_tok * SONNET_OUTPUT_PER_MTOK) / 1_000_000
            running_cost += cost

            v2 = verdict.get("verdict") or "PARSE_FAIL"
            verdicts[v2] += 1

            out_w.writerow({
                "prediction_id": pid,
                "ticker": ticker or "",
                "direction": direction or "",
                "video_id": vid or "",
                "company_name": company or "",
                "quote": quote,
                "v1_verdict": row.get("verdict") or "",
                "v1_confidence": row.get("confidence") or "",
                "v1_reason": row.get("reason") or "",
                "v2_verdict": v2,
                "v2_confidence": verdict.get("confidence") or "",
                "v2_reason": (verdict.get("reason") or "").strip(),
                "v2_suggested_ticker": verdict.get("suggested_ticker") or "",
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "call_cost_usd": round(cost, 6),
                "quote_located": q_idx >= 0,
                "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            out_f.flush()
            scored += 1

            elapsed = time.time() - t0
            rate = scored / max(1.0, elapsed)
            sugg = verdict.get("suggested_ticker") or ""
            sugg_str = f"  suggest={sugg}" if sugg else ""
            print(f"  [{scored}/{len(todo)}]  id={pid}  ticker={ticker}  "
                  f"v1={row.get('verdict')}  v2={v2}{sugg_str}  "
                  f"conf={verdict.get('confidence')}  "
                  f"tokens={in_tok}/{out_tok}  cost=${cost:.4f}  "
                  f"total=${running_cost:.4f}  "
                  f"rate={rate:.2f}/s", flush=True)

            if scored % 100 == 0:
                remaining = args.spend_cap - running_cost
                print(f"  [cap-check] running=${running_cost:.4f}  "
                      f"cap=${args.spend_cap}  remaining=${remaining:.4f}")
    finally:
        out_f.close()

    elapsed = time.time() - t0
    print()
    print("=" * 68)
    print(f"  run complete  scored={scored}  "
          f"elapsed={elapsed:.1f}s  cost=${running_cost:.4f}")
    print("=" * 68)
    for v, n in verdicts.most_common():
        print(f"  {v:<22}  {n:>5}")
    print(f"\n  csv → {CSV_OUT}  ({CSV_OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

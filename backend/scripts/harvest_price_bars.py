"""
harvest_price_bars.py — bulk download historical EOD into price_bars.

One-shot script for the FMP Ultimate window. Idempotent (ON CONFLICT DO NOTHING),
resumable (skip tickers that already have bars), atexit summary on every exit.

Per-ticker: GET /stable/historical-price-eod/full?symbol=X&from=Y&to=Z
Parses the OHLCV bars, batch-inserts into price_bars. Each ticker is one
transaction so a mid-run crash leaves a clean per-ticker boundary.

Designed to run in 30–60 minutes for ~12K tickers at 2500 calls/min, leaving
500/min headroom on FMP's 3000/min Ultimate cap so other jobs can still call.

After harvest completes, a separate SQL pass joins price_bars onto predictions
to fix entry_price for every stuck row — zero new API calls.
"""
import argparse
import atexit
import os
import signal
import sys
import time
from datetime import datetime, timedelta, date as _date

if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from sqlalchemy import text as sql_text

from database import BgSessionLocal

FMP_KEY = os.getenv("FMP_KEY", "").strip()
BASE = "https://financialmodelingprep.com/stable/historical-price-eod/full"
TAG = "[harvest]"

# Clamp earliest harvest date — FMP coverage is shaky pre-2011 anyway
EARLIEST = _date(2011, 1, 1)

_stats = {
    "started_at": datetime.utcnow().isoformat(),
    "tickers_total": 0,
    "tickers_processed": 0,
    "tickers_skipped_resume": 0,
    "tickers_with_no_data": 0,
    "tickers_429_failed": 0,
    "tickers_5xx_failed": 0,
    "tickers_connection_failed": 0,
    "total_bars_inserted": 0,
    "by_status": {},  # status → count
    "exit_reason": "unknown",
    "summary_path": "",
    "argv": " ".join(sys.argv),
}


# -------------------------------------------------------------- exit hook
def _write_summary():
    sp = _stats.get("summary_path")
    if not sp:
        return
    try:
        os.makedirs(os.path.dirname(sp), exist_ok=True)
        now = datetime.utcnow()
        started = datetime.fromisoformat(_stats["started_at"])
        runtime = (now - started).total_seconds()
        lines = []
        lines.append("# price_bars harvest summary\n")
        lines.append(f"- Started: {_stats['started_at']}Z")
        lines.append(f"- Finished: {now.isoformat()}Z")
        lines.append(f"- Runtime: {runtime:.0f}s ({runtime/3600:.2f}h)")
        lines.append(f"- Argv: `{_stats['argv']}`")
        lines.append(f"- Exit reason: **{_stats['exit_reason']}**\n")
        lines.append("## Counts")
        for k in ("tickers_total", "tickers_processed", "tickers_skipped_resume",
                  "tickers_with_no_data", "tickers_429_failed", "tickers_5xx_failed",
                  "tickers_connection_failed", "total_bars_inserted"):
            v = _stats.get(k, 0)
            lines.append(f"- {k}: {v:,}")
        lines.append("\n## HTTP status tally")
        for k, v in sorted(_stats["by_status"].items()):
            lines.append(f"- {k}: {v:,}")
        with open(sp, "w") as f:
            f.write("\n".join(lines) + "\n")
        print(f"{TAG} summary written → {sp}", flush=True)
    except Exception as e:
        print(f"{TAG} summary write failed: {e}", flush=True)


def _signal_handler(signum, frame):
    _stats["exit_reason"] = f"signal {signum}"
    print(f"{TAG} received signal {signum}, writing summary + exiting", flush=True)
    sys.exit(128 + signum)


# -------------------------------------------------------------- schema
def _ensure_table(db) -> None:
    """Idempotent. SELECT before CREATE to avoid heavy locks on busy DB."""
    exists = db.execute(sql_text("""
        SELECT 1 FROM information_schema.tables
         WHERE table_schema='public' AND table_name='price_bars'
    """)).first()
    if not exists:
        db.execute(sql_text("""
            CREATE TABLE price_bars (
                ticker      VARCHAR(20)   NOT NULL,
                bar_date    DATE          NOT NULL,
                open        NUMERIC(14,4),
                high        NUMERIC(14,4),
                low         NUMERIC(14,4),
                close       NUMERIC(14,4) NOT NULL,
                volume      BIGINT,
                adj_close   NUMERIC(14,4),
                source      VARCHAR(16)   NOT NULL,
                fetched_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
                PRIMARY KEY (ticker, bar_date)
            )
        """))
        db.commit()
    for idx, ddl in [
        ("ix_price_bars_ticker",   "CREATE INDEX ix_price_bars_ticker  ON price_bars(ticker)"),
        ("ix_price_bars_bar_date", "CREATE INDEX ix_price_bars_bar_date ON price_bars(bar_date)"),
    ]:
        present = db.execute(sql_text("""
            SELECT 1 FROM pg_indexes
             WHERE schemaname='public' AND tablename='price_bars' AND indexname=:n
        """), {"n": idx}).first()
        if not present:
            db.execute(sql_text(ddl))
            db.commit()


# -------------------------------------------------------------- loader
def _load_tickers(path: str) -> list[tuple[str, str, str, int]]:
    out = []
    with open(path) as f:
        for ln in f:
            ln = ln.rstrip("\n")
            if not ln or ln.startswith("#"):
                continue
            parts = ln.split("\t")
            if len(parts) < 4:
                continue
            try:
                out.append((parts[0].strip(), parts[1].strip(), parts[2].strip(), int(parts[3])))
            except (ValueError, IndexError):
                continue
    return out


def _ticker_has_bars(db, ticker: str) -> bool:
    return db.execute(
        sql_text("SELECT 1 FROM price_bars WHERE ticker=:t LIMIT 1"),
        {"t": ticker},
    ).first() is not None


# -------------------------------------------------------------- fetch + parse
def _fetch_ticker(ticker: str, hfrom: str, hto: str, max_retries: int = 3) -> tuple[list, str]:
    """Returns (bars, status_str). Backoff on 429/5xx/conn. Never raises."""
    backoff = [30, 60, 120]
    last_status = "unknown"
    for attempt in range(max_retries):
        try:
            r = httpx.get(
                BASE,
                params={"symbol": ticker, "from": hfrom, "to": hto, "apikey": FMP_KEY},
                timeout=30,
            )
            last_status = str(r.status_code)
            if r.status_code == 429:
                if attempt < max_retries - 1:
                    print(f"{TAG} {ticker} 429 try {attempt+1} — sleep {backoff[attempt]}s", flush=True)
                    time.sleep(backoff[attempt])
                    continue
                return [], "429"
            if 500 <= r.status_code < 600:
                if attempt < max_retries - 1:
                    print(f"{TAG} {ticker} {r.status_code} try {attempt+1} — sleep {backoff[attempt]}s", flush=True)
                    time.sleep(backoff[attempt])
                    continue
                return [], "5xx"
            if r.status_code != 200:
                return [], f"HTTP_{r.status_code}"
            data = r.json()
            # /stable/ returns a list directly; /v3 wrapped in {"historical":[...]}
            hist = data.get("historical", data) if isinstance(data, dict) else data
            if not isinstance(hist, list) or not hist:
                return [], "empty"
            bars = []
            for d in hist:
                if not isinstance(d, dict):
                    continue
                ds = (d.get("date") or "")[:10]
                close = d.get("close")
                if not ds or close is None:
                    continue
                try:
                    close_f = float(close)
                except (ValueError, TypeError):
                    continue
                if close_f <= 0:
                    continue
                bars.append({
                    "date": ds,
                    "open": d.get("open"),
                    "high": d.get("high"),
                    "low": d.get("low"),
                    "close": close_f,
                    "volume": d.get("volume"),
                    "adj_close": d.get("adjClose"),
                })
            return bars, "200" if bars else "empty"
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout,
                httpx.RemoteProtocolError) as e:
            if attempt < max_retries - 1:
                print(f"{TAG} {ticker} conn try {attempt+1}: {type(e).__name__} — sleep {backoff[attempt]}s", flush=True)
                time.sleep(backoff[attempt])
                continue
            return [], "conn"
        except Exception as e:
            print(f"{TAG} {ticker} unexpected error: {e}", flush=True)
            return [], "exception"
    return [], last_status


def _insert_bars(db, ticker: str, bars: list, source: str = "fmp") -> int:
    """Batch-insert with ON CONFLICT DO NOTHING. Returns rowcount inserted."""
    if not bars:
        return 0
    chunk_size = 500
    total = 0
    for i in range(0, len(bars), chunk_size):
        chunk = bars[i:i + chunk_size]
        placeholders = []
        params = {}
        for j, b in enumerate(chunk):
            placeholders.append(
                f"(:t{j}, :d{j}, :o{j}, :h{j}, :l{j}, :c{j}, :v{j}, :a{j}, :s{j})"
            )
            params[f"t{j}"] = ticker
            params[f"d{j}"] = b["date"]
            params[f"o{j}"] = b["open"]
            params[f"h{j}"] = b["high"]
            params[f"l{j}"] = b["low"]
            params[f"c{j}"] = b["close"]
            params[f"v{j}"] = b["volume"]
            params[f"a{j}"] = b["adj_close"]
            params[f"s{j}"] = source
        sql = (
            "INSERT INTO price_bars (ticker, bar_date, open, high, low, close, volume, adj_close, source) "
            "VALUES " + ", ".join(placeholders) + " "
            "ON CONFLICT (ticker, bar_date) DO NOTHING"
        )
        result = db.execute(sql_text(sql), params)
        # Postgres rowcount reflects actual inserts after ON CONFLICT
        if result.rowcount and result.rowcount >= 0:
            total += result.rowcount
    return total


# ---------------------------------------------------------------- main
def _clamp_from(hfrom_str: str) -> str:
    """Clamp harvest_from to EARLIEST. TSV may contain 1900-xx sentinel dates."""
    try:
        d = datetime.strptime(hfrom_str, "%Y-%m-%d").date()
    except Exception:
        return EARLIEST.strftime("%Y-%m-%d")
    if d < EARLIEST:
        return EARLIEST.strftime("%Y-%m-%d")
    return hfrom_str


def main():
    ap = argparse.ArgumentParser(description="Bulk-harvest historical EOD into price_bars")
    ap.add_argument("--tickers", default="/tmp/eidolum_ticker_ranges.tsv",
                    help="TSV: ticker\\tharvest_from\\tharvest_to\\tprediction_count")
    ap.add_argument("--batch-commit", type=int, default=50,
                    help="Postgres commit every N tickers")
    ap.add_argument("--rate-limit", type=int, default=2500,
                    help="Max FMP calls/minute (leaves 500/min headroom on Ultimate's 3000)")
    ap.add_argument("--max-retries", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0, help="0 = unbounded (process all tickers)")
    ap.add_argument("--resume", action="store_true",
                    help="Skip tickers that already have any bars in price_bars")
    ap.add_argument("--summary-path", default="")
    args = ap.parse_args()

    if not FMP_KEY:
        print(f"{TAG} ERROR: FMP_KEY not set", flush=True)
        sys.exit(2)

    if not args.summary_path:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M")
        args.summary_path = (
            f"/mnt/g/My Drive/eidolum.prompts/_alerts/"
            f"price_bars_harvest_{ts}_SUMMARY.md"
        )
    _stats["summary_path"] = args.summary_path

    atexit.register(_write_summary)
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    print(f"{TAG} mode=COMMIT rate_limit={args.rate_limit}/min resume={args.resume} limit={args.limit}")
    print(f"{TAG} summary: {args.summary_path}")

    tickers = _load_tickers(args.tickers)
    _stats["tickers_total"] = len(tickers)
    print(f"{TAG} loaded {len(tickers):,} tickers from {args.tickers}", flush=True)
    if args.limit > 0:
        tickers = tickers[:args.limit]
        print(f"{TAG} limit applied → {len(tickers)} tickers", flush=True)

    delay_sec = 60.0 / max(1, args.rate_limit)
    db = BgSessionLocal()
    _ensure_table(db)

    last_call_t = 0.0
    last_progress_t = time.time()

    for i, (ticker, hfrom, hto, _count) in enumerate(tickers):
        # rate-limit pace
        elapsed = time.time() - last_call_t
        if elapsed < delay_sec:
            time.sleep(delay_sec - elapsed)

        # resume: skip if already harvested
        if args.resume and _ticker_has_bars(db, ticker):
            _stats["tickers_skipped_resume"] += 1
            last_call_t = time.time()
            continue

        last_call_t = time.time()
        hfrom_clamped = _clamp_from(hfrom)
        bars, status = _fetch_ticker(ticker, hfrom_clamped, hto, args.max_retries)
        _stats["tickers_processed"] += 1
        _stats["by_status"][status] = _stats["by_status"].get(status, 0) + 1

        if status == "429":
            _stats["tickers_429_failed"] += 1
        elif status == "5xx":
            _stats["tickers_5xx_failed"] += 1
        elif status == "conn":
            _stats["tickers_connection_failed"] += 1

        if bars:
            try:
                inserted = _insert_bars(db, ticker, bars)
                _stats["total_bars_inserted"] += inserted
            except Exception as e:
                print(f"{TAG} {ticker} insert failed: {e}", flush=True)
                try:
                    db.rollback()
                except Exception:
                    pass
        else:
            _stats["tickers_with_no_data"] += 1

        if (i + 1) % args.batch_commit == 0:
            try:
                db.commit()
            except Exception as e:
                print(f"{TAG} commit err at i={i+1}: {e}", flush=True)
                db.rollback()

        if i == 0 or time.time() - last_progress_t > 30:
            print(
                f"{TAG} i={i+1}/{len(tickers)} bars={_stats['total_bars_inserted']:,} "
                f"no_data={_stats['tickers_with_no_data']} "
                f"skip={_stats['tickers_skipped_resume']} "
                f"429={_stats['by_status'].get('429',0)} "
                f"5xx={_stats['by_status'].get('5xx',0)}",
                flush=True,
            )
            last_progress_t = time.time()

    try:
        db.commit()
    except Exception:
        db.rollback()
    db.close()

    if _stats["exit_reason"] == "unknown":
        _stats["exit_reason"] = "completed"
    print(
        f"\n{TAG} done — bars={_stats['total_bars_inserted']:,} "
        f"tickers_processed={_stats['tickers_processed']:,} "
        f"no_data={_stats['tickers_with_no_data']:,} "
        f"skipped={_stats['tickers_skipped_resume']:,}",
        flush=True,
    )


if __name__ == "__main__":
    main()

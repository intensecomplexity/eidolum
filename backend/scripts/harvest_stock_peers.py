"""
harvest_stock_peers.py — per-ticker peer harvest into stock_peers.

The /stable/stock-peers-bulk endpoint was removed (audit 2026-05-27). The
per-ticker replacement /stable/stock-peers?symbol=X returns 8-10 peer
records per call. With ~10K US-listed tickers in our universe and a
2500/min budget, the full harvest is ~4 minutes.

Foreign tickers are skipped — FMP returns mostly empty/404 for non-US
listings and the bulk would waste FMP quota. The skip patterns match the
ones used by the Phase 4 price_bars harvester.

Idempotent (ON CONFLICT DO NOTHING). Resumable (--resume skips any ticker
already in stock_peers). atexit summary writer.
"""
import argparse
import atexit
import os
import signal
import sys
import time
from datetime import datetime

if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from sqlalchemy import text as sql_text

from database import BgSessionLocal

FMP_KEY = os.getenv("FMP_KEY", "").strip()
BASE = "https://financialmodelingprep.com/stable/stock-peers"
TAG = "[stock_peers]"

# Foreign listing suffixes to skip
FOREIGN_SUFFIXES = (
    ".L",   # London
    ".HK",  # Hong Kong
    ".DE",  # Germany (Xetra)
    ".F",   # Frankfurt
    ".TO",  # Toronto
    ".V",   # Toronto Venture
    ".PA",  # Paris
    ".MI",  # Milan
    ".MC",  # Madrid
    ".AS",  # Amsterdam
    ".BR",  # Brussels
    ".SW",  # Swiss
    ".SZ",  # Shenzhen
    ".SS",  # Shanghai
    ".KS",  # Korea
    ".AX",  # Australia
    ".T",   # Tokyo
    ".MX",  # Mexico
    ".BO",  # Bombay
    ".NS",  # NSE India
)


_stats = {
    "started_at": datetime.utcnow().isoformat(),
    "tickers_total": 0,
    "tickers_processed": 0,
    "tickers_skipped_foreign": 0,
    "tickers_skipped_resume": 0,
    "tickers_with_no_peers": 0,
    "tickers_errors": 0,
    "peer_rows_inserted": 0,
    "by_status": {},
    "exit_reason": "unknown",
    "summary_path": "",
    "argv": " ".join(sys.argv),
}


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
        lines.append("# stock_peers harvest summary\n")
        lines.append(f"- Started: {_stats['started_at']}Z")
        lines.append(f"- Finished: {now.isoformat()}Z")
        lines.append(f"- Runtime: {runtime:.0f}s ({runtime/3600:.2f}h)")
        lines.append(f"- Argv: `{_stats['argv']}`")
        lines.append(f"- Exit reason: **{_stats['exit_reason']}**\n")
        lines.append("## Counts")
        for k in ("tickers_total", "tickers_processed", "tickers_skipped_foreign",
                  "tickers_skipped_resume", "tickers_with_no_peers",
                  "tickers_errors", "peer_rows_inserted"):
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
    print(f"{TAG} received signal {signum}, exiting", flush=True)
    sys.exit(128 + signum)


def _is_foreign(ticker: str) -> bool:
    t = ticker.upper()
    if any(t.endswith(s) for s in FOREIGN_SUFFIXES):
        return True
    # All-numeric (some Asian markets)
    if t.replace(".", "").isdigit():
        return True
    return False


def _load_tickers(path: str) -> list[str]:
    out = []
    with open(path) as f:
        for ln in f:
            ln = ln.rstrip("\n")
            if not ln or ln.startswith("#"):
                continue
            parts = ln.split("\t")
            if len(parts) < 1:
                continue
            t = parts[0].strip()
            if t:
                out.append(t)
    return out


def _ticker_already_done(db, ticker: str) -> bool:
    return db.execute(
        sql_text("SELECT 1 FROM stock_peers WHERE ticker=:t LIMIT 1"),
        {"t": ticker},
    ).first() is not None


def _fetch_peers(ticker: str) -> tuple[list, str]:
    """Returns (peer_tickers, status). Never raises."""
    try:
        r = httpx.get(BASE, params={"symbol": ticker, "apikey": FMP_KEY}, timeout=15)
        status = str(r.status_code)
        if r.status_code == 429:
            return [], "429"
        if r.status_code != 200:
            return [], status
        data = r.json()
        if not isinstance(data, list):
            return [], "non_list"
        peers = []
        for item in data:
            if not isinstance(item, dict):
                continue
            sym = (item.get("symbol") or "").strip()
            if sym and sym != ticker:
                peers.append(sym)
        return peers, "200"
    except Exception as e:
        print(f"{TAG} {ticker} exception: {e}", flush=True)
        return [], "exception"


def _insert_peers(db, ticker: str, peers: list[str]) -> int:
    """ON CONFLICT DO NOTHING. Returns inserted count."""
    if not peers:
        return 0
    # Dedup peers (just in case)
    peers = list(dict.fromkeys(peers))
    placeholders = []
    params = {}
    for j, p in enumerate(peers):
        placeholders.append(f"(:t{j}, :p{j})")
        params[f"t{j}"] = ticker
        params[f"p{j}"] = p
    sql = (
        "INSERT INTO stock_peers (ticker, peer_ticker) VALUES "
        + ",".join(placeholders) +
        " ON CONFLICT (ticker, peer_ticker) DO NOTHING"
    )
    try:
        result = db.execute(sql_text(sql), params)
        return result.rowcount if (result.rowcount and result.rowcount > 0) else len(peers)
    except Exception as e:
        print(f"{TAG} {ticker} insert failed: {e}", flush=True)
        try:
            db.rollback()
        except Exception:
            pass
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="/tmp/eidolum_ticker_ranges.tsv")
    ap.add_argument("--batch-commit", type=int, default=100)
    ap.add_argument("--rate-limit", type=int, default=2500,
                    help="Max FMP calls/minute")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", action="store_true", default=True,
                    help="Skip tickers already in stock_peers (default on)")
    ap.add_argument("--summary-path", default="")
    args = ap.parse_args()

    if not FMP_KEY:
        print(f"{TAG} ERROR: FMP_KEY not set", flush=True)
        sys.exit(2)

    if not args.summary_path:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M")
        args.summary_path = (
            f"/mnt/g/My Drive/eidolum.prompts/_alerts/"
            f"stock_peers_harvest_{ts}_SUMMARY.md"
        )
    _stats["summary_path"] = args.summary_path

    atexit.register(_write_summary)
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    tickers = _load_tickers(args.tickers)
    _stats["tickers_total"] = len(tickers)
    print(f"{TAG} loaded {len(tickers):,} tickers from {args.tickers}", flush=True)
    if args.limit > 0:
        tickers = tickers[:args.limit]
        print(f"{TAG} limit applied → {len(tickers)} tickers", flush=True)

    delay_sec = 60.0 / max(1, args.rate_limit)
    db = BgSessionLocal()

    last_call_t = 0.0
    last_progress_t = time.time()

    for i, ticker in enumerate(tickers):
        if _is_foreign(ticker):
            _stats["tickers_skipped_foreign"] += 1
            continue
        if args.resume and _ticker_already_done(db, ticker):
            _stats["tickers_skipped_resume"] += 1
            continue

        # rate-limit pace
        elapsed = time.time() - last_call_t
        if elapsed < delay_sec:
            time.sleep(delay_sec - elapsed)
        last_call_t = time.time()

        peers, status = _fetch_peers(ticker)
        _stats["tickers_processed"] += 1
        _stats["by_status"][status] = _stats["by_status"].get(status, 0) + 1

        if status != "200":
            _stats["tickers_errors"] += 1
            continue

        if not peers:
            _stats["tickers_with_no_peers"] += 1
            continue

        inserted = _insert_peers(db, ticker, peers)
        _stats["peer_rows_inserted"] += inserted

        if (_stats["tickers_processed"]) % args.batch_commit == 0:
            try:
                db.commit()
            except Exception as e:
                print(f"{TAG} commit err: {e}", flush=True)
                db.rollback()

        if i == 0 or time.time() - last_progress_t > 30:
            print(
                f"{TAG} i={i+1}/{len(tickers)} processed={_stats['tickers_processed']} "
                f"peers={_stats['peer_rows_inserted']:,} "
                f"skip_foreign={_stats['tickers_skipped_foreign']} "
                f"skip_resume={_stats['tickers_skipped_resume']} "
                f"no_peers={_stats['tickers_with_no_peers']} "
                f"errors={_stats['tickers_errors']}",
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
        f"\n{TAG} done — peers={_stats['peer_rows_inserted']:,} "
        f"tickers_processed={_stats['tickers_processed']:,} "
        f"skipped_foreign={_stats['tickers_skipped_foreign']:,} "
        f"skipped_resume={_stats['tickers_skipped_resume']:,}",
        flush=True,
    )


if __name__ == "__main__":
    main()

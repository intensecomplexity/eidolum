"""
fmp_endgame_harvest.py — "use it before you lose it" harvest of the remaining
high-value FMP /stable/ datasets, BEFORE the FMP Ultimate plan is cancelled.

Complements fmp_ultimate_harvest.py (wave 1) and the wave-2 tables. Captures the
gaps confirmed by the STEP-1 audit: earnings-call transcripts, crypto/forex EOD,
price-target & grade news, historical market cap, full 13F holdings, stock news,
index constituents, economic calendar, and P9 nice-to-haves.

Dual sink, every dataset persisted in the SAME pass that fetches it:
  (1) COMPLETE local archive on the laptop disk  (parquet/snappy or jsonl.gz),
      partitioned so files stay manageable — the source of truth for firehoses.
  (2) the bounded/queryable subset additionally loaded into Railway Postgres.

Design / safety (matches fmp_ultimate_harvest.py conventions):
  * /stable/ only; reuses that module's httpx transport with 429/5xx
    exponential backoff, the Rate limiter, execute_values upsert (::type casts,
    page_size=5000, dedup-by-PK), map_rows, row_hash, KIND.
  * Connects ONLY as the least-priv app_worker role, over the public host
    (app_worker creds spliced onto the Postgres public host:port — the URL is
    never printed or written to disk). NO superuser, NO DDL: tables are created
    out-of-band by `fmp_endgame_tables.sql`; this script verifies a table exists
    and, if so, loads it — otherwise it archives only and tells you to run the
    SQL. Run `--print-ddl` to (re)generate that SQL from the specs below.
  * Idempotent + resumable: sibling checkpoint
    _artifacts/fmp_endgame_harvest_checkpoint.json at (dataset, symbol/page)
    granularity. A kill loses at most one in-flight batch; a resume is a top-up.
  * Storage guards: Postgres kept < ~30GB (firehoses never touch PG); archive
    kept < MAX_ARCHIVE_GB (default 120) and paused if /mnt/c free < 60GB.
  * SIGINT/SIGTERM flush the parquet buffers + checkpoint before exiting.

Run (from backend/), data as app_worker, FMP_KEY from the worker service:
    export PG_PUBLIC_URL="$(railway run -s Postgres python3 -c \
       'import os;print(os.environ["DATABASE_PUBLIC_URL"])' 2>/dev/null | tail -1)"
    railway run -s hopeful-expression python3 scripts/fmp_endgame_harvest.py \
       [--only p1,p2] [--skip p5] [--from-priority p3] [--limit N] [--probe-only]

    # generate the CREATE+GRANT SQL (no DB / no network needed):
    python3 scripts/fmp_endgame_harvest.py --print-ddl > scripts/fmp_endgame_tables.sql
"""
import argparse
import atexit
import gzip
import json
import os
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse, urlunparse

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Reuse wave-1 helpers verbatim (httpx transport + backoff, rate limiter, DB I/O)
from fmp_ultimate_harvest import (  # noqa: E402
    _get_json, Rate, upsert, map_rows, row_hash, db_size_gb, KIND,
    _f, _i, _s, _d,
)

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

TAG = "[fmp-endgame]"
ART = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_artifacts")
CHECKPOINT = os.path.join(ART, "fmp_endgame_harvest_checkpoint.json")
ARCHIVE_ROOT = os.environ.get("FMP_ARCHIVE_ROOT", "/mnt/c/Users/yarde/eidolum_fmp_archive")
MAX_ARCHIVE_GB = float(os.environ.get("MAX_ARCHIVE_GB", "120"))
DB_GUARD_GB = float(os.environ.get("FMP_DB_GUARD_GB", "30"))
MIN_FREE_GB_FIREHOSE = 60.0

FOREIGN_SUFFIXES = (".L", ".HK", ".DE", ".TO", ".PA", ".MI", ".F", ".SZ", ".KS",
                    ".V", ".AX", ".T", ".MX", ".BO", ".NS", ".SW", ".ST", ".HE",
                    ".OL", ".VI", ".BR", ".LS", ".MC", ".IL", ".SA", ".JK", ".TW")

_STOP = False
_WRITERS = []           # parquet writers to flush on exit
_stats = {}             # dataset -> dict(fetched, pg, arch_rows, arch_bytes)


def log(msg):
    print(f"{TAG} {msg}", flush=True)


def st(ds):
    return _stats.setdefault(ds, {"fetched": 0, "pg": 0, "arch_rows": 0, "arch_bytes": 0})


# ───────────────────────────────────────────────── connection (app_worker only)
def resolve_app_worker_url():
    """app_worker creds (worker DATABASE_URL, internal host) spliced onto the
    public host:port/db/query from the Postgres DATABASE_PUBLIC_URL. Never logged."""
    dburl = os.environ.get("DATABASE_URL")
    pub = os.environ.get("PG_PUBLIC_URL") or os.environ.get("DATABASE_PUBLIC_URL")
    if not dburl:
        sys.exit(f"{TAG} ERROR: DATABASE_URL (app_worker) absent from env")
    u = urlparse(dburl)
    if u.hostname and not u.hostname.endswith("railway.internal"):
        return dburl
    if not pub:
        sys.exit(f"{TAG} ERROR: PG_PUBLIC_URL needed to reach app_worker over public host")
    p = urlparse(pub)
    netloc = f"{u.username}:{u.password}@{p.hostname}:{p.port}"
    return urlunparse((p.scheme, netloc, p.path or u.path, "", p.query, ""))


def app_connect():
    c = psycopg2.connect(resolve_app_worker_url())
    c.autocommit = False
    return c


def table_exists(conn, table):
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (f"public.{table}",))
        return cur.fetchone()[0] is not None


def safe_db_gb(conn):
    try:
        return db_size_gb(conn)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return 0.0


# ───────────────────────────────────────────────── archive sinks
class Archive:
    """Tracks archive byte budget across all writers."""
    def __init__(self, root, max_gb):
        self.root = root
        self.max_bytes = max_gb * 1e9
        os.makedirs(root, exist_ok=True)
        self.base = self._dirsize(root)
        self.added = 0
        free = self._free_gb()
        self.firehose_ok = free >= MIN_FREE_GB_FIREHOSE
        log(f"archive root={root} existing={self.base/1e9:.2f}GB cap={max_gb}GB "
            f"/mnt/c free={free:.1f}GB firehose={'ON' if self.firehose_ok else 'PAUSED(<60GB free)'}")
        if not self.firehose_ok:
            log("!!! WARNING: <60GB free on archive volume — firehose datasets "
                "(transcripts/13F/news) PAUSED; bounded datasets still run.")

    @staticmethod
    def _free_gb():
        import shutil
        try:
            return shutil.disk_usage(ARCHIVE_ROOT if os.path.isdir(ARCHIVE_ROOT)
                                     else os.path.dirname(ARCHIVE_ROOT)).free / 1e9
        except Exception:
            try:
                return __import__("shutil").disk_usage("/mnt/c").free / 1e9
            except Exception:
                return 1e9

    @staticmethod
    def _dirsize(p):
        tot = 0
        for dp, _, fs in os.walk(p):
            for f in fs:
                try:
                    tot += os.path.getsize(os.path.join(dp, f))
                except OSError:
                    pass
        return tot

    def used_gb(self):
        return (self.base + self.added) / 1e9

    def has_room(self):
        return (self.base + self.added) < self.max_bytes

    def note(self, nbytes):
        self.added += nbytes


def _to_table(rows):
    """pyarrow Table from list-of-dicts, with an all-string fallback for the
    messy mixed-type columns FMP occasionally returns."""
    norm = []
    for r in rows:
        o = {}
        for k, v in r.items():
            o[k] = v if (v is None or isinstance(v, (int, float, bool, str))) \
                else json.dumps(v, ensure_ascii=False)
        norm.append(o)
    try:
        return pa.Table.from_pylist(norm)
    except (pa.ArrowInvalid, pa.ArrowTypeError, pa.ArrowNotImplementedError):
        keys = []
        seen = set()
        for r in norm:
            for k in r:
                if k not in seen:
                    seen.add(k); keys.append(k)
        srows = [{k: (None if r.get(k) is None else str(r.get(k))) for k in keys} for r in norm]
        return pa.Table.from_pylist(srows)


class PQWriter:
    """Partitioned snappy-parquet writer. add(partition, rows) buffers; flushes
    to part-NNNNN.parquet per partition at flush_rows or on close."""
    def __init__(self, archive, dataset, flush_rows=100_000):
        self.archive = archive
        self.dataset = dataset
        self.dir = os.path.join(archive.root, dataset)
        os.makedirs(self.dir, exist_ok=True)
        self.buf = {}
        self.idx = {}
        self.flush_rows = flush_rows
        _WRITERS.append(self)

    def add(self, partition, rows):
        if not rows:
            return
        part = str(partition) if partition not in (None, "") else "_"
        b = self.buf.setdefault(part, [])
        b.extend(rows)
        st(self.dataset)["arch_rows"] += len(rows)
        if len(b) >= self.flush_rows:
            self.flush(part)

    def flush(self, partition=None):
        parts = [partition] if partition is not None else list(self.buf.keys())
        for part in parts:
            rows = self.buf.get(part)
            if not rows:
                continue
            subdir = self.dir if part == "_" else os.path.join(self.dir, part)
            os.makedirs(subdir, exist_ok=True)
            i = self.idx.get(part, 0)
            path = os.path.join(subdir, f"part-{i:05d}.parquet")
            try:
                pq.write_table(_to_table(rows), path, compression="snappy")
                self.idx[part] = i + 1
                self.buf[part] = []
                nb = os.path.getsize(path)
                self.archive.note(nb)
                st(self.dataset)["arch_bytes"] += nb
            except Exception as e:
                log(f"PARQUET write failed {self.dataset}/{part}: {type(e).__name__}: {e}")
                self.buf[part] = []

    def close(self):
        self.flush()


def write_jsonl_gz(archive, dataset, relpath, objs):
    path = os.path.join(archive.root, dataset, relpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for o in objs:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    nb = os.path.getsize(path)
    archive.note(nb)
    s = st(dataset)
    s["arch_rows"] += len(objs)
    s["arch_bytes"] += nb
    return os.path.join(dataset, relpath), nb


def _flush_all():
    for w in _WRITERS:
        try:
            w.close()
        except Exception:
            pass


atexit.register(_flush_all)


def _sig(*_a):
    global _STOP
    _STOP = True
    log("SIGINT/SIGTERM received — finishing current batch, then flushing buffers + checkpoint")


signal.signal(signal.SIGINT, _sig)
signal.signal(signal.SIGTERM, _sig)


# ───────────────────────────────────────────────── checkpoint
def load_cp():
    try:
        with open(CHECKPOINT) as f:
            return json.load(f)
    except Exception:
        return {}


def save_cp(cp):
    os.makedirs(os.path.dirname(CHECKPOINT), exist_ok=True)
    tmp = CHECKPOINT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cp, f)
    os.replace(tmp, CHECKPOINT)


# ═══════════════════════════════════════════════════════ TABLE SPECS (col, src, kind)
EOD = [("symbol", "symbol", "s"), ("date", "date", "d"), ("open", "open", "f"),
       ("high", "high", "f"), ("low", "low", "f"), ("close", "close", "f"),
       ("volume", "volume", "i"), ("change", "change", "f"),
       ("change_percent", "changePercent", "f"), ("vwap", "vwap", "f")]

TRANSCRIPT_IDX = [("symbol", "symbol", "s"), ("year", "year", "i"),
                  ("quarter", "quarter", "i"), ("call_date", "date", "d"),
                  ("n_chars", "n_chars", "i"), ("archive_path", "archive_path", "s")]

PT_NEWS = [("row_hash", "", "s"), ("symbol", "symbol", "s"),
           ("published_date", "publishedDate", "s"), ("news_url", "newsURL", "s"),
           ("news_title", "newsTitle", "s"), ("analyst_name", "analystName", "s"),
           ("price_target", "priceTarget", "f"), ("adj_price_target", "adjPriceTarget", "f"),
           ("price_when_posted", "priceWhenPosted", "f"),
           ("news_publisher", "newsPublisher", "s"), ("news_base_url", "newsBaseURL", "s"),
           ("analyst_company", "analystCompany", "s")]

GRADE_NEWS = [("row_hash", "", "s"), ("symbol", "symbol", "s"),
              ("published_date", "publishedDate", "s"), ("news_url", "newsURL", "s"),
              ("news_title", "newsTitle", "s"), ("news_base_url", "newsBaseURL", "s"),
              ("news_publisher", "newsPublisher", "s"), ("new_grade", "newGrade", "s"),
              ("previous_grade", "previousGrade", "s"), ("grading_company", "gradingCompany", "s"),
              ("action", "action", "s"), ("price_when_posted", "priceWhenPosted", "f")]

MKTCAP = [("symbol", "symbol", "s"), ("date", "date", "d"), ("market_cap", "marketCap", "i")]

IDX_CONST = [("index_name", "index", "s"), ("symbol", "symbol", "s"), ("name", "name", "s"),
             ("sector", "sector", "s"), ("sub_sector", "subSector", "s"),
             ("headquarter", "headQuarter", "s"), ("date_first_added", "dateFirstAdded", "s"),
             ("cik", "cik", "s"), ("founded", "founded", "s")]

IDX_CHG = [("row_hash", "", "s"), ("index_name", "index", "s"), ("date_added", "dateAdded", "s"),
           ("added_security", "addedSecurity", "s"), ("removed_ticker", "removedTicker", "s"),
           ("removed_security", "removedSecurity", "s"), ("date", "date", "s"),
           ("symbol", "symbol", "s"), ("reason", "reason", "s")]

ECON_CAL = [("row_hash", "", "s"), ("event_date", "date", "s"), ("country", "country", "s"),
            ("event", "event", "s"), ("currency", "currency", "s"),
            ("previous", "previous", "f"), ("estimate", "estimate", "f"),
            ("actual", "actual", "f"), ("change", "change", "f"), ("impact", "impact", "s"),
            ("change_percentage", "changePercentage", "f"), ("unit", "unit", "s")]

DCF = [("symbol", "symbol", "s"), ("date", "date", "d"), ("dcf", "dcf", "f"),
       ("levered_dcf", "levered_dcf", "f"), ("stock_price", "Stock Price", "f")]

MNA = [("row_hash", "", "s"), ("symbol", "symbol", "s"), ("company_name", "companyName", "s"),
       ("cik", "cik", "s"), ("targeted_company", "targetedCompanyName", "s"),
       ("targeted_cik", "targetedCik", "s"), ("targeted_symbol", "targetedSymbol", "s"),
       ("transaction_date", "transactionDate", "d"), ("accepted_date", "acceptedDate", "s"),
       ("link", "link", "s")]

IPOS = [("symbol", "symbol", "s"), ("date", "date", "d"), ("company", "company", "s"),
        ("exchange", "exchange", "s"), ("actions", "actions", "s"), ("shares", "shares", "i"),
        ("price_range", "priceRange", "s"), ("market_cap", "marketCap", "i")]

ETF_HOLD = [("etf", "etf", "s"), ("asset", "asset", "s"), ("name", "name", "s"),
            ("isin", "isin", "s"), ("cusip", "securityCusip", "s"),
            ("shares", "sharesNumber", "f"), ("weight_percentage", "weightPercentage", "f"),
            ("market_value", "marketValue", "f"), ("updated_at", "updatedAt", "s")]

ETF_WEIGHT = [("etf", "etf", "s"), ("kind", "kind", "s"), ("label", "label", "s"),
              ("weight_percentage", "weightPercentage", "f")]

SEC8K = [("row_hash", "", "s"), ("symbol", "symbol", "s"), ("cik", "cik", "s"),
         ("filing_date", "filingDate", "s"), ("accepted_date", "acceptedDate", "s"),
         ("form_type", "formType", "s"), ("has_financials", "hasFinancials", "s"),
         ("link", "link", "s"), ("final_link", "finalLink", "s")]

# table -> (columns, pk_cols, [extra index cols])
TABLES = {
    "fmp_crypto_prices":           (EOD, ["symbol", "date"], ["symbol"]),
    "fmp_transcript_index":        (TRANSCRIPT_IDX, ["symbol", "year", "quarter"], ["symbol"]),
    "fmp_price_target_news":       (PT_NEWS, ["row_hash"], ["symbol"]),
    "fmp_grade_news":              (GRADE_NEWS, ["row_hash"], ["symbol"]),
    "fmp_historical_market_cap":   (MKTCAP, ["symbol", "date"], ["symbol"]),
    "fmp_index_constituents":      (IDX_CONST, ["index_name", "symbol"], []),
    "fmp_index_constituent_changes": (IDX_CHG, ["row_hash"], ["index_name"]),
    "fmp_economic_calendar":       (ECON_CAL, ["row_hash"], ["event_date"]),
    "fmp_dcf":                     (DCF, ["symbol", "date"], ["symbol"]),
    "fmp_mergers_acquisitions":    (MNA, ["row_hash"], ["symbol"]),
    "fmp_ipos_calendar":           (IPOS, ["symbol", "date"], []),
    "fmp_etf_holdings":            (ETF_HOLD, ["etf", "asset"], ["etf"]),
    "fmp_etf_weightings":          (ETF_WEIGHT, ["etf", "kind", "label"], ["etf"]),
    "fmp_sec_filings":             (SEC8K, ["row_hash"], ["symbol"]),
}


# row_hash field sets — shared by harvest AND reload so they never diverge
PT_HASH = ["symbol", "published_date", "news_url", "analyst_company", "price_target"]
GRADE_HASH = ["symbol", "published_date", "news_url", "grading_company", "new_grade"]
CHG_HASH = ["index_name", "date", "symbol", "added_security", "removed_ticker", "reason"]
CAL_HASH = ["event_date", "country", "event"]
MNA_HASH = ["symbol", "targeted_symbol", "transaction_date", "link"]
SEC_HASH = ["cik", "accepted_date", "form_type", "final_link"]

# archive-dir → (pg_table, columns, pk, conflict, hash_fields) for --reload-pg-from-archive
RELOAD = [
    ("crypto_eod", "fmp_crypto_prices", EOD, ["symbol", "date"], "nothing", None),
    ("forex_eod", "fmp_forex", EOD, ["symbol", "date"], "nothing", None),
    ("historical_market_cap", "fmp_historical_market_cap", MKTCAP, ["symbol", "date"], "nothing", None),
    ("price_target_news", "fmp_price_target_news", PT_NEWS, ["row_hash"], "nothing", PT_HASH),
    ("grade_news", "fmp_grade_news", GRADE_NEWS, ["row_hash"], "nothing", GRADE_HASH),
    ("index_constituents/current", "fmp_index_constituents", IDX_CONST, ["index_name", "symbol"], "update", None),
    ("index_constituents/changes", "fmp_index_constituent_changes", IDX_CHG, ["row_hash"], "nothing", CHG_HASH),
    ("economic_calendar", "fmp_economic_calendar", ECON_CAL, ["row_hash"], "update", CAL_HASH),
    ("dcf", "fmp_dcf", DCF, ["symbol", "date"], "update", None),
    ("mergers_acquisitions", "fmp_mergers_acquisitions", MNA, ["row_hash"], "nothing", MNA_HASH),
    ("ipos_calendar", "fmp_ipos_calendar", IPOS, ["symbol", "date"], "update", None),
    ("etf_holdings", "fmp_etf_holdings", ETF_HOLD, ["etf", "asset"], "update", None),
    ("etf_weightings", "fmp_etf_weightings", ETF_WEIGHT, ["etf", "kind", "label"], "update", None),
    ("sec_filings_8k", "fmp_sec_filings", SEC8K, ["row_hash"], "nothing", SEC_HASH),
]


def gen_ddl():
    """Emit CREATE TABLE IF NOT EXISTS + GRANT for every new table, matching
    fmp_ultimate_harvest.ensure_table exactly (fetched_at + source defaults)."""
    out = ["-- fmp_endgame_tables.sql — run as a privileged role (table owner).",
           "-- Generated by fmp_endgame_harvest.py --print-ddl. app_worker only",
           "-- gets SELECT/INSERT/UPDATE; the harvest never runs DDL.",
           "BEGIN;", ""]
    for table, (columns, pk, idxs) in TABLES.items():
        defs = []
        for name, _src, kind in columns:
            nn = " NOT NULL" if name in pk else ""
            defs.append(f"  {name} {KIND[kind][1]}{nn}")
        defs.append("  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()")
        defs.append("  source VARCHAR(16) NOT NULL DEFAULT 'fmp'")
        defs.append(f"  PRIMARY KEY ({', '.join(pk)})")
        out.append(f"CREATE TABLE IF NOT EXISTS {table} (\n" + ",\n".join(defs) + "\n);")
        out.append(f"GRANT SELECT, INSERT, UPDATE ON {table} TO app_worker;")
        for ic in idxs:
            out.append(f"CREATE INDEX IF NOT EXISTS {table}_{ic}_idx ON {table} ({ic});")
        out.append("")
    out.append("-- forex top-up reuses the existing fmp_forex table:")
    out.append("GRANT SELECT, INSERT, UPDATE ON fmp_forex TO app_worker;")
    out.append("")
    out.append("COMMIT;")
    return "\n".join(out)


# ═══════════════════════════════════════════════════════ universe
def is_foreign(sym):
    return any(sym.endswith(s) for s in FOREIGN_SUFFIXES)


def build_universe(conn, cp):
    if cp.get("_universe"):
        return cp["_universe"]
    syms, seen = [], set()

    def add(s):
        s = (s or "").strip().upper()
        if s and s not in seen:
            seen.add(s); syms.append(s)

    with conn.cursor() as cur:
        cur.execute("SELECT ticker, count(*) c FROM predictions "
                    "WHERE ticker IS NOT NULL AND ticker<>'' GROUP BY ticker ORDER BY c DESC")
        for t, _ in cur.fetchall():
            add(t)
    for ep in ("sp500-constituent", "nasdaq-constituent", "dowjones-constituent"):
        for r in (_get_json(ep) or []):
            add(r.get("symbol"))
    with conn.cursor() as cur:
        cur.execute("SELECT symbol FROM fmp_stock_list WHERE symbol IS NOT NULL")
        for (s,) in cur.fetchall():
            add(s)
    cp["_universe"] = syms
    save_cp(cp)
    log(f"universe built: {len(syms):,} symbols (predictions → constituents → stock_list)")
    return syms


# ═══════════════════════════════════════════════════════ generic per-symbol driver
def per_symbol(ctx, ds, cp_key, symbols, fetch_fn, on_batch, batch=200,
               guard_pg=True, firehose=False):
    """Fan out fetch_fn(symbol)->raw across symbols under the rate limiter;
    on_batch(list[(symbol, raw)]) archives + upserts on the main thread.
    Resumable via cp[cp_key]['hw'] (high-water index into `symbols`)."""
    cp = ctx["cp"]
    hw = cp.get(cp_key, {}).get("hw", 0)
    todo = symbols[hw:]
    if not todo:
        log(f"{ds}: already complete ({hw:,}/{len(symbols):,})")
        return
    t0 = time.time()
    for b in range(0, len(todo), batch):
        if _STOP:
            break
        if firehose and not ctx["archive"].firehose_ok:
            log(f"{ds}: firehose paused (low disk) — skipping")
            return
        if firehose and not ctx["archive"].has_room():
            log(f"{ds}: archive cap {MAX_ARCHIVE_GB}GB reached — stopping")
            return
        if guard_pg and safe_db_gb(ctx["conn"]) >= DB_GUARD_GB:
            log(f"{ds}: DB guard {DB_GUARD_GB}GB reached — stopping PG-bound dataset")
            return
        chunk = todo[b:b + batch]
        collected = []
        with ThreadPoolExecutor(max_workers=ctx["workers"]) as ex:
            futs = {ex.submit(_guarded_fetch, ctx, fetch_fn, s): s for s in chunk}
            for fut in as_completed(futs):
                raw = fut.result()
                if raw:
                    collected.append((futs[fut], raw))
        try:
            on_batch(collected)
        except Exception as e:
            log(f"{ds}: on_batch error {type(e).__name__}: {e}")
            try:
                ctx["conn"].rollback()
            except Exception:
                pass
        hw += len(chunk)
        cp[cp_key] = {"hw": hw}
        save_cp(cp)
        rate = hw / max(1e-6, time.time() - t0)
        log(f"{ds}: {hw:,}/{len(symbols):,} symbols  fetched={st(ds)['fetched']:,} "
            f"pg={st(ds)['pg']:,} arch={st(ds)['arch_rows']:,}  ({rate*60:.0f}/min)")


def _guarded_fetch(ctx, fetch_fn, symbol):
    try:
        ctx["rate"].wait()
        return fetch_fn(ctx, symbol)
    except Exception as e:
        log(f"fetch err {symbol}: {type(e).__name__}: {e}")
        return None


def _upsert_if(ctx, table, columns, pk, rows, conflict, ds):
    """Upsert only if the table exists (else archive-only); count PG rows."""
    if not rows or table not in ctx["present"]:
        return
    n = upsert(ctx["conn"], table, columns, pk, rows, conflict=conflict)
    st(ds)["pg"] += n


def _hash_rows(rows, fields):
    for r in rows:
        r["row_hash"] = row_hash(r, fields)
    return rows


# ═══════════════════════════════════════════════════════ P1 transcripts
def _fetch_transcripts(ctx, symbol):
    dates = _get_json("earning-call-transcript-dates", {"symbol": symbol})
    if not dates:
        return None
    objs = []
    for d in dates:
        if _STOP:
            break
        yr, q = d.get("fiscalYear"), d.get("quarter")
        if yr is None or q is None:
            continue
        ctx["rate"].wait()
        tr = _get_json("earning-call-transcript", {"symbol": symbol, "year": yr, "quarter": q})
        if not tr or not isinstance(tr[0], dict):
            continue
        o = tr[0]
        objs.append({"symbol": symbol, "year": _i(yr), "quarter": _i(q),
                     "date": o.get("date"), "content": o.get("content") or ""})
    return objs or None


def harvest_p1_transcripts(ctx):
    if not ctx["archive"].firehose_ok:
        log("p1 transcripts: firehose paused (low disk) — skipping")
        return
    eq = [s for s in ctx["universe"] if not is_foreign(s)]

    def on_batch(collected):
        idx_rows = []
        for symbol, objs in collected:
            st("p1_transcripts")["fetched"] += len(objs)
            rel = os.path.join(symbol[0].upper() if symbol[:1].isalnum() else "_",
                               f"{symbol}.jsonl.gz")
            apath, _ = write_jsonl_gz(ctx["archive"], "transcripts", rel, objs)
            for o in objs:
                idx_rows.append({"symbol": o["symbol"], "year": o["year"],
                                 "quarter": o["quarter"], "call_date": _d(o.get("date")),
                                 "n_chars": len(o.get("content") or ""), "archive_path": apath})
        cols, pk, _ = TABLES["fmp_transcript_index"]
        _upsert_if(ctx, "fmp_transcript_index", cols, pk, idx_rows, "update", "p1_transcripts")

    per_symbol(ctx, "p1_transcripts", "p1_transcripts", eq, _fetch_transcripts,
               on_batch, batch=120, guard_pg=False, firehose=True)


# ═══════════════════════════════════════════════════════ P2 crypto / forex EOD
def _fetch_eod(ctx, symbol):
    raw = _get_json("historical-price-eod/full", {"symbol": symbol})
    if not raw:
        return None
    for r in raw:
        r.setdefault("symbol", symbol)
    return raw


def _harvest_eod(ctx, ds, cp_key, list_endpoint, pg_table, archive_ds):
    cp = ctx["cp"]
    cache = f"_{cp_key}_syms"
    syms = cp.get(cache)
    if not syms:
        listing = _get_json(list_endpoint) or []
        syms = sorted({(r.get("symbol") or "").strip().upper()
                       for r in listing if r.get("symbol")})
        cp[cache] = syms
        save_cp(cp)
    # skip symbols already present in the PG table (saves quota on resume/top-up)
    have = set()
    if pg_table in ctx["present"]:
        with ctx["conn"].cursor() as cur:
            cur.execute(f"SELECT DISTINCT symbol FROM {pg_table}")
            have = {r[0] for r in cur.fetchall()}
    todo = [s for s in syms if s not in have]
    log(f"{ds}: {len(syms):,} listed, {len(have):,} already in PG → {len(todo):,} to fetch")

    def on_batch(collected):
        arch, prows = [], []
        for symbol, raw in collected:
            st(ds)["fetched"] += len(raw)
            arch.extend(raw)
            prows.extend(map_rows(raw, EOD))
        if arch:
            ctx["pq"][archive_ds].add(arch[0]["symbol"][0].upper()
                                      if arch[0].get("symbol") else "_", arch)
        prows = [r for r in prows if r.get("symbol") and r.get("date")]
        _upsert_if(ctx, pg_table, EOD, ["symbol", "date"], prows, "nothing", ds)

    per_symbol(ctx, ds, cp_key, todo, _fetch_eod, on_batch, batch=200,
               guard_pg=True, firehose=False)


def harvest_p2_crypto(ctx):
    ctx["pq"].setdefault("crypto_eod", PQWriter(ctx["archive"], "crypto_eod"))
    _harvest_eod(ctx, "p2_crypto", "p2_crypto", "cryptocurrency-list",
                 "fmp_crypto_prices", "crypto_eod")


def harvest_p2_forex(ctx):
    ctx["pq"].setdefault("forex_eod", PQWriter(ctx["archive"], "forex_eod"))
    _harvest_eod(ctx, "p2_forex", "p2_forex", "forex-list", "fmp_forex", "forex_eod")


# ═══════════════════════════════════════════════════════ P3 PT news / grade news
def _paginate_symbol(endpoint, symbol, max_pages=20, page_size=100):
    out = []
    for page in range(max_pages):
        raw = _get_json(endpoint, {"symbol": symbol, "page": page, "limit": page_size})
        if not raw:
            break
        out.extend(raw)
        if len(raw) < page_size:
            break
    return out


def _harvest_news(ctx, ds, cp_key, endpoint, pg_table, cols, hash_fields, archive_ds):
    ctx["pq"].setdefault(archive_ds, PQWriter(ctx["archive"], archive_ds))
    eq = [s for s in ctx["universe"] if not is_foreign(s)]

    def fetch(ctx_, symbol):
        rows = _paginate_symbol(endpoint, symbol)
        return rows or None

    def on_batch(collected):
        arch, prows = [], []
        for symbol, raw in collected:
            st(ds)["fetched"] += len(raw)
            for r in raw:
                r.setdefault("symbol", symbol)
            arch.extend(raw)
            mapped = map_rows(raw, cols)
            _hash_rows(mapped, hash_fields)
            prows.extend(mapped)
        if arch:
            ctx["pq"][archive_ds].add(arch[0].get("symbol", "_")[:1].upper() or "_", arch)
        _upsert_if(ctx, pg_table, cols, ["row_hash"], prows, "nothing", ds)

    per_symbol(ctx, ds, cp_key, eq, fetch, on_batch, batch=200, guard_pg=True)


def harvest_p3_pt_news(ctx):
    _harvest_news(ctx, "p3_pt_news", "p3_pt_news", "price-target-news",
                  "fmp_price_target_news", PT_NEWS, PT_HASH, "price_target_news")


def harvest_p3_grade_news(ctx):
    _harvest_news(ctx, "p3_grade_news", "p3_grade_news", "grades-news",
                  "fmp_grade_news", GRADE_NEWS, GRADE_HASH, "grade_news")


# ═══════════════════════════════════════════════════════ P4 historical market cap
def _fetch_mktcap(ctx, symbol):
    raw = _get_json("historical-market-capitalization", {"symbol": symbol, "limit": 100000})
    if not raw:
        return None
    for r in raw:
        r.setdefault("symbol", symbol)
    return raw


def harvest_p4_mktcap(ctx):
    ctx["pq"].setdefault("historical_market_cap", PQWriter(ctx["archive"], "historical_market_cap"))
    eq = [s for s in ctx["universe"] if not is_foreign(s)]

    def on_batch(collected):
        arch, prows = [], []
        for symbol, raw in collected:
            st("p4_mktcap")["fetched"] += len(raw)
            arch.extend(raw)
            prows.extend(map_rows(raw, MKTCAP))
        if arch:
            ctx["pq"]["historical_market_cap"].add(
                arch[0]["symbol"][:1].upper() if arch[0].get("symbol") else "_", arch)
        prows = [r for r in prows if r.get("symbol") and r.get("date")]
        _upsert_if(ctx, "fmp_historical_market_cap", MKTCAP, ["symbol", "date"],
                   prows, "nothing", "p4_mktcap")

    per_symbol(ctx, "p4_mktcap", "p4_mktcap", eq, _fetch_mktcap, on_batch,
               batch=200, guard_pg=True)


# ═══════════════════════════════════════════════════════ P7 index constituents
def harvest_p7_constituents(ctx):
    if ctx["cp"].get("p7_constituents", {}).get("done"):
        log("p7 constituents: already done")
        return
    ctx["pq"].setdefault("index_constituents", PQWriter(ctx["archive"], "index_constituents"))
    cur_rows, chg_rows, arch_cur, arch_chg = [], [], [], []
    for index, ep in (("sp500", "sp500-constituent"), ("nasdaq", "nasdaq-constituent"),
                      ("dow", "dowjones-constituent")):
        raw = _get_json(ep) or []
        for r in raw:
            r["index"] = index
        arch_cur.extend(raw)
        cur_rows.extend(map_rows(raw, IDX_CONST))
        st("p7_constituents")["fetched"] += len(raw)
    for index, ep in (("sp500", "historical-sp500-constituent"),
                      ("nasdaq", "historical-nasdaq-constituent"),
                      ("dow", "historical-dowjones-constituent")):
        raw = _get_json(ep) or []
        for r in raw:
            r["index"] = index
        arch_chg.extend(raw)
        mapped = map_rows(raw, IDX_CHG)
        _hash_rows(mapped, CHG_HASH)
        chg_rows.extend(mapped)
        st("p7_constituents")["fetched"] += len(raw)
    ctx["pq"]["index_constituents"].add("current", arch_cur)
    ctx["pq"]["index_constituents"].add("changes", arch_chg)
    _upsert_if(ctx, "fmp_index_constituents", IDX_CONST, ["index_name", "symbol"],
               cur_rows, "update", "p7_constituents")
    _upsert_if(ctx, "fmp_index_constituent_changes", IDX_CHG, ["row_hash"],
               chg_rows, "nothing", "p7_constituents")
    ctx["cp"]["p7_constituents"] = {"done": True}
    save_cp(ctx["cp"])
    log(f"p7 constituents: current={len(cur_rows)} changes={len(chg_rows)}")


# ═══════════════════════════════════════════════════════ P8 economic calendar
def harvest_p8_calendar(ctx):
    ctx["pq"].setdefault("economic_calendar", PQWriter(ctx["archive"], "economic_calendar"))
    cp = ctx["cp"]
    done = set(cp.get("p8_calendar", {}).get("done", []))
    this_year = datetime.utcnow().year
    units = [(y, q) for y in range(2008, this_year + 1) for q in range(4)]
    for y, q in units:
        if _STOP:
            break
        key = f"{y}Q{q}"
        if key in done:
            continue
        frm = f"{y}-{q*3+1:02d}-01"
        to = f"{y}-{q*3+3:02d}-28"
        raw = _get_json("economic-calendar", {"from": frm, "to": to})
        if raw is None:
            log(f"p8 calendar {key}: transient fail — retry next run")
            continue
        st("p8_calendar")["fetched"] += len(raw)
        ctx["pq"]["economic_calendar"].add(str(y), raw)
        mapped = map_rows(raw, ECON_CAL)
        _hash_rows(mapped, CAL_HASH)
        _upsert_if(ctx, "fmp_economic_calendar", ECON_CAL, ["row_hash"], mapped, "update", "p8_calendar")
        done.add(key)
        cp["p8_calendar"] = {"done": sorted(done)}
        save_cp(cp)
    log(f"p8 calendar: fetched={st('p8_calendar')['fetched']:,}")


# ═══════════════════════════════════════════════════════ P5 full 13F holdings (archive-only firehose)
def harvest_p5_13f(ctx):
    if not ctx["archive"].firehose_ok:
        log("p5 13F: firehose paused (low disk) — skipping")
        return
    ctx["pq"].setdefault("inst_holdings", PQWriter(ctx["archive"], "inst_holdings"))
    cp = ctx["cp"]
    p5 = cp.setdefault("p5_13f", {})
    # Phase A: enumerate (cik, year, quarter) units via the latest-filings feed
    units = p5.get("units")
    if units is None:
        seen, ulist = set(), []
        page = p5.get("enum_page", 0)
        max_pages = ctx["args"].max_pages or 600
        while page < max_pages and not _STOP:
            ctx["rate"].wait()
            raw = _get_json("institutional-ownership/latest", {"page": page, "limit": 100})
            if not raw:
                break
            for r in raw:
                cik = r.get("cik")
                d = (r.get("date") or "")[:10]
                if not cik or len(d) != 10:
                    continue
                yr, mo = int(d[:4]), int(d[5:7])
                q = (mo - 1) // 3 + 1
                u = f"{cik}:{yr}:{q}"
                if u not in seen:
                    seen.add(u); ulist.append(u)
            page += 1
            if page % 25 == 0:
                p5["enum_page"] = page
                save_cp(cp)
                log(f"p5 13F enum: page {page}, {len(ulist):,} unique filings")
        units = ulist
        p5["units"] = units
        p5["hw"] = p5.get("hw", 0)
        save_cp(cp)
        log(f"p5 13F: enumerated {len(units):,} (cik,quarter) filings to extract")
    # Phase B: extract holdings per unit, archive partitioned by quarter
    hw = p5.get("hw", 0)
    for i in range(hw, len(units)):
        if _STOP:
            break
        if not ctx["archive"].has_room():
            log("p5 13F: archive cap reached — stopping")
            break
        cik, yr, q = units[i].split(":")
        ctx["rate"].wait()
        raw = _get_json("institutional-ownership/extract",
                        {"cik": cik, "year": yr, "quarter": q})
        if raw:
            st("p5_13f")["fetched"] += len(raw)
            ctx["pq"]["inst_holdings"].add(f"{yr}Q{q}", raw)
        if (i + 1) % 200 == 0:
            p5["hw"] = i + 1
            save_cp(cp)
            ctx["pq"]["inst_holdings"].flush()
            log(f"p5 13F: {i+1:,}/{len(units):,} filings  rows={st('p5_13f')['fetched']:,} "
                f"arch={ctx['archive'].used_gb():.1f}GB")
    p5["hw"] = min(len(units), p5.get("hw", 0)) if _STOP else len(units)
    save_cp(cp)


# ═══════════════════════════════════════════════════════ P6 news + press (archive-only firehose)
def _harvest_feed(ctx, ds, cp_key, endpoint, archive_ds):
    if not ctx["archive"].firehose_ok:
        log(f"{ds}: firehose paused (low disk) — skipping")
        return
    ctx["pq"].setdefault(archive_ds, PQWriter(ctx["archive"], archive_ds))
    cp = ctx["cp"]
    page = cp.get(cp_key, {}).get("page", 0)
    max_pages = ctx["args"].max_pages or 20000
    while page < max_pages and not _STOP:
        if not ctx["archive"].has_room():
            log(f"{ds}: archive cap reached — stopping")
            break
        ctx["rate"].wait()
        raw = _get_json(endpoint, {"page": page, "limit": 250})
        if not raw:
            break
        st(ds)["fetched"] += len(raw)
        bucket = {}
        for r in raw:
            yr = (r.get("publishedDate") or "0000")[:4]
            bucket.setdefault(yr, []).append(r)
        for yr, rows in bucket.items():
            ctx["pq"][archive_ds].add(yr, rows)
        page += 1
        cp[cp_key] = {"page": page}
        if page % 50 == 0:
            save_cp(cp)
            ctx["pq"][archive_ds].flush()
            log(f"{ds}: page {page:,}  rows={st(ds)['fetched']:,}  arch={ctx['archive'].used_gb():.1f}GB")
    save_cp(cp)


def harvest_p6_news(ctx):
    _harvest_feed(ctx, "p6_news", "p6_news", "news/stock-latest", "stock_news")


def harvest_p6_press(ctx):
    _harvest_feed(ctx, "p6_press", "p6_press", "news/press-releases-latest", "press_releases")


# ═══════════════════════════════════════════════════════ P9 nice-to-haves
def _fetch_dcf(ctx, symbol):
    base = _get_json("discounted-cash-flow", {"symbol": symbol}) or []
    lev = _get_json("levered-discounted-cash-flow", {"symbol": symbol}) or []
    if not base and not lev:
        return None
    row = dict(base[0]) if base else {"symbol": symbol, "date": (lev[0].get("date") if lev else None)}
    if lev:
        row["levered_dcf"] = lev[0].get("dcf")
    row.setdefault("symbol", symbol)
    return [row]


def harvest_p9_dcf(ctx):
    ctx["pq"].setdefault("dcf", PQWriter(ctx["archive"], "dcf"))
    eq = [s for s in ctx["universe"] if not is_foreign(s)]

    def on_batch(collected):
        arch, prows = [], []
        for _s, raw in collected:
            st("p9_dcf")["fetched"] += len(raw)
            arch.extend(raw)
            prows.extend(map_rows(raw, DCF))
        if arch:
            ctx["pq"]["dcf"].add(arch[0].get("symbol", "_")[:1].upper() or "_", arch)
        prows = [r for r in prows if r.get("symbol") and r.get("date")]
        _upsert_if(ctx, "fmp_dcf", DCF, ["symbol", "date"], prows, "update", "p9_dcf")

    per_symbol(ctx, "p9_dcf", "p9_dcf", eq, _fetch_dcf, on_batch, batch=200, guard_pg=True)


def harvest_p9_mna(ctx):
    ctx["pq"].setdefault("mergers_acquisitions", PQWriter(ctx["archive"], "mergers_acquisitions"))
    cp = ctx["cp"]
    page = cp.get("p9_mna", {}).get("page", 0)
    max_pages = ctx["args"].max_pages or 3000
    while page < max_pages and not _STOP:
        ctx["rate"].wait()
        raw = _get_json("mergers-acquisitions-latest", {"page": page, "limit": 100})
        if not raw:
            break
        st("p9_mna")["fetched"] += len(raw)
        ctx["pq"]["mergers_acquisitions"].add("_", raw)
        mapped = map_rows(raw, MNA)
        _hash_rows(mapped, MNA_HASH)
        _upsert_if(ctx, "fmp_mergers_acquisitions", MNA, ["row_hash"], mapped, "nothing", "p9_mna")
        page += 1
        cp["p9_mna"] = {"page": page}
        save_cp(cp)
    log(f"p9 mna: fetched={st('p9_mna')['fetched']:,}")


def harvest_p9_ipos(ctx):
    ctx["pq"].setdefault("ipos_calendar", PQWriter(ctx["archive"], "ipos_calendar"))
    cp = ctx["cp"]
    done = set(cp.get("p9_ipos", {}).get("done", []))
    this_year = datetime.utcnow().year
    for y in range(2000, this_year + 1):
        if _STOP:
            break
        if str(y) in done:
            continue
        raw = _get_json("ipos-calendar", {"from": f"{y}-01-01", "to": f"{y}-12-31"})
        if raw is None:
            continue
        st("p9_ipos")["fetched"] += len(raw)
        ctx["pq"]["ipos_calendar"].add(str(y), raw)
        mapped = [r for r in map_rows(raw, IPOS) if r.get("symbol") and r.get("date")]
        _upsert_if(ctx, "fmp_ipos_calendar", IPOS, ["symbol", "date"], mapped, "update", "p9_ipos")
        done.add(str(y))
        cp["p9_ipos"] = {"done": sorted(done)}
        save_cp(cp)
    log(f"p9 ipos: fetched={st('p9_ipos')['fetched']:,}")


def harvest_p9_etf(ctx):
    ctx["pq"].setdefault("etf_holdings", PQWriter(ctx["archive"], "etf_holdings"))
    ctx["pq"].setdefault("etf_weightings", PQWriter(ctx["archive"], "etf_weightings"))
    cp = ctx["cp"]
    cache = "_p9_etf_syms"
    etfs = cp.get(cache)
    if etfs is None:
        listing = _get_json("etf-list") or []
        etfs = sorted({(r.get("symbol") or "").strip().upper()
                       for r in listing if r.get("symbol")})
        if not etfs:  # fallback: ETF-like symbols from our universe
            etfs = [s for s in ctx["universe"] if s in ("SPY", "QQQ", "IWM", "DIA", "VOO",
                    "VTI", "ARKK", "XLF", "XLK", "XLE", "GLD", "TLT", "HYG", "EEM")]
        cp[cache] = etfs
        save_cp(cp)
    hw = cp.get("p9_etf", {}).get("hw", 0)
    log(f"p9 etf: {len(etfs):,} ETFs, resume at {hw}")
    for i in range(hw, len(etfs)):
        if _STOP or not ctx["archive"].has_room():
            break
        sym = etfs[i]
        ctx["rate"].wait()
        hold = _get_json("etf/holdings", {"symbol": sym}) or []
        for r in hold:
            r["etf"] = sym
        if hold:
            st("p9_etf")["fetched"] += len(hold)
            ctx["pq"]["etf_holdings"].add(sym[:1].upper(), hold)
            _upsert_if(ctx, "fmp_etf_holdings", ETF_HOLD, ["etf", "asset"],
                       map_rows(hold, ETF_HOLD), "update", "p9_etf")
        wrows = []
        for kind, ep, lab in (("sector", "etf/sector-weightings", "sector"),
                              ("country", "etf/country-weightings", "country")):
            ctx["rate"].wait()
            for r in (_get_json(ep, {"symbol": sym}) or []):
                wrows.append({"etf": sym, "kind": kind, "label": r.get(lab),
                              "weightPercentage": r.get("weightPercentage")})
        if wrows:
            ctx["pq"]["etf_weightings"].add(sym[:1].upper(), wrows)
            _upsert_if(ctx, "fmp_etf_weightings", ETF_WEIGHT, ["etf", "kind", "label"],
                       map_rows(wrows, ETF_WEIGHT), "update", "p9_etf")
        if (i + 1) % 50 == 0:
            cp["p9_etf"] = {"hw": i + 1}
            save_cp(cp)
    cp["p9_etf"] = {"hw": len(etfs) if not _STOP else hw}
    save_cp(cp)
    log(f"p9 etf: holdings rows={st('p9_etf')['fetched']:,}")


def harvest_p9_sec(ctx):
    ctx["pq"].setdefault("sec_filings_8k", PQWriter(ctx["archive"], "sec_filings_8k"))
    cp = ctx["cp"]
    done = set(cp.get("p9_sec", {}).get("done", []))
    this_year = datetime.utcnow().year
    for y in range(2015, this_year + 1):
        if _STOP:
            break
        for q in range(4):
            key = f"{y}Q{q}"
            if key in done:
                continue
            frm, to = f"{y}-{q*3+1:02d}-01", f"{y}-{q*3+3:02d}-28"
            page = 0
            while page < (ctx["args"].max_pages or 200) and not _STOP:
                ctx["rate"].wait()
                raw = _get_json("sec-filings-8k", {"from": frm, "to": to, "page": page, "limit": 100})
                if not raw:
                    break
                st("p9_sec")["fetched"] += len(raw)
                ctx["pq"]["sec_filings_8k"].add(str(y), raw)
                mapped = map_rows(raw, SEC8K)
                _hash_rows(mapped, SEC_HASH)
                _upsert_if(ctx, "fmp_sec_filings", SEC8K, ["row_hash"], mapped, "nothing", "p9_sec")
                page += 1
            done.add(key)
            cp["p9_sec"] = {"done": sorted(done)}
            save_cp(cp)
    log(f"p9 sec-8k: fetched={st('p9_sec')['fetched']:,}")


# ═══════════════════════════════════════════════════════ probe-only (re-verify endpoints)
def run_probe():
    import csv as _csv
    import io as _io
    import httpx
    from fmp_ultimate_harvest import FMP_KEY, BASE
    checks = [
        ("p1 dates", "earning-call-transcript-dates", {"symbol": "AAPL"}),
        ("p2 crypto-list", "cryptocurrency-list", {}),
        ("p2 eod", "historical-price-eod/full", {"symbol": "BTCUSD"}),
        ("p3 pt-news", "price-target-news", {"symbol": "AAPL", "limit": 3}),
        ("p3 grade-news", "grades-news", {"symbol": "AAPL", "limit": 3}),
        ("p4 mktcap", "historical-market-capitalization", {"symbol": "AAPL", "limit": 3}),
        ("p5 inst-latest", "institutional-ownership/latest", {"page": 0, "limit": 3}),
        ("p5 inst-extract", "institutional-ownership/extract", {"cik": "0001067983", "year": 2023, "quarter": 4}),
        ("p6 news", "news/stock-latest", {"page": 0, "limit": 3}),
        ("p6 press", "news/press-releases-latest", {"page": 0, "limit": 3}),
        ("p7 sp500", "sp500-constituent", {}),
        ("p8 calendar", "economic-calendar", {"from": "2024-01-01", "to": "2024-01-15"}),
        ("p9 dcf", "discounted-cash-flow", {"symbol": "AAPL"}),
        ("p9 mna", "mergers-acquisitions-latest", {"page": 0, "limit": 3}),
        ("p9 ipos", "ipos-calendar", {"from": "2024-01-01", "to": "2024-03-01"}),
        ("p9 etf-list", "etf-list", {}),
        ("p9 etf-holdings", "etf/holdings", {"symbol": "SPY"}),
        ("p9 sec-8k", "sec-filings-8k", {"from": "2024-01-01", "to": "2024-01-03", "limit": 3}),
    ]
    for label, path, params in checks:
        p = dict(params); p["apikey"] = FMP_KEY
        try:
            r = httpx.get(BASE + path, params=p, timeout=60)
            n = "?"
            try:
                j = r.json(); n = len(j) if isinstance(j, list) else "dict"
            except Exception:
                n = "csv" if (r.text[:1] == '"') else "?"
            log(f"PROBE {label:18s} {path:40s} HTTP {r.status_code} n={n}")
        except Exception as e:
            log(f"PROBE {label:18s} {path:40s} EXC {type(e).__name__}")


# ═══════════════════════════════════════════════════════ reload PG from archive (no FMP calls)
def _reload_one(conn, present, ds_dir, table, columns, pk, conflict, hash_fields):
    if table not in present:
        log(f"reload {ds_dir}: PG table {table} absent — skip (run the SQL first)")
        return 0
    root = os.path.join(ARCHIVE_ROOT, ds_dir)
    if not os.path.isdir(root):
        return 0
    files = [os.path.join(dp, f) for dp, _, fs in os.walk(root)
             for f in fs if f.endswith(".parquet")]
    total, buf = 0, []
    for fp in files:
        try:
            rows = pq.read_table(fp).to_pylist()
        except Exception as e:
            log(f"reload {ds_dir}: read {os.path.basename(fp)} failed {type(e).__name__}")
            continue
        mapped = map_rows(rows, columns)
        if hash_fields:
            _hash_rows(mapped, hash_fields)
        mapped = [r for r in mapped if all(r.get(k) is not None for k in pk if k != "row_hash")]
        buf.extend(mapped)
        if len(buf) >= 20000:
            total += upsert(conn, table, columns, pk, buf, conflict=conflict); buf = []
    if buf:
        total += upsert(conn, table, columns, pk, buf, conflict=conflict)
    log(f"reload {ds_dir} -> {table}: {total:,} rows (from {len(files)} files)")
    return total


def _reload_transcript_index(conn, present):
    table = "fmp_transcript_index"
    if table not in present:
        log("reload transcripts: fmp_transcript_index absent — skip")
        return 0
    root = os.path.join(ARCHIVE_ROOT, "transcripts")
    if not os.path.isdir(root):
        return 0
    cols, pk, _ = TABLES[table]

    def _flush(buf):
        good = [r for r in buf if r.get("symbol") and r.get("year") is not None
                and r.get("quarter") is not None]
        return upsert(conn, table, cols, pk, good, conflict="update") if good else 0

    total, buf = 0, []
    for dp, _, fs in os.walk(root):
        for f in fs:
            if not f.endswith(".jsonl.gz"):
                continue
            fp = os.path.join(dp, f)
            apath = os.path.relpath(fp, ARCHIVE_ROOT)
            try:
                with gzip.open(fp, "rt", encoding="utf-8") as fh:
                    for line in fh:
                        o = json.loads(line)
                        buf.append({"symbol": o.get("symbol"), "year": _i(o.get("year")),
                                    "quarter": _i(o.get("quarter")), "call_date": _d(o.get("date")),
                                    "n_chars": len(o.get("content") or ""), "archive_path": apath})
            except Exception as e:
                log(f"reload transcripts: {f} failed {type(e).__name__}")
            if len(buf) >= 20000:
                total += _flush(buf); buf = []
    total += _flush(buf)
    log(f"reload transcripts -> {table}: {total:,} rows")
    return total


def run_reload(conn):
    present = {t for t in TABLES if table_exists(conn, t)}
    if table_exists(conn, "fmp_forex"):
        present.add("fmp_forex")
    log(f"reload-pg-from-archive: {len(present)} target tables present, archive={ARCHIVE_ROOT}")
    grand = 0
    for ds_dir, table, columns, pk, conflict, hf in RELOAD:
        grand += _reload_one(conn, present, ds_dir, table, columns, pk, conflict, hf)
    grand += _reload_transcript_index(conn, present)
    log(f"reload DONE: {grand:,} total rows upserted")


# ═══════════════════════════════════════════════════════ registry + main
def dataset_registry():
    # (key, p-group, fn)
    return [
        ("p1_transcripts", 1, harvest_p1_transcripts),
        ("p2_crypto", 2, harvest_p2_crypto),
        ("p2_forex", 2, harvest_p2_forex),
        ("p3_pt_news", 3, harvest_p3_pt_news),
        ("p3_grade_news", 3, harvest_p3_grade_news),
        ("p4_mktcap", 4, harvest_p4_mktcap),
        ("p7_constituents", 7, harvest_p7_constituents),
        ("p8_calendar", 8, harvest_p8_calendar),
        ("p5_13f", 5, harvest_p5_13f),
        ("p6_news", 6, harvest_p6_news),
        ("p6_press", 6, harvest_p6_press),
        ("p9_dcf", 9, harvest_p9_dcf),
        ("p9_mna", 9, harvest_p9_mna),
        ("p9_ipos", 9, harvest_p9_ipos),
        ("p9_etf", 9, harvest_p9_etf),
        ("p9_sec", 9, harvest_p9_sec),
    ]


def parse_groups(s):
    return {int(x.strip().lstrip("pP")) for x in s.split(",") if x.strip()}


def print_summary(conn, archive):
    log("══════════════════════ SUMMARY ══════════════════════")
    for ds, s in _stats.items():
        log(f"  {ds:18s} fetched={s['fetched']:>10,}  pg={s['pg']:>10,}  "
            f"arch_rows={s['arch_rows']:>10,}  arch={s['arch_bytes']/1e6:>8.1f}MB")
    # per archive-dir size
    try:
        for d in sorted(os.listdir(archive.root)):
            p = os.path.join(archive.root, d)
            if os.path.isdir(p):
                log(f"  archive/{d}: {Archive._dirsize(p)/1e9:.2f}GB")
    except Exception:
        pass
    # PG table counts
    for table in TABLES:
        try:
            if table_exists(conn, table):
                with conn.cursor() as cur:
                    cur.execute(f"SELECT count(*) FROM {table}")
                    log(f"  PG {table}: {cur.fetchone()[0]:,} rows")
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
    log(f"TOTAL archive={archive.used_gb():.2f}GB   DB={safe_db_gb(conn):.2f}GB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma p-groups e.g. p1,p2")
    ap.add_argument("--skip", default="", help="comma p-groups to skip")
    ap.add_argument("--from-priority", default="", help="start at p-group e.g. p3")
    ap.add_argument("--limit", type=int, default=0, help="cap universe (testing)")
    ap.add_argument("--rate-limit", type=int, default=1200)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-pages", type=int, default=0, help="cap firehose feed pages")
    ap.add_argument("--probe-only", action="store_true")
    ap.add_argument("--print-ddl", action="store_true")
    ap.add_argument("--reload-pg-from-archive", action="store_true",
                    help="upsert PG from the parquet/jsonl archive (no FMP calls)")
    ap.add_argument("--checkpoint", default="", help="override checkpoint path (isolate runs)")
    args = ap.parse_args()
    if args.checkpoint:
        global CHECKPOINT
        CHECKPOINT = args.checkpoint

    if args.print_ddl:
        print(gen_ddl())
        return
    if args.probe_only:
        run_probe()
        return
    if args.reload_pg_from_archive:
        conn = app_connect()
        with conn.cursor() as cur:
            cur.execute("SELECT current_user")
            log(f"connected as {cur.fetchone()[0]} (reload mode)")
        run_reload(conn)
        conn.close()
        return

    from fmp_ultimate_harvest import FMP_KEY
    if not FMP_KEY:
        sys.exit(f"{TAG} ERROR: FMP_KEY not set (run under `railway run -s hopeful-expression`)")

    conn = app_connect()
    with conn.cursor() as cur:
        cur.execute("SELECT current_user")
        log(f"connected as {cur.fetchone()[0]}  DB={safe_db_gb(conn):.2f}GB  guard={DB_GUARD_GB}GB")
    cp = load_cp()
    archive = Archive(ARCHIVE_ROOT, MAX_ARCHIVE_GB)
    universe = build_universe(conn, cp)
    if args.limit:
        universe = universe[:args.limit]
    present = {t for t in TABLES if table_exists(conn, t)}
    present |= {"fmp_forex"} if table_exists(conn, "fmp_forex") else set()
    missing = [t for t in TABLES if t not in present]
    if missing:
        log(f"NOTE: {len(missing)} PG tables absent (archive-only for those): {missing}")
        log("      run `python3 scripts/fmp_endgame_harvest.py --print-ddl` → apply as superuser to enable PG load")

    ctx = {"conn": conn, "rate": Rate(args.rate_limit), "archive": archive,
           "cp": cp, "args": args, "universe": universe, "present": present,
           "workers": args.workers, "pq": {}}

    reg = dataset_registry()
    only = parse_groups(args.only) if args.only else None
    skip = parse_groups(args.skip) if args.skip else set()
    frm = min(parse_groups(args.from_priority)) if args.from_priority else 0

    log(f"universe={len(universe):,}  rate={args.rate_limit}/min workers={args.workers}")
    for key, grp, fn in reg:
        if _STOP:
            break
        if only is not None and grp not in only:
            continue
        if grp in skip or grp < frm:
            continue
        log(f"═══ {key} (P{grp}) ═══")
        try:
            fn(ctx)
        except Exception as e:
            log(f"{key} FAILED: {type(e).__name__}: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
        for w in ctx["pq"].values():
            w.flush()
    _flush_all()
    print_summary(conn, archive)
    conn.close()
    log(f"DONE ({'interrupted' if _STOP else 'completed'})")


if __name__ == "__main__":
    main()

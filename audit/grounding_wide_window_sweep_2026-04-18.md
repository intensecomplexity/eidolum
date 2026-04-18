# Grounding Wide-Window Sweep — 2026-04-18 (PARTIAL)

**Run state:** partial. Sweep killed at 628/1884 videos after stalling on a shared-cursor / leaked-SSL-thread deadlock (see post-mortem). The incremental CSV captured every row its workers touched — no data lost from the completed work, and the full-population non-inferred rows were streamed up front.

- full population: `6,430` yt_ rows
- total narrow-inferred: `2,969`
- CSV rows: `4,451` (= all non-inferred streamed upfront + processed inferred)
- inferred rows processed: `990` (33.3% of target)
- inferred rows NOT reached: `1,979` (no CSV entry — these rows still have `grounding_type IS NULL` in prod)

## Flip rate (within processed inferred subset)

**Overall: `264` / `990` = 26.7%**
- → `explicit`: 112
- → `implicit_alias`: 152

**Big-tech subset (NVDA/TSLA/META/AAPL/GOOGL/MSFT/AMZN): `50/82` = 61.0%** — matches the 70% figure from the narrow-quote hypothesis test (commit c79dbad) within sampling noise.

The lower 27% overall figure vs 70% big-tech comes from ETF/macro tickers (SPY, TLT, QQQ, SH, TBT) where speakers use generic vocabulary ("stocks", "the market") that often doesn't match any alias even in a wider window.

## Buckets (CSV snapshot — subset only)

| bucket | before (narrow, in CSV) | after (final, in CSV) |
|---|---:|---:|
| `explicit` | 982 | 1,094 |
| `implicit_alias` | 2,479 | 2,631 |
| `inferred` | 990 | 726 |
| `no_window_text` | 0 | 0 |

## Top wide-window match terms (newly hitting)

| term | count |
|---|---:|
| `bitcoin` | 12 |
| `nvidia` | 9 |
| `apple` | 8 |
| `the market` | 8 |
| `amazon` | 7 |
| `ethereum` | 7 |
| `stock market` | 7 |
| `google` | 7 |
| `microsoft` | 6 |
| `starbucks` | 6 |
| `tesla` | 6 |
| `broadcom` | 5 |
| `META` | 5 |
| `disney` | 4 |
| `ASML` | 4 |
| `XRP` | 4 |
| `target` | 3 |
| `nike` | 3 |
| `applied materials` | 3 |
| `paypal` | 3 |
| `TPL` | 3 |
| `netflix` | 3 |
| `oracle` | 3 |
| `costco` | 3 |
| `UBER` | 3 |
| `UNH` | 3 |
| `stocks` | 2 |
| `rate cuts` | 2 |
| `verizon` | 2 |
| `CVS` | 2 |

## Tickers moved out of inferred

| ticker | count |
|---|---:|
| `SPY` | 21 |
| `BTC` | 11 |
| `NVDA` | 9 |
| `AMZN` | 8 |
| `AAPL` | 8 |
| `GOOGL` | 7 |
| `MSFT` | 6 |
| `ETH` | 6 |
| `META` | 6 |
| `SBUX` | 6 |
| `TSLA` | 6 |
| `AVGO` | 5 |
| `DIS` | 4 |
| `ASML` | 4 |
| `AMAT` | 4 |
| `XRP` | 4 |
| `UNH` | 4 |
| `TGT` | 3 |
| `NKE` | 3 |
| `PYPL` | 3 |
| `TPL` | 3 |
| `NFLX` | 3 |
| `ORCL` | 3 |
| `COST` | 3 |
| `UBER` | 3 |
| `UUP` | 3 |
| `TLT` | 2 |
| `VZ` | 2 |
| `CVS` | 2 |
| `MA` | 2 |

## Tickers still inferred (within processed subset)

| ticker | count |
|---|---:|
| `SPY` | 20 |
| `TBT` | 16 |
| `SH` | 13 |
| `NVDA` | 12 |
| `QQQ` | 11 |
| `PLTR` | 11 |
| `PEP` | 10 |
| `SNPS` | 8 |
| `JNJ` | 8 |
| `INTU` | 8 |
| `AEHR` | 8 |
| `CRWD` | 7 |
| `AAPL` | 7 |
| `KO` | 7 |
| `MCD` | 7 |
| `SPGI` | 6 |
| `LRCX` | 6 |
| `DPZ` | 6 |
| `WBA` | 5 |
| `ISRG` | 5 |
| `XRP` | 5 |
| `SNDK` | 5 |
| `O` | 5 |
| `LVMHF` | 5 |
| `TTD` | 5 |
| `GOOG` | 5 |
| `MACRO` | 5 |
| `TLT` | 5 |
| `MRK` | 5 |
| `ABBV` | 4 |

## Post-mortem: why this run stalled

Diagnosis from `/proc/25381/task/*/wchan` at kill time:
- **22 live threads**: main + 7 outer-pool workers in `futex_wait_queue`, plus **14 leaked inner-fetch threads in `wait_woken`** (SSL hangs timed out but the thread can't be killed in CPython).
- **12 ESTABLISHED Webshare sockets** — orphaned SSL recvs accumulated over the run.
- Most likely culprit for the full freeze: `mark_unrecoverable` calls shared a single psycopg2 cursor across worker threads under a `db_lock`. psycopg2 cursors are not thread-safe even with an external lock; a bad-transaction state on one thread can deadlock the lock holder indefinitely.

**Fix for next run:**
1. Per-thread psycopg2 connections (or a `psycopg2.pool.ThreadedConnectionPool`) so no cursor is shared.
2. Cap per-cycle leaked-thread count: if N≥16 leaked workers, stop submitting new fetches — proxy is degraded.
3. Write a checkpoint file every N videos so a kill can be resumed from the last known-good boundary.

The CSV is still streamed row-by-row with `flush()` after each write, so a partial-run re-kill loses at most one video's output. The `audit/grounding_wide_window_sweep_2026-04-18.csv` file in this commit reflects exactly what the sweep had classified at kill time.
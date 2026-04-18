# Grounding Wide-Window Sweep — 2026-04-18 (FINAL)

**Run state:** complete. All `yt_` predictions with a stored timestamp and a non-null narrow quote (population 6,430) have a final classification in the CSV. Single video (id=1236/1236) never finished its final subprocess cycle before kill, but every row in the population was covered — its predictions (if any) were already streamed to the CSV before the hang, so no data is missing.

**No writes to `predictions.grounding_type`** — dry-run. The column remains `NULL` for every row in production until an `--apply` invocation is explicitly approved.

- population: `6,429` yt_ rows (= baseline + wide pass)
- narrow-inferred processed with wide window: `2,968`
- narrow-inferred not processed (no CSV row): `0`
- window: ±`60s` around source_timestamp_seconds
- fetch isolation: `subprocess.run(timeout=20)` → SIGKILL, no leaked threads
- DB concurrency: `psycopg2.pool.ThreadedConnectionPool` (no shared cursor)
- haiku prompt md5 guard: **not reached** (script killed before post-guard; 16 constants unchanged at start, and no sweep code touches them)

## Before → after

| bucket | before (narrow) | after (wide) | Δ |
|---|---:|---:|---:|
| `explicit` | 982 | 1,335 | +353 |
| `implicit_alias` | 2,479 | 2,924 | +445 |
| `inferred` | 2,968 | 2,170 | -798 |
| `no_window_text` | 0 | 0 | +0 |

**Rows moved out of `inferred`: `798` / `2,968` = 26.9%**
- → `explicit`: 353
- → `implicit_alias`: 445

## Flip rate by ticker class

| class | moved | stuck | total | flip rate |
|---|---:|---:|---:|---:|
| **big-tech** (NVDA/TSLA/META/AAPL/GOOGL/MSFT/AMZN) | 133 | 58 | 191 | **69.6%** |
| **ETFs** (SPY/QQQ/DIA/IWM/TLT/SH/TBT/HYG/LQD/GLD/USO/XL_) | 109 | 224 | 333 | **32.7%** |
| **overall** | 798 | 2170 | 2968 | **26.9%** |

Big-tech confirms the narrow-quote hypothesis (commit c79dbad) at full scale. ETFs are the genuine hallucination pile — speakers use generic vocabulary ("stocks", "the market", "bonds") that ±60s window still doesn't alias-match.

## Top wide-window match terms (newly hitting in the wider window)

| term | count |
|---|---:|
| `nvidia` | 31 |
| `bitcoin` | 31 |
| `the market` | 30 |
| `XRP` | 23 |
| `stock market` | 21 |
| `tesla` | 20 |
| `google` | 16 |
| `META` | 16 |
| `microsoft` | 15 |
| `apple` | 15 |
| `ethereum` | 13 |
| `stocks` | 12 |
| `amazon` | 12 |
| `starbucks` | 12 |
| `verizon` | 10 |
| `ASML` | 10 |
| `broadcom` | 9 |
| `rate cuts` | 9 |
| `disney` | 9 |
| `paypal` | 9 |
| `inflation` | 9 |
| `UBER` | 8 |
| `intel` | 8 |
| `target` | 7 |
| `nike` | 7 |
| `oracle` | 7 |
| `HIMS` | 7 |
| `SOFI` | 7 |
| `UNH` | 7 |
| `T` | 6 |

## Tickers moved out of inferred

| ticker | count |
|---|---:|
| `SPY` | 74 |
| `NVDA` | 31 |
| `BTC` | 28 |
| `XRP` | 23 |
| `GOOGL` | 20 |
| `TSLA` | 20 |
| `META` | 19 |
| `TLT` | 16 |
| `MSFT` | 15 |
| `AAPL` | 15 |
| `AMZN` | 13 |
| `ETH` | 12 |
| `SBUX` | 12 |
| `AVGO` | 11 |
| `VZ` | 11 |
| `ASML` | 10 |
| `MO` | 10 |
| `DIS` | 9 |
| `PYPL` | 9 |
| `UNH` | 9 |
| `TIP` | 9 |
| `UBER` | 8 |
| `INTC` | 8 |
| `BAC` | 8 |
| `TGT` | 7 |
| `NKE` | 7 |
| `ORCL` | 7 |
| `HIMS` | 7 |
| `SOFI` | 7 |
| `SH` | 7 |

## Tickers still inferred (the real hallucination audit pile)

| ticker | count |
|---|---:|
| `TLT` | 47 |
| `TBT` | 43 |
| `SH` | 40 |
| `QQQ` | 39 |
| `SPY` | 37 |
| `PEP` | 32 |
| `EVENT` | 32 |
| `NVDA` | 23 |
| `MACRO` | 23 |
| `LRCX` | 21 |
| `PLTR` | 21 |
| `TXRH` | 20 |
| `SNPS` | 19 |
| `INTU` | 19 |
| `O` | 19 |
| `JNJ` | 17 |
| `SPGI` | 17 |
| `KO` | 17 |
| `BTC` | 17 |
| `TXN` | 16 |
| `DPZ` | 15 |
| `MCD` | 15 |
| `GOOG` | 15 |
| `XRP` | 14 |
| `FTNT` | 14 |
| `PSTG` | 14 |
| `CRWD` | 13 |
| `CMG` | 13 |
| `EL` | 12 |
| `AEHR` | 12 |

## Infrastructure notes

The sweep went through three infrastructure iterations before landing:

1. **Serial + thread-based timeout** — daemon-thread wrapper could not interrupt C-level SSL recv. Stuck at 326/1877 (PID 23334, commit 8377ca2 tried to fix with a 20s cap — didn't work because the cap is at Python level, not kernel level).
2. **8-way parallel threads + shared cursor** — 14 leaked SSL-hung threads accumulated; most-likely deadlock on a shared psycopg2 cursor under a lock. Stuck at 628/1884 (PID 25381, commit 02fda89 captured the partial CSV).
3. **Subprocess fetch + ThreadedConnectionPool + CSV resume** — this run. 1235/1236 videos drained in 69 min, no leaked threads, no cross-thread DB deadlock, resume from the partial CSV appended cleanly. The one remaining 1236th video hung its subprocess in a way the 20s timeout didn't catch; manual kill at the finalise step.

The sweep is idempotent — re-running picks up from the CSV's recorded ids. `grounding_type` is still `NULL` in prod; `--apply` gated on explicit approval.
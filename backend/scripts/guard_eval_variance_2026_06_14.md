# Guard eval variance study — is the eval noisy, and were last session's "breach" verdicts real? (2026-06-14)

MEASUREMENT ONLY. No guard code changed (module byte-identical to c64e38f, restored at end).
5 independent runs of each eval on the SHIPPED prompt + 5 runs of conditional candidate R3,
all on the same fixtures used last session (conditional: 311 LLM-judged rows w/ cached transcripts,
46 a / 38 b / 227 c; representativeness: 203-row fixture).

## STEP 1 — where the noise comes from
The guard does NOT make a direct Sonnet API call. It shells out to `claude -p --model sonnet`
(Claude Code 2.1.175), billing the Max plan. **That CLI exposes NO temperature / top-p / seed flag**
(verified against `claude --help`). So the classifier runs at Claude Code's default sampling with no
determinism control, and **temperature cannot be set to 0 on the production path.** A direct-API
temp=0 comparison is off-path AND unavailable (no ANTHROPIC_API_KEY in env; ops balance ~$0). The
temp=0 sub-experiment is therefore N/A; the robustness question is answered from the noise bands.

## STEP 2 — noise bands (5 runs each, zero code change)

### Conditional — SHIPPED (R0)
| metric | mean | min | max | std |
|---|---|---|---|---|
| (a) event/macro recall | 63.9% | 58.7 | 67.4 | **3.25** |
| (b) price-trigger recall | 50.0% | 47.4 | 55.3 | **2.88** |
| **(c) FALSE-ROUTE** | **1.59%** | 0.88 | 1.76 | **0.35** |
| (c)->route_price | 0.0 | 0 | 0 | 0 |

### Conditional — R3 (named-discrete-event)
| metric | mean | min | max | std |
|---|---|---|---|---|
| (a) event/macro recall | 74.8% | 71.7 | 78.3 | 2.22 |
| (b) price-trigger recall | 55.3% | 50.0 | 57.9 | 2.88 |
| **(c) FALSE-ROUTE** | **4.85%** | 3.96 | 5.29 | 0.48 |
| (c)->route_price | 0.4 | 0 | 1 | 0.49 |

### Representativeness — SHIPPED
| metric | mean | min | max | std |
|---|---|---|---|---|
| clean hard-reject | 0.0% | 0 | 0 | 0 |
| clean soft-flag | 7.5% | 6.25 | 8.75 | 1.12 |
| no-call catch | 45.3% | 36.7 | 53.3 | **5.42** |
| reported catch | 57.1% | 57.1 | 57.1 | 0 |
| flip-correct | 83.3% | 83.3 | 83.3 | 0 |

**Read:** the noise is METRIC-DEPENDENT.
- The PRECISION-floor metrics are LOW-noise: conditional (c) false-route std 0.35pp; rep clean
  hard-reject 0 always. Single runs of these are trustworthy.
- The RECALL metrics are NOISY: conditional (a) ±3.25pp, rep no-call ±5.4pp. A single run of a recall
  number can wiggle ±3-5pp, so per-round recall point-estimates from last session were soft.
- rep clean soft-flag (mean 7.5%, std 1.12) STRADDLES the ~7% floor — it's right at the edge.

## STEP 3 — R3 floor verdict (5 runs)
R3 (c) false-route: **mean 4.85%, min 3.96%, max 5.29%, std 0.48pp**. The floor is 3.0%.
- R3's mean is **+1.85pp over the floor — ~4 standard deviations above it.** Even R3's BEST run (3.96%)
  is above 3%. R3 also produced a scoring-breaking (c)->route_price in 2 of 5 runs (mean 0.4).
- **Last session's single R3 reading of 4.0% was NOT noise — it was actually a LOW draw** (R3's true
  mean is 4.85%). The "R3 breaches the floor" verdict was correct and, if anything, understated.
- Shipped (c) false-route mean 1.59% (max 1.76%) is a clean ~1.4pp below the floor with tiny noise —
  shipped holds robustly.

## STEP 4 — contested rows
52 rows surfaced (36 flip between runs, 20 gold-(a) the shipped prompt misses, 18 gold-(c) R3 routes).
Full table in `guard_eval_contested_rows_2026_06_14.md` (do NOT auto-relabel — for human adjudication).
Notable: several gold-(a) "named discrete event" rows the shipped prompt consistently misses but R3
catches cleanly (e.g. 614638 TLT "almost certainly get the rate cut on December 10th") — these are the
real recall the floor costs. Several gold-(c) rows R3 routes are valuation/commentary "if"s where the
gold label looks defensible (R3 over-reach), confirming the precision/recall entanglement is genuine,
not a labeling artifact.

## RECOMMENDATION (one line)
Noise is real but small on the floor metrics (single runs trustworthy for (c) false-route / hard-reject)
and larger on recall (±3-5pp, average 3+ runs); **temp=0 is unavailable via claude -p, so it cannot fix
the noise; R3 genuinely breaches the 3% floor (4.85% mean, 4σ over) — keep shipped. Last session's breach
verdicts were real.** If more (a)-recall is wanted, the lever is relabeling the fuzzy contested rows +
relaxing the floor to ~5%, not a prompt tweak.

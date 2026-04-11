# Eidolum three-source evaluator — eval harness

Canonical eval harness for the `jobs/youtube_classifier.py::classify_video`
pipeline (the live HAIKU_SYSTEM stack). Used as the **release gate** for
any edit to `HAIKU_SYSTEM`, `YOUTUBE_HAIKU_*_INSTRUCTIONS`, or the
Haiku model version.

## Layout

```
backend/evals/evaluator/
├── fixtures/
│   ├── tsla_tier1.json   # golden path — explicit target + timeframe + high conviction
│   ├── anet_tier2.json   # medium   — softer conviction, relative timeframe
│   └── btc_tier3.json    # edge     — crypto ticker, 6-figure target
├── graders.py            # deterministic + tolerance graders
├── runner.py             # loads fixtures, calls classify_video, grades output
└── README.md             # this file
```

Each fixture carries:

- `input`: the raw `(channel_name, title, publish_date, transcript)`
  tuple that `classify_video` actually accepts.
- `expected`: the canonical extraction — `ticker`, `direction`,
  `timeframe`, `conviction` (maps to HAIKU_SYSTEM's `confidence` field),
  and a `tier_score` (the numerical `price_target`) graded via the
  Eidolum scoring tolerance table (`_TOLERANCE` in `jobs/evaluator.py`).

## Running

From the `backend/` directory (so `jobs.*` imports resolve):

```bash
cd backend
ANTHROPIC_API_KEY=sk-... python -m evals.evaluator.runner
```

Flags:

```bash
# Run a single fixture
python -m evals.evaluator.runner --fixture tsla_tier1

# Machine-readable output (for CI)
python -m evals.evaluator.runner --json

# Override the run history log directory
python -m evals.evaluator.runner --log-dir /tmp/eval-logs
```

Exit codes:

- `0` — every fixture passed (regression gate satisfied)
- `1` — one or more fixtures failed
- `2` — runner infrastructure error (missing API key, import failure)

Run history is appended as JSONL to
`.claude/evals/evaluator.log` by default.

## Graders

`graders.py` exposes five pure functions, one per field:

| Grader                | Kind          | Rule                                                                   |
|-----------------------|---------------|------------------------------------------------------------------------|
| `grade_ticker`        | deterministic | Exact match after uppercase + `$` strip                                |
| `grade_direction`     | deterministic | Exact match in {`bullish`, `bearish`, `neutral`}                       |
| `grade_timeframe`     | deterministic | ISO parse, \|delta_days\| ≤ fixture `timeframe_tolerance_days`         |
| `grade_conviction`    | deterministic | Exact match in {`high`, `medium`, `low`}                               |
| `grade_tier_score`    | tolerance     | `\|actual - expected\| / expected ≤ _TOLERANCE[window_days]`           |

`grade_tier_score` pulls the tolerance band from
`jobs.evaluator._TOLERANCE` so the harness uses the exact same table
the live three-tier scoring path uses:

```
 1d → 2%   |  1w → 3%  |  2w → 4%  |  1m → 5%
 3m → 5%   |  6m → 7%  |  1y → 10%
```

`window_days` is computed per fixture as `expected.timeframe - publish_date`,
so the fixture's declared timeframe drives which row of the table applies.

## Release gate

Per the `Prompt eval before merging` rule: **no HAIKU_SYSTEM edit ships
without this harness returning pass^3 = 1.00 on the regression suite.**
See `.claude/evals/evaluator.md` for the capability + regression eval
definitions and pass thresholds.

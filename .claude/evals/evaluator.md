# EVAL DEFINITION: Eidolum three-source evaluator (HAIKU_SYSTEM)

Target under test: `backend/jobs/youtube_classifier.py::classify_video`
running the live `HAIKU_SYSTEM` prompt stack (plus any
`YOUTUBE_HAIKU_*_INSTRUCTIONS` blocks that feature flags append).

Run command:

```bash
cd backend
ANTHROPIC_API_KEY=sk-... python -m evals.evaluator.runner
```

Harness source:

- Fixtures: `backend/evals/evaluator/fixtures/*.json`
- Runner:   `backend/evals/evaluator/runner.py`
- Graders:  `backend/evals/evaluator/graders.py`
- Docs:     `backend/evals/evaluator/README.md`
- History:  `.claude/evals/evaluator.log` (JSONL, one run per line)

## Capability evals

Each capability is scored per-field on the fixtures below. A
capability "passes" only when every fixture passes that field's
grader on the same run.

| # | Capability                                | Grader                              | Fields graded              |
|---|-------------------------------------------|-------------------------------------|----------------------------|
| 1 | Extract ticker from transcript            | `grade_ticker` (deterministic)      | `ticker`                   |
| 2 | Extract direction (bullish/bearish/neut)  | `grade_direction` (deterministic)   | `direction`                |
| 3 | Extract / resolve timeframe to ISO date   | `grade_timeframe` (±tolerance days) | `timeframe`                |
| 4 | Assign conviction label (high/med/low)    | `grade_conviction` (deterministic)  | `confidence`               |
| 5 | Score price target within tolerance table | `grade_tier_score` (% tolerance)    | `price_target`             |

Target threshold: **pass@3 ≥ 0.90** for each capability. Below that
bar, the prompt is considered regressed on that capability and may
not ship.

## Regression evals

The three canonical teaching cases below constitute the regression
suite. Each must pass on every release candidate build of
`HAIKU_SYSTEM`.

| Fixture        | Tier | Difficulty    | What it guards                                                        |
|----------------|------|---------------|-----------------------------------------------------------------------|
| `tsla_tier1`   | 1    | golden path   | Baseline extraction of explicit ticker + target + end-of-year date    |
| `anet_tier2`   | 2    | medium        | Relative timeframe resolution ("six months"), softer conviction       |
| `btc_tier3`    | 3    | edge (crypto) | Crypto ticker recognition, 6-figure target, large tolerance window    |

**Regression gate: `pass^3 = 1.00`** — all three fixtures must pass
on the same run before any edit to `HAIKU_SYSTEM` or any
`YOUTUBE_HAIKU_*_INSTRUCTIONS` constant may ship. This codifies the
standing "Prompt eval before merging" rule that forbids shipping a
classifier prompt change without a TPR/FPR/parse-rate fixture check.

## Release gate procedure

Before merging any of the following, run the harness and confirm
`pass^3 = 1.00`:

1. Any diff to `HAIKU_SYSTEM` in `jobs/youtube_classifier.py`
2. Any new `YOUTUBE_HAIKU_*_INSTRUCTIONS` constant or edit to an
   existing one
3. Any bump of `HAIKU_MODEL` in `jobs/youtube_classifier.py`
4. Any change to `classify_video`'s system-prompt assembly order
5. Any change to `_validate_and_dedupe_predictions` that could drop
   valid predictions

If a fixture fails:

- Do NOT edit the fixture to make it pass — the fixture codifies the
  known-good contract.
- Investigate whether the prompt change genuinely regressed the
  capability, or whether the fixture's expected field is wrong.
- If the regression is real: revert the prompt change.
- If the fixture is wrong: update it in a separate commit with a
  note explaining the intent change, and re-baseline.

## Adding new fixtures

Drop a new `<name>.json` file in
`backend/evals/evaluator/fixtures/` with the same schema as the
existing three. The runner picks up every `*.json` file in that
directory on each run. Prefer adding a new fixture to
re-baselining an existing one.

Fixture schema:

```json
{
  "id": "<unique_id>",
  "case_tier": 1|2|3,
  "case_label": "<short_label>",
  "description": "<why this fixture exists>",
  "input": {
    "channel_name": "...",
    "title": "...",
    "publish_date": "YYYY-MM-DD",
    "transcript": "..."
  },
  "expected": {
    "ticker": "TICKER",
    "direction": "bullish|bearish|neutral",
    "timeframe": "YYYY-MM-DD",
    "timeframe_tolerance_days": 7,
    "conviction": "high|medium|low",
    "tier_score": 123.45,
    "tolerance_pct_override": null
  }
}
```

## Metrics tracked per run

- `pass@1` — first-attempt pass rate across all fixtures
- `pass^3` — whether every regression fixture passed in the same run
- Per-capability pass counts (ticker / direction / timeframe /
  conviction / tier_score)
- Classifier error tags from telemetry (parse_error, no_content, etc)
- Per-fixture wall-clock elapsed seconds

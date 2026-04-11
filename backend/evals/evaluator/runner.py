"""Eval harness runner for the three-source evaluator.

Loads every fixture in fixtures/*.json, invokes the real
jobs/youtube_classifier.py::classify_video function (which
sends the live HAIKU_SYSTEM stack to Haiku), then runs the
deterministic + tolerance graders from graders.py on the
returned prediction list.

Run from the backend directory so the jobs.* imports resolve:

    cd backend
    python -m evals.evaluator.runner
    # or
    python -m evals.evaluator.runner --fixture tsla_tier1

Flags:
    --fixture <id>     Run a single fixture (by filename stem)
    --json             Emit machine-readable JSON report on stdout
    --log-dir <dir>    Append run history JSONL to this dir (default:
                       .claude/evals/ at the repo root)

Exit codes:
    0 — all fixtures passed (regression gate satisfied)
    1 — one or more fixtures failed
    2 — runner infrastructure error (missing key, import failure, etc)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Make `backend/` the import root so `jobs.*` and `evals.*` resolve the
# same way they do in production worker.py invocations.
_BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from evals.evaluator.graders import (  # noqa: E402
    grade_conviction,
    grade_direction,
    grade_ticker,
    grade_tier_score,
    grade_timeframe,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"
DEFAULT_LOG_DIR = _BACKEND_DIR.parent / ".claude" / "evals"


def _load_fixtures(only: str | None = None) -> list[dict]:
    fixtures = []
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        if only and path.stem != only:
            continue
        with path.open() as f:
            data = json.load(f)
        data["_path"] = str(path)
        fixtures.append(data)
    return fixtures


def _pick_prediction(preds: list[dict], expected_ticker: str) -> dict | None:
    """Match the classifier's output list against the expected ticker.

    The classifier can legitimately return multiple predictions from one
    transcript (ranked lists, multi-ticker videos). We match on normalized
    ticker; if none match, return None so the grader reports misses for
    every field.
    """
    target = (expected_ticker or "").strip().upper().lstrip("$")
    for p in preds:
        if not isinstance(p, dict):
            continue
        t = str(p.get("ticker") or "").strip().upper().lstrip("$")
        if t == target:
            return p
    return None


def _window_days(publish_date: str, expected_timeframe: str) -> int:
    """Compute the window_days used by the tolerance grader.

    Derives from (expected_timeframe - publish_date) so the fixture
    drives which row of the _TOLERANCE table we use. Falls back to
    90 (the HAIKU_SYSTEM default) if parsing fails.
    """
    try:
        pub = datetime.strptime(publish_date, "%Y-%m-%d").date()
        exp = datetime.strptime(expected_timeframe, "%Y-%m-%d").date()
        return max(1, (exp - pub).days)
    except (TypeError, ValueError):
        return 90


def run_fixture(fixture: dict) -> dict:
    """Run a single fixture through the real classifier and grade it."""
    from jobs.youtube_classifier import classify_video

    inp = fixture["input"]
    expected = fixture["expected"]

    t0 = time.monotonic()
    preds, telemetry = classify_video(
        channel_name=inp["channel_name"],
        title=inp["title"],
        publish_date=inp["publish_date"],
        transcript=inp["transcript"],
        video_id=f"eval_{fixture['id']}",
        db=None,
    )
    elapsed = time.monotonic() - t0

    matched = _pick_prediction(preds, expected["ticker"])

    if matched is None:
        none_result = {
            "pass": False,
            "expected": expected["ticker"],
            "actual": None,
            "detail": f"no prediction matched ticker={expected['ticker']!r}",
        }
        graders = [
            {"field": "ticker", **none_result},
            {"field": "direction", **none_result},
            {"field": "timeframe", **none_result},
            {"field": "conviction", **none_result},
            {"field": "tier_score", **none_result},
        ]
    else:
        window = _window_days(inp["publish_date"], expected["timeframe"])
        graders = [
            grade_ticker(expected["ticker"], matched.get("ticker")),
            grade_direction(expected["direction"], matched.get("direction")),
            grade_timeframe(
                expected["timeframe"],
                matched.get("timeframe"),
                tolerance_days=int(expected.get("timeframe_tolerance_days", 7)),
            ),
            grade_conviction(expected.get("conviction", ""), matched.get("confidence")),
            grade_tier_score(
                expected.get("tier_score"),
                matched.get("price_target"),
                window_days=window,
                override_pct=expected.get("tolerance_pct_override"),
            ),
        ]

    passed = all(g["pass"] for g in graders)
    return {
        "id": fixture["id"],
        "case_tier": fixture.get("case_tier"),
        "pass": passed,
        "elapsed_s": round(elapsed, 2),
        "classifier_error": telemetry.get("error"),
        "n_preds_returned": len(preds),
        "matched": matched,
        "graders": graders,
    }


def _format_report(results: list[dict]) -> str:
    lines = []
    lines.append("")
    lines.append("=" * 72)
    lines.append("EIDOLUM THREE-SOURCE EVALUATOR — EVAL HARNESS RESULTS")
    lines.append("=" * 72)
    for r in results:
        badge = "PASS" if r["pass"] else "FAIL"
        lines.append(
            f"\n[{badge}] {r['id']} (tier {r['case_tier']}) "
            f"— {r['elapsed_s']}s, {r['n_preds_returned']} preds returned"
        )
        if r.get("classifier_error"):
            lines.append(f"   classifier_error: {r['classifier_error']}")
        for g in r["graders"]:
            mark = "PASS" if g["pass"] else "FAIL"
            lines.append(f"   {mark}  {g['field']:<11}  {g['detail']}")
    n_pass = sum(1 for r in results if r["pass"])
    n = len(results)
    pct = (n_pass / n * 100) if n else 0
    lines.append("")
    lines.append("-" * 72)
    lines.append(f"pass@1: {n_pass}/{n} ({pct:.0f}%)")
    lines.append(
        "regression gate (pass^3 = 1.00): "
        + ("SATISFIED" if n_pass == n and n >= 3 else "NOT SATISFIED")
    )
    lines.append("-" * 72)
    return "\n".join(lines)


def _append_log(log_dir: Path, results: list[dict]) -> None:
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "evaluator.log"
        with log_path.open("a") as f:
            f.write(json.dumps({
                "ts": datetime.utcnow().isoformat() + "Z",
                "n_fixtures": len(results),
                "n_pass": sum(1 for r in results if r["pass"]),
                "results": [
                    {
                        "id": r["id"],
                        "pass": r["pass"],
                        "elapsed_s": r["elapsed_s"],
                        "classifier_error": r.get("classifier_error"),
                        "graders": [
                            {"field": g["field"], "pass": g["pass"], "detail": g["detail"]}
                            for g in r["graders"]
                        ],
                    }
                    for r in results
                ],
            }) + "\n")
    except OSError as e:
        print(f"[eval-runner] could not write log: {e}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixture", help="Run a single fixture (by filename stem)")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    ap.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    args = ap.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        print("[eval-runner] ANTHROPIC_API_KEY is not set — cannot run the "
              "real HAIKU_SYSTEM stack.", file=sys.stderr)
        return 2

    fixtures = _load_fixtures(only=args.fixture)
    if not fixtures:
        print(f"[eval-runner] no fixtures found in {FIXTURE_DIR}", file=sys.stderr)
        return 2

    results = []
    for fx in fixtures:
        try:
            results.append(run_fixture(fx))
        except Exception as e:
            results.append({
                "id": fx["id"],
                "case_tier": fx.get("case_tier"),
                "pass": False,
                "elapsed_s": 0,
                "classifier_error": f"{type(e).__name__}: {e}",
                "n_preds_returned": 0,
                "matched": None,
                "graders": [
                    {"field": "runner", "pass": False,
                     "detail": f"harness exception: {type(e).__name__}: {e}"}
                ],
            })

    _append_log(Path(args.log_dir), results)

    if args.json:
        print(json.dumps({
            "pass_at_1": sum(1 for r in results if r["pass"]) / len(results),
            "results": results,
        }, indent=2, default=str))
    else:
        print(_format_report(results))

    return 0 if all(r["pass"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())

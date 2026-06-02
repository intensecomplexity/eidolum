"""Fixture runner for classifier_validation Rules 11-14.

Loads classifier_rules_11_14.json and runs each rule IN ISOLATION against
its labeled examples, reporting TP / FP / TN / FN per rule plus the ship
decision (0 false positives AND >=70% true-positive rate => ship in shadow).

Rule 13 runs with db=None (symbol-only individual-mention check); fixtures
are authored so the symbol presence/absence is the determinant. Production
additionally accepts company-name aliases via db, which is strictly more
lenient and so cannot introduce false positives beyond this set.

Run:  python3 backend/jobs/_fixtures/run_rules_11_14_tests.py
Exit code is non-zero if any rule has a false positive or <70% TP rate.
"""
import json
import os
import sys

# Allow `python3 backend/jobs/_fixtures/run_rules_11_14_tests.py` from repo root.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.jobs import classifier_validation as g  # noqa: E402

_FIXTURE = os.path.join(os.path.dirname(__file__), "classifier_rules_11_14.json")

# rule key -> callable(example) -> accepted(bool). Each adapter pulls the
# fields that rule consumes from the example dict, mirroring the orchestrator.
RUNNERS = {
    "rule_11_question_rhetorical":
        lambda e: g.check_question_rhetorical(e.get("source_verbatim_quote"))[0],
    "rule_12_prediction_date_passed":
        lambda e: g.check_date_passed(
            e.get("prediction_date"), e.get("video_published_at"),
            e.get("window_days"), e.get("inferred_timeframe_days"),
            e.get("timeframe_category"))[0],
    "rule_13_basket_too_broad":
        lambda e: g.check_basket_too_broad(
            e.get("source_verbatim_quote"), e.get("ticker"), None)[0],
    "rule_14_news_recap_no_prediction":
        lambda e: g.check_news_recap(e.get("source_verbatim_quote"))[0],
}


def _run_rule(name, block, runner):
    """Return (tp, fp, tn, fn, fp_examples, fn_examples)."""
    tp = fp = tn = fn = 0
    fp_ex, fn_ex = [], []
    for e in block.get("should_reject", []):
        accepted = runner(e)
        if accepted:
            fn += 1
            fn_ex.append(e)
        else:
            tp += 1
    for e in block.get("should_pass", []):
        accepted = runner(e)
        if accepted:
            tn += 1
        else:
            fp += 1
            fp_ex.append(e)
    return tp, fp, tn, fn, fp_ex, fn_ex


def main():
    with open(_FIXTURE) as fh:
        data = json.load(fh)

    overall_ok = True
    print("=" * 72)
    print("Classifier Rules 11-14 — fixture results")
    print("=" * 72)
    for name, runner in RUNNERS.items():
        block = data[name]
        tp, fp, tn, fn, fp_ex, fn_ex = _run_rule(name, block, runner)
        n_pos = tp + fn
        tp_rate = (tp / n_pos * 100) if n_pos else 0.0
        rule_ok = (fp == 0) and (tp_rate >= 70.0)
        overall_ok = overall_ok and rule_ok
        verdict = "SHIP (shadow)" if rule_ok else "BLOCK"
        print(f"\n{name}")
        print(f"  TP={tp}  FP={fp}  TN={tn}  FN={fn}   "
              f"TP-rate={tp_rate:.0f}%   -> {verdict}")
        if fp_ex:
            print("  !! FALSE POSITIVES (should_pass but rejected):")
            for e in fp_ex:
                print(f"     [{e.get('ticker')}] "
                      f"{(e.get('source_verbatim_quote') or '')[:90]}")
        if fn_ex:
            print(f"  .. false negatives ({fn}/{n_pos}, "
                  f"{fn/n_pos*100:.0f}% missed):")
            for e in fn_ex:
                print(f"     [{e.get('ticker')}] "
                      f"{(e.get('source_verbatim_quote') or '')[:90]}")
            if fn / n_pos > 0.20:
                print("  ** FN rate >20% — flag for refinement (does not block ship)")

    print("\n" + "=" * 72)
    print("OVERALL:", "ALL RULES SHIP-READY (shadow)" if overall_ok
          else "ONE OR MORE RULES BLOCKED")
    print("=" * 72)
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())

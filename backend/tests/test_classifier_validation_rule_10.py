"""Unit test for classifier_validation Rule 10 (Tier-1 hypothetical-scenario
rejection).

The critical precision invariant is in PASS_CASES below: Tier-2 hedged
commitments ("could", "might", "may", "should") MUST NOT trigger Rule 10.
Those are real (if soft) predictions and are tagged conviction=hedged
elsewhere; gate-rejecting them would discard useful signal. If any of the
Tier-2 PASS_CASES start rejecting, the patterns are too broad — narrow
them rather than ship.

Run:  python3 backend/tests/test_classifier_validation_rule_10.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jobs.classifier_validation import check_hypothetical_scenario


# Tier 1 — MUST reject (pure scenarios)
REJECT_CASES = [
    "In a bull case, TSLA hits $300 by year end",
    "In a bear case scenario, BTC drops to $20K",
    "Imagine if AAPL doubled by 2027",
    "Let's say NVDA reaches $2000, then it's a 4x from here",
    "Hypothetically, MSFT could break $500 this year",
    "In a world where the Fed cuts to zero, TSLA hits $400",
    "Purely hypothetical: AMZN at $300 in a soft-landing scenario",
    "If we assume strong earnings, PLTR hits $80 next quarter",
]

# Tier 2 hedged commitments — MUST pass (separately tagged conviction=hedged)
# Tier 3 explicit conditionals — MUST pass (extracted as conditional_call)
# Plus generic edge cases.
PASS_CASES = [
    # Tier 2 hedged
    "TSLA could break $300 by year end",
    "PLTR might see $50 if government contracts come through",
    "AAPL may hit $250 in Q4",
    "I think NVDA could reach $1500 next year",
    "BTC should test $100K before year end",
    # Tier 3 conditional
    "If Apple breaks $200 this week, Tesla follows to $300",
    # Generic predictions with no scenario markers
    "Bullish on PLTR, target $50 in 6 months",
    "I'm calling AMD a strong buy with a $250 target",
    "Expecting HOOD to break $50 next quarter",
    # Edge cases
    "",
    None,
]


def run():
    failures = []

    for quote in REJECT_CASES:
        ok, reason = check_hypothetical_scenario(quote)
        if ok or reason != "hypothetical_scenario":
            failures.append(
                f"FAIL [should REJECT but got ok={ok} reason={reason}]: {quote!r}"
            )
        else:
            print(f"PASS REJECT: {quote!r}")

    for quote in PASS_CASES:
        ok, reason = check_hypothetical_scenario(quote)
        if not ok:
            failures.append(
                f"FAIL [should PASS but got ok={ok} reason={reason}]: {quote!r}"
            )
        else:
            print(f"PASS ACCEPT: {quote!r}")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print("  " + f)
        sys.exit(1)
    print(f"All {len(REJECT_CASES) + len(PASS_CASES)} cases passed.")
    sys.exit(0)


if __name__ == "__main__":
    run()

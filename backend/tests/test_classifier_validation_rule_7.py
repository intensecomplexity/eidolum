"""Unit test for classifier_validation Rule 7 (reported-speech rejection).

Operates purely on the verbatim quote — no DB, no caller plumbing. Runs as:

    python3 backend/tests/test_classifier_validation_rule_7.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jobs.classifier_validation import check_reported_speech


# Cases that SHOULD reject (reported_speech)
REJECT_CASES = [
    "Cathie Wood said TSLA is going to $2000 by 2027",
    "According to Buffett, the market is overvalued at these levels",
    "Pomp tweeted that BTC hits $200K this year",
    "Per Goldman Sachs, AAPL is a buy with a $250 target by year end",
    "Tom Lee believes the S&P hits 6000 by year end",
    "In his latest note, Mike Wilson warned of a 20% correction",
    "Bill Ackman recommended HHH at $80 with a $120 target",
]

# Cases that SHOULD pass — first-person predictions or no attribution at all
PASS_CASES = [
    "I think TSLA hits $300 in the next year",
    "We're targeting $200 on AAPL by end of Q4",
    "My call: NVDA to $1500 by Q4. Buffett also said something about Apple.",
    "Bullish on PLTR, target $50 in 6 months",
    "I'm calling AMD a strong buy with a $250 target",
    "Expecting HOOD to break $50 next quarter",
    "",
    None,
]


def run():
    failures = []

    for quote in REJECT_CASES:
        ok, reason = check_reported_speech(quote)
        if ok or reason != "reported_speech":
            failures.append(
                f"FAIL [should REJECT but got ok={ok} reason={reason}]: {quote!r}"
            )
        else:
            print(f"PASS REJECT: {quote!r}")

    for quote in PASS_CASES:
        ok, reason = check_reported_speech(quote)
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

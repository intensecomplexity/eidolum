"""Regression test for Ship #13B Bug 15.

The homepage "Biggest Calls" widget used to reshuffle rows between
page loads — the SQL ``ORDER BY ABS(p.actual_return) DESC`` had no
tie-breaker, so two predictions with identical magnitudes could swap
positions (and the LIMIT 5 could swap which row was excluded). This
test pins the SQL so the ordering clause always contains:

    ORDER BY ABS(p.actual_return) DESC, p.id ASC

Also asserts the upper cap was removed so we reflect the uncapped
return in the widget ordering.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestBiggestCallsDeterministicSort(unittest.TestCase):
    def setUp(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "routers", "leaderboard.py"
        )
        with open(path) as f:
            self.src = f.read()
        # Isolate the Biggest Calls SQL section so unrelated ORDER BY
        # clauses elsewhere in the file don't poison the assertions.
        marker = "# Biggest Calls:"
        self.assertIn(marker, self.src, "Biggest Calls section marker missing")
        after = self.src.split(marker, 1)[1]
        next_marker = "# Most Divided:"
        self.bc_block = after.split(next_marker, 1)[0]

    def test_order_by_has_deterministic_tiebreaker(self):
        # Must order primarily by magnitude, then deterministically by id.
        self.assertIn("ORDER BY ABS(p.actual_return) DESC", self.bc_block)
        self.assertRegex(
            self.bc_block,
            r"ORDER BY ABS\(p\.actual_return\) DESC,\s*p\.id ASC",
            "biggest_calls ORDER BY missing p.id ASC tiebreaker",
        )

    def test_upper_cap_removed(self):
        # The old query had `ABS(p.actual_return) BETWEEN 5 AND 200`
        # which artificially capped how big a "Biggest Call" could be.
        # Option B removes the upper bound — only a floor remains.
        self.assertNotIn("BETWEEN 5 AND 200", self.bc_block)
        self.assertIn("ABS(p.actual_return) >= 5", self.bc_block)


class TestPythonSortStability(unittest.TestCase):
    """Independent sanity check: Python's sorted() with the same key
    tuple Postgres uses is stable, so if SQL hands us rows with ties
    our tiebreaker would still produce a deterministic order."""

    def test_stable_tiebreaker(self):
        # Three rows with identical ABS(actual_return)=50. Ids 1, 2, 3.
        rows = [
            (3, "TSLA", 50.0),
            (1, "AAPL", 50.0),
            (2, "NVDA", 50.0),
        ]
        ordered = sorted(rows, key=lambda r: (-abs(r[2]), r[0]))
        self.assertEqual([r[0] for r in ordered], [1, 2, 3])

    def test_magnitude_dominates_tiebreaker(self):
        rows = [
            (1, "A", 50.0),
            (2, "B", 80.0),
            (3, "C", -90.0),
        ]
        ordered = sorted(rows, key=lambda r: (-abs(r[2]), r[0]))
        self.assertEqual([r[0] for r in ordered], [3, 2, 1])


if __name__ == "__main__":
    unittest.main()

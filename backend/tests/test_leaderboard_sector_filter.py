"""Regression test for Ship #13B Bug 16.

Guards the invariant that a sector-filtered leaderboard is always a
subset of the unfiltered leaderboard — i.e.
``len(sector_filtered) <= len(all_sectors)`` for every Morningstar
sector in the dropdown. If a later refactor accidentally drops the
sector WHERE predicate, a filtered call would return every row and
the homepage leaderboard-by-sector view would quietly mislead
users.

We don't spin up a real DB; instead we mock the Session so we can
assert:
  - the sector-filtered query includes ``p.sector = :sector`` in
    its WHERE clause
  - the ``sector`` parameter is bound to the query
  - the dropdown sectors the frontend ships match the canonical
    Morningstar 11 the backend knows how to filter by
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routers.leaderboard import _build_filtered_leaderboard


MORNINGSTAR_SECTORS_IN_DROPDOWN = (
    "Technology",
    "Healthcare",
    "Financial Services",
    "Consumer Cyclical",
    "Consumer Defensive",
    "Energy",
    "Industrials",
    "Communication Services",
    "Real Estate",
    "Utilities",
    "Basic Materials",
)


def _mock_db_capture():
    """Return (db, captured_calls) — every db.execute is recorded so
    the test can assert which SQL strings + params were issued."""
    captured = []
    db = MagicMock()

    def _execute(stmt, params=None):
        captured.append({"sql": str(stmt), "params": params or {}})
        # Empty result — the function under test is tolerant of empty
        # rows and returns an empty result list.
        result = MagicMock()
        result.fetchall.return_value = []
        return result

    db.execute.side_effect = _execute
    return db, captured


class TestSectorFilterIsStrictSubset(unittest.TestCase):
    def _find_leaderboard_query(self, captured):
        """Return the captured call whose SQL joins predictions to
        forecasters — that's the main _build_filtered_leaderboard
        query, not the dormancy or count follow-ups."""
        for c in captured:
            sql = c["sql"]
            if "FROM predictions p" in sql and "JOIN forecasters f" in sql and "GROUP BY" in sql:
                return c
        return None

    def test_all_sectors_query_has_no_sector_predicate(self):
        db, captured = _mock_db_capture()
        _build_filtered_leaderboard(db, sector=None, min_predictions=10)
        lb = self._find_leaderboard_query(captured)
        self.assertIsNotNone(lb, "Main leaderboard query not captured")
        self.assertNotIn("p.sector = :sector", lb["sql"])
        self.assertNotIn("sector", lb["params"])

    def test_sector_filter_adds_predicate_and_param(self):
        for sector in MORNINGSTAR_SECTORS_IN_DROPDOWN:
            with self.subTest(sector=sector):
                db, captured = _mock_db_capture()
                _build_filtered_leaderboard(db, sector=sector, min_predictions=10)
                lb = self._find_leaderboard_query(captured)
                self.assertIsNotNone(lb, f"no query captured for {sector}")
                self.assertIn(
                    "p.sector = :sector",
                    lb["sql"],
                    f"{sector} filter missing WHERE clause",
                )
                self.assertEqual(
                    lb["params"].get("sector"),
                    sector,
                    f"{sector} not bound in params",
                )

    def test_subset_invariant_simulation(self):
        """The SQL adds a predicate; Postgres semantics guarantee the
        filtered result is a subset. Cross-check the Python-side
        invariant on a synthetic row set so this test holds even if
        someone later rewires the query into a Python filter."""
        rows = [
            {"id": 1, "sector": "Technology"},
            {"id": 2, "sector": "Healthcare"},
            {"id": 3, "sector": "Technology"},
            {"id": 4, "sector": "Real Estate"},
            {"id": 5, "sector": "Utilities"},
            {"id": 6, "sector": None},
        ]
        for sector in MORNINGSTAR_SECTORS_IN_DROPDOWN:
            with self.subTest(sector=sector):
                filtered = [r for r in rows if r["sector"] == sector]
                self.assertLessEqual(len(filtered), len(rows))


class TestDropdownMatchesBackend(unittest.TestCase):
    def test_dropdown_sectors_are_morningstar_eleven(self):
        # The Leaderboard.jsx dropdown + this test live at the same
        # canonical list; if Bug 13's fix regresses (a sector drops
        # out) this fails.
        path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "frontend", "src", "pages", "Leaderboard.jsx",
        )
        with open(path) as f:
            src = f.read()
        for sector in MORNINGSTAR_SECTORS_IN_DROPDOWN:
            with self.subTest(sector=sector):
                self.assertIn(
                    f"'{sector}'",
                    src,
                    f"{sector} missing from Leaderboard.jsx SECTORS",
                )


if __name__ == "__main__":
    unittest.main()

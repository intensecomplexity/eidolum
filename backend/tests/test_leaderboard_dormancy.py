"""Regression tests for the Eidolum 100 leaderboard top-up.

Guards against the Ship #13 Bug A regression where dormant forecasters
in the top-N window caused the Eidolum 100 to under-fill (74 rows instead
of 100) after the 43bbf51 rank-gap fix.

The tests exercise:
  - _apply_dormancy: dense re-rank, idempotency, include_dormant branch
  - _fetch_dormancy: graceful degradation when the column doesn't exist
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routers.leaderboard import _apply_dormancy, _fetch_dormancy, _count_non_dormant


def _fake_db_with_dormancy(dormancy_map):
    """Build a MagicMock Session whose execute().fetchall() returns dormancy
    rows shaped like SELECT id, is_dormant, last_prediction_at."""
    db = MagicMock()
    rows = [(fid, is_d, last_at) for fid, (is_d, last_at) in dormancy_map.items()]
    db.execute.return_value.fetchall.return_value = rows
    return db


class TestApplyDormancy(unittest.TestCase):
    def test_dense_rerank_removes_gaps(self):
        # 5 results; rows 2 and 4 are dormant. After filter we get 3 rows
        # ranked densely 1,2,3 — never 1,3,5.
        results = [{"id": i, "rank": i} for i in range(1, 6)]
        db = _fake_db_with_dormancy({
            1: (False, None),
            2: (True, None),
            3: (False, None),
            4: (True, None),
            5: (False, None),
        })
        out = _apply_dormancy(db, results, include_dormant=False, top_n=10)
        self.assertEqual(len(out), 3)
        self.assertEqual([r["rank"] for r in out], [1, 2, 3])
        self.assertEqual([r["id"] for r in out], [1, 3, 5])

    def test_top_n_slice_after_filter(self):
        # 200 results, 20% dormant. top_n=100 should give exactly 100 rows.
        results = [{"id": i, "rank": i} for i in range(1, 201)]
        dormancy = {i: ((i % 5 == 0), None) for i in range(1, 201)}
        db = _fake_db_with_dormancy(dormancy)
        out = _apply_dormancy(db, results, include_dormant=False, top_n=100)
        self.assertEqual(len(out), 100)
        self.assertEqual(out[0]["rank"], 1)
        self.assertEqual(out[-1]["rank"], 100)

    def test_include_dormant_preserves_all(self):
        results = [{"id": i, "rank": i} for i in range(1, 6)]
        db = _fake_db_with_dormancy({
            1: (False, None),
            2: (True, None),
            3: (False, None),
            4: (True, None),
            5: (False, None),
        })
        out = _apply_dormancy(db, results, include_dormant=True, top_n=10)
        self.assertEqual(len(out), 5)
        self.assertEqual([r["rank"] for r in out], [1, 2, 3, 4, 5])
        # is_dormant annotation still applied on dormant rows
        self.assertTrue(out[1]["is_dormant"])
        self.assertFalse(out[0]["is_dormant"])

    def test_idempotent_repeated_calls(self):
        # Calling _apply_dormancy twice on the same list must not double-trim
        # or mutate ranks across invocations — important because the refresh
        # loop can probe dormancy during top-up and then call it again at
        # read time.
        results = [{"id": i, "rank": i} for i in range(1, 11)]
        dormancy = {i: ((i in {3, 7}), None) for i in range(1, 11)}
        db = _fake_db_with_dormancy(dormancy)
        first = _apply_dormancy(db, results, include_dormant=False, top_n=100)
        second = _apply_dormancy(db, results, include_dormant=False, top_n=100)
        self.assertEqual([r["id"] for r in first], [r["id"] for r in second])
        self.assertEqual([r["rank"] for r in first], [r["rank"] for r in second])
        self.assertEqual(len(first), 8)

    def test_empty_list(self):
        db = _fake_db_with_dormancy({})
        self.assertEqual(_apply_dormancy(db, [], include_dormant=False), [])


class TestFetchDormancy(unittest.TestCase):
    def test_graceful_degradation_on_missing_column(self):
        db = MagicMock()
        db.execute.side_effect = Exception("column is_dormant does not exist")
        self.assertEqual(_fetch_dormancy(db, [1, 2, 3]), {})

    def test_empty_fids_short_circuit(self):
        db = MagicMock()
        self.assertEqual(_fetch_dormancy(db, []), {})
        db.execute.assert_not_called()


class TestCountNonDormant(unittest.TestCase):
    def test_counts_live_only(self):
        results = [{"id": i} for i in range(1, 6)]
        dormancy = {1: (False, None), 2: (True, None), 3: (False, None),
                    4: (True, None), 5: (False, None)}
        self.assertEqual(_count_non_dormant(results, dormancy), 3)

    def test_unknown_ids_treated_live(self):
        # Forecasters missing from the dormancy map default to live — this
        # matches the refresh-loop top-up check, which can't distinguish
        # "never queried" from "known-live".
        results = [{"id": 1}, {"id": 2}]
        self.assertEqual(_count_non_dormant(results, {}), 2)


if __name__ == "__main__":
    unittest.main()

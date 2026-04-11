"""Regression tests for Ship #13B Bug 12.

The /asset/{ticker}/consensus and /ticker/{ticker}/discussions POST
endpoints used to quietly render an empty-state dict (or allow a
comment) for any string you threw at them. That let /asset/RANDOMXYZ
look like a real asset page and let users pin discussion threads to
bogus symbols. Both now 404 when the ticker is unknown.

These tests exercise the shared helper directly with a fake DB since
the routers don't need to spin up a full app to validate the gate.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.ticker import ticker_is_known


def _fake_db_with_rows(ticker_sector_hits=None, prediction_hits=None):
    """Build a MagicMock Session whose execute().first() returns a truthy
    row for the specific queries we care about."""
    ticker_sector_hits = ticker_sector_hits or {}
    prediction_hits = prediction_hits or {}
    db = MagicMock()

    def _execute(stmt, params=None):
        result = MagicMock()
        sql = str(stmt)
        t = (params or {}).get("t", "")
        if "ticker_sectors" in sql:
            result.first.return_value = (1,) if ticker_sector_hits.get(t) else None
        elif "predictions" in sql:
            result.first.return_value = (1,) if prediction_hits.get(t) else None
        else:
            result.first.return_value = None
        return result

    db.execute.side_effect = _execute
    return db


class TestTickerIsKnown(unittest.TestCase):
    def test_unknown_ticker_returns_false(self):
        db = _fake_db_with_rows()
        self.assertFalse(ticker_is_known(db, "RANDOMXYZ"))

    def test_known_via_ticker_info(self):
        # TICKER_INFO is the hardcoded lookup — AAPL is always there.
        db = _fake_db_with_rows()
        self.assertTrue(ticker_is_known(db, "AAPL"))

    def test_known_via_ticker_sectors_row(self):
        db = _fake_db_with_rows(ticker_sector_hits={"NEWCO": True})
        self.assertTrue(ticker_is_known(db, "NEWCO"))

    def test_known_via_predictions_row(self):
        db = _fake_db_with_rows(prediction_hits={"OLDTKR": True})
        self.assertTrue(ticker_is_known(db, "OLDTKR"))

    def test_case_insensitive(self):
        db = _fake_db_with_rows(ticker_sector_hits={"FOO": True})
        self.assertTrue(ticker_is_known(db, "foo"))
        self.assertTrue(ticker_is_known(db, "Foo"))

    def test_blank_returns_false(self):
        db = _fake_db_with_rows()
        self.assertFalse(ticker_is_known(db, ""))
        self.assertFalse(ticker_is_known(db, "   "))
        self.assertFalse(ticker_is_known(db, None))

    def test_db_error_does_not_crash(self):
        # ticker_sectors query raising an exception must be swallowed so
        # we still fall through to the predictions check.
        db = MagicMock()
        call_count = {"n": 0}

        def _execute(stmt, params=None):
            call_count["n"] += 1
            sql = str(stmt)
            if "ticker_sectors" in sql:
                raise Exception("simulated DB error")
            result = MagicMock()
            # predictions query: yes, this ticker has predictions
            result.first.return_value = (1,)
            return result

        db.execute.side_effect = _execute
        self.assertTrue(ticker_is_known(db, "DBERR"))
        self.assertGreaterEqual(call_count["n"], 2)


class TestAssetEndpointUsesGuard(unittest.TestCase):
    """Sanity check that both guarded routers import the helper."""

    def test_assets_router_imports_guard(self):
        import routers.assets as m
        self.assertTrue(hasattr(m, "ticker_is_known"))

    def test_discussions_router_imports_guard(self):
        import routers.ticker_discussions as m
        self.assertTrue(hasattr(m, "ticker_is_known"))


if __name__ == "__main__":
    unittest.main()

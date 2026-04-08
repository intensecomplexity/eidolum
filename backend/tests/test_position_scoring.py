"""Unit tests for position-disclosure scoring logic.

Tests cover:
  - score_position_disclosure: hit/near/miss thresholds for bullish & bearish
  - _extract_position_fields: Haiku response parsing
  - Open -> exit lifecycle via position_matcher (with an in-memory DB)
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

# Make the backend importable when tests run from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jobs.historical_evaluator import score_position_disclosure
from jobs.x_scraper import _extract_position_fields


class TestScorePositionDisclosure(unittest.TestCase):
    def test_bullish_hit(self):
        # +10% return → hit
        outcome, ret = score_position_disclosure("bullish", 100.0, 110.0)
        self.assertEqual(outcome, "hit")
        self.assertEqual(ret, 10.0)

    def test_bullish_exactly_five_pct(self):
        outcome, ret = score_position_disclosure("bullish", 100.0, 105.0)
        self.assertEqual(outcome, "hit")
        self.assertEqual(ret, 5.0)

    def test_bullish_near(self):
        # +2% → near
        outcome, ret = score_position_disclosure("bullish", 100.0, 102.0)
        self.assertEqual(outcome, "near")

    def test_bullish_exactly_zero(self):
        outcome, ret = score_position_disclosure("bullish", 100.0, 100.0)
        self.assertEqual(outcome, "near")
        self.assertEqual(ret, 0.0)

    def test_bullish_miss(self):
        # -3% → miss
        outcome, ret = score_position_disclosure("bullish", 100.0, 97.0)
        self.assertEqual(outcome, "miss")
        self.assertEqual(ret, -3.0)

    def test_bearish_hit(self):
        # short, stock dropped 10% → hit
        outcome, ret = score_position_disclosure("bearish", 100.0, 90.0)
        self.assertEqual(outcome, "hit")
        self.assertEqual(ret, -10.0)

    def test_bearish_near(self):
        outcome, ret = score_position_disclosure("bearish", 100.0, 98.0)
        self.assertEqual(outcome, "near")

    def test_bearish_miss(self):
        # short, stock went UP → miss
        outcome, ret = score_position_disclosure("bearish", 100.0, 110.0)
        self.assertEqual(outcome, "miss")
        self.assertEqual(ret, 10.0)

    def test_missing_prices(self):
        outcome, ret = score_position_disclosure("bullish", None, 100.0)
        self.assertEqual(outcome, "no_data")
        outcome, ret = score_position_disclosure("bullish", 100.0, None)
        self.assertEqual(outcome, "no_data")

    def test_zero_entry_price(self):
        outcome, ret = score_position_disclosure("bullish", 0.0, 100.0)
        self.assertEqual(outcome, "no_data")


class TestExtractPositionFields(unittest.TestCase):
    def test_position_disclosure_open(self):
        result = {"prediction_type": "position_disclosure", "position_action": "open"}
        ptype, action = _extract_position_fields(result)
        self.assertEqual(ptype, "position_disclosure")
        self.assertEqual(action, "open")

    def test_position_disclosure_exit(self):
        result = {"prediction_type": "position_disclosure", "position_action": "exit"}
        ptype, action = _extract_position_fields(result)
        self.assertEqual(ptype, "position_disclosure")
        self.assertEqual(action, "exit")

    def test_price_target_default(self):
        result = {"prediction_type": "price_target"}
        ptype, action = _extract_position_fields(result)
        self.assertEqual(ptype, "price_target")
        self.assertIsNone(action)

    def test_missing_prediction_type(self):
        result = {}
        ptype, action = _extract_position_fields(result)
        self.assertEqual(ptype, "price_target")
        self.assertIsNone(action)

    def test_invalid_action_falls_back(self):
        result = {"prediction_type": "position_disclosure", "position_action": "bogus"}
        ptype, action = _extract_position_fields(result)
        self.assertEqual(ptype, "price_target")
        self.assertIsNone(action)

    def test_case_insensitive(self):
        result = {"prediction_type": "POSITION_DISCLOSURE", "position_action": "OPEN"}
        ptype, action = _extract_position_fields(result)
        self.assertEqual(ptype, "position_disclosure")
        self.assertEqual(action, "open")


class TestPositionLifecycle(unittest.TestCase):
    """End-to-end open → exit lifecycle on an in-memory SQLite DB."""

    def setUp(self):
        os.environ["DATABASE_URL"] = "sqlite:///:memory:"
        # Force re-import so engine picks up the in-memory URL
        for mod in [
            "database", "models", "services.position_matcher",
        ]:
            if mod in sys.modules:
                del sys.modules[mod]
        from database import engine, Base
        import models  # noqa: F401 — register tables
        Base.metadata.create_all(bind=engine)
        from database import SessionLocal
        self.db = SessionLocal()

        # Insert a minimal forecaster row
        from sqlalchemy import text
        self.db.execute(text(
            "INSERT INTO forecasters (id, name, handle) VALUES (1, 'Test', 'test')"
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_open_then_exit_closes_position(self):
        from models import Prediction
        from services.position_matcher import find_open_position, close_position

        open_date = datetime(2026, 1, 15, 10, 0, 0)
        p = Prediction(
            forecaster_id=1, ticker="NVDA", direction="bullish",
            prediction_date=open_date,
            evaluation_date=open_date + timedelta(days=365),
            window_days=365,
            source_type="x", source_platform_id="x_1_NVDA",
            context="@test: New position in $NVDA", exact_quote="New position in $NVDA",
            outcome="pending", verified_by="x_scraper",
            prediction_type="position_disclosure",
            position_action="open",
            confidence_tier=0.85,
        )
        self.db.add(p)
        self.db.commit()
        self.db.refresh(p)

        # Lookup finds it
        open_pos = find_open_position(self.db, 1, "NVDA")
        self.assertIsNotNone(open_pos)
        self.assertEqual(open_pos["id"], p.id)

        # Close it
        exit_date = datetime(2026, 3, 1, 14, 0, 0)
        close_position(self.db, p.id, exit_date)
        self.db.commit()

        # Verify position_closed_at and evaluation_date both updated
        self.db.refresh(p)
        self.assertEqual(p.position_closed_at, exit_date)
        self.assertEqual(p.evaluation_date, exit_date)

        # Subsequent lookup no longer finds it
        open_pos_after = find_open_position(self.db, 1, "NVDA")
        self.assertIsNone(open_pos_after)

    def test_exit_without_matching_open_returns_none(self):
        from services.position_matcher import find_open_position
        result = find_open_position(self.db, 1, "AAPL")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

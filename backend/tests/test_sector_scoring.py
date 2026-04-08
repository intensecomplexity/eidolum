"""Unit tests for sector_call scoring + sector_etf_map.

Run from backend/ with:
    python -m unittest tests.test_sector_scoring -v
"""
import os
import sys
import unittest
from pathlib import Path

# Make backend/ importable as a package root
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))


class TestSectorEtfMap(unittest.TestCase):
    def test_resolves_canonical_sectors(self):
        from services.sector_etf_map import resolve_sector_to_etf
        self.assertEqual(resolve_sector_to_etf("semis"), "SOXX")
        self.assertEqual(resolve_sector_to_etf("regional banks"), "KRE")
        self.assertEqual(resolve_sector_to_etf("homebuilders"), "XHB")
        self.assertEqual(resolve_sector_to_etf("tech"), "XLK")
        self.assertEqual(resolve_sector_to_etf("energy"), "XLE")

    def test_normalizes_input(self):
        from services.sector_etf_map import resolve_sector_to_etf
        self.assertEqual(resolve_sector_to_etf("  SEMIS  "), "SOXX")
        self.assertEqual(resolve_sector_to_etf("Semis"), "SOXX")

    def test_unknown_returns_none(self):
        from services.sector_etf_map import resolve_sector_to_etf
        self.assertIsNone(resolve_sector_to_etf("crypto"))
        self.assertIsNone(resolve_sector_to_etf(""))
        self.assertIsNone(resolve_sector_to_etf(None))

    def test_find_sector_phrase_in_text_multiword_wins(self):
        from services.sector_etf_map import find_sector_phrase_in_text
        # 'regional banks' must match before 'banks' (longest wins)
        self.assertEqual(
            find_sector_phrase_in_text("Bearish on regional banks for 6 months"),
            "regional banks",
        )

    def test_find_sector_phrase_no_match(self):
        from services.sector_etf_map import find_sector_phrase_in_text
        self.assertIsNone(find_sector_phrase_in_text("I love AAPL"))
        self.assertIsNone(find_sector_phrase_in_text(""))


class TestSectorScoring(unittest.TestCase):
    """The 5 cases from the spec, plus boundaries."""

    def setUp(self):
        from jobs.historical_evaluator import score_sector_call, _TOLERANCE, _MIN_MOVEMENT, _get_tolerance
        self.score = score_sector_call
        self.tol = _get_tolerance(90, _TOLERANCE)         # 90d window: tol=5%
        self.min = _get_tolerance(90, _MIN_MOVEMENT)      # 90d window: min=2%
        self.tol_6m = _get_tolerance(180, _TOLERANCE)     # 6m window: tol=7%
        self.min_6m = _get_tolerance(180, _MIN_MOVEMENT)  # 6m window: min=3%

    # ── Spec case 1: Bullish SOXX, ETF +15%, SPY +3%, tol 5% → HIT, spread 12 ──
    def test_bullish_hit_spec_case_1(self):
        # ETF goes 100 -> 115 = +15%, SPY goes 100 -> 103 = +3%, spread = +12
        outcome, etf, spy, spread = self.score("bullish", 100.0, 115.0, 100.0, 103.0,
                                                self.tol, self.min)
        self.assertEqual(outcome, "hit")
        self.assertEqual(etf, 15.0)
        self.assertEqual(spy, 3.0)
        self.assertEqual(spread, 12.0)

    # ── Spec case 2: Bullish SOXX, ETF +5%, SPY +3%, tol 5% → NEAR, spread 2 ──
    # Spread = 2, which equals min_movement (2). Test treats >= min as NEAR.
    def test_bullish_near_spec_case_2(self):
        outcome, etf, spy, spread = self.score("bullish", 100.0, 105.0, 100.0, 103.0,
                                                self.tol, self.min)
        self.assertEqual(outcome, "near")
        self.assertEqual(spread, 2.0)

    # ── Spec case 3: Bullish SOXX, ETF +1%, SPY +3%, tol 5% → MISS, spread -2 ──
    def test_bullish_miss_spec_case_3(self):
        outcome, etf, spy, spread = self.score("bullish", 100.0, 101.0, 100.0, 103.0,
                                                self.tol, self.min)
        self.assertEqual(outcome, "miss")
        self.assertEqual(spread, -2.0)

    # ── Spec case 4: Bearish KRE, ETF -10%, SPY +3%, tol 7% → HIT, spread -13 ──
    def test_bearish_hit_spec_case_4(self):
        outcome, etf, spy, spread = self.score("bearish", 100.0, 90.0, 100.0, 103.0,
                                                self.tol_6m, self.min_6m)
        self.assertEqual(outcome, "hit")
        self.assertEqual(etf, -10.0)
        self.assertEqual(spy, 3.0)
        self.assertEqual(spread, -13.0)

    # ── Spec case 5: Bearish KRE, ETF -3%, SPY +3%, tol 7% → NEAR, spread -6 ──
    def test_bearish_near_spec_case_5(self):
        outcome, etf, spy, spread = self.score("bearish", 100.0, 97.0, 100.0, 103.0,
                                                self.tol_6m, self.min_6m)
        self.assertEqual(outcome, "near")
        self.assertEqual(spread, -6.0)

    # ── Boundaries ──
    def test_bullish_exactly_at_tolerance_is_hit(self):
        # Spread exactly == tolerance (5%) should HIT
        outcome, *_ = self.score("bullish", 100.0, 105.0, 100.0, 100.0,
                                  self.tol, self.min)
        self.assertEqual(outcome, "hit")

    def test_bearish_just_above_min_movement_is_miss(self):
        # spread = -1.99 (above -min_movement = -2) → MISS
        outcome, *_ = self.score("bearish", 100.0, 98.01, 100.0, 100.0,
                                  self.tol, self.min)
        self.assertEqual(outcome, "miss")

    def test_zero_etf_start_returns_no_data(self):
        outcome, *_ = self.score("bullish", 0.0, 100.0, 100.0, 105.0,
                                  self.tol, self.min)
        self.assertEqual(outcome, "no_data")

    def test_zero_spy_start_returns_no_data(self):
        outcome, *_ = self.score("bullish", 100.0, 110.0, 0.0, 105.0,
                                  self.tol, self.min)
        self.assertEqual(outcome, "no_data")

    def test_neutral_direction_returns_no_data(self):
        outcome, *_ = self.score("neutral", 100.0, 110.0, 100.0, 105.0,
                                  self.tol, self.min)
        self.assertEqual(outcome, "no_data")


class TestBuildSectorSummary(unittest.TestCase):
    def test_summary_format(self):
        from jobs.historical_evaluator import build_sector_summary
        s = build_sector_summary("bullish", "SOXX", "semis", 15.2, 3.1, 12.1, "hit")
        # Spec format: "Sector call: bullish on SOXX (semis). SOXX +15.2%, SPY +3.1%, spread +12.1%. HIT."
        self.assertIn("Sector call:", s)
        self.assertIn("bullish on SOXX", s)
        self.assertIn("(semis)", s)
        self.assertIn("SOXX +15.2%", s)
        self.assertIn("SPY +3.1%", s)
        self.assertIn("spread +12.1%", s)
        self.assertIn("HIT", s)

    def test_summary_handles_negative_returns(self):
        from jobs.historical_evaluator import build_sector_summary
        s = build_sector_summary("bearish", "KRE", "regional banks", -10.0, 3.0, -13.0, "hit")
        self.assertIn("KRE -10.0%", s)
        self.assertIn("spread -13.0%", s)

    def test_summary_without_sector_phrase(self):
        from jobs.historical_evaluator import build_sector_summary
        s = build_sector_summary("bullish", "XLE", None, 8.0, 4.0, 4.0, "near")
        self.assertNotIn("(", s)  # no sector parenthetical


if __name__ == "__main__":
    unittest.main()

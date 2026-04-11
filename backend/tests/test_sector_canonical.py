"""Regression tests for the sector canonicalization helper.

Guards against Bug H from Ship #13 — raw SIC industry strings leaking
into the user-facing sector slot on /consensus, /asset/:ticker, and
/forecaster/:id (sector chips). Every value that currently lives in
``tickers.sector`` MUST map to one of the 11 Morningstar sectors (or
the permitted "Unknown" fallback).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.sector import (
    canonical_sector,
    canonical_sectors_distinct,
    ALLOWED_SECTORS,
    MORNINGSTAR_SECTORS,
    UNKNOWN_SECTOR,
)


class TestAllowedSet(unittest.TestCase):
    def test_eleven_morningstar_sectors_exactly(self):
        self.assertEqual(len(MORNINGSTAR_SECTORS), 11)
        self.assertIn("Technology", MORNINGSTAR_SECTORS)
        self.assertIn("Healthcare", MORNINGSTAR_SECTORS)
        self.assertIn("Financial Services", MORNINGSTAR_SECTORS)
        self.assertIn("Consumer Cyclical", MORNINGSTAR_SECTORS)
        self.assertIn("Consumer Defensive", MORNINGSTAR_SECTORS)
        self.assertIn("Communication Services", MORNINGSTAR_SECTORS)
        self.assertIn("Real Estate", MORNINGSTAR_SECTORS)
        self.assertIn("Utilities", MORNINGSTAR_SECTORS)
        self.assertIn("Energy", MORNINGSTAR_SECTORS)
        self.assertIn("Industrials", MORNINGSTAR_SECTORS)
        self.assertIn("Basic Materials", MORNINGSTAR_SECTORS)

    def test_allowed_includes_unknown(self):
        self.assertEqual(len(ALLOWED_SECTORS), 12)
        self.assertIn("Unknown", ALLOWED_SECTORS)


class TestCanonicalSectorReturns(unittest.TestCase):
    def test_every_result_is_allowed(self):
        # Sample a variety of inputs and verify the output is always
        # one of the allowed set.
        samples = [
            "Technology", "technology", "TECHNOLOGY",
            "SERVICES-VIDEO TAPE RENTAL",
            "MOTOR VEHICLES & PASSENGER CAR BODIES",
            "Life Sciences Tools & Services",
            "Pharmaceuticals",
            "Oil & Gas",
            "REITs",
            "Telecommunication Services",
            "Crypto",
            "gibberish-not-a-real-sector",
            "",
            None,
        ]
        for s in samples:
            out = canonical_sector(s)
            self.assertIn(out, ALLOWED_SECTORS, f"canonical_sector({s!r}) -> {out!r} not allowed")


class TestBugHLeaks(unittest.TestCase):
    """The specific leaked strings the user surfaced during the sweep."""

    def test_netflix_video_tape_rental(self):
        # NFLX was showing "SERVICES-VIDEO TAPE RENTAL" on /consensus.
        # Should render as Communication Services now.
        self.assertEqual(
            canonical_sector("SERVICES-VIDEO TAPE RENTAL"),
            "Communication Services",
        )
        self.assertEqual(
            canonical_sector("Service-Video Tape Rental"),
            "Communication Services",
        )

    def test_tsla_motor_vehicles(self):
        # /ticker/TSLA was rendering "MOTOR VEHICLES & PASSENGER CAR BODIES".
        self.assertEqual(
            canonical_sector("MOTOR VEHICLES & PASSENGER CAR BODIES"),
            "Consumer Cyclical",
        )

    def test_forecaster_leaked_chips(self):
        # Jefferies /forecaster/599 had these chips.
        leaks = {
            "Consumer products": "Consumer Defensive",
            "Professional Services": "Industrials",
            "Packaging": "Industrials",
            "Communications": "Communication Services",
            "Life Sciences Tools & Services": "Healthcare",
            "Marine": "Industrials",
            "Commercial Services & Supplies": "Industrials",
            "Building": "Industrials",
            "Diversified Consumer Services": "Consumer Cyclical",
        }
        for raw, expected in leaks.items():
            with self.subTest(raw=raw):
                self.assertEqual(canonical_sector(raw), expected)


class TestAlreadyCanonical(unittest.TestCase):
    def test_all_morningstar_roundtrip(self):
        for m in MORNINGSTAR_SECTORS:
            self.assertEqual(canonical_sector(m), m)
            self.assertEqual(canonical_sector(m.upper()), m)
            self.assertEqual(canonical_sector(m.lower()), m)


class TestUnknownFallback(unittest.TestCase):
    def test_none_returns_unknown(self):
        self.assertEqual(canonical_sector(None), UNKNOWN_SECTOR)

    def test_empty_returns_unknown(self):
        self.assertEqual(canonical_sector(""), UNKNOWN_SECTOR)
        self.assertEqual(canonical_sector("   "), UNKNOWN_SECTOR)

    def test_whitelisted_noise_returns_unknown(self):
        self.assertEqual(canonical_sector("Other"), UNKNOWN_SECTOR)
        self.assertEqual(canonical_sector("Crypto"), UNKNOWN_SECTOR)
        self.assertEqual(canonical_sector("Index"), UNKNOWN_SECTOR)
        self.assertEqual(canonical_sector("N/A"), UNKNOWN_SECTOR)


class TestDistinctCount(unittest.TestCase):
    def test_collapses_sic_variants(self):
        # Multiple raw strings that all map to the same Morningstar
        # sector should collapse to one entry in the distinct set.
        raws = [
            "MOTOR VEHICLES & PASSENGER CAR BODIES",
            "Automobile",
            "Consumer Discretionary",
            "Diversified Consumer Services",
        ]
        out = canonical_sectors_distinct(raws)
        self.assertEqual(out, {"Consumer Cyclical"})

    def test_excludes_unknown(self):
        out = canonical_sectors_distinct(["", "Crypto", "Unknown", None])
        self.assertEqual(out, set())

    def test_mixed(self):
        raws = [
            "Technology",
            "SERVICES-VIDEO TAPE RENTAL",
            "Pharmaceuticals",
            "Crypto",
        ]
        out = canonical_sectors_distinct(raws)
        self.assertEqual(
            out,
            {"Technology", "Communication Services", "Healthcare"},
        )


if __name__ == "__main__":
    unittest.main()

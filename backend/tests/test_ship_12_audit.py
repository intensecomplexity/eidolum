"""Unit tests for Ship #12 audit + apply logic.

Uses an in-memory sqlite DB with a slimmed-down `predictions` table
shaped to match the columns the audit actually touches. The audit
module does all regex work in Python, so dialect compatibility is
not a problem — the SELECTs are standard SQL.

Run with:
    cd backend
    python -m unittest tests.test_ship_12_audit -v
"""
import os
import sqlite3
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import ship_12_audit  # noqa: E402


_SCHEMA = """
CREATE TABLE predictions (
    id INTEGER PRIMARY KEY,
    ticker TEXT,
    direction TEXT,
    target_price REAL,
    context TEXT,
    exact_quote TEXT,
    quote_context TEXT,
    window_days INTEGER,
    timeframe_source TEXT,
    source_platform_id TEXT,
    prediction_date TEXT,
    forecaster_id INTEGER,
    created_at TEXT,
    excluded_from_training INTEGER DEFAULT 0,
    exclusion_reason TEXT,
    exclusion_flagged_at TEXT,
    exclusion_rule_version TEXT
);
"""


def _seed_row(conn, **kw):
    defaults = {
        "ticker": "AAPL",
        "direction": "bullish",
        "target_price": None,
        "context": None,
        "exact_quote": None,
        "quote_context": None,
        "window_days": 30,
        "timeframe_source": "explicit",
        "source_platform_id": None,
        "prediction_date": datetime.utcnow().isoformat(),
        "forecaster_id": 1,
        "created_at": datetime.utcnow().isoformat(),
        "excluded_from_training": 0,
        "exclusion_reason": None,
    }
    defaults.update(kw)
    cols = ",".join(defaults.keys())
    placeholders = ",".join(["?"] * len(defaults))
    cur = conn.cursor()
    cur.execute(
        f"INSERT INTO predictions ({cols}) VALUES ({placeholders})",
        list(defaults.values()),
    )
    conn.commit()
    return cur.lastrowid


class Ship12AuditTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(_SCHEMA)

        # Row 1: disclosure_misroute — "we hold" ownership voice.
        self.id_disclosure = _seed_row(
            self.conn,
            ticker="ANET",
            direction="neutral",
            context="we hold ANET as a long-term position",
            window_days=30,
        )

        # Row 2: disclosure_misroute escape hatch — "we rate X a hold"
        # is analyst voice and must NOT be flagged.
        self.id_rating_voice = _seed_row(
            self.conn,
            ticker="MSFT",
            direction="neutral",
            context="we rate MSFT a hold with a $400 rating",
            window_days=30,
        )

        # Row 3: invented_timeframe — window_days=90, no explicit
        # timeframe in source text, timeframe_source NULL.
        self.id_invented_tf = _seed_row(
            self.conn,
            ticker="NVDA",
            direction="bullish",
            context="NVDA goes to 200",
            window_days=90,
            timeframe_source=None,
        )

        # Row 4: window_days=90 BUT timeframe_source='explicit' — must
        # NOT be flagged.
        self.id_tf_explicit = _seed_row(
            self.conn,
            ticker="TSLA",
            direction="bullish",
            context="TSLA hits 300 in 3 months",
            window_days=90,
            timeframe_source="explicit",
        )

        # Row 5: unresolvable_reference — context opens with "it", no
        # ticker literally anywhere, no cashtag.
        self.id_unresolvable = _seed_row(
            self.conn,
            ticker="AMD",
            direction="bullish",
            context="it's going to break out soon",
            window_days=30,
            timeframe_source="inferred",
        )

        # Row 6: starts with pronoun BUT ticker literally appears —
        # must NOT be flagged.
        self.id_pronoun_with_ticker = _seed_row(
            self.conn,
            ticker="GOOG",
            direction="bullish",
            context="it's a buy, GOOG looks ready",
            window_days=30,
            timeframe_source="inferred",
        )

        # Row 7: basket_shoehorn — "semis are toppy" shoehorned to NVDA.
        self.id_basket = _seed_row(
            self.conn,
            ticker="NVDA",
            direction="bearish",
            context="semis are toppy here",
            window_days=30,
            timeframe_source="inferred",
        )

        # Row 8: basket phrase BUT "specifically" escape hatch.
        self.id_basket_specific = _seed_row(
            self.conn,
            ticker="NVDA",
            direction="bearish",
            context="semis are toppy, NVDA specifically looks weak",
            window_days=30,
            timeframe_source="inferred",
        )

        # Rows 9-10: duplicate_source — two rows with same spid.
        # The older one must NOT be flagged; the newer one MUST be.
        self.id_dup_first = _seed_row(
            self.conn,
            ticker="META",
            direction="bullish",
            context="META looks strong",
            source_platform_id="yt_vid123_META",
            created_at="2024-01-01T00:00:00",
        )
        self.id_dup_second = _seed_row(
            self.conn,
            ticker="META",
            direction="bullish",
            context="META another call",
            source_platform_id="yt_vid123_META",
            created_at="2024-06-01T00:00:00",
        )

        # Control rows 11-12: clean, must not be flagged.
        self.id_clean_1 = _seed_row(
            self.conn,
            ticker="AAPL",
            direction="bullish",
            context="AAPL to 210 by end of year",
            window_days=365,
            timeframe_source="explicit",
        )
        self.id_clean_2 = _seed_row(
            self.conn,
            ticker="MSFT",
            direction="bullish",
            context="MSFT breaks out next week",
            window_days=7,
            timeframe_source="explicit",
        )

    def tearDown(self):
        self.conn.close()

    def test_disclosure_misroute_count(self):
        flagged = ship_12_audit.run_audit(self.conn)
        self.assertIn(self.id_disclosure, flagged["disclosure_misroute"])
        self.assertNotIn(
            self.id_rating_voice, flagged["disclosure_misroute"]
        )

    def test_invented_timeframe_count(self):
        flagged = ship_12_audit.run_audit(self.conn)
        self.assertIn(self.id_invented_tf, flagged["invented_timeframe"])
        self.assertNotIn(
            self.id_tf_explicit, flagged["invented_timeframe"]
        )

    def test_unresolvable_reference_count(self):
        flagged = ship_12_audit.run_audit(self.conn)
        self.assertIn(self.id_unresolvable, flagged["unresolvable_reference"])
        self.assertNotIn(
            self.id_pronoun_with_ticker, flagged["unresolvable_reference"]
        )

    def test_basket_shoehorn_count(self):
        flagged = ship_12_audit.run_audit(self.conn)
        self.assertIn(self.id_basket, flagged["basket_shoehorn"])
        self.assertNotIn(self.id_basket_specific, flagged["basket_shoehorn"])

    def test_duplicate_source_keeps_first(self):
        flagged = ship_12_audit.run_audit(self.conn)
        self.assertNotIn(self.id_dup_first, flagged["duplicate_source"])
        self.assertIn(self.id_dup_second, flagged["duplicate_source"])

    def test_control_rows_are_not_flagged(self):
        flagged = ship_12_audit.run_audit(self.conn)
        all_flagged = set()
        for ids in flagged.values():
            all_flagged.update(ids)
        self.assertNotIn(self.id_clean_1, all_flagged)
        self.assertNotIn(self.id_clean_2, all_flagged)

    def test_report_shape(self):
        flagged = ship_12_audit.run_audit(self.conn)
        report = ship_12_audit._build_report(flagged)
        self.assertEqual(report["rule_version"], "v12.1")
        self.assertIn("generated_at", report)
        self.assertEqual(set(report["counts"].keys()), set(ship_12_audit.REASONS))
        for reason in ship_12_audit.REASONS:
            self.assertLessEqual(
                len(report["sample_ids"][reason]), 20
            )


class Ship12ApplySmokeTests(unittest.TestCase):
    """Minimal smoke tests for the apply path. We can't import
    ship_12_apply directly (it imports psycopg2 via _connect), so we
    exercise the filter-and-update shape via a tiny helper that mirrors
    _apply_one_reason but uses sqlite parameter binding."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(_SCHEMA)
        self.id_a = _seed_row(
            self.conn,
            ticker="ANET",
            direction="neutral",
            context="we hold ANET as a long-term position",
            source_platform_id="yt_v1_ANET",
        )
        self.id_b = _seed_row(
            self.conn,
            ticker="ANET",
            direction="neutral",
            context="we are still holding ANET here",
            source_platform_id="yt_v2_ANET",
        )
        # Already-excluded row — must NOT be overwritten.
        self.id_preexcluded = _seed_row(
            self.conn,
            ticker="META",
            direction="neutral",
            context="we hold META too",
            source_platform_id="yt_v3_META",
            excluded_from_training=1,
            exclusion_reason="manual_review",
        )

    def tearDown(self):
        self.conn.close()

    def _apply_mock(self, reason, ids, limit=10000):
        capped = ids[:limit]
        if not capped:
            return 0
        placeholders = ",".join(["?"] * len(capped))
        cur = self.conn.cursor()
        cur.execute(
            f"UPDATE predictions "
            f"SET excluded_from_training=1, exclusion_reason=?, "
            f"    exclusion_rule_version=? "
            f"WHERE id IN ({placeholders}) "
            f"  AND excluded_from_training=0",
            [reason, "v12.1"] + capped,
        )
        affected = cur.rowcount
        self.conn.commit()
        return affected

    def test_apply_writes_only_non_excluded(self):
        flagged = ship_12_audit.run_audit(self.conn)
        disc = flagged["disclosure_misroute"]
        self.assertIn(self.id_a, disc)
        self.assertIn(self.id_b, disc)
        # The pre-excluded row should already be filtered out because
        # the audit's structural filter has excluded_from_training=0.
        self.assertNotIn(self.id_preexcluded, disc)

        written = self._apply_mock("disclosure_misroute", disc)
        self.assertEqual(written, 2)

        cur = self.conn.cursor()
        cur.execute(
            "SELECT exclusion_reason FROM predictions WHERE id=?",
            (self.id_preexcluded,),
        )
        self.assertEqual(cur.fetchone()[0], "manual_review")

    def test_second_apply_skips_already_flagged(self):
        flagged = ship_12_audit.run_audit(self.conn)
        disc = flagged["disclosure_misroute"]
        self._apply_mock("disclosure_misroute", disc)
        # Re-run audit — those rows are now excluded_from_training=1
        # and get filtered out of the candidate SELECT.
        flagged_again = ship_12_audit.run_audit(self.conn)
        self.assertEqual(flagged_again["disclosure_misroute"], [])


if __name__ == "__main__":
    unittest.main()

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
    verified_by TEXT,
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
        # v12.3 Shape A invented_timeframe filter only flags rows whose
        # verified_by is in the synthetic-template source list. Default
        # to a non-synthetic value so the existing fixtures don't
        # accidentally land in the flagged set.
        "verified_by": "youtube_haiku_v1",
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
        # timeframe, AND verified_by from a synthetic-template ingest
        # (v12.3 Shape A rule restricts the flag to fmp_grades /
        # massive_benzinga / alphavantage rows so YouTube/X human
        # speech doesn't get retroactively poisoned).
        self.id_invented_tf = _seed_row(
            self.conn,
            ticker="NVDA",
            direction="bullish",
            context="NVDA goes to 200",
            window_days=90,
            timeframe_source=None,
            verified_by="fmp_grades",
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

        # v12.3 basket_shoehorn fixtures.
        #
        # The new 3-signal rule requires:
        #   S1: source_platform_id starts with yt_<vid>_, and the SAME
        #       <vid> produced ≥3 distinct ticker_call rows.
        #   S2: context contains a basket-phrasing pattern.
        #   S3: context does NOT contain a conviction marker.
        #
        # Row 7 is part of a 3-ticker basket video and uses real basket
        # phrasing with no conviction marker → MUST flag.
        self.id_basket = _seed_row(
            self.conn,
            ticker="NVDA",
            direction="bullish",
            context="one of these stocks should outperform the rest",
            source_platform_id="yt_basketvid_NVDA",
            window_days=30,
            timeframe_source="inferred",
        )
        # Sibling rows for the same video (NOT seeding their own
        # basket-phrasing, just present so signal 1 sees ≥3 tickers).
        self.id_basket_sibling_a = _seed_row(
            self.conn,
            ticker="AMD",
            direction="bullish",
            context="i like AMD here",
            source_platform_id="yt_basketvid_AMD",
            window_days=30,
            timeframe_source="inferred",
        )
        self.id_basket_sibling_b = _seed_row(
            self.conn,
            ticker="INTC",
            direction="bullish",
            context="i like INTC here",
            source_platform_id="yt_basketvid_INTC",
            window_days=30,
            timeframe_source="inferred",
        )

        # Row 8: same basket phrasing AND multi-ticker, BUT a conviction
        # marker singles this ticker out — MUST NOT flag.
        self.id_basket_conviction = _seed_row(
            self.conn,
            ticker="META",
            direction="bullish",
            context="one of these stocks but we would be going with META",
            source_platform_id="yt_convvid_META",
            window_days=30,
            timeframe_source="inferred",
        )
        self.id_basket_conviction_sib1 = _seed_row(
            self.conn,
            ticker="GOOGL",
            direction="bullish",
            context="i like GOOGL too",
            source_platform_id="yt_convvid_GOOGL",
            window_days=30,
            timeframe_source="inferred",
        )
        self.id_basket_conviction_sib2 = _seed_row(
            self.conn,
            ticker="AMZN",
            direction="bullish",
            context="AMZN is also fine",
            source_platform_id="yt_convvid_AMZN",
            window_days=30,
            timeframe_source="inferred",
        )

        # Row: basket phrasing fires but the video only emitted ONE
        # ticker — signal 1 fails, MUST NOT flag.
        self.id_basket_solo = _seed_row(
            self.conn,
            ticker="MSFT",
            direction="bullish",
            context="one of these stocks looks ready to break out",
            source_platform_id="yt_solovid_MSFT",
            window_days=30,
            timeframe_source="inferred",
        )

        # Row: X-source row whose context happens to mention "one of
        # these" — signal 1 fails (not a yt_ prefix), MUST NOT flag.
        self.id_basket_x = _seed_row(
            self.conn,
            ticker="QQQ",
            direction="bullish",
            context="one of these stocks today is QQQ",
            source_platform_id="x_99999_QQQ",
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
        # The 3-signal video flags exactly the row with basket phrasing
        # and no conviction marker.
        self.assertIn(self.id_basket, flagged["basket_shoehorn"])
        # Conviction-marker row stays clean even though it's in a basket video.
        self.assertNotIn(self.id_basket_conviction, flagged["basket_shoehorn"])
        # Single-ticker video never flags (signal 1 fails).
        self.assertNotIn(self.id_basket_solo, flagged["basket_shoehorn"])
        # X-source rows never flag (no yt_ prefix → signal 1 fails).
        self.assertNotIn(self.id_basket_x, flagged["basket_shoehorn"])

    def test_v124_another_dollar_followers_rejected(self):
        """v12.4 — `another $3,500 ... stock` must NOT match S2."""
        from scripts.ship_12_audit import _BASKET_PHRASING_RE
        # Direct regex check (independent of the multi-ticker map gate
        # — we only care that the phrasing pattern itself doesn't fire).
        false_positive = (
            "later this year I'll likely add another $3,500 to that "
            "Roth IRA to buy some Tesla stock especially if it dips"
        )
        self.assertIsNone(
            _BASKET_PHRASING_RE.search(false_positive),
            "v12.4 regex still matches `another $<digit> ... stock` — "
            "the negative lookahead is broken.",
        )

    def test_v124_another_word_word_noun_still_matches(self):
        """v12.4 — `another Key Automotive supplier` must STILL match S2."""
        from scripts.ship_12_audit import _BASKET_PHRASING_RE
        true_positive = (
            "another Key Automotive supplier nxp semiconductors or nxpi"
        )
        self.assertIsNotNone(
            _BASKET_PHRASING_RE.search(true_positive),
            "v12.4 regex stopped matching `another Key Automotive supplier` "
            "— the lookahead change went too far.",
        )

    def test_v124_top_pick_standalone_conviction(self):
        """v12.4 — `top pick` is endorsement language; fires conviction
        regardless of ticker adjacency."""
        from scripts.ship_12_audit import _has_conviction_marker
        qcom_ctx = (
            'Chip Stock Investor: Bullish on QCOM. "Qualcomm is another '
            'top pick for 2023. we think eventually Qualcomm will also '
            'return to growth"'
        )
        self.assertTrue(_has_conviction_marker(qcom_ctx, "QCOM"))
        # The legitimate basket phrase must NOT trigger conviction.
        legit_basket = (
            "Tesla would be my two buys among the seven if you really "
            "wanted to add two of these stocks"
        )
        self.assertFalse(_has_conviction_marker(legit_basket, "TSLA"))

    def test_v124_one_of_our_top_picks(self):
        from scripts.ship_12_audit import _has_conviction_marker
        self.assertTrue(_has_conviction_marker("one of our top picks for 2026", "AAPL"))
        self.assertTrue(_has_conviction_marker("one of my top picks here", "AAPL"))
        self.assertTrue(_has_conviction_marker("one of the top picks", "AAPL"))

    def test_basket_shoehorn_protected_id(self):
        # Protected IDs are dropped silently. Re-seed row 7 with the
        # protected id and assert it does NOT flag even though all 3
        # signals fire.
        ship_12_audit.PHASE_A_PROTECTED_IDS[self.id_basket] = "test_protect"
        try:
            flagged = ship_12_audit.run_audit(self.conn)
            self.assertNotIn(self.id_basket, flagged["basket_shoehorn"])
        finally:
            ship_12_audit.PHASE_A_PROTECTED_IDS.pop(self.id_basket, None)

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
        self.assertEqual(report["rule_version"], "v12.4")
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


class HitRowSafetyGuardTests(unittest.TestCase):
    """v12.4 belt-and-suspenders guard. Refuse to proceed if any
    flagged row is already a scored hit with a stamped entry_price."""

    def _meta(self, **overrides):
        # Mirror the tuple shape that ship_12_audit_phase_a's main()
        # constructs from the per-id meta query:
        #   (id, forecaster_id, prediction_date, outcome,
        #    entry_price, target_price, sector)
        defaults = {
            "id": 1,
            "forecaster_id": 10,
            "prediction_date": datetime.utcnow(),
            "outcome": "pending",
            "entry_price": None,
            "target_price": None,
            "sector": "Technology",
        }
        defaults.update(overrides)
        return (
            defaults["id"],
            defaults["forecaster_id"],
            defaults["prediction_date"],
            defaults["outcome"],
            defaults["entry_price"],
            defaults["target_price"],
            defaults["sector"],
        )

    def test_guard_returns_empty_when_no_hit_rows(self):
        from scripts.ship_12_audit_phase_a import check_no_hit_rows_in_flagged
        meta_by_id = {
            1: self._meta(id=1, outcome="pending", entry_price=None),
            2: self._meta(id=2, outcome="miss", entry_price=100.0),
            3: self._meta(id=3, outcome="near", entry_price=50.0),
        }
        offenders = check_no_hit_rows_in_flagged([1, 2, 3], meta_by_id)
        self.assertEqual(offenders, [])

    def test_guard_flags_hit_with_entry_price(self):
        from scripts.ship_12_audit_phase_a import check_no_hit_rows_in_flagged
        # Synthetic 605937 QCOM-style row — outcome=hit, entry_price stamped.
        meta_by_id = {
            605937: self._meta(id=605937, outcome="hit", entry_price=124.76),
            605713: self._meta(id=605713, outcome="pending", entry_price=None),
        }
        offenders = check_no_hit_rows_in_flagged([605937, 605713], meta_by_id)
        self.assertEqual(offenders, [605937])

    def test_guard_ignores_hit_with_null_entry_price(self):
        from scripts.ship_12_audit_phase_a import check_no_hit_rows_in_flagged
        # A hit without a stamped entry_price is a different bug class —
        # the guard only fires when both signals are present.
        meta_by_id = {
            42: self._meta(id=42, outcome="hit", entry_price=None),
        }
        offenders = check_no_hit_rows_in_flagged([42], meta_by_id)
        self.assertEqual(offenders, [])

    def test_guard_handles_missing_meta(self):
        from scripts.ship_12_audit_phase_a import check_no_hit_rows_in_flagged
        meta_by_id = {1: self._meta(id=1, outcome="pending")}
        # id 99 is not in meta_by_id — guard should silently skip it.
        offenders = check_no_hit_rows_in_flagged([1, 99], meta_by_id)
        self.assertEqual(offenders, [])

    def test_guard_flags_multiple_offenders(self):
        from scripts.ship_12_audit_phase_a import check_no_hit_rows_in_flagged
        meta_by_id = {
            605937: self._meta(id=605937, outcome="hit", entry_price=124.76),
            606405: self._meta(id=606405, outcome="hit", entry_price=197.88),
            605761: self._meta(id=605761, outcome="pending", entry_price=None),
        }
        offenders = check_no_hit_rows_in_flagged(
            [605937, 606405, 605761], meta_by_id,
        )
        self.assertEqual(sorted(offenders), [605937, 606405])


if __name__ == "__main__":
    unittest.main()

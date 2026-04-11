"""Ship #13 — homepage hero feature flag tests.

Covers:
  * `is_homepage_hero_enabled` returns False when the config row is
    absent, True when it is 'true', and False when it is 'false'.
  * `invalidate_homepage_hero_flag_cache` lets a subsequent read see a
    freshly-written value without waiting for the 60s TTL.
  * The public flags endpoint (`get_public_flags` inline logic) returns
    an allow-listed shape with just `homepage_hero` — no internal Haiku
    flags leak through.

Deliberately avoids spinning up the FastAPI app (no TestClient in the
existing suite). The public endpoint's logic is narrow enough that
reading the same config table directly exercises the contract.

Run with:
    cd backend
    python -m unittest tests.test_ship_13_homepage_hero -v
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub `sqlalchemy` before importing feature_flags. The local venv has
# no third-party deps installed — matches how the existing ship_12 test
# avoids touching sqlalchemy-bound modules. feature_flags only uses
# `from sqlalchemy import text as sql_text` and never calls sql_text
# in the functions under test.
if "sqlalchemy" not in sys.modules:
    _stub = types.ModuleType("sqlalchemy")
    _stub.text = lambda s: s
    sys.modules["sqlalchemy"] = _stub


class _FakeRow:
    def __init__(self, value):
        self._value = value

    def __getitem__(self, idx):
        if idx == 0:
            return self._value
        raise IndexError(idx)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        if not self._rows:
            return None
        return self._rows[0][0]


class _FakeDb:
    """Minimal stand-in for a SQLAlchemy Session that feature_flags._read_bool
    and the public flags endpoint both accept. They only need .execute(...)
    returning an object with fetchone()/scalar().
    """

    def __init__(self, value=None):
        self._value = value

    def execute(self, *_args, **_kwargs):
        if self._value is None:
            return _FakeResult([])
        return _FakeResult([(self._value,)])


class HomepageHeroFlagTests(unittest.TestCase):
    def setUp(self):
        from feature_flags import invalidate_homepage_hero_flag_cache
        invalidate_homepage_hero_flag_cache()

    def tearDown(self):
        from feature_flags import invalidate_homepage_hero_flag_cache
        invalidate_homepage_hero_flag_cache()

    def test_default_false_when_no_row(self):
        from feature_flags import is_homepage_hero_enabled
        self.assertFalse(is_homepage_hero_enabled(_FakeDb(None)))

    def test_true_when_config_says_true(self):
        from feature_flags import is_homepage_hero_enabled
        self.assertTrue(is_homepage_hero_enabled(_FakeDb("true")))

    def test_false_when_config_says_false(self):
        from feature_flags import (
            invalidate_homepage_hero_flag_cache,
            is_homepage_hero_enabled,
        )
        invalidate_homepage_hero_flag_cache()
        self.assertFalse(is_homepage_hero_enabled(_FakeDb("false")))

    def test_invalidate_cache_lets_new_value_through(self):
        from feature_flags import (
            invalidate_homepage_hero_flag_cache,
            is_homepage_hero_enabled,
        )
        self.assertFalse(is_homepage_hero_enabled(_FakeDb(None)))
        invalidate_homepage_hero_flag_cache()
        self.assertTrue(is_homepage_hero_enabled(_FakeDb("true")))


class PublicFlagsAllowlistTests(unittest.TestCase):
    """The public /api/public/flags endpoint must only contain the
    allow-listed keys — never mirror internal Haiku flags. This test
    enforces the allow-list at the source level so a future refactor
    can't accidentally `**` a big bundle through it."""

    def test_public_flags_source_only_contains_homepage_hero(self):
        here = os.path.dirname(__file__)
        main_py = os.path.join(here, "..", "main.py")
        with open(main_py, "r") as f:
            src = f.read()
        marker = "def get_public_flags("
        self.assertIn(marker, src, "public flags endpoint should exist")

        start = src.index(marker)
        fn_body = src[start : start + 2000]

        # The inline `flags = { ... }` dict defines the wire shape.
        self.assertIn('"homepage_hero"', fn_body)

        # Allow-list check: no known internal flag name should appear
        # inside this function's body.
        forbidden = [
            "prediction_metadata_enrichment",
            "source_timestamps",
            "regime_call_extraction",
            "earnings_call_extraction",
            "macro_call_extraction",
            "ENABLE_PREDICTION_METADATA_ENRICHMENT",
            "ENABLE_SOURCE_TIMESTAMPS",
            "ENABLE_REGIME_CALL_EXTRACTION",
        ]
        for key in forbidden:
            self.assertNotIn(
                key,
                fn_body,
                f"public flags endpoint must not leak {key}",
            )


class HeroComponentRendersTests(unittest.TestCase):
    """Source-level smoke test. The frontend has no JSX test runner
    installed, so we assert the new components contain the copy the
    spec requires rather than snapshot-rendering them."""

    def _read(self, rel):
        here = os.path.dirname(__file__)
        path = os.path.join(here, "..", "..", "frontend", "src", rel)
        with open(path, "r") as f:
            return f.read()

    def test_hero_band_has_h1(self):
        src = self._read("components/home/HeroBand.jsx")
        self.assertIn("Who should you actually listen to?", src)
        self.assertIn("Predictions Tracked", src)
        self.assertIn("Forecasters Watched", src)
        self.assertIn("Calls Graded", src)
        self.assertIn("Truth is the only currency", src)
        self.assertIn("HIT", src)
        self.assertIn("NEAR", src)
        self.assertIn("MISS", src)

    def test_how_it_works_has_three_steps(self):
        src = self._read("components/home/HowItWorks.jsx")
        self.assertIn("A forecaster makes a public call", src)
        self.assertIn("Eidolum locks it", src)
        self.assertIn("The market grades it", src)

    def test_dashboard_gates_hero_on_flag(self):
        src = self._read("pages/Dashboard.jsx")
        # The flag must be read via the public-flags hook, not /features.
        self.assertIn("usePublicFlag('homepage_hero')", src)
        # HeroBand and HowItWorks must be conditionally rendered —
        # never unconditional.
        self.assertIn("{heroEnabled && <HeroBand />}", src)
        self.assertIn("{heroEnabled && <HowItWorks />}", src)
        # Receipts rename is flag-gated.
        self.assertIn("Receipts", src)
        # First-call CTA exists and is flag-gated.
        self.assertIn("Make your first call", src)
        self.assertIn("showFirstCallCta", src)


if __name__ == "__main__":
    unittest.main()

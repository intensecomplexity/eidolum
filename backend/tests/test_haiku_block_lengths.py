"""Byte-exact length guard for the 14 Haiku instruction blocks.

The classifier prompt stack is additive — per feedback memory
``feedback_eidolum_haiku_prompt_additive.md``, nobody should edit
HAIKU_SYSTEM or any of the ``YOUTUBE_HAIKU_*_INSTRUCTIONS`` blocks
in place; new guidance is appended as a new constant at call time.

This test pins the length of each of the 14 existing blocks so a
silent in-place edit during a ship fails CI instead of shipping a
broken classifier. Updating a block intentionally means updating
the expected length here in the same commit.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jobs import youtube_classifier as yc


EXPECTED_LENGTHS = {
    "HAIKU_SYSTEM": 2531,
    "YOUTUBE_HAIKU_RANKED_LIST_INSTRUCTIONS": 1875,
    "YOUTUBE_HAIKU_REVISIONS_INSTRUCTIONS": 1662,
    "YOUTUBE_HAIKU_OPTIONS_INSTRUCTIONS": 4370,
    "YOUTUBE_HAIKU_EARNINGS_INSTRUCTIONS": 4881,
    "YOUTUBE_HAIKU_MACRO_INSTRUCTIONS": 5595,
    "YOUTUBE_HAIKU_PAIR_INSTRUCTIONS": 6039,
    "YOUTUBE_HAIKU_CONDITIONAL_INSTRUCTIONS": 6352,
    "YOUTUBE_HAIKU_BINARY_EVENT_INSTRUCTIONS": 6675,
    "YOUTUBE_HAIKU_METRIC_FORECAST_INSTRUCTIONS": 8566,
    "YOUTUBE_HAIKU_DISCLOSURE_INSTRUCTIONS": 13059,
    "YOUTUBE_HAIKU_REGIME_INSTRUCTIONS": 8149,
    "YOUTUBE_HAIKU_SOURCE_TIMESTAMP_INSTRUCTIONS": 7174,
    "YOUTUBE_HAIKU_METADATA_ENRICHMENT_INSTRUCTIONS": 10667,
}


class TestHaikuBlockLengths(unittest.TestCase):
    def test_all_fourteen_blocks_byte_identical(self):
        for name, expected in EXPECTED_LENGTHS.items():
            with self.subTest(block=name):
                value = getattr(yc, name, None)
                self.assertIsNotNone(value, f"{name} not defined in youtube_classifier")
                actual = len(value)
                self.assertEqual(
                    actual,
                    expected,
                    f"{name} length drifted from {expected} to {actual} — "
                    "the Haiku prompt stack is additive; do NOT edit these "
                    "blocks in place (see feedback_eidolum_haiku_prompt_additive).",
                )


if __name__ == "__main__":
    unittest.main()

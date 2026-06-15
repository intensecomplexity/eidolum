"""Bug 4b — sanity_check_target wrong-side rule (2026-06-15).

The magnitude cap already drops upside blowups. These tests lock the NEW
direction-aware wrong-side behaviour: a bullish target far below entry, or a
bearish target far above entry, degrades to direction-only (returns None),
while merely-conservative targets and correct-side targets are preserved.
Omitting `direction` must reproduce the original magnitude-only behaviour.
"""
from services.target_sanity import sanity_check_target


def test_backward_compatible_without_direction():
    # original magnitude-only behaviour is unchanged when direction is omitted
    assert sanity_check_target(50, 60, 90) == 60.0
    assert sanity_check_target(50, 2000, 90) is None          # 40x blowup
    assert sanity_check_target(50, 75, 365) == 75.0
    assert sanity_check_target(None, 60, 90) is None
    # a bullish target below entry is KEPT when direction not supplied (legacy)
    assert sanity_check_target(385, 34, 1095) == 34.0


def test_wrong_side_bullish_target_below_entry_dropped():
    # AVGO leak: bullish, target 34 on a ~385 stock -> direction-only
    assert sanity_check_target(385.57, 34.0, 1095, direction="bullish") is None
    # ADBE/UNH/LMT EPS-misread class
    assert sanity_check_target(511.25, 62.3, 365, direction="bullish") is None
    assert sanity_check_target(524.99, 68.7, 365, direction="bullish") is None


def test_wrong_side_bearish_target_far_above_entry_dropped():
    # bearish, target 2.5x entry (within the 365d magnitude cap of 2.0) -> wrong-side drop
    assert sanity_check_target(100, 250, 365, direction="bearish") is None


def test_correct_side_targets_preserved():
    # bullish target above entry within cap -> kept
    assert sanity_check_target(100, 150, 365, direction="bullish") == 150.0
    # bearish target below entry within the magnitude cap -> kept (EXPECTED side)
    assert sanity_check_target(100, 80, 180, direction="bearish") == 80.0
    # conservative bullish target just below entry (within the 0.5x band) -> kept
    assert sanity_check_target(100, 70, 180, direction="bullish") == 70.0
    # conservative bearish target just above entry (within the 2x band) -> kept
    assert sanity_check_target(100, 130, 180, direction="bearish") == 130.0


def test_wrong_side_never_overrides_a_valid_none():
    # bad inputs still return None regardless of direction
    assert sanity_check_target(0, 50, 90, direction="bullish") is None
    assert sanity_check_target(50, 0, 90, direction="bearish") is None

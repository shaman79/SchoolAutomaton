"""Frozen XP/leveling math (SPEC §7). If these change, the gamification contract changed."""

from __future__ import annotations

from app.services import leveling


def test_xp_total_curve():
    assert leveling.xp_total_for_level(1) == 100
    assert leveling.xp_total_for_level(2) == 283
    assert leveling.xp_total_for_level(3) == 520
    assert leveling.xp_total_for_level(5) == 1118
    assert leveling.xp_total_for_level(10) == 3162


def test_level_from_xp_roundtrip():
    for level in range(1, 40):
        floor_xp = leveling.xp_total_for_level(level)
        assert leveling.level_from_xp(floor_xp) == level
        assert leveling.level_from_xp(floor_xp + 1) == level


def test_level_from_xp_low_values():
    assert leveling.level_from_xp(0) == 1
    assert leveling.level_from_xp(99) == 1
    assert leveling.level_from_xp(100) == 1
    assert leveling.level_from_xp(283) == 2


def test_xp_to_next():
    assert leveling.xp_to_next(100) == leveling.xp_total_for_level(2) - 100
    assert leveling.xp_to_next(0) >= 0


def test_progress_pct_bounds():
    assert 0.0 <= leveling.level_progress_pct(150) <= 100.0
    assert leveling.level_progress_pct(100) == 0.0


def test_item_xp_diminishing_returns():
    fresh = leveling.item_xp(item_difficulty=3, mastery_before=0.0)
    mastered = leveling.item_xp(item_difficulty=3, mastery_before=1.0)
    assert fresh == 10
    assert mastered == 0
    # harder items award more
    assert leveling.item_xp(5, 0.0) > leveling.item_xp(1, 0.0)


def test_combo_multiplier():
    assert leveling.combo_multiplier(0) == 1.0
    assert leveling.combo_multiplier(8) == 2.0
    assert leveling.combo_multiplier(100) == 2.0  # capped
    assert 1.0 < leveling.combo_multiplier(4) < 2.0

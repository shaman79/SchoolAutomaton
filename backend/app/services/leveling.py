"""Pure XP / leveling math (SPEC §7, gamification design). No DB, no I/O — fully unit-tested.

xp_total(L) = round(BASE_XP * L**CURVE_EXP). Store only total_xp; derive level on read to avoid drift.
"""

from __future__ import annotations

from ..core.constants import (
    BASE_ITEM_XP,
    BASE_XP,
    COMBO_CAP,
    COMBO_FULL_AT,
    CURVE_EXP,
)


def xp_total_for_level(level: int) -> int:
    """Cumulative XP required to *reach* ``level`` (level 1 = 100)."""
    if level <= 1:
        return BASE_XP if level == 1 else 0
    return round(BASE_XP * (level**CURVE_EXP))


def level_from_xp(total_xp: int) -> int:
    """Highest level fully paid for by ``total_xp`` (>= 1)."""
    if total_xp < BASE_XP:
        return 1
    level = int((total_xp / BASE_XP) ** (1.0 / CURVE_EXP))
    level = max(1, level)
    # Guard against float rounding at the boundary.
    while xp_total_for_level(level + 1) <= total_xp:
        level += 1
    while level > 1 and xp_total_for_level(level) > total_xp:
        level -= 1
    return level


def xp_to_next(total_xp: int) -> int:
    level = level_from_xp(total_xp)
    return max(0, xp_total_for_level(level + 1) - total_xp)


def level_progress_pct(total_xp: int) -> float:
    """Percent (0..100) of the way from the current level's floor to the next level."""
    level = level_from_xp(total_xp)
    floor_xp = xp_total_for_level(level)
    ceil_xp = xp_total_for_level(level + 1)
    span = ceil_xp - floor_xp
    if span <= 0:
        return 0.0
    return round(max(0.0, min(1.0, (total_xp - floor_xp) / span)) * 100, 1)


def item_xp(item_difficulty: int, mastery_before: float, *, base: int = BASE_ITEM_XP) -> int:
    """Per-correct-answer XP with diminishing returns on already-mastered material.

    item_xp = round(base * (item_difficulty/3) * (1 - mastery_before)). Re-grinding a mastered
    node (mastery≈1) yields ≈0 XP, preventing grind-for-points."""
    difficulty_mult = max(1, min(5, item_difficulty)) / 3.0
    value = base * difficulty_mult * (1.0 - max(0.0, min(1.0, mastery_before)))
    return max(0, round(value))


def combo_multiplier(consecutive_first_try_correct: int) -> float:
    """Session multiplier for consecutive first-try-correct answers. 1.0 → COMBO_CAP at COMBO_FULL_AT.
    A wrong answer resets the streak to 0 (handled by caller) — never a points penalty."""
    n = max(0, consecutive_first_try_correct)
    frac = min(n, COMBO_FULL_AT) / COMBO_FULL_AT
    return round(1.0 + (COMBO_CAP - 1.0) * frac, 3)

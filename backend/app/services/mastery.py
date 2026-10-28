"""Derived mastery + knowledge-tree node state (SPEC §4 #5). Mastery is NOT a second scheduling
algorithm — it aggregates per-item FSRS retrievability, weighted by each card's FSRS state and its
latest answer, plus one evidence rule (correct answers on two different days). The retrievability
values come from
``srs_service`` (FSRS is the single source of truth); this module only aggregates them, so it is pure
and fully unit-tested."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..core.constants import (
    MASTERY_MASTERED_THRESHOLD,
    MASTERY_MIN_CORRECT_DAYS,
    MASTERY_STATE_WEIGHTS,
    MASTERY_UNPROVEN_CAP,
)
from ..schemas.enums import NodeState


@dataclass(frozen=True)
class CardView:
    """Minimal projection of an item's FSRS card needed for mastery aggregation."""

    state: int          # 0 New, 1 Learning, 2 Review, 3 Relearning
    retrievability: float  # R(t,S) at evaluation time, 0..1 (0 for New / unscheduled)
    last_correct: bool = False  # the learner's latest graded answer on this item was correct


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def concept_mastery(cards: list[CardView], *, correct_days: int) -> float:
    """mastery = clamp01( Σ wₛ·R / N ) over the concept's N non-New cards (SPEC §4 #5), held at
    MASTERY_UNPROVEN_CAP until the concept was answered correctly on MASTERY_MIN_CORRECT_DAYS
    different days.

    Each card contributes at most its state weight, so a card still being learned (Learning 0.5,
    Relearning 0.7) can't count as known. The old weighted MEAN (÷ Σwₛ) cancelled the weights out:
    right after ANY answer — even a wrong one — R is ~1.0 for the rest of that day, so one wrong
    answer made a concept "mastered" (badges, and 0 XP for its next correct answers). The day rule
    makes "mastered" mean remembered on another day, not just answered once.

    Once the concept is proven, a card whose latest answer was correct counts at full weight
    whatever its FSRS state: a correct but slow or hinted answer is rated Hard, and Hard never
    advances a learning step, so such a card stays in Learning however often it is answered right —
    on state weights alone a slow reader could never master anything. A wrong latest answer keeps
    the state weight, so a slip still drops the concept below mastered until it is answered right.

    Returns 0.0 when there are no cards or every card is New."""
    proven = correct_days >= MASTERY_MIN_CORRECT_DAYS
    num = 0.0
    seen = 0
    for c in cards:
        w = MASTERY_STATE_WEIGHTS.get(c.state, 0.0)
        if w <= 0.0:
            continue  # New / unscheduled: no retention signal yet
        if proven and c.last_correct:
            w = 1.0
        num += w * _clamp01(c.retrievability)
        seen += 1
    if seen == 0:
        return 0.0
    value = _clamp01(num / seen)
    if not proven:
        value = min(value, MASTERY_UNPROVEN_CAP)
    return value


def is_mastered(mastery: float) -> bool:
    return mastery >= MASTERY_MASTERED_THRESHOLD


def node_state(
    mastery: float,
    *,
    prereqs_met: bool,
    decay_due_at: datetime | None,
    now: datetime,
) -> NodeState:
    """Map mastery + prerequisite + FSRS-decay status to a knowledge-tree node state.

    locked (prereqs unmet) → available → learning → mastered → needs_review (FSRS due)."""
    if not prereqs_met and mastery <= 0.0:
        return NodeState.LOCKED
    if is_mastered(mastery):
        if decay_due_at is not None and now >= decay_due_at:
            return NodeState.NEEDS_REVIEW
        return NodeState.MASTERED
    if mastery > 0.0:
        return NodeState.LEARNING
    return NodeState.AVAILABLE

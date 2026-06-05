"""Derived mastery + knowledge-tree node state (SPEC §4 #5). Mastery is NOT a second scheduling
algorithm — it is a weighted mean of per-item FSRS retrievability. The retrievability values come
from ``srs_service`` (FSRS is the single source of truth); this module only aggregates them, so it is
pure and fully unit-tested."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..core.constants import MASTERY_MASTERED_THRESHOLD, MASTERY_STATE_WEIGHTS
from ..schemas.enums import NodeState


@dataclass(frozen=True)
class CardView:
    """Minimal projection of an item's FSRS card needed for mastery aggregation."""

    state: int          # 0 New, 1 Learning, 2 Review, 3 Relearning
    retrievability: float  # R(t,S) at evaluation time, 0..1 (0 for New / unscheduled)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def concept_mastery(cards: list[CardView]) -> float:
    """mastery = Σ(wₛ·R) / Σ(wₛ) over the concept's items, weights by FSRS state (SPEC §4 #5).

    Returns 0.0 when there are no cards or every card is New (total weight 0)."""
    if not cards:
        return 0.0
    num = 0.0
    den = 0.0
    for c in cards:
        w = MASTERY_STATE_WEIGHTS.get(c.state, 0.0)
        num += w * _clamp01(c.retrievability)
        den += w
    if den <= 0.0:
        return 0.0
    return _clamp01(num / den)


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

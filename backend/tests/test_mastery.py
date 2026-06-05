"""Frozen mastery formula + node-state mapping (SPEC §4 #5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.schemas.enums import NodeState
from app.services.mastery import CardView, concept_mastery, node_state


def test_empty_and_all_new_is_zero():
    assert concept_mastery([]) == 0.0
    assert concept_mastery([CardView(state=0, retrievability=0.9)]) == 0.0  # New weight 0


def test_review_card_dominates():
    cards = [CardView(state=2, retrievability=0.9), CardView(state=2, retrievability=0.9)]
    assert abs(concept_mastery(cards) - 0.9) < 1e-9


def test_weighted_mix():
    # Review (w=1.0, R=1.0) + Learning (w=0.5, R=0.0) => 1.0 / 1.5
    cards = [CardView(state=2, retrievability=1.0), CardView(state=1, retrievability=0.0)]
    assert abs(concept_mastery(cards) - (1.0 / 1.5)) < 1e-9


def test_clamped():
    assert 0.0 <= concept_mastery([CardView(state=2, retrievability=5.0)]) <= 1.0


def test_node_state_transitions():
    now = datetime.now(UTC)
    assert node_state(0.0, prereqs_met=False, decay_due_at=None, now=now) == NodeState.LOCKED
    assert node_state(0.0, prereqs_met=True, decay_due_at=None, now=now) == NodeState.AVAILABLE
    assert node_state(0.4, prereqs_met=True, decay_due_at=None, now=now) == NodeState.LEARNING
    assert node_state(0.9, prereqs_met=True, decay_due_at=None, now=now) == NodeState.MASTERED
    past = now - timedelta(days=1)
    assert node_state(0.9, prereqs_met=True, decay_due_at=past, now=now) == NodeState.NEEDS_REVIEW

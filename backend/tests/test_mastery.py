"""Frozen mastery formula + node-state mapping (SPEC §4 #5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.constants import MASTERY_MASTERED_THRESHOLD, MASTERY_UNPROVEN_CAP
from app.schemas.enums import NodeState
from app.services.mastery import CardView, concept_mastery, node_state


PROVEN = 2  # correct on two different days


def test_empty_and_all_new_is_zero():
    assert concept_mastery([], correct_days=PROVEN) == 0.0
    # New carries no retention signal
    assert concept_mastery([CardView(state=0, retrievability=0.9)], correct_days=PROVEN) == 0.0


def test_review_card_dominates():
    cards = [CardView(state=2, retrievability=0.9), CardView(state=2, retrievability=0.9)]
    assert abs(concept_mastery(cards, correct_days=PROVEN) - 0.9) < 1e-9


def test_each_card_counts_at_most_its_state_weight():
    # Review (w=1.0, R=1.0) + Learning (w=0.5, R=0.0) => (1.0 + 0.0) / 2 cards
    cards = [CardView(state=2, retrievability=1.0), CardView(state=1, retrievability=0.0)]
    assert abs(concept_mastery(cards, correct_days=PROVEN) - 0.5) < 1e-9
    # A card still being learned can't make a concept look known, however fresh it is.
    assert concept_mastery([CardView(state=1, retrievability=1.0)], correct_days=PROVEN) == 0.5
    assert concept_mastery([CardView(state=3, retrievability=1.0)], correct_days=PROVEN) == 0.7


def test_new_cards_do_not_dilute():
    cards = [CardView(state=2, retrievability=0.9), CardView(state=0, retrievability=0.0)]
    assert abs(concept_mastery(cards, correct_days=PROVEN) - 0.9) < 1e-9


def test_mastered_needs_correct_answers_on_two_days():
    known = [CardView(state=2, retrievability=1.0)]
    for days in (0, 1):
        m = concept_mastery(known, correct_days=days)
        assert m == MASTERY_UNPROVEN_CAP < MASTERY_MASTERED_THRESHOLD
    assert concept_mastery(known, correct_days=2) == 1.0
    # The cap only ever lowers.
    assert concept_mastery([CardView(state=1, retrievability=0.6)], correct_days=0) == 0.3


def test_clamped():
    m = concept_mastery([CardView(state=2, retrievability=5.0)], correct_days=PROVEN)
    assert 0.0 <= m <= 1.0


def test_node_state_transitions():
    now = datetime.now(UTC)
    assert node_state(0.0, prereqs_met=False, decay_due_at=None, now=now) == NodeState.LOCKED
    assert node_state(0.0, prereqs_met=True, decay_due_at=None, now=now) == NodeState.AVAILABLE
    assert node_state(0.4, prereqs_met=True, decay_due_at=None, now=now) == NodeState.LEARNING
    assert node_state(0.9, prereqs_met=True, decay_due_at=None, now=now) == NodeState.MASTERED
    past = now - timedelta(days=1)
    assert node_state(0.9, prereqs_met=True, decay_due_at=past, now=now) == NodeState.NEEDS_REVIEW

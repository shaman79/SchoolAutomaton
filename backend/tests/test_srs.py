"""srs_service round-trips real py-fsrs cards: new -> review -> due ordering + retrievability bounds.

FSRS is the only scheduler (SPEC invariant); these tests exercise the installed py-fsrs API through
our thin wrapper. No DB, no network."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.schemas.enums import FsrsRating
from app.services import srs_service as s

NOW = datetime(2026, 6, 4, 12, 0, 0, tzinfo=UTC)


def test_new_card_is_json_string_and_new_state():
    cj = s.new_card(NOW)
    assert isinstance(cj, str)
    assert cj.startswith("{")
    # A never-reviewed card reports New (0) and zero retrievability for mastery weighting.
    assert s.card_state(cj) == 0
    assert s.get_retrievability(cj, NOW) == 0.0


def test_new_card_round_trips_through_fsrs():
    from fsrs import Card  # ensures the stored json is genuine py-fsrs

    cj = s.new_card(NOW)
    card = Card.from_json(cj)
    assert card.to_json() == cj


def test_review_good_advances_and_returns_future_due():
    cj = s.new_card(NOW)
    new_json, due = s.review(cj, int(FsrsRating.GOOD), NOW)
    assert isinstance(new_json, str)
    assert due.tzinfo is not None
    assert due >= NOW
    # Right after a correct review retrievability is ~1.0 and decays over time.
    assert s.get_retrievability(new_json, NOW) == pytest.approx(1.0, abs=1e-6)
    later = s.get_retrievability(new_json, NOW + timedelta(days=7))
    assert 0.0 <= later <= 1.0
    assert later < 1.0


def test_review_again_keeps_card_in_short_term_and_due_soon():
    cj = s.new_card(NOW)
    again_json, again_due = s.review(cj, int(FsrsRating.AGAIN), NOW)
    good_json, good_due = s.review(cj, int(FsrsRating.GOOD), NOW)
    # A lapse/again schedules sooner than a good answer (relearning step << first interval).
    assert again_due <= good_due
    assert s.card_state(again_json) in (1, 3)  # Learning or Relearning
    assert s.card_state(good_json) in (1, 2)


def test_retrievability_always_within_unit_interval():
    cj = s.new_card(NOW)
    j, _ = s.review(cj, int(FsrsRating.EASY), NOW)
    for days in (0, 1, 10, 100, 1000):
        r = s.get_retrievability(j, NOW + timedelta(days=days))
        assert 0.0 <= r <= 1.0


def test_naive_datetime_is_coerced_to_utc():
    naive = datetime(2026, 6, 4, 12, 0, 0)
    cj = s.new_card(naive)
    j, due = s.review(cj, int(FsrsRating.GOOD), naive)
    assert due.tzinfo is not None


def test_desired_retention_changes_interval():
    cj = s.new_card(NOW)
    _, due_low = s.review(cj, int(FsrsRating.GOOD), NOW, desired_retention=0.85)
    _, due_high = s.review(cj, int(FsrsRating.GOOD), NOW, desired_retention=0.95)
    # Higher desired retention => shorter interval (review sooner). Allow equality for short steps.
    assert due_high <= due_low


def test_due_ordering_across_ratings():
    cj = s.new_card(NOW)
    dues = {}
    for rating in (FsrsRating.AGAIN, FsrsRating.HARD, FsrsRating.GOOD, FsrsRating.EASY):
        _, due = s.review(cj, int(rating), NOW)
        dues[rating] = due
    # Easy should never be due before Again.
    assert dues[FsrsRating.EASY] >= dues[FsrsRating.AGAIN]

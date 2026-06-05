"""Frozen FSRS rating derivation (SPEC §4 #6)."""

from __future__ import annotations

from app.schemas.enums import FsrsRating
from app.services.srs_service import derive_rating


def test_incorrect_is_again():
    assert derive_rating(False, False, 1000, "mcq") == FsrsRating.AGAIN


def test_hint_makes_hard():
    assert derive_rating(True, True, 1000, "mcq") == FsrsRating.HARD


def test_fast_is_easy():
    assert derive_rating(True, False, 1000, "mcq") == FsrsRating.EASY  # below quick=4000


def test_slow_is_hard():
    assert derive_rating(True, False, 999_999, "mcq") == FsrsRating.HARD


def test_normal_is_good():
    assert derive_rating(True, False, 10_000, "mcq") == FsrsRating.GOOD


def test_unknown_latency_is_good():
    assert derive_rating(True, False, None, "short_answer") == FsrsRating.GOOD


def test_unknown_item_type_uses_default():
    assert derive_rating(True, False, 1000, "totally_unknown") == FsrsRating.EASY

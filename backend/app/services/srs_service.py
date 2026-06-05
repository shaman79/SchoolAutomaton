"""FSRS-6 wrapper (py-fsrs). FSRS is the ONLY scheduler; never hand-code its math (SPEC invariant).

``derive_rating`` is deterministic and frozen (SPEC §4 #6) — implemented + tested here. The
FSRS-backed functions are stubbed for the **B4 agent**, who must implement them against the installed
``fsrs`` package (verify Scheduler/Card/Rating API & version first) and keep these exact signatures.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache

from fsrs import Card, Rating, Scheduler

from ..core.constants import (
    DEFAULT_LATENCY_THRESHOLD,
    DESIRED_RETENTION_DEFAULT,
    FSRS_ENABLE_FUZZING,
    FSRS_LEARNING_STEPS_MIN,
    FSRS_MAXIMUM_INTERVAL_DAYS,
    FSRS_RELEARNING_STEPS_MIN,
    LATENCY_THRESHOLDS,
)
from ..schemas.enums import FsrsRating


@lru_cache(maxsize=8)
def _scheduler(desired_retention: float) -> Scheduler:
    """Build (and memoize) a configured FSRS Scheduler (SPEC §4 #5/#6, design pedagogy_framework).

    FSRS is the ONLY scheduler — its internals are a black box; we never hand-code its math."""
    return Scheduler(
        desired_retention=desired_retention,
        learning_steps=tuple(timedelta(minutes=m) for m in FSRS_LEARNING_STEPS_MIN),
        relearning_steps=tuple(timedelta(minutes=m) for m in FSRS_RELEARNING_STEPS_MIN),
        maximum_interval=FSRS_MAXIMUM_INTERVAL_DAYS,
        enable_fuzzing=FSRS_ENABLE_FUZZING,
    )


def _aware(now: datetime | None) -> datetime:
    """Coerce to a timezone-aware UTC datetime (FSRS requires tz-aware datetimes)."""
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now


def derive_rating(
    is_correct: bool,
    used_hint: bool,
    latency_ms: int | None,
    item_type: str,
) -> int:
    """Map a graded answer to an FSRS rating (1..4). Frozen mapping (SPEC §4 #6):
    Again=incorrect; Hard=correct AND (used_hint OR slow); Good=correct/normal; Easy=correct/fast."""
    if not is_correct:
        return int(FsrsRating.AGAIN)
    if used_hint:
        return int(FsrsRating.HARD)
    thresholds = LATENCY_THRESHOLDS.get(item_type, DEFAULT_LATENCY_THRESHOLD)
    if latency_ms is None:
        return int(FsrsRating.GOOD)
    if latency_ms > thresholds["slow"]:
        return int(FsrsRating.HARD)
    if latency_ms < thresholds["quick"]:
        return int(FsrsRating.EASY)
    return int(FsrsRating.GOOD)


# --------------------------------------------------------------------------- FSRS-backed
def new_card(now: datetime | None = None) -> str:
    """Return a fresh py-fsrs Card serialized via ``Card.to_json()`` (the authoritative form
    persisted in ``item_fsrs_cards.fsrs_card_json``). A brand-new card is due immediately."""
    card = Card(due=_aware(now))
    return card.to_json()


def review(
    card_json: str,
    rating: int,
    now: datetime,
    *,
    desired_retention: float = DESIRED_RETENTION_DEFAULT,
) -> tuple[str, datetime]:
    """Apply ``scheduler.review_card`` → (new card_json, next due UTC).

    ``rating`` is the deterministic FSRS rating from :func:`derive_rating` (1..4)."""
    card = Card.from_json(card_json)
    new_card_obj, _log = _scheduler(desired_retention).review_card(
        card, Rating(int(rating)), _aware(now)
    )
    return new_card_obj.to_json(), new_card_obj.due


def get_retrievability(
    card_json: str,
    now: datetime,
    *,
    desired_retention: float = DESIRED_RETENTION_DEFAULT,
) -> float:
    """Current FSRS retrievability R(t,S) of the card at ``now`` (0..1).

    A never-reviewed card (no stability yet) has 0 retrievability — it carries no retention signal
    for mastery aggregation (matches MASTERY_STATE_WEIGHTS giving New weight 0)."""
    card = Card.from_json(card_json)
    if card.stability is None or card.last_review is None:
        return 0.0
    r = _scheduler(desired_retention).get_card_retrievability(card, _aware(now))
    return max(0.0, min(1.0, float(r)))


def card_state(card_json: str) -> int:
    """Integer FSRS state of the card (1 Learning, 2 Review, 3 Relearning per py-fsrs ``State``).

    A never-reviewed card (no stability) is reported as 0 (New) to match the mastery weight table,
    even though py-fsrs initializes fresh cards in the Learning state."""
    card = Card.from_json(card_json)
    if card.stability is None or card.last_review is None:
        return 0
    return int(card.state.value)

"""Resume-where-you-left-off schemas: the learner's saved position in a lesson / quiz attempt, plus
their already-graded answers replayed so the reader/runner can rebuild its exact state.

A replayed answer re-reveals correctness ONLY for an item this same learner already had graded (the
grading endpoint revealed it then) — never for an unanswered item (SPEC §5)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from .common import AppModel, StrictModel
from .gamification import GradeResult, StreakInfo


class RestoredAnswer(AppModel):
    """One previously graded answer: what the learner submitted + the result they were shown."""

    item_id: int
    submitted_value: Any | None = None
    result: GradeResult


class SessionProgress(AppModel):
    """How far the learner is through a session (drives "Continue" + the history labels).

    ``position`` is 1-based: lesson = parts revealed so far; quiz = the question they are on."""

    position: int
    total: int
    completed: bool = False
    last_active_at: datetime | None = None


class LessonProgressIn(StrictModel):
    """The learner is reading (at least) up to this section ordinal. Never moves the boundary back."""

    revealed_up_to: int = Field(default=0, ge=0)


class LessonProgressOut(AppModel):
    lesson_id: int
    revealed_up_to: int
    completed: bool = False
    answers: list[RestoredAnswer] = []
    # Set when this call moved the boundary forward — a finished lesson part counts toward the daily
    # streak — so the header can update without a refetch; null otherwise.
    streak: StreakInfo | None = None


class AttemptPosition(StrictModel):
    """Index (in question-ordinal order) of the question the learner is on. Sent when they move on;
    echoed back as the position actually saved (forward-only, clamped to the last question)."""

    current_index: int = Field(ge=0)

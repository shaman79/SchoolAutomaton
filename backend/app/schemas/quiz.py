"""Public quiz delivery + attempt lifecycle schemas (TestRunner). Correctness withheld."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .common import AppModel, StrictModel
from .enums import QuizType
from .questions import ItemPublic


class QuizQuestionPublic(AppModel):
    question_id: int        # quiz_questions.id
    ordinal: int
    points: int = 10
    item: ItemPublic


class QuizPublic(AppModel):
    id: int
    request_id: str
    title: str
    language: str
    grade_band: str
    subject: str
    quiz_type: QuizType = QuizType.STANDARD
    questions: list[QuizQuestionPublic] = []


class AttemptStartOut(AppModel):
    attempt_id: int
    started_at: datetime


class AttemptCompleteIn(StrictModel):
    pass  # body intentionally empty; attempt_id is in the path


class QuizReviewItem(AppModel):
    """One graded question, revealed for post-completion review (correct answer + explanation)."""

    ordinal: int
    points: int = 10
    item: ItemPublic
    submitted_value: Any | None = None
    is_correct: bool = False
    partial_credit: float = 0.0
    correct_answer: Any | None = None
    explanation: str | None = None


class QuizReview(AppModel):
    """The learner's most recent attempt at a quiz, with answers revealed for review."""

    quiz_id: int
    request_id: str
    title: str
    subject: str
    attempt_id: int
    completed_at: datetime | None = None
    correct_count: int = 0
    total: int = 0
    accuracy: float = 0.0
    items: list[QuizReviewItem] = []

"""Public quiz delivery + attempt lifecycle schemas (TestRunner). Correctness withheld."""

from __future__ import annotations

from datetime import datetime

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

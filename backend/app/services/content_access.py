"""Who may open a lesson or a quiz.

Lesson and quiz ids are sequential, so an id alone must not open one: anyone could walk the ids and
read every learner's lessons. Lessons and quizzes are still meant to be shared — the recommendations
offer other learners' ready ones — so the rule is about knowing the content's learning session, not
owning it. A caller may open it when any of these holds:

1. it presents the content's request id (``X-Learning-Session``) — a random UUID that the reader has in
   its URL (``/lesson/<request_id>``), and that the history, "continue" and recommendations hand out;
2. its profile (``X-Resume-Code``) asked for it;
3. its profile has already opened it (a saved lesson position / a quiz attempt).

(2) and (3) keep tabs opened before this rule — whose code doesn't send the header yet — working for
everything the learner had already been in. A denied caller gets the same 404 as for a missing id.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import LearningRequest, LessonProgress, Profile, QuizAttempt

# Request ids are uuid4 strings; anything that couldn't be one is ignored rather than queried.
_KEY = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def session_key(raw: str | None) -> str | None:
    """The ``X-Learning-Session`` header value when it looks like a request id, else None."""
    value = (raw or "").strip()
    return value if _KEY.match(value) else None


async def _exists(db: AsyncSession, stmt) -> bool:  # noqa: ANN001
    return await db.scalar(stmt.limit(1)) is not None


async def may_open_lesson(db: AsyncSession, lesson_id: int, profile: Profile | None, key: str | None) -> bool:
    if key and await _exists(db, select(LearningRequest.id).where(
        LearningRequest.request_id == key, LearningRequest.lesson_id == lesson_id
    )):
        return True
    if profile is None:
        return False
    if await _exists(db, select(LearningRequest.id).where(
        LearningRequest.profile_id == profile.id, LearningRequest.lesson_id == lesson_id
    )):
        return True
    return await _exists(db, select(LessonProgress.id).where(
        LessonProgress.profile_id == profile.id, LessonProgress.lesson_id == lesson_id
    ))


async def may_open_quiz(db: AsyncSession, quiz_id: int, profile: Profile | None, key: str | None) -> bool:
    if key and await _exists(db, select(LearningRequest.id).where(
        LearningRequest.request_id == key, LearningRequest.quiz_id == quiz_id
    )):
        return True
    if profile is None:
        return False
    if await _exists(db, select(LearningRequest.id).where(
        LearningRequest.profile_id == profile.id, LearningRequest.quiz_id == quiz_id
    )):
        return True
    return await _exists(db, select(QuizAttempt.id).where(
        QuizAttempt.profile_id == profile.id, QuizAttempt.quiz_id == quiz_id
    ))

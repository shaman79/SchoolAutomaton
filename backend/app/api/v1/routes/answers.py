"""Unified grading endpoint — grades one answer and applies all reward/scheduling side-effects."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Answer, Item, Profile, QuizAttempt, QuizQuestion
from ....schemas.gamification import GradeResult
from ....schemas.questions import AnswerIn
from ....services import gamification
from ...deps import get_db, get_profile

router = APIRouter(tags=["answers"])


@router.post("/answers", response_model=GradeResult)
async def submit_answer(
    body: AnswerIn, profile: Profile = Depends(get_profile), db: AsyncSession = Depends(get_db)
):
    item = await db.get(Item, body.item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    if body.attempt_id is not None:
        # Quiz path. The attempt must be THIS learner's, still open, and own the item — otherwise a
        # client could grade against someone else's attempt, keep writing to a completed one, or
        # poison the combo. And each item can be answered ONCE per attempt (idempotency): a
        # refresh/replay or concurrent double-submit must not double-award XP.
        attempt = await db.get(QuizAttempt, body.attempt_id)
        if attempt is None or attempt.profile_id != profile.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
        if attempt.completed_at is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Attempt already completed")
        belongs = await db.scalar(
            select(func.count())
            .select_from(QuizQuestion)
            .where(QuizQuestion.quiz_id == attempt.quiz_id, QuizQuestion.item_id == body.item_id)
        )
        if not belongs:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Item is not part of this attempt")
        already = await db.scalar(
            select(Answer.id).where(
                Answer.attempt_id == body.attempt_id, Answer.item_id == body.item_id
            ).limit(1)
        )
        if already is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "This item was already answered in this attempt"
            )
    else:
        # Lesson-embedded practice only. A quiz-bank item must be answered INSIDE its attempt, so its
        # correct answer + explanation can't be revealed simply by POSTing the item id with no
        # attempt (answers/explanations are server-only until genuinely graded — SPEC §5). Lesson
        # items (the learner is reading the lesson) reveal on submit as intended.
        in_quiz = await db.scalar(
            select(func.count())
            .select_from(QuizQuestion)
            .where(QuizQuestion.item_id == body.item_id)
        )
        if in_quiz:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "This item must be answered within a quiz attempt"
            )
    return await gamification.grade_and_reward(db, profile, item, body, body.attempt_id)

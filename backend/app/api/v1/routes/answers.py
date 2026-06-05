"""Unified grading endpoint — grades one answer and applies all reward/scheduling side-effects."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Item, Profile, QuizAttempt, QuizQuestion
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
    # When an attempt is supplied, it must be THIS learner's, still open, and the item must belong to
    # its quiz — otherwise a client could grade against someone else's attempt, keep writing to a
    # completed one, or poison the combo by referencing an unrelated attempt. (Lesson-embedded
    # practice posts attempt_id=None and skips this.)
    if body.attempt_id is not None:
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
    return await gamification.grade_and_reward(db, profile, item, body, body.attempt_id)

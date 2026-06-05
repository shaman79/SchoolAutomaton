"""Quiz delivery + attempt lifecycle (start / complete)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Profile, Quiz, QuizAttempt, QuizQuestion
from ....schemas.gamification import ResultsSummary
from ....schemas.quiz import AttemptStartOut, QuizPublic
from ....services import gamification
from ...deps import get_db, get_profile
from ..serializers import quiz_public

router = APIRouter(tags=["quizzes"])


@router.get("/quizzes/{quiz_id}", response_model=QuizPublic)
async def get_quiz(quiz_id: int, db: AsyncSession = Depends(get_db)):
    quiz = await db.get(Quiz, quiz_id)
    if quiz is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    return await quiz_public(db, quiz)


@router.post(
    "/quizzes/{quiz_id}/attempts", response_model=AttemptStartOut, status_code=status.HTTP_201_CREATED
)
async def start_attempt(
    quiz_id: int, profile: Profile = Depends(get_profile), db: AsyncSession = Depends(get_db)
):
    quiz = await db.get(Quiz, quiz_id)
    if quiz is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    max_score = await db.scalar(
        select(func.coalesce(func.sum(QuizQuestion.points), 0)).where(QuizQuestion.quiz_id == quiz_id)
    )
    attempt = QuizAttempt(
        profile_id=profile.id,
        quiz_id=quiz_id,
        started_at=datetime.now(UTC),
        max_score=int(max_score or 0),
    )
    db.add(attempt)
    await db.flush()
    return AttemptStartOut(attempt_id=attempt.id, started_at=attempt.started_at)


@router.post("/attempts/{attempt_id}/complete", response_model=ResultsSummary)
async def complete_attempt(
    attempt_id: int, profile: Profile = Depends(get_profile), db: AsyncSession = Depends(get_db)
):
    attempt = await db.get(QuizAttempt, attempt_id)
    if attempt is None or attempt.profile_id != profile.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    return await gamification.finalize_attempt(db, profile, attempt_id)

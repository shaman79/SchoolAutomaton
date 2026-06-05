"""Quiz delivery + attempt lifecycle (start / complete)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Answer, Item, Profile, Quiz, QuizAttempt, QuizQuestion
from ....schemas.gamification import ResultsSummary
from ....schemas.quiz import AttemptStartOut, QuizPublic, QuizReview, QuizReviewItem
from ....services import gamification
from ...deps import get_db, get_profile
from ..serializers import item_public, quiz_public

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
    # Idempotent: if the learner already has an open (uncompleted) attempt for this quiz, resume it
    # instead of minting a duplicate. This is the server-side anchor for resume-after-refresh and
    # stops orphaned attempts skewing stats.
    existing = await db.scalar(
        select(QuizAttempt)
        .where(
            QuizAttempt.profile_id == profile.id,
            QuizAttempt.quiz_id == quiz_id,
            QuizAttempt.completed_at.is_(None),
        )
        .order_by(QuizAttempt.id.desc())
    )
    if existing is not None:
        return AttemptStartOut(attempt_id=existing.id, started_at=existing.started_at)
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


@router.get("/quizzes/{quiz_id}/review", response_model=QuizReview)
async def get_quiz_review(
    quiz_id: int, profile: Profile = Depends(get_profile), db: AsyncSession = Depends(get_db)
):
    """Reveal the learner's most recent attempt at a quiz for review (answers + explanations).

    Picks the latest attempt that actually has graded answers, so a learner can revisit a completed
    quiz anytime. 404 if the quiz is unknown or the learner has no attempt with answers yet."""
    quiz = await db.get(Quiz, quiz_id)
    if quiz is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")

    attempts = (
        await db.execute(
            select(QuizAttempt)
            .where(QuizAttempt.profile_id == profile.id, QuizAttempt.quiz_id == quiz_id)
            .order_by(QuizAttempt.id.desc())
        )
    ).scalars().all()

    chosen: QuizAttempt | None = None
    answers_by_item: dict[int, Answer] = {}
    for at in attempts:
        rows = (
            await db.execute(select(Answer).where(Answer.attempt_id == at.id))
        ).scalars().all()
        if rows:
            chosen = at
            answers_by_item = {a.item_id: a for a in rows}
            break
    if chosen is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No attempt to review yet")

    qrows = (
        await db.execute(
            select(QuizQuestion, Item)
            .join(Item, Item.id == QuizQuestion.item_id)
            .where(QuizQuestion.quiz_id == quiz_id)
            .order_by(QuizQuestion.ordinal)
        )
    ).all()

    items: list[QuizReviewItem] = []
    correct_count = 0
    for qq, item in qrows:
        a = answers_by_item.get(item.id)
        if a is not None and a.is_correct:
            correct_count += 1
        items.append(
            QuizReviewItem(
                ordinal=qq.ordinal,
                points=qq.points,
                item=await item_public(db, item),
                submitted_value=a.submitted_value_json if a is not None else None,
                is_correct=a.is_correct if a is not None else False,
                partial_credit=a.partial_credit if a is not None else 0.0,
                correct_answer=gamification._reveal_correct_answer(item),
                explanation=item.explanation,
            )
        )

    total = len(items)
    accuracy = round(correct_count / total, 4) if total else 0.0
    return QuizReview(
        quiz_id=quiz.id,
        request_id=quiz.request_id,
        title=quiz.title,
        subject=quiz.subject,
        attempt_id=chosen.id,
        completed_at=chosen.completed_at,
        correct_count=correct_count,
        total=total,
        accuracy=accuracy,
        items=items,
    )


@router.post("/attempts/{attempt_id}/complete", response_model=ResultsSummary)
async def complete_attempt(
    attempt_id: int, profile: Profile = Depends(get_profile), db: AsyncSession = Depends(get_db)
):
    attempt = await db.get(QuizAttempt, attempt_id)
    if attempt is None or attempt.profile_id != profile.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    return await gamification.finalize_attempt(db, profile, attempt_id)

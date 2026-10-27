"""Anonymous profile endpoints — create (issues resume code once), resume, me, settings, gamification
snapshot, knowledge tree."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Answer, LearningRequest, Lesson, Profile, Quiz, QuizAttempt
from ....schemas.gamification import GamificationSnapshot, TreeResponse
from ....schemas.profile import (
    CreateProfileIn,
    LearningSessionSummary,
    ParentSummary,
    ProfileCreateOut,
    ProfileEnvelope,
    ProfileSettingsPublic,
    ProfileSettingsUpdate,
    ResumeIn,
)
from ....sanitization import ratelimit
from ....services import (
    profile_service,
    progress_service,
    recommendation_service,
    summary_service,
    tree_service,
)
from ...deps import client_ip_hash, get_db, get_profile, lookup_profile_by_code

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.post("", response_model=ProfileCreateOut, status_code=status.HTTP_201_CREATED)
async def create_profile(
    body: CreateProfileIn, request: Request, db: AsyncSession = Depends(get_db)
):
    # Per-IP cap on new anonymous profiles: generous enough for a class starting at once, but fresh
    # codes can't be minted without limit (each one carries its own generation allowance).
    ratelimit.check_profile_create(client_ip_hash(request))
    code, profile = await profile_service.create_profile(
        db,
        locale=body.locale,
        education_locale=body.education_locale,
        school_year=body.school_year,
        age_band=body.age_band.value,
        display_name=body.display_name,
    )
    settings = await profile_service._get_settings(db, profile)
    return ProfileCreateOut(
        resume_code=code,
        profile=profile_service.profile_public(profile),
        settings=profile_service.settings_public(profile, settings),
    )


@router.post("/resume", response_model=ProfileEnvelope)
async def resume_profile(body: ResumeIn, request: Request, db: AsyncSession = Depends(get_db)):
    # Guarded lookup: unknown codes are throttled per client IP against guessing.
    profile = await lookup_profile_by_code(db, request, body.resume_code)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown resume code")
    await profile_service.touch_last_active(db, profile)
    return await profile_service.build_envelope(db, profile)


@router.get("/me", response_model=ProfileEnvelope)
async def get_me(profile: Profile = Depends(get_profile), db: AsyncSession = Depends(get_db)):
    await profile_service.touch_last_active(db, profile)
    return await profile_service.build_envelope(db, profile)


@router.get("/me/requests", response_model=list[LearningSessionSummary])
async def list_my_requests(
    profile: Profile = Depends(get_profile),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=200),
):
    """The learner's own lesson/quiz history (most recent first) for the 'My lessons' list.

    Only content-bearing requests (decision was 'proceed') that are ready or still generating — so a
    learner can re-open a past lesson/quiz or rejoin one that's still building. Failed generations are
    never surfaced here (they linger only to let the loading screen offer Retry)."""
    rows = (
        await db.execute(
            select(LearningRequest, Lesson, Quiz)
            .outerjoin(Lesson, Lesson.id == LearningRequest.lesson_id)
            .outerjoin(Quiz, Quiz.id == LearningRequest.quiz_id)
            .where(
                LearningRequest.profile_id == profile.id,
                LearningRequest.decision_type == "proceed",
                LearningRequest.status.in_(("ready", "generating")),
            )
            .order_by(LearningRequest.created_at.desc())
            .limit(limit)
        )
    ).all()
    # Which quizzes this learner has a FINISHED, graded attempt for — so the UI only offers "Review"
    # where there is something reviewable (an attempt still in progress is not: see get_quiz_review).
    attempted_quiz_ids = set(
        (
            await db.execute(
                select(QuizAttempt.quiz_id)
                .join(Answer, Answer.attempt_id == QuizAttempt.id)
                .where(
                    QuizAttempt.profile_id == profile.id,
                    QuizAttempt.completed_at.is_not(None),
                )
                .distinct()
            )
        ).scalars().all()
    )
    # How far the learner got in each — so the list can say "part 5 of 12" and reopening resumes there.
    lesson_progress = await progress_service.lesson_progress_map(
        db, profile, {lr.lesson_id for lr, _, _ in rows if lr.lesson_id is not None}
    )
    quiz_progress = await progress_service.quiz_progress_map(
        db, profile, {lr.quiz_id for lr, _, _ in rows if lr.quiz_id is not None}
    )
    return [
        LearningSessionSummary(
            request_id=lr.request_id,
            mode=lr.mode,
            status=lr.status,
            lesson_id=lr.lesson_id,
            quiz_id=lr.quiz_id,
            title=(lesson.topic if lesson else (quiz.title if quiz else None)),
            subject=(lesson.subject if lesson else (quiz.subject if quiz else None)),
            created_at=lr.created_at,
            attempted=(lr.quiz_id is not None and lr.quiz_id in attempted_quiz_ids),
            progress=(
                lesson_progress.get(lr.lesson_id)
                if lr.lesson_id is not None
                else quiz_progress.get(lr.quiz_id)
            ),
        )
        for lr, lesson, quiz in rows
    ]


@router.get("/me/continue", response_model=LearningSessionSummary | None)
async def get_continue(
    profile: Profile = Depends(get_profile), db: AsyncSession = Depends(get_db)
):
    """The unfinished lesson/quiz the learner was most recently in ("Continue where you left off"),
    with their position; ``null`` when nothing is in progress."""
    return await progress_service.continue_candidate(db, profile)


@router.get("/me/recommendations", response_model=list[LearningSessionSummary])
async def list_recommendations(
    profile: Profile = Depends(get_profile),
    db: AsyncSession = Depends(get_db),
    request_id: str | None = Query(default=None),
    subject: str | None = Query(default=None),
    limit: int = Query(default=6, ge=1, le=20),
):
    """Ready lessons/quizzes to revisit or explore next.

    With ``request_id`` (a just-finished session) the picks are seeded by that session's subject +
    topic for "more like this" reuse; without it they are the learner's own recent sessions for the
    home screen. Only ready, content-bearing requests are returned."""
    return await recommendation_service.suggest(
        db, profile, request_id=request_id, subject=subject, limit=limit
    )


@router.patch("/me/settings", response_model=ProfileSettingsPublic)
async def update_settings(
    body: ProfileSettingsUpdate,
    profile: Profile = Depends(get_profile),
    db: AsyncSession = Depends(get_db),
):
    return await profile_service.update_settings(db, profile, body)


@router.get("/me/gamification", response_model=GamificationSnapshot)
async def get_gamification(
    profile: Profile = Depends(get_profile), db: AsyncSession = Depends(get_db)
):
    return await profile_service.build_snapshot(db, profile)


@router.get("/me/tree", response_model=TreeResponse)
async def get_tree(
    subject: str | None = Query(default=None),
    profile: Profile = Depends(get_profile),
    db: AsyncSession = Depends(get_db),
):
    return await tree_service.build_tree(db, profile, subject)


@router.get("/me/summary", response_model=ParentSummary)
async def get_summary(
    days: int = Query(default=7, ge=1, le=31),
    profile: Profile = Depends(get_profile),
    db: AsyncSession = Depends(get_db),
):
    """Parent overview of the last ``days`` days: activity, practised topics judged in words, the
    wrong ideas met, and how many reviews are due."""
    return await summary_service.build_summary(db, profile, days)

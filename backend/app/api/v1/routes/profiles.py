"""Anonymous profile endpoints — create (issues resume code once), resume, me, settings, gamification
snapshot, knowledge tree."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import LearningRequest, Lesson, Profile, Quiz
from ....schemas.gamification import GamificationSnapshot, TreeResponse
from ....schemas.profile import (
    CreateProfileIn,
    LearningSessionSummary,
    ProfileCreateOut,
    ProfileEnvelope,
    ProfileSettingsPublic,
    ProfileSettingsUpdate,
    ResumeIn,
)
from ....services import profile_service, recommendation_service, tree_service
from ...deps import get_db, get_profile

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.post("", response_model=ProfileCreateOut, status_code=status.HTTP_201_CREATED)
async def create_profile(body: CreateProfileIn, db: AsyncSession = Depends(get_db)):
    code, profile = await profile_service.create_profile(
        db, locale=body.locale, age_band=body.age_band.value, display_name=body.display_name
    )
    settings = await profile_service._get_settings(db, profile)
    return ProfileCreateOut(
        resume_code=code,
        profile=profile_service.profile_public(profile),
        settings=profile_service.settings_public(profile, settings),
    )


@router.post("/resume", response_model=ProfileEnvelope)
async def resume_profile(body: ResumeIn, db: AsyncSession = Depends(get_db)):
    profile = await profile_service.get_by_code(db, body.resume_code)
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
        )
        for lr, lesson, quiz in rows
    ]


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

"""Anonymous profile endpoints — create (issues resume code once), resume, me, settings, gamification
snapshot, knowledge tree."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Profile
from ....schemas.gamification import GamificationSnapshot, TreeResponse
from ....schemas.profile import (
    CreateProfileIn,
    ProfileCreateOut,
    ProfileEnvelope,
    ProfileSettingsPublic,
    ProfileSettingsUpdate,
    ResumeIn,
)
from ....services import profile_service, tree_service
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

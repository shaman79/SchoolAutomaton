"""Anonymous profile lifecycle + gamification snapshot assembly. Fully implemented (no AI needed).

Creates a profile with a unique resume code (we store only its hash), 1:1 settings + streak rows,
and builds the ProfileEnvelope / GamificationSnapshot the frontend header and Results screens read."""

from __future__ import annotations

from datetime import UTC, datetime, time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.security import generate_resume_code, hash_resume_code
from ..models import (
    BadgeDefinition,
    Profile,
    ProfileBadge,
    ProfileSettings,
    StreakState,
    XpEvent,
)
from ..schemas.enums import DailyGoal
from ..schemas.gamification import BadgeInfo, GamificationSnapshot, StreakInfo
from ..schemas.profile import (
    ProfileEnvelope,
    ProfilePublic,
    ProfileSettingsPublic,
    ProfileSettingsUpdate,
)
from . import leveling


async def _unique_resume_code(db: AsyncSession) -> tuple[str, str]:
    for _ in range(12):
        code = generate_resume_code()
        h = hash_resume_code(code)
        exists = await db.scalar(select(Profile.id).where(Profile.resume_code_hash == h))
        if not exists:
            return code, h
    raise RuntimeError("Could not allocate a unique resume code")


async def create_profile(
    db: AsyncSession,
    *,
    locale: str = "en",
    education_locale: str | None = None,
    age_band: str = "unknown",
    display_name: str | None = None,
) -> tuple[str, Profile]:
    code, code_hash = await _unique_resume_code(db)
    profile = Profile(
        resume_code_hash=code_hash,
        display_name=display_name,
        age_band=age_band,
        primary_language=locale or "en",
    )
    db.add(profile)
    await db.flush()  # assign profile.id
    db.add(
        ProfileSettings(
            profile_id=profile.id, locale=locale or "en", education_locale=education_locale
        )
    )
    db.add(StreakState(profile_id=profile.id))
    await db.flush()
    return code, profile


async def get_by_code(db: AsyncSession, code: str) -> Profile | None:
    return await db.scalar(select(Profile).where(Profile.resume_code_hash == hash_resume_code(code)))


async def touch_last_active(db: AsyncSession, profile: Profile) -> None:
    profile.last_active_at = datetime.now(UTC)


async def _get_settings(db: AsyncSession, profile: Profile) -> ProfileSettings:
    settings = await db.get(ProfileSettings, profile.id)
    if settings is None:  # self-heal legacy/edge rows
        settings = ProfileSettings(profile_id=profile.id, locale=profile.primary_language)
        db.add(settings)
        await db.flush()
    return settings


async def _get_streak(db: AsyncSession, profile: Profile) -> StreakState:
    streak = await db.get(StreakState, profile.id)
    if streak is None:
        streak = StreakState(profile_id=profile.id)
        db.add(streak)
        await db.flush()
    return streak


async def _daily_xp(db: AsyncSession, profile: Profile) -> int:
    start = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    total = await db.scalar(
        select(func.coalesce(func.sum(XpEvent.amount), 0)).where(
            XpEvent.profile_id == profile.id, XpEvent.created_at >= start
        )
    )
    return int(total or 0)


async def build_badges(db: AsyncSession, profile: Profile, locale: str) -> list[BadgeInfo]:
    rows = (
        await db.execute(
            select(ProfileBadge, BadgeDefinition).join(
                BadgeDefinition, BadgeDefinition.id == ProfileBadge.badge_id
            ).where(ProfileBadge.profile_id == profile.id)
        )
    ).all()
    out: list[BadgeInfo] = []
    for pb, bd in rows:
        titles = bd.title_i18n_json or {}
        descs = bd.description_i18n_json or {}
        out.append(
            BadgeInfo(
                code=bd.code,
                title=titles.get(locale) or titles.get("en") or bd.code,
                description=descs.get(locale) or descs.get("en"),
                tier=pb.tier,
                unlocked_at=pb.unlocked_at,
                progress_numerator=pb.progress_numerator,
                progress_denominator=pb.progress_denominator,
                icon_url=f"/api/v1/assets/{bd.icon_asset_hash}" if bd.icon_asset_hash else None,
            )
        )
    return out


async def build_snapshot(db: AsyncSession, profile: Profile) -> GamificationSnapshot:
    settings = await _get_settings(db, profile)
    streak = await _get_streak(db, profile)
    level = leveling.level_from_xp(profile.total_xp)
    daily_goal = DailyGoal(settings.daily_goal) if settings.daily_goal in DailyGoal._value2member_map_ else DailyGoal.REGULAR
    return GamificationSnapshot(
        level=level,
        total_xp=profile.total_xp,
        xp_to_next=leveling.xp_to_next(profile.total_xp),
        level_progress_pct=leveling.level_progress_pct(profile.total_xp),
        streak=StreakInfo(
            current=streak.current_streak_len,
            longest=streak.longest_streak,
            freeze_inventory=streak.freeze_inventory,
            is_perfect=streak.is_perfect,
        ),
        daily_goal=daily_goal.value,
        daily_progress_xp=await _daily_xp(db, profile),
        badges=await build_badges(db, profile, settings.locale),
    )


def settings_public(profile: Profile, settings: ProfileSettings) -> ProfileSettingsPublic:
    return ProfileSettingsPublic(
        theme=settings.theme,
        font=settings.font,
        font_scale=settings.font_scale,
        reduced_motion=settings.reduced_motion,
        sound=settings.sound,
        locale=settings.locale,
        education_locale=settings.education_locale,
        daily_goal=settings.daily_goal,
        interleave_strength=settings.interleave_strength,
        rest_days_per_week=settings.rest_days_per_week,
        desired_retention=profile.desired_retention,
    )


def profile_public(profile: Profile) -> ProfilePublic:
    return ProfilePublic(
        id=profile.id,
        display_name=profile.display_name,
        total_xp=profile.total_xp,
        level=leveling.level_from_xp(profile.total_xp),
        age_band=profile.age_band,
        primary_language=profile.primary_language,
        created_at=profile.created_at,
    )


async def build_envelope(db: AsyncSession, profile: Profile) -> ProfileEnvelope:
    settings = await _get_settings(db, profile)
    return ProfileEnvelope(
        profile=profile_public(profile),
        settings=settings_public(profile, settings),
        gamification=await build_snapshot(db, profile),
    )


async def update_settings(
    db: AsyncSession, profile: Profile, upd: ProfileSettingsUpdate
) -> ProfileSettingsPublic:
    settings = await _get_settings(db, profile)
    data = upd.model_dump(exclude_unset=True)
    if "display_name" in data:
        profile.display_name = data.pop("display_name")
    if "desired_retention" in data:
        profile.desired_retention = data.pop("desired_retention")
    for field, value in data.items():
        if value is not None and hasattr(settings, field):
            setattr(settings, field, value.value if hasattr(value, "value") else value)
    if settings.locale:
        profile.primary_language = settings.locale
    await db.flush()
    return settings_public(profile, settings)

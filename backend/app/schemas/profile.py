"""Profile + settings I/O schemas. Resume code is shown ONCE on create (SPEC §4 #1)."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import AppModel, StrictModel
from .enums import AgeBand, DailyGoal
from .gamification import GamificationSnapshot


class CreateProfileIn(StrictModel):
    locale: str = "en"
    age_band: AgeBand = AgeBand.UNKNOWN
    display_name: str | None = Field(default=None, max_length=40)


class ResumeIn(StrictModel):
    resume_code: str


class ProfileSettingsPublic(AppModel):
    theme: str = "default"
    font: str = "lexend"
    font_scale: float = 1.0
    reduced_motion: bool = False
    sound: bool = True
    locale: str = "en"
    daily_goal: DailyGoal = DailyGoal.REGULAR
    interleave_strength: float = 0.30
    rest_days_per_week: int = 0
    desired_retention: float = 0.90


class ProfileSettingsUpdate(StrictModel):
    theme: str | None = None
    font: str | None = None
    font_scale: float | None = None
    reduced_motion: bool | None = None
    sound: bool | None = None
    locale: str | None = None
    daily_goal: DailyGoal | None = None
    interleave_strength: float | None = None
    rest_days_per_week: int | None = None
    desired_retention: float | None = Field(default=None, ge=0.80, le=0.97)
    display_name: str | None = Field(default=None, max_length=40)


class ProfilePublic(AppModel):
    id: int
    display_name: str | None = None
    total_xp: int = 0
    level: int = 1
    age_band: AgeBand = AgeBand.UNKNOWN
    primary_language: str = "en"
    created_at: datetime | None = None


class ProfileEnvelope(AppModel):
    profile: ProfilePublic
    settings: ProfileSettingsPublic
    gamification: GamificationSnapshot


class ProfileCreateOut(AppModel):
    """Create response — the ONLY time the raw resume_code is returned."""

    resume_code: str
    profile: ProfilePublic
    settings: ProfileSettingsPublic

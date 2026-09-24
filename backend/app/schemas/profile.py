"""Profile + settings I/O schemas. Resume code is shown ONCE on create (SPEC §4 #1)."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from .common import AppModel, StrictModel
from .enums import SCHOOL_YEAR_MAX, SCHOOL_YEAR_MIN, AgeBand, DailyGoal, normalize_school_year
from .gamification import GamificationSnapshot


class CreateProfileIn(StrictModel):
    locale: str = "en"
    education_locale: str | None = None  # BCP-47 region setting (en-US/en-GB/cs-CZ)
    school_year: int | None = None  # the learner's class (exact school year); None = not set
    age_band: AgeBand = AgeBand.UNKNOWN
    display_name: str | None = Field(default=None, max_length=40)

    @field_validator("school_year", mode="before")
    @classmethod
    def _norm_school_year(cls, v: object) -> int | None:
        return normalize_school_year(v)


class ResumeIn(StrictModel):
    resume_code: str


class ProfileSettingsPublic(AppModel):
    theme: str = "default"
    font: str = "lexend"
    font_scale: float = 1.0
    reduced_motion: bool = False
    sound: bool = True
    locale: str = "en"
    education_locale: str | None = None  # BCP-47 (en-US/en-GB/cs-CZ); drives generated content
    school_year: int | None = None  # the learner's class (exact school year); None = not set
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
    education_locale: str | None = None
    # Explicit null clears the class setting (unlike the other fields, where null means "unchanged").
    school_year: int | None = None
    daily_goal: DailyGoal | None = None
    interleave_strength: float | None = None
    rest_days_per_week: int | None = None
    desired_retention: float | None = Field(default=None, ge=0.80, le=0.97)
    display_name: str | None = Field(default=None, max_length=40)

    @field_validator("school_year", mode="before")
    @classmethod
    def _strict_school_year(cls, v: object) -> int | None:
        # Unlike the lenient request/classifier paths, a bad value here must be a 422 — coercing it
        # to None would silently CLEAR the learner's stored class.
        if v is None:
            return None
        year = normalize_school_year(v)
        if year is None:
            raise ValueError(
                f"school_year must be a whole number {SCHOOL_YEAR_MIN}-{SCHOOL_YEAR_MAX} or null"
            )
        return year


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


class LearningSessionSummary(AppModel):
    """One past (or in-progress) learning session for the 'My lessons' history list."""

    request_id: str
    mode: str  # study|test
    status: str  # queued|generating|ready|error
    lesson_id: int | None = None
    quiz_id: int | None = None
    title: str | None = None  # lesson topic or quiz title
    subject: str | None = None
    created_at: datetime | None = None
    attempted: bool = False  # quiz only: the learner has a graded attempt (so "Review" has content)


class TopicProgress(AppModel):
    """One concept the learner practised in the window, judged in words rather than a percentage."""

    concept_id: int
    title: str
    subject: str
    answers: int
    correct: int
    # confident = solid (mastered, or reliably right); mostly = on the way; practice = worth another go.
    status: str  # confident|mostly|practice


class ParentSummary(AppModel):
    """A calm, parent-facing overview of the last ``days`` days (GET /profiles/me/summary)."""

    days: int
    active_days: int
    lessons: int
    quizzes_completed: int
    answers: int
    correct: int
    due_reviews: int
    topics: list[TopicProgress] = Field(default_factory=list)
    misconceptions: list[str] = Field(default_factory=list)  # wrong ideas met this week (deduped)

"""Learner identity + preferences + streak state. Anonymous; the only credential is a resume code
(we persist ONLY its sha256 hash — SPEC §4 #1)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.constants import (
    DESIRED_RETENTION_DEFAULT,
    INTERLEAVE_STRENGTH_DEFAULT,
    REST_DAYS_PER_WEEK_DEFAULT,
    STREAK_FREEZE_CAP_DEFAULT,
)
from ..db.base import Base, utcnow


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resume_code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    total_xp: Mapped[int] = mapped_column(Integer, default=0)
    age_band: Mapped[str] = mapped_column(String(20), default="unknown")
    primary_language: Mapped[str] = mapped_column(String(12), default="en")
    desired_retention: Mapped[float] = mapped_column(Float, default=DESIRED_RETENTION_DEFAULT)
    competitive_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    settings: Mapped[ProfileSettings] = relationship(
        back_populates="profile", uselist=False, cascade="all, delete-orphan"
    )
    streak: Mapped[StreakState] = relationship(
        back_populates="profile", uselist=False, cascade="all, delete-orphan"
    )


class ProfileSettings(Base):
    __tablename__ = "profile_settings"

    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), primary_key=True)
    theme: Mapped[str] = mapped_column(String(20), default="default")  # default|highcontrast|dyslexia
    font: Mapped[str] = mapped_column(String(20), default="lexend")    # lexend|atkinson|opendyslexic
    font_scale: Mapped[float] = mapped_column(Float, default=1.0)      # 1.0|1.15|1.3
    reduced_motion: Mapped[bool] = mapped_column(Boolean, default=False)
    sound: Mapped[bool] = mapped_column(Boolean, default=True)
    locale: Mapped[str] = mapped_column(String(12), default="en")
    daily_goal: Mapped[str] = mapped_column(String(12), default="regular")
    interleave_strength: Mapped[float] = mapped_column(Float, default=INTERLEAVE_STRENGTH_DEFAULT)
    rest_days_per_week: Mapped[int] = mapped_column(Integer, default=REST_DAYS_PER_WEEK_DEFAULT)

    profile: Mapped[Profile] = relationship(back_populates="settings")


class StreakState(Base):
    __tablename__ = "streak_state"

    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), primary_key=True)
    current_streak_len: Mapped[int] = mapped_column(Integer, default=0)
    longest_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_active_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    freeze_inventory: Mapped[int] = mapped_column(Integer, default=STREAK_FREEZE_CAP_DEFAULT)
    freezes_used_in_current_streak: Mapped[int] = mapped_column(Integer, default=0)
    rest_days_used_this_week: Mapped[int] = mapped_column(Integer, default=0)
    is_perfect: Mapped[bool] = mapped_column(Boolean, default=True)
    repair_window_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    profile: Mapped[Profile] = relationship(back_populates="streak")

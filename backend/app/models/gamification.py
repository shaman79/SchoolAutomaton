"""Derived mastery, XP ledger, badge definitions + per-profile badge progress."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, utcnow


class SkillMastery(Base):
    """One row per (profile, concept). ``mastery`` is DERIVED from FSRS retrievability (SPEC §4 #5)."""

    __tablename__ = "skill_mastery"
    __table_args__ = (UniqueConstraint("profile_id", "concept_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), index=True)
    concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), index=True)
    mastery: Mapped[float] = mapped_column(Float, default=0.0)
    node_state: Mapped[str] = mapped_column(String(16), default="locked")  # NodeState
    recent_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    decay_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reviewed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class XpEvent(Base):
    """Event-sourced XP ledger. profiles.total_xp is the denormalized SUM. Never decremented."""

    __tablename__ = "xp_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(24))  # XpReason
    concept_id: Mapped[int | None] = mapped_column(ForeignKey("concepts.id"), nullable=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BadgeDefinition(Base):
    __tablename__ = "badge_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    title_i18n_json: Mapped[dict] = mapped_column(JSON)
    description_i18n_json: Mapped[dict] = mapped_column(JSON)
    icon_asset_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    criterion_key: Mapped[str] = mapped_column(String(48))
    criterion_params_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tiered: Mapped[bool] = mapped_column(Boolean, default=False)


class ProfileBadge(Base):
    __tablename__ = "profile_badges"
    __table_args__ = (UniqueConstraint("profile_id", "badge_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), index=True)
    badge_id: Mapped[int] = mapped_column(ForeignKey("badge_definitions.id"), index=True)
    tier: Mapped[int] = mapped_column(Integer, default=1)
    progress_numerator: Mapped[int] = mapped_column(Integer, default=0)
    progress_denominator: Mapped[int] = mapped_column(Integer, default=1)
    unlocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

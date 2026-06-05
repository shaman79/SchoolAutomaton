"""Quizzes compose ordered references to the shared Item pool; attempts + immutable answer log."""

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
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, utcnow


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(200))
    language: Mapped[str] = mapped_column(String(12))
    grade_band: Mapped[str] = mapped_column(String(12))
    subject: Mapped[str] = mapped_column(String(40))
    concept_id: Mapped[int | None] = mapped_column(ForeignKey("concepts.id"), nullable=True)
    quiz_type: Mapped[str] = mapped_column(String(16), default="standard")  # QuizType
    model_id: Mapped[str] = mapped_column(String(48))
    prompt_version: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    points: Mapped[int] = mapped_column(Integer, default=10)


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), index=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    max_score: Mapped[int] = mapped_column(Integer, default=0)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    xp_awarded: Mapped[int] = mapped_column(Integer, default=0)
    combo_max: Mapped[int] = mapped_column(Integer, default=0)


class Answer(Base):
    """Immutable answer log; one row per graded answer (quiz or lesson-embedded practice)."""

    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempt_id: Mapped[int | None] = mapped_column(ForeignKey("quiz_attempts.id"), nullable=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    submitted_value_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    partial_credit: Mapped[float] = mapped_column(Float, default=0.0)
    used_hint: Mapped[bool] = mapped_column(Boolean, default=False)
    is_first_try: Mapped[bool] = mapped_column(Boolean, default=True)  # combo counts first-try only
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fsrs_rating: Mapped[int] = mapped_column(Integer)  # 1..4
    detected_misconception_id: Mapped[int | None] = mapped_column(
        ForeignKey("misconceptions.id"), nullable=True
    )
    xp_awarded: Mapped[int] = mapped_column(Integer, default=0)
    mastery_delta: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

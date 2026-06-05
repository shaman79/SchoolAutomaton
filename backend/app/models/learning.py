"""Per-prompt request row + the sanitization audit trail.

Raw prompt text is NEVER stored on ``learning_requests``. ``sanitization_audit`` stores no raw text
by default; only a Fernet-encrypted copy when RAW_CAPTURE_ON_FLAG and a safety flag fired (SPEC §5)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, utcnow


class LearningRequest(Base):
    __tablename__ = "learning_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)  # uuid4 = sessionId
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id"), nullable=True)
    decision_type: Mapped[str] = mapped_column(String(12))  # proceed|clarify|refuse|crisis
    mode: Mapped[str | None] = mapped_column(String(8), nullable=True)  # study|test
    structured_intent_json: Mapped[dict] = mapped_column(JSON)
    detected_language: Mapped[str] = mapped_column(String(12), default="en")
    grade_band: Mapped[str] = mapped_column(String(12), default="unknown")
    status: Mapped[str] = mapped_column(String(12), default="queued", index=True)
    lesson_id: Mapped[int | None] = mapped_column(ForeignKey("lessons.id"), nullable=True)
    quiz_id: Mapped[int | None] = mapped_column(ForeignKey("quizzes.id"), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(20))
    model_id: Mapped[str] = mapped_column(String(48))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SanitizationAudit(Base):
    __tablename__ = "sanitization_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), index=True)
    hashed_profile_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_hash: Mapped[str] = mapped_column(String(64), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw_length: Mapped[int] = mapped_column(Integer, default=0)
    language: Mapped[str | None] = mapped_column(String(12), nullable=True)
    removed_char_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    suspicion_score: Mapped[float] = mapped_column(Float, default=0.0)
    heuristic_hit_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    classifier_verdict_json: Mapped[dict] = mapped_column(JSON)  # StructuredIntent w/ topic HASHED
    decision_type: Mapped[str] = mapped_column(String(12), index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    injection_detected: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    safety_flags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_id: Mapped[str] = mapped_column(String(48))
    prompt_version: Mapped[str] = mapped_column(String(20))
    token_usage_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Only populated when RAW_CAPTURE_ON_FLAG and a safety flag fired; Fernet-encrypted; auto-purged.
    raw_prompt_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

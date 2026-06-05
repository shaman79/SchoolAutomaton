"""Admin realm schemas: login, dashboard, audit browsing, settings."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .common import AppModel, StrictModel


class AdminLoginIn(StrictModel):
    username: str
    password: str


class TokenOut(AppModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class DashboardOut(AppModel):
    requests_24h: int = 0
    decisions_breakdown: dict[str, int] = {}
    anthropic_cost_usd: float = 0.0
    replicate_cost_usd: float = 0.0
    cache_hit_rate: float = 0.0
    crisis_events: int = 0
    refusals: int = 0
    injection_attempts: int = 0
    profiles_total: int = 0
    lessons_total: int = 0
    quizzes_total: int = 0


class AuditRecord(AppModel):
    id: int
    request_id: str
    ts: datetime
    decision_type: str
    language: str | None = None
    suspicion_score: float = 0.0
    injection_detected: bool = False
    safety_flags: list[str] | None = None
    reason: str | None = None
    raw_length: int = 0
    # topic is HASHED in storage; raw only surfaces when flagged + RAW_CAPTURE_ON_FLAG
    topic_hash: str | None = None


class SettingItem(AppModel):
    key: str
    value: Any | None = None     # masked to '***' for secrets
    is_secret: bool = False
    updated_at: datetime | None = None


class SettingUpdateIn(StrictModel):
    key: str
    value: Any
    is_secret: bool = False


class ContentRecord(AppModel):
    id: int
    kind: str  # lesson|quiz
    topic: str
    grade_band: str
    language: str
    cache_key: str | None = None
    created_at: datetime

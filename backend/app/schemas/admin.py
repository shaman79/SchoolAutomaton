"""Admin realm schemas: login, dashboard, audit browsing, runtime settings."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import AppModel, StrictModel


class AdminLoginIn(StrictModel):
    # Bounded so a huge body can't be fed to Argon2 (CPU) or the throttle's key table.
    username: str = Field(max_length=64)
    password: str = Field(max_length=1024)


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


ConfigValue = str | bool | int | float | None
ConfigSource = Literal["default", "env", "admin", "code"]
ConfigKind = Literal["choice", "number", "integer", "text", "status"]
ConfigGroup = Literal["models", "spending", "limits", "keys", "about"]


class ConfigItem(AppModel):
    """One setting as the backend runs it now (admin console → Settings).

    ``source``: ``default`` = the app's own default; ``env`` = the server's environment / .env
    (``env_name``); ``admin`` = changed on this page (``updated_at``/``updated_by``); ``code`` = fixed in
    this release. API keys (kind ``status``) only ever report whether they are set."""

    key: str
    group: ConfigGroup
    kind: ConfigKind
    value: ConfigValue = None
    source: ConfigSource
    env_name: str | None = None
    editable: bool = False
    # What applies without an admin change (the environment's value, else the default) — what
    # "undo" returns to.
    base_value: ConfigValue = None
    base_source: ConfigSource | None = None
    default_value: ConfigValue = None  # the app's own default (the recommended choice)
    choices: list[str] = []
    min: float | None = None
    max: float | None = None
    updated_at: datetime | None = None
    updated_by: str | None = None


class ModelUsageToday(AppModel):
    provider: str
    model: str
    calls: int
    cost_usd: float | None = None  # None when the model has no known price
    last_call_at: datetime | None = None


class AdminConfigOut(AppModel):
    can_edit: bool
    items: list[ConfigItem]
    usage_today: list[ModelUsageToday]
    spent_today_usd: float
    budget_usd: float  # 0 = no daily cap
    day_started_at: datetime  # 00:00 UTC — "today" for the budget and the usage list


class ConfigUpdateIn(StrictModel):
    value: str | bool | int | float


class ContentRecord(AppModel):
    id: int
    kind: str  # lesson|quiz
    topic: str
    grade_band: str
    language: str
    cache_key: str | None = None
    created_at: datetime

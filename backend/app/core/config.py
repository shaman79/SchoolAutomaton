"""Application settings (env-driven). Single source for credentials, paths and runtime knobs.

Loaded once as the module-level ``settings`` singleton. Secrets read from env at boot can be
overridden/extended at runtime via the ``app_settings`` DB table (admin), but env always wins for
provider keys at startup (SPEC).
"""

from __future__ import annotations

import base64
import hashlib
from functools import cached_property
from pathlib import Path

from pydantic import Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = "dev-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- App ----
    app_name: str = "SchoolAutomaton"
    env: str = Field(default="development", alias="SA_ENV")
    debug: bool = Field(default=True, alias="SA_DEBUG")

    # ---- Provider credentials ----
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    replicate_api_token: str = Field(default="", alias="REPLICATE_API_TOKEN")

    # ---- Models ----
    model_id: str = Field(default="claude-opus-4-8", alias="SA_MODEL_ID")
    sanitizer_model_id: str = Field(default="claude-haiku-4-5", alias="SA_SANITIZER_MODEL_ID")

    # ---- Secrets / admin ----
    app_secret: str = Field(default=_DEV_SECRET, alias="APP_SECRET")
    admin_username: str = Field(default="admin", alias="ADMIN_USERNAME")
    admin_password: str = Field(default="admin", alias="ADMIN_PASSWORD")
    jwt_alg: str = "HS256"
    jwt_expire_minutes: int = 60

    # ---- Persistence / paths ----
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/schoolautomaton.db", alias="SA_DATABASE_URL"
    )
    data_dir: Path = Field(default=Path("./data"), alias="SA_DATA_DIR")

    # ---- CORS ----
    cors_origins_raw: str = Field(
        default="http://localhost:5173,http://localhost:8080", alias="SA_CORS_ORIGINS"
    )

    # ---- Safety / audit ----
    raw_capture_on_flag: bool = Field(default=False, alias="SA_RAW_CAPTURE_ON_FLAG")
    audit_raw_retention_days: int = Field(default=30, alias="SA_AUDIT_RAW_RETENTION_DAYS")

    # ---- Rate limiting ----
    rate_per_min: int = Field(default=20, alias="SA_RATE_PER_MIN")
    rate_per_day: int = Field(default=300, alias="SA_RATE_PER_DAY")
    max_prompt_chars: int = 2000

    # ---- Cost guardrails ----
    video_enabled: bool = Field(default=False, alias="SA_VIDEO_ENABLED")
    daily_video_quota: int = Field(default=0, alias="SA_DAILY_VIDEO_QUOTA")

    # ---- Derived paths ----
    @computed_field  # type: ignore[prop-decorator]
    @property
    def visual_cache_dir(self) -> Path:
        return self.data_dir / "cache" / "visuals"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @cached_property
    def jwt_secret(self) -> str:
        """JWT signing key derived from APP_SECRET (stable across restarts)."""
        return hashlib.sha256(f"jwt::{self.app_secret}".encode()).hexdigest()

    @cached_property
    def fernet_key(self) -> bytes:
        """A urlsafe-base64 32-byte Fernet key derived from APP_SECRET."""
        digest = hashlib.sha256(f"fernet::{self.app_secret}".encode()).digest()
        return base64.urlsafe_b64encode(digest)

    @model_validator(mode="after")
    def _guard_production_secrets(self) -> Settings:
        """Fail closed: in production, refuse to boot with default/weak secrets (SPEC §5 / security)."""
        if self.env.lower() == "production":
            problems: list[str] = []
            if self.app_secret == _DEV_SECRET or len(self.app_secret) < 32:
                problems.append("APP_SECRET must be set to a strong (>=32 char) non-default value")
            if self.admin_password in ("", "admin", "change-me-too") or len(self.admin_password) < 8:
                problems.append("ADMIN_PASSWORD must be a strong (>=8 char) non-default value")
            if problems:
                raise ValueError("Insecure production config: " + "; ".join(problems))
        return self

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.visual_cache_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()

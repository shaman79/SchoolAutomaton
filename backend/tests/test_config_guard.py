"""The production fail-closed guard on Settings: default/weak secrets must refuse to boot in prod.

Dev/test (env != production) is unaffected. No app import here — Settings is constructed directly
with explicit kwargs so the OS env / .env never leaks into the assertion."""

from __future__ import annotations

import pytest

from app.core.config import _DEV_SECRET, Settings

_STRONG = "x" * 40  # >= 32 chars, non-default


def test_production_rejects_default_secret():
    with pytest.raises(ValueError, match="APP_SECRET"):
        Settings(SA_ENV="production", APP_SECRET=_DEV_SECRET, ADMIN_PASSWORD="strongpw")


def test_production_rejects_short_secret():
    with pytest.raises(ValueError, match="APP_SECRET"):
        Settings(SA_ENV="production", APP_SECRET="short", ADMIN_PASSWORD="strongpw")


def test_production_rejects_default_admin_password():
    with pytest.raises(ValueError, match="ADMIN_PASSWORD"):
        Settings(SA_ENV="production", APP_SECRET=_STRONG, ADMIN_PASSWORD="admin")


def test_production_rejects_empty_admin_password():
    # The critical case: a non-interactive deploy must never boot with an empty admin password.
    with pytest.raises(ValueError, match="ADMIN_PASSWORD"):
        Settings(SA_ENV="production", APP_SECRET=_STRONG, ADMIN_PASSWORD="")


def test_production_rejects_short_admin_password():
    with pytest.raises(ValueError, match="ADMIN_PASSWORD"):
        Settings(SA_ENV="production", APP_SECRET=_STRONG, ADMIN_PASSWORD="short7x")  # 7 chars


def test_production_accepts_strong_config():
    s = Settings(SA_ENV="production", APP_SECRET=_STRONG, ADMIN_PASSWORD="strongpw")
    assert s.is_production is True


def test_development_allows_defaults():
    # The dev default secret / admin password must NOT raise outside production.
    s = Settings(SA_ENV="development", APP_SECRET=_DEV_SECRET, ADMIN_PASSWORD="admin")
    assert s.is_production is False


def test_test_env_allows_defaults():
    s = Settings(SA_ENV="test", APP_SECRET=_DEV_SECRET, ADMIN_PASSWORD="admin")
    assert s.env == "test"

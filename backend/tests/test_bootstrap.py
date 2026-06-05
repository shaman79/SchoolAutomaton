"""bootstrap_admin: the env-specified admin is the source of truth — created on first boot, and its
password is ROTATED on a later boot when ADMIN_PASSWORD changes (no silent no-op, no duplicates)."""

from __future__ import annotations

import os

os.environ.setdefault("SA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("APP_SECRET", "test-secret-please-ignore")
os.environ.setdefault("SA_ENV", "test")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import verify_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.bootstrap import bootstrap_admin  # noqa: E402
from app.models import AdminUser  # noqa: E402


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_bootstrap_creates_then_rotates(db, monkeypatch):
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "firstpass1")
    await bootstrap_admin(db)
    await db.flush()
    a = await db.scalar(select(AdminUser).where(AdminUser.username == "admin"))
    assert a is not None and verify_password("firstpass1", a.password_hash)
    first_hash = a.password_hash

    # Re-deploy with a changed password → it must rotate, not silently no-op.
    monkeypatch.setattr(settings, "admin_password", "secondpass2")
    await bootstrap_admin(db)
    await db.flush()
    a2 = await db.scalar(select(AdminUser).where(AdminUser.username == "admin"))
    assert verify_password("secondpass2", a2.password_hash)
    assert a2.password_hash != first_hash
    # No duplicate admin row was created.
    assert (await db.scalar(select(func.count()).select_from(AdminUser))) == 1

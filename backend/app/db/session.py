"""Async engine + session factory + FastAPI dependency, with SQLite tuned for concurrency.

SQLite is single-writer; we enable WAL + busy_timeout + foreign_keys on every connection so
concurrent generation, grading and asset-cache inserts don't immediately error on write locks
(SPEC risk: SQLite write contention).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ..core.config import settings
from .base import Base

_is_sqlite = settings.database_url.startswith("sqlite")

_engine_kwargs: dict = {"echo": settings.debug and settings.env == "development", "future": True}
if _is_sqlite and ":memory:" in settings.database_url:
    # Tests: one shared in-memory connection.
    _engine_kwargs.update(poolclass=StaticPool, connect_args={"check_same_thread": False})

engine = create_async_engine(settings.database_url, **_engine_kwargs)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


if _is_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a session, commits on success, rolls back on error."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create tables if absent (dev/first-boot convenience; Alembic owns migrations in prod)."""
    settings.ensure_dirs()
    # Import models so they register on Base.metadata before create_all.
    from .. import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if _is_sqlite:
            await conn.execute(text("PRAGMA journal_mode=WAL"))

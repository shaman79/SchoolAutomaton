"""Async engine + session factory + FastAPI dependency, with SQLite tuned for concurrency.

SQLite is single-writer; we enable WAL + busy_timeout + foreign_keys on every connection so
concurrent generation, grading and asset-cache inserts don't immediately error on write locks
(SPEC risk: SQLite write contention).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ..core.config import settings
from .base import Base

logger = logging.getLogger("schoolautomaton.db")

_is_sqlite = settings.database_url.startswith("sqlite")

_engine_kwargs: dict = {"echo": settings.debug and settings.env == "development", "future": True}
if _is_sqlite and ":memory:" in settings.database_url:
    # Tests: one shared in-memory connection.
    _engine_kwargs.update(poolclass=StaticPool, connect_args={"check_same_thread": False})
elif _is_sqlite:
    # SQLite connections are cheap (WAL: many readers, one writer), and the default 5 + 10 ran out
    # when a classroom was waiting on slow work at once — every other request then failed after the
    # pool timeout. Long waits release their connection anyway (see the generators); this is headroom.
    _engine_kwargs.update(pool_size=10, max_overflow=40)

engine = create_async_engine(settings.database_url, **_engine_kwargs)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


if _is_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        # A write waits up to 30s for SQLite's single write lock before "database is locked". Writes
        # hold it for milliseconds (no provider call ever runs inside a write — see the generators),
        # but a classroom's worth of answers + progress saves arriving at once queue behind each
        # other, and at 5s the tail of that queue failed: a save that takes a moment beats an error.
        cur.execute("PRAGMA busy_timeout=30000")
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


# Additive SQLite migrations (no Alembic in this deployment): (table, column, ADD COLUMN DDL).
# create_all builds these on a fresh DB; for an EXISTING DB we add any missing column in place so
# upgrades never require wiping the volume (and the learner's resume code + history survive).
_ADDITIVE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("lessons", "plan_json", "ALTER TABLE lessons ADD COLUMN plan_json JSON"),
    (
        "lesson_sections",
        "gen_status",
        "ALTER TABLE lesson_sections ADD COLUMN gen_status VARCHAR(12) NOT NULL DEFAULT 'ready'",
    ),
    # Education-system locale (nullable → existing rows are generic): generated-content region.
    ("lessons", "education_locale", "ALTER TABLE lessons ADD COLUMN education_locale VARCHAR(12)"),
    ("quizzes", "education_locale", "ALTER TABLE quizzes ADD COLUMN education_locale VARCHAR(12)"),
    (
        "profile_settings",
        "education_locale",
        "ALTER TABLE profile_settings ADD COLUMN education_locale VARCHAR(12)",
    ),
    # Exact school year (nullable → existing rows fall back to the coarse grade band).
    ("lessons", "school_year", "ALTER TABLE lessons ADD COLUMN school_year INTEGER"),
    ("quizzes", "school_year", "ALTER TABLE quizzes ADD COLUMN school_year INTEGER"),
    ("profile_settings", "school_year", "ALTER TABLE profile_settings ADD COLUMN school_year INTEGER"),
    # Resume-where-you-left-off: the learner's position inside an open quiz attempt.
    (
        "quiz_attempts",
        "current_index",
        "ALTER TABLE quiz_attempts ADD COLUMN current_index INTEGER NOT NULL DEFAULT 0",
    ),
    ("quiz_attempts", "last_active_at", "ALTER TABLE quiz_attempts ADD COLUMN last_active_at DATETIME"),
    # Why a generation failed (busy | unavailable | budget | failed), for the loading screen.
    ("learning_requests", "error_code", "ALTER TABLE learning_requests ADD COLUMN error_code VARCHAR(16)"),
)

# Before the unique (attempt, item) answer index can be built on a database that predates it, drop
# the extra copies a double-tap race could store then (the first answer is the one that counted).
_DEDUPE_ATTEMPT_ANSWERS = """
DELETE FROM answers
WHERE attempt_id IS NOT NULL
  AND id NOT IN (
    SELECT MIN(id) FROM answers WHERE attempt_id IS NOT NULL GROUP BY attempt_id, item_id
  )
"""


async def _ensure_sqlite_columns(conn) -> None:
    for table, column, ddl in _ADDITIVE_COLUMNS:
        rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).all()
        if rows and column not in {r[1] for r in rows}:  # table exists but lacks the column
            await conn.execute(text(ddl))


async def _ensure_sqlite_indexes(conn) -> None:
    """create_all builds whole tables, but not an index added later to a table that already exists —
    so an upgraded database silently lacked e.g. the unique (attempt, item) answer index that stops a
    double-tapped answer from counting twice. Create any missing index in place."""
    exists = (
        await conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='index' AND name='uq_answer_attempt_item'")
        )
    ).first()
    answers = (
        await conn.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='answers'"))
    ).first()
    if answers and not exists:
        removed = (await conn.execute(text(_DEDUPE_ATTEMPT_ANSWERS))).rowcount
        if removed:
            logger.warning("Removed %s duplicate quiz answer(s) before indexing", removed)

    def _create(sync_conn) -> None:  # noqa: ANN001
        for table in Base.metadata.sorted_tables:
            for index in table.indexes:
                # One that can't be built must not keep the app from starting (a missing index
                # costs speed or a backstop; a backend that won't boot costs every child their
                # lessons): log it and carry on.
                try:
                    with sync_conn.begin_nested():
                        index.create(sync_conn, checkfirst=True)
                except Exception:  # noqa: BLE001
                    logger.exception("Could not create index %s; continuing without it", index.name)

    await conn.run_sync(_create)


async def init_db() -> None:
    """Create tables if absent (dev/first-boot convenience; Alembic owns migrations in prod)."""
    settings.ensure_dirs()
    # Import models so they register on Base.metadata before create_all.
    from .. import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if _is_sqlite:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await _ensure_sqlite_columns(conn)
            await _ensure_sqlite_indexes(conn)

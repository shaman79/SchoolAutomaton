"""Upgrading an existing database in place: create_all adds whole tables but never an index added to
a table that already exists, so a production database created before the unique (attempt, item)
answer index silently lacked it — and a double-tapped quiz answer could still count twice there."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  (register tables)
from app.db.base import Base
from app.db.session import _ensure_sqlite_columns, _ensure_sqlite_indexes


async def _indexes(conn) -> set[str]:
    rows = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))
    return {r[0] for r in rows}


_ANSWER = (
    "INSERT INTO answers (attempt_id, profile_id, item_id, submitted_value_json, is_correct, "
    "partial_credit, used_hint, is_first_try, fsrs_rating, xp_awarded, mastery_delta, created_at) "
    "VALUES (:a, 1, :i, '\"x\"', 1, 1.0, 0, 1, 3, 10, 0.0, '2026-10-01 10:00:00')"
)


@pytest.mark.asyncio
async def test_missing_indexes_are_added_and_duplicate_answers_dropped(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'old.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # An "old" database: built before these indexes existed...
            await conn.execute(text("DROP INDEX uq_answer_attempt_item"))
            await conn.execute(text("DROP INDEX ix_learning_requests_profile_id"))
            await conn.execute(text("ALTER TABLE learning_requests DROP COLUMN error_code"))
            # ...holding a double-tapped quiz answer (same attempt + item twice), plus lesson
            # practice answers (no attempt) that legitimately repeat.
            for attempt, item in [(7, 1), (7, 1), (7, 2), (None, 3), (None, 3)]:
                await conn.execute(text(_ANSWER), {"a": attempt, "i": item})

        async with engine.begin() as conn:
            await _ensure_sqlite_columns(conn)
            await _ensure_sqlite_indexes(conn)

        async with engine.begin() as conn:
            assert {"uq_answer_attempt_item", "ix_learning_requests_profile_id"} <= await _indexes(
                conn
            )
            cols = {r[1] for r in await conn.execute(text("PRAGMA table_info(learning_requests)"))}
            assert "error_code" in cols
            rows = (
                await conn.execute(text("SELECT attempt_id, item_id FROM answers ORDER BY id"))
            ).all()
            assert rows == [(7, 1), (7, 2), (None, 3), (None, 3)]  # first copy kept
            with pytest.raises(Exception, match="UNIQUE"):
                await conn.execute(text(_ANSWER), {"a": 7, "i": 2})

        # Running it again at the next start is a no-op.
        async with engine.begin() as conn:
            await _ensure_sqlite_indexes(conn)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_an_index_that_cannot_be_built_does_not_stop_the_app(tmp_path, caplog):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'odd.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text("DROP INDEX ix_learning_requests_profile_id"))
            # Something unexpected on a real database: the index name is taken by a TABLE.
            await conn.execute(text("CREATE TABLE ix_learning_requests_profile_id (x INTEGER)"))
        async with engine.begin() as conn:
            await _ensure_sqlite_indexes(conn)  # must not raise
        assert "ix_learning_requests_profile_id" in caplog.text
        async with engine.begin() as conn:
            assert "uq_answer_attempt_item" in await _indexes(conn)  # the others still built
    finally:
        await engine.dispose()

"""A lesson part's pictures: drawn side by side within the time budget, each failure on its own.

On a real (file) database, because the pictures now run in parallel sessions — the shared in-memory
test connection can't show how concurrent sessions behave. Production finding (Nov 2026): with Opus
5.5 a detailed diagram takes ~40-55 s; drawn one after another, a part's second diagram overran the
75 s budget and silently disappeared."""

from __future__ import annotations

import os

os.environ.setdefault("SA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("APP_SECRET", "test-secret-please-ignore")
os.environ.setdefault("SA_ENV", "test")

import asyncio  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import event, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

import app.visuals as visuals_mod  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db import session as session_mod  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.llm import lesson_generator  # noqa: E402
from app.models import Lesson, LessonSection, SectionVisual, VisualAsset  # noqa: E402
from app.schemas.enums import VisualKind  # noqa: E402
from app.schemas.generation import GenVisualSpec  # noqa: E402


@pytest_asyncio.fixture
async def real_db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'visuals.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _pragmas(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(session_mod, "SessionLocal", maker)
    monkeypatch.setattr(settings, "per_visual_timeout_s", 5.0)
    monkeypatch.setattr(settings, "visual_phase_budget_s", 5.0)
    yield maker
    await engine.dispose()


async def _part_with_pictures(maker, n: int) -> int:
    async with maker() as db:
        lesson = Lesson(request_id="r", topic="koloběh vody", detected_language="cs", grade_band="G3-5",
                        subject="science", target_fkgl=5.0, objectives_json=[], model_id="m",
                        prompt_version="v")
        db.add(lesson)
        await db.flush()
        part = LessonSection(lesson_id=lesson.id, ordinal=0, kind="explanation", title="Voda",
                             body_markdown="Voda koluje.", gen_status="ready")
        db.add(part)
        await db.flush()
        for i in range(n):
            spec = GenVisualSpec(section_ordinal=0, visual_kind=VisualKind.DIAGRAM, alt_text=f"obrázek {i}",
                                 svg_request=f"nakresli {i}")
            db.add(SectionVisual(lesson_section_id=part.id, ordinal=i, visual_kind="diagram",
                                 layout_slot="INLINE_FIGURE", alt_text=spec.alt_text,
                                 spec_json=spec.model_dump(mode="json"), status="pending"))
        await db.commit()
        return part.id


def _fake_pictures(delays: list[float], fail: frozenset[int] = frozenset()):
    """ensure_visual stand-in: picture i takes delays[i] seconds; the ones in ``fail`` raise."""
    async def ensure(session, spec, *, language, grade_band, usage_sink=None):  # noqa: ANN001
        i = int(spec.alt_text.split()[-1])
        await asyncio.sleep(delays[i])
        if i in fail:
            raise RuntimeError("provider down")
        asset = VisualAsset(hash=f"h{i}", asset_type="svg", model="claude", params_json={}, prompt="p",
                            mime="image/svg+xml", svg_inline="<svg/>")
        session.add(asset)
        await session.flush()
        return asset
    return ensure


async def _statuses(maker, part_id: int) -> list[tuple[str, str | None]]:
    async with maker() as db:
        rows = await db.scalars(
            select(SectionVisual).where(SectionVisual.lesson_section_id == part_id).order_by(SectionVisual.ordinal)
        )
        return [(sv.status, sv.visual_asset_hash) for sv in rows]


@pytest.mark.asyncio
async def test_a_parts_pictures_are_drawn_side_by_side(real_db, monkeypatch):
    part = await _part_with_pictures(real_db, 2)
    monkeypatch.setattr(visuals_mod, "ensure_visual", _fake_pictures([0.4, 0.4]))
    started = time.monotonic()
    await lesson_generator.realize_section_visuals(part)
    assert time.monotonic() - started < 0.7  # one after another would take 0.8 s
    assert await _statuses(real_db, part) == [("ready", "h0"), ("ready", "h1")]


@pytest.mark.asyncio
async def test_one_failing_picture_does_not_take_the_other_down(real_db, monkeypatch):
    part = await _part_with_pictures(real_db, 2)
    monkeypatch.setattr(visuals_mod, "ensure_visual", _fake_pictures([0.05, 0.1], fail={0}))
    await lesson_generator.realize_section_visuals(part)
    assert await _statuses(real_db, part) == [("failed", None), ("ready", "h1")]


@pytest.mark.asyncio
async def test_the_parts_budget_still_caps_pictures_waiting_their_turn(real_db, monkeypatch):
    """With one picture at a time and a 0.5 s budget: the first (0.3 s) is drawn, the second gets only
    what is left of the budget and times out, the third never starts."""
    part = await _part_with_pictures(real_db, 3)
    monkeypatch.setattr(lesson_generator, "_SECTION_VISUAL_CONCURRENCY", 1)
    monkeypatch.setattr(settings, "visual_phase_budget_s", 0.5)
    monkeypatch.setattr(visuals_mod, "ensure_visual", _fake_pictures([0.3, 0.3, 0.3]))
    await lesson_generator.realize_section_visuals(part)
    assert await _statuses(real_db, part) == [("ready", "h0"), ("failed", None), ("failed", None)]


@pytest.mark.asyncio
async def test_at_most_a_few_pictures_of_a_part_run_at_once(real_db, monkeypatch):
    part = await _part_with_pictures(real_db, 3)
    monkeypatch.setattr(lesson_generator, "_SECTION_VISUAL_CONCURRENCY", 2)
    now = {"running": 0, "peak": 0}

    async def ensure(session, spec, *, language, grade_band, usage_sink=None):  # noqa: ANN001
        now["running"] += 1
        now["peak"] = max(now["peak"], now["running"])
        await asyncio.sleep(0.1)
        now["running"] -= 1
        i = int(spec.alt_text.split()[-1])
        asset = VisualAsset(hash=f"h{i}", asset_type="svg", model="claude", params_json={}, prompt="p",
                            mime="image/svg+xml", svg_inline="<svg/>")
        session.add(asset)
        await session.flush()
        return asset

    monkeypatch.setattr(visuals_mod, "ensure_visual", ensure)
    await lesson_generator.realize_section_visuals(part)
    assert now["peak"] == 2
    assert [s for s, _ in await _statuses(real_db, part)] == ["ready"] * 3


def test_limits_leave_room_for_a_detailed_diagram():
    """Measured on production diagrams with Opus 5.5 (medium effort): up to ~55 s each."""
    from app.core.config import Settings

    defaults = Settings.model_fields
    assert defaults["per_visual_timeout_s"].default >= 90
    assert defaults["visual_phase_budget_s"].default >= defaults["per_visual_timeout_s"].default

"""Lesson delivery for the LessonReader, incl. on-demand (lazy) section generation."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....llm.lesson_generator import generate_one_section
from ....models import LearningRequest, Lesson, LessonSection
from ....sanitization.ratelimit import rate_limit_dependency
from ....schemas.content import LessonPublic, LessonSectionPublic
from ....schemas.intent import StructuredIntent
from ...deps import get_db
from ..serializers import lesson_public, lesson_section_public

router = APIRouter(prefix="/lessons", tags=["lessons"])
logger = logging.getLogger("schoolautomaton.generation")

# Per-lesson in-process locks so two concurrent "generate section" calls don't double-spend tokens.
_section_locks: dict[int, asyncio.Lock] = {}


@router.get("/{lesson_id}", response_model=LessonPublic)
async def get_lesson(lesson_id: int, db: AsyncSession = Depends(get_db)):
    lesson = await db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    return await lesson_public(db, lesson)


@router.post(
    "/{lesson_id}/sections/{ordinal}/generate",
    response_model=LessonSectionPublic,
    # Rate-limited: on-demand section fill drives paid Opus generation, so an anonymous caller must
    # not be able to spam it across arbitrary lesson ids (cost-amplification).
    dependencies=[Depends(rate_limit_dependency)],
)
async def generate_section(
    lesson_id: int, ordinal: int, db: AsyncSession = Depends(get_db)
):
    """Generate (or return, if already built) the lesson section at ``ordinal``.

    Progressive generation: the lesson is delivered with only its first section filled; the reader
    calls this as the learner advances. Idempotent — a ready section is returned as-is."""
    lesson = await db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    section = await db.scalar(
        select(LessonSection).where(
            LessonSection.lesson_id == lesson_id, LessonSection.ordinal == ordinal
        )
    )
    if section is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Section not found")
    if section.gen_status == "ready" and section.body_markdown is not None:
        return await lesson_section_public(db, section)

    lock = _section_locks.setdefault(lesson_id, asyncio.Lock())
    async with lock:
        await db.refresh(section)
        if section.gen_status == "ready" and section.body_markdown is not None:
            return await lesson_section_public(db, section)

        request = await db.scalar(
            select(LearningRequest).where(LearningRequest.request_id == lesson.request_id)
        )
        if request is None or not request.structured_intent_json:
            raise HTTPException(status.HTTP_409_CONFLICT, "Lesson is missing its generation context.")
        intent = StructuredIntent.model_validate(request.structured_intent_json)

        try:
            await generate_one_section(db, lesson, intent, ordinal)
            await db.commit()
        except Exception:  # noqa: BLE001 — surface a clean error; mark the section errored
            logger.exception("On-demand section generation failed (lesson=%s ordinal=%s)",
                             lesson_id, ordinal)
            try:
                await db.rollback()
                errored = await db.scalar(
                    select(LessonSection).where(
                        LessonSection.lesson_id == lesson_id, LessonSection.ordinal == ordinal
                    )
                )
                if errored is not None:
                    errored.gen_status = "error"
                    await db.commit()
            except Exception:  # noqa: BLE001 — best-effort; the 503 below must still be returned
                logger.exception("Failed to mark section errored (lesson=%s ordinal=%s)",
                                 lesson_id, ordinal)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Couldn't prepare the next part just now. Please try again in a moment.",
            ) from None

    await db.refresh(section)
    return await lesson_section_public(db, section)

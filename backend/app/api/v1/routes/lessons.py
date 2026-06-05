"""Lesson delivery for the LessonReader."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Lesson
from ....schemas.content import LessonPublic
from ...deps import get_db
from ..serializers import lesson_public

router = APIRouter(prefix="/lessons", tags=["lessons"])


@router.get("/{lesson_id}", response_model=LessonPublic)
async def get_lesson(lesson_id: int, db: AsyncSession = Depends(get_db)):
    lesson = await db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    return await lesson_public(db, lesson)

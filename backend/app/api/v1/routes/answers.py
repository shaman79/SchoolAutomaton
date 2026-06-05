"""Unified grading endpoint — grades one answer and applies all reward/scheduling side-effects."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Item, Profile
from ....schemas.gamification import GradeResult
from ....schemas.questions import AnswerIn
from ....services import gamification
from ...deps import get_db, get_profile

router = APIRouter(tags=["answers"])


@router.post("/answers", response_model=GradeResult)
async def submit_answer(
    body: AnswerIn, profile: Profile = Depends(get_profile), db: AsyncSession = Depends(get_db)
):
    item = await db.get(Item, body.item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    return await gamification.grade_and_reward(db, profile, item, body, body.attempt_id)

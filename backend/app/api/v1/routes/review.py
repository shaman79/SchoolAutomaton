"""Spaced-repetition review: the FSRS-due interleaved session + direct rating submission."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Item, Profile
from ....schemas.gamification import GradeResult, ReviewDueResponse, ReviewRatingIn
from ....schemas.questions import AnswerIn
from ....services import gamification, interleave
from ...deps import get_db, get_profile
from ..serializers import item_public

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/due", response_model=ReviewDueResponse)
async def get_due(
    limit: int | None = Query(default=None, ge=1, le=100),
    subject: str | None = Query(default=None),
    profile: Profile = Depends(get_profile),
    db: AsyncSession = Depends(get_db),
):
    items, composition = await interleave.build_review_session(db, profile, limit, subject)
    public = [await item_public(db, it) for it in items]
    return ReviewDueResponse(items=public, composition=composition)


@router.post("/{item_id}", response_model=GradeResult)
async def review_item(
    item_id: int,
    body: ReviewRatingIn,
    profile: Profile = Depends(get_profile),
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(Item, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    # Rating-only path: an explicit FSRS self-rating (1..4) with no answer value advances the card
    # by that rating instead of grading None as wrong (schema/api advertise this capability).
    if body.rating is not None and body.submitted_value is None:
        return await gamification.review_with_rating(
            db,
            profile,
            item,
            body.rating,
            used_hint=body.used_hint,
            latency_ms=body.latency_ms,
        )
    answer = AnswerIn(
        item_id=item_id,
        attempt_id=None,
        submitted_value=body.submitted_value,
        used_hint=body.used_hint,
        latency_ms=body.latency_ms,
    )
    return await gamification.grade_and_reward(db, profile, item, answer, None)

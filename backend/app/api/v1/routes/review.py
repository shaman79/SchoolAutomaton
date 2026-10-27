"""Spaced-repetition review: the FSRS-due interleaved session + direct rating submission."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Answer, Item, ItemFsrsCard, Profile
from ....sanitization import ratelimit
from ....schemas.gamification import GradeResult, ReviewDueResponse, ReviewRatingIn
from ....schemas.questions import AnswerIn
from ....services import gamification, interleave
from ...deps import client_ip_hash, get_db, get_profile
from ..serializers import item_public

router = APIRouter(prefix="/review", tags=["review"])

_NOT_DUE = "This item isn't due for review yet."


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
    request: Request,
    profile: Profile = Depends(get_profile),
    db: AsyncSession = Depends(get_db),
):
    """Review one item the learner has ALREADY been graded on (what ``GET /review/due`` hands out:
    items with an FSRS card of theirs), and only while it is due.

    * 404 — no such item, or this learner has never been graded on it. Anything else would reveal
      ``correct_answer``/``explanation`` of items they never answered (e.g. a quiz they are sitting
      right now) and pay XP for them.
    * 409 — the card isn't due (yet / any more). Each due review is rewarded once; repeating it, or
      firing copies of it in parallel, can't farm XP. The review flow only ever submits due items.
    * 429 — per-learner answer rate limits (tighter for AI-graded free text)."""
    ratelimit.check_answer_rate(profile.id)
    item = await db.get(Item, item_id)
    card = None
    if item is not None:
        card = await db.scalar(
            select(ItemFsrsCard).where(
                ItemFsrsCard.profile_id == profile.id, ItemFsrsCard.item_id == item_id
            )
        )
    graded_before = card is not None and (
        await db.scalar(
            select(Answer.id)
            .where(Answer.profile_id == profile.id, Answer.item_id == item_id)
            .limit(1)
        )
    ) is not None
    if not graded_before:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    if not gamification.card_is_due(card, datetime.now(UTC)):
        raise HTTPException(status.HTTP_409_CONFLICT, _NOT_DUE)

    try:
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
                only_if_due=True,
            )
        if gamification.uses_llm_grader(item, body.submitted_value):
            ratelimit.check_llm_grading_rate(profile.id, client_ip_hash(request))
        answer = AnswerIn(
            item_id=item_id,
            attempt_id=None,
            submitted_value=body.submitted_value,
            used_hint=body.used_hint,
            latency_ms=body.latency_ms,
        )
        return await gamification.grade_and_reward(
            db, profile, item, answer, None, only_if_due=True
        )
    except gamification.CardNotDue:
        # A parallel copy of this review was applied first; keep nothing of this one.
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, _NOT_DUE) from None

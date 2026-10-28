"""Mastery end to end through grading: a wrong answer never makes a topic "mastered" (it used to, with
4 mastery badges and then 0 XP for the topic's correct answers), and "mastered" needs correct answers
on two different days."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.constants import MASTERY_MASTERED_THRESHOLD
from app.models import SkillMastery
from app.schemas.enums import NodeState
from app.schemas.questions import AnswerIn
from app.services import gamification
from tests.test_gamification import _make_concept, _make_item, _make_profile, db  # noqa: F401

MCQ = {
    "kind": "mcq",
    "options": [{"id": "a", "text": "A", "is_correct": True}, {"id": "b", "text": "B"}],
}
DAY1 = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)


async def _answer(db, profile, item, value, now):  # noqa: F811
    return await gamification.grade_and_reward(
        db, profile, item, AnswerIn(item_id=item.id, submitted_value=value), None, now=now
    )


async def _mastery(db, profile) -> SkillMastery:  # noqa: F811
    return await db.scalar(select(SkillMastery).where(SkillMastery.profile_id == profile.id))


@pytest.mark.asyncio
async def test_a_wrong_answer_does_not_master_the_topic(db):  # noqa: F811
    p = await _make_profile(db)
    c = await _make_concept(db)
    it = await _make_item(db, c.id, "mcq", MCQ)
    res = await _answer(db, p, it, "b", DAY1)
    sm = await _mastery(db, p)
    assert not res.is_correct
    assert sm.mastery < MASTERY_MASTERED_THRESHOLD
    assert sm.node_state != NodeState.MASTERED.value
    assert not [b for b in res.new_badges if "master" in b.code]


@pytest.mark.asyncio
async def test_correct_answers_after_a_wrong_one_still_earn_xp(db):  # noqa: F811
    p = await _make_profile(db)
    c = await _make_concept(db)
    a = await _make_item(db, c.id, "mcq", MCQ)
    b = await _make_item(db, c.id, "mcq", MCQ)
    await _answer(db, p, a, "b", DAY1)
    again = await _answer(db, p, a, "a", DAY1 + timedelta(minutes=2))
    other = await _answer(db, p, b, "a", DAY1 + timedelta(minutes=3))
    assert again.xp_awarded > 0 and other.xp_awarded > 0


@pytest.mark.asyncio
async def test_mastered_only_after_correct_answers_on_two_days(db):  # noqa: F811
    p = await _make_profile(db)
    c = await _make_concept(db)
    items = [await _make_item(db, c.id, "mcq", MCQ) for _ in range(3)]
    # Day 1: everything right, several times — still not "mastered".
    for i, it in enumerate(items * 2):
        await _answer(db, p, it, "a", DAY1 + timedelta(minutes=i))
    assert (await _mastery(db, p)).mastery < MASTERY_MASTERED_THRESHOLD
    # Day 2: right again — now it is (the cards are still fresh).
    res = await _answer(db, p, items[0], "a", DAY1 + timedelta(days=1))
    sm = await _mastery(db, p)
    assert sm.mastery >= MASTERY_MASTERED_THRESHOLD
    assert sm.node_state == NodeState.MASTERED.value
    assert res.mastery_delta > 0


@pytest.mark.asyncio
async def test_wrong_answers_on_day_two_do_not_count_as_evidence(db):  # noqa: F811
    p = await _make_profile(db)
    c = await _make_concept(db)
    it = await _make_item(db, c.id, "mcq", MCQ)
    await _answer(db, p, it, "a", DAY1)
    await _answer(db, p, it, "a", DAY1 + timedelta(minutes=5))
    await _answer(db, p, it, "b", DAY1 + timedelta(days=1))
    assert (await _mastery(db, p)).mastery < MASTERY_MASTERED_THRESHOLD

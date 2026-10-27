"""Answer/review abuse guards (security review).

* POST /review/{id} only for items THIS learner was already graded on (else 404 — it used to hand
  out any quiz item's answer key + explanation, and XP, to anyone), and only while due (else 409 —
  repeating a review used to pay XP every time).
* Answer values are size-bounded (422) and answer submissions are rate limited per learner (429)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import (
    Answer,
    Concept,
    Item,
    ItemFsrsCard,
    LessonSection,
    Profile,
    ProfileSettings,
    StreakState,
)
from app.schemas.questions import AnswerIn
from app.services import gamification
from tests.test_progress_resume import _new_profile, _seed_lesson, _seed_quiz

API = "/api/v1"


async def _xp(pid: int) -> int:
    async with SessionLocal() as db:
        return await db.scalar(select(Profile.total_xp).where(Profile.id == pid))


async def _make_due(pid: int, item_id: int) -> None:
    async with SessionLocal() as db:
        await db.execute(
            update(ItemFsrsCard)
            .where(ItemFsrsCard.profile_id == pid, ItemFsrsCard.item_id == item_id)
            .values(due=datetime.now(UTC) - timedelta(days=1))
        )
        await db.commit()


async def _seed_free_text_item(lesson_id: int) -> int:
    async with SessionLocal() as db:
        sec = await db.scalar(select(LessonSection).where(LessonSection.lesson_id == lesson_id))
        concept = await db.scalar(select(Concept))
        it = Item(concept_id=concept.id, lesson_section_id=sec.id, item_type="short_answer",
                  bloom_tier=2, difficulty="medium", item_difficulty=3, language="en",
                  stem_markdown="What do plants make?", explanation="Sugar.",
                  expected_answer="glucose", model_id="m", prompt_version="v",
                  payload_json={"kind": "short_answer"})
        db.add(it)
        await db.commit()
        return it.id


# --------------------------------------------------------------------------- POST /review/{id}
async def test_review_does_not_leak_answer_keys_of_items_never_answered(client):
    victim, victim_pid = await _new_profile(client)
    quiz_id, item_ids = await _seed_quiz("victim-quiz", victim_pid, n=3)
    attacker, attacker_pid = await _new_profile(client)

    for iid in item_ids:
        for body in ({"rating": 4}, {"submitted_value": "zzz"}):
            r = await client.post(f"{API}/review/{iid}", headers=attacker, json=body)
            assert r.status_code == 404, r.text
            assert "correct_answer" not in r.text and "Because." not in r.text
    assert await _xp(attacker_pid) == 0  # no XP for items never answered

    # Mid-quiz peek at a question of the learner's OWN open attempt: refused too.
    r = await client.post(f"{API}/quizzes/{quiz_id}/attempts", headers=victim, json={})
    assert r.status_code == 201
    r = await client.post(f"{API}/review/{item_ids[1]}", headers=victim, json={"submitted_value": "zzz"})
    assert r.status_code == 404
    r = await client.post(f"{API}/review/{item_ids[1]}", headers=victim, json={"rating": 1})
    assert r.status_code == 404
    # Unknown ids look the same.
    assert (await client.post(f"{API}/review/999999", headers=victim, json={"rating": 3})).status_code == 404


async def test_review_of_a_due_item_works_once_and_cannot_be_farmed(client):
    headers, pid = await _new_profile(client)
    _lesson_id, item_id = await _seed_lesson("rev-lesson", pid)
    r = await client.post(f"{API}/answers", headers=headers, json={"item_id": item_id, "submitted_value": "a"})
    assert r.status_code == 200

    # Just answered: the card is scheduled into the future, so it isn't reviewable yet.
    r = await client.post(f"{API}/review/{item_id}", headers=headers, json={"rating": 4})
    assert r.status_code == 409

    # Once due, it is in the review session and reviewing it works (and reveals the answer — the
    # learner has been graded on it before).
    await _make_due(pid, item_id)
    due = (await client.get(f"{API}/review/due", headers=headers)).json()["items"]
    assert [it["id"] for it in due] == [item_id]
    xp_before = await _xp(pid)
    r = await client.post(f"{API}/review/{item_id}", headers=headers, json={"submitted_value": "a"})
    assert r.status_code == 200, r.text
    assert r.json()["correct_answer"] == "a"
    xp_after = await _xp(pid)

    # Repeating it — graded or self-rated — is refused and pays nothing.
    for body in ({"submitted_value": "a"}, {"rating": 4}, {"rating": 4}):
        r = await client.post(f"{API}/review/{item_id}", headers=headers, json=body)
        assert r.status_code == 409
    assert await _xp(pid) == xp_after >= xp_before
    async with SessionLocal() as db:
        n = await db.scalar(select(func.count()).select_from(Answer).where(Answer.profile_id == pid))
    assert n == 2  # the lesson answer + the one due review


async def test_rating_only_review_of_a_due_item_still_works(client):
    headers, pid = await _new_profile(client)
    _lesson_id, item_id = await _seed_lesson("rate-lesson", pid)
    await client.post(f"{API}/answers", headers=headers, json={"item_id": item_id, "submitted_value": "a"})
    await _make_due(pid, item_id)
    r = await client.post(f"{API}/review/{item_id}", headers=headers, json={"rating": 3})
    assert r.status_code == 200
    assert r.json()["fsrs_rating"] == 3


@pytest.fixture
async def file_session_factory(tmp_path):
    """A real file-backed SQLite (WAL) with a normal pool: separate sessions are really separate."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'race.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _seed_answered_item(sm) -> tuple[int, int]:
    async with sm() as db:
        p = Profile(resume_code_hash="r" * 16, primary_language="en")
        db.add(p)
        await db.flush()
        db.add_all([ProfileSettings(profile_id=p.id), StreakState(profile_id=p.id)])
        c = Concept(slug="c", name="C", subject="science")
        db.add(c)
        await db.flush()
        it = Item(concept_id=c.id, item_type="true_false", bloom_tier=2, difficulty="medium",
                  item_difficulty=3, language="en", stem_markdown="Q", explanation="E",
                  model_id="m", prompt_version="v", payload_json={"kind": "true_false", "answer": True})
        db.add(it)
        await db.flush()
        past = datetime.now(UTC) - timedelta(days=2)
        await gamification.grade_and_reward(
            db, p, it, AnswerIn(item_id=it.id, submitted_value=True, latency_ms=3000), None, past
        )
        await db.execute(update(ItemFsrsCard).values(due=past))  # due again now
        await db.commit()
        return p.id, it.id


async def test_parallel_copies_of_one_review_award_once(file_session_factory):
    """Two copies of one due review both pass the route's due check (both read the card while due);
    the conditional claim at write time lets exactly one through."""
    sm = file_session_factory
    pid, item_id = await _seed_answered_item(sm)
    a, b = sm(), sm()
    try:
        loaded = []
        for db in (a, b):
            prof = await db.get(Profile, pid)
            item = await db.get(Item, item_id)
            card = await db.scalar(select(ItemFsrsCard).where(ItemFsrsCard.item_id == item_id))
            assert gamification.card_is_due(card, datetime.now(UTC))
            loaded.append((prof, item))
            await db.commit()  # end the read; B now holds a stale view of the card

        ans = AnswerIn(item_id=item_id, submitted_value=True, latency_ms=3000)
        first = await gamification.grade_and_reward(a, *loaded[0], ans, None, only_if_due=True)
        await a.commit()
        assert first.xp_awarded >= 0
        with pytest.raises(gamification.CardNotDue):
            await gamification.grade_and_reward(b, *loaded[1], ans, None, only_if_due=True)
        await b.rollback()
    finally:
        await a.close()
        await b.close()
    async with sm() as db:
        n = await db.scalar(select(func.count()).select_from(Answer).where(Answer.item_id == item_id))
        assert n == 2  # the original answer + ONE review


# --------------------------------------------------------------------------- answer size bounds
@pytest.mark.parametrize(
    "value",
    [
        "a " * 400_000,  # the 800 KB free-text answer from the review PoC
        "x" * 2001,
        ["y" * 1900] * 5,  # > 8 KB in total
        {"a": [[[[[[1]]]]]] * 1000},  # deep + wide
        ["t"] * 201,
    ],
)
async def test_oversized_answers_are_422(client, value):
    headers, pid = await _new_profile(client)
    _lesson_id, item_id = await _seed_lesson("big-lesson", pid)
    r = await client.post(f"{API}/answers", headers=headers, json={"item_id": item_id, "submitted_value": value})
    assert r.status_code == 422
    await client.post(f"{API}/answers", headers=headers, json={"item_id": item_id, "submitted_value": "a"})
    await _make_due(pid, item_id)
    r = await client.post(f"{API}/review/{item_id}", headers=headers, json={"submitted_value": value})
    assert r.status_code == 422


@pytest.mark.parametrize(
    "value",
    [
        "x" * 2000,
        ["a", "b"],
        {"b1": "photosynthesis", "b2": "chlorophyll"},
        [{"left_id": f"l{i}", "right_id": f"r{i}"} for i in range(12)],
        [f"tok{i}" for i in range(30)],
        42.5,
        True,
        None,
    ],
)
def test_normal_answer_shapes_are_accepted(value):
    assert AnswerIn(item_id=1, submitted_value=value).submitted_value == value


async def test_negative_review_latency_is_422_not_500(client):
    headers, _ = await _new_profile(client)
    r = await client.post(f"{API}/review/1", headers=headers, json={"submitted_value": "a", "latency_ms": -5})
    assert r.status_code == 422


# --------------------------------------------------------------------------- answer rate limits
async def test_answers_are_rate_limited_per_learner(client, monkeypatch):
    monkeypatch.setattr(settings, "answer_rate_per_min", 5)
    headers, pid = await _new_profile(client)
    other, _ = await _new_profile(client)
    _lesson_id, item_id = await _seed_lesson("rl-answers", pid)
    body = {"item_id": item_id, "submitted_value": "a"}
    for _ in range(5):
        assert (await client.post(f"{API}/answers", headers=headers, json=body)).status_code == 200
    r = await client.post(f"{API}/answers", headers=headers, json=body)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1
    # /review shares the learner's budget...
    assert (await client.post(f"{API}/review/{item_id}", headers=headers, json={"rating": 3})).status_code == 429
    # ...and a classmate on the same IP is unaffected.
    assert (await client.post(f"{API}/answers", headers=other, json=body)).status_code == 200


async def test_ai_graded_answers_have_a_tighter_limit(client, monkeypatch):
    from app.llm import grader
    from app.schemas.generation import GraderOutput

    calls = []

    async def fake_grade(item, submitted, language, **kw):
        calls.append(submitted)
        return GraderOutput(correct=True, partial_credit=1.0, explanation="ok")

    monkeypatch.setattr(grader, "grade_free_text", fake_grade)
    monkeypatch.setattr(settings, "answer_llm_rate_per_min", 2)
    headers, pid = await _new_profile(client)
    lesson_id, mcq_id = await _seed_lesson("rl-llm", pid)
    ft_id = await _seed_free_text_item(lesson_id)

    for _ in range(2):
        r = await client.post(f"{API}/answers", headers=headers, json={"item_id": ft_id, "submitted_value": "sugar"})
        assert r.status_code == 200
    r = await client.post(f"{API}/answers", headers=headers, json={"item_id": ft_id, "submitted_value": "sugar"})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    assert len(calls) == 2  # the refused one never reached the model
    # Deterministic items and blank free text (never sent to the model) are unaffected.
    assert (await client.post(f"{API}/answers", headers=headers, json={"item_id": mcq_id, "submitted_value": "a"})).status_code == 200
    assert (await client.post(f"{API}/answers", headers=headers, json={"item_id": ft_id, "submitted_value": "  "})).status_code == 200

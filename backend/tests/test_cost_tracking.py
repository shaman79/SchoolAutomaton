"""AI cost tracking + guards (security review).

* Every logged model call carries an estimated USD cost (one price table, ``core.pricing``); the
  admin dashboard used to show $0 because ``est_cost_usd`` was never written.
* The free-text grader's usage is logged — after the call returns, never staged during it.
* A global daily AI budget (``SA_DAILY_BUDGET_USD``): ``ensure_ai_budget`` → 503 ``daily_budget``;
  free-text grading falls back to deterministic grading instead.
* Grading releases its pooled DB connection while it waits for the model (a class answering free
  text at once used to exhaust the pool and stall every other request)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.pricing import estimate_cost_usd
from app.db.base import Base
from app.db.session import SessionLocal
from app.llm import client as client_mod
from app.llm import grader
from app.llm.client import Usage, usage_row
from app.models import Concept, GenerationUsage, Item, Profile, ProfileSettings, StreakState
from app.schemas.generation import GraderOutput
from app.schemas.questions import AnswerIn
from app.services import cost_guard, gamification

API = "/api/v1"


# --------------------------------------------------------------------------- pricing
def test_cost_estimate_uses_the_price_table():
    # Opus 4.8: $5 in, $6.25 5-min cache write, $0.50 cache read, $25 out — per million tokens.
    cost = estimate_cost_usd("claude-opus-4-8", input_tokens=1000, cache_creation_tokens=2000,
                             cache_read_tokens=10_000, output_tokens=500)
    assert cost == pytest.approx((1000 * 5 + 2000 * 6.25 + 10_000 * 0.5 + 500 * 25) / 1e6)
    # Haiku 4.5: $1 / $1.25 / $0.10 / $5; a dated snapshot id prices the same.
    assert estimate_cost_usd("claude-haiku-4-5", input_tokens=1_000_000) == pytest.approx(1.0)
    assert estimate_cost_usd("claude-haiku-4-5-20251001", output_tokens=1_000_000) == pytest.approx(5.0)
    assert estimate_cost_usd("claude-haiku-4-5", cache_read_tokens=1_000_000) == pytest.approx(0.10)


def test_unknown_model_cost_is_left_null():
    assert estimate_cost_usd("some-future-model", input_tokens=1000) is None
    row = usage_row(Usage(input_tokens=10, model="some-future-model"), request_id=None)
    assert row.est_cost_usd is None


def test_usage_rows_carry_the_cost():
    row = usage_row(
        Usage(input_tokens=120, cache_read_tokens=4096, output_tokens=300, model="claude-opus-4-8"),
        request_id="r",
    )
    assert row.est_cost_usd == pytest.approx((120 * 5 + 4096 * 0.5 + 300 * 25) / 1e6)


# --------------------------------------------------------------------------- grader usage logging
def _usage():
    return SimpleNamespace(input_tokens=120, cache_creation_input_tokens=0,
                           cache_read_input_tokens=4096, output_tokens=300)


def _parsed(obj):
    return SimpleNamespace(parsed_output=obj, stop_reason="end_turn", id="msg_1", usage=_usage(), content=[])


def _grader_client(*, observe=None, fail_first=False):
    """A mock AsyncAnthropic whose parse() returns a GraderOutput (optionally a bad first reply)."""
    calls = {"n": 0}

    async def _parse(**kwargs):
        calls["n"] += 1
        if observe is not None:
            observe(kwargs)
        if fail_first and calls["n"] == 1:
            return _parsed(None)  # no structured output → validation retry (still billed)
        return _parsed(GraderOutput(correct=True, partial_credit=1.0, explanation="Yes."))

    return SimpleNamespace(messages=SimpleNamespace(parse=AsyncMock(side_effect=_parse), create=AsyncMock()))


async def _seed(db: AsyncSession, item_type="short_answer", **kw) -> tuple[Profile, Item]:
    p = Profile(resume_code_hash=kw.pop("code_hash", "c" * 16), primary_language="en")
    db.add(p)
    await db.flush()
    db.add_all([ProfileSettings(profile_id=p.id, education_locale=kw.pop("education_locale", None)),
                StreakState(profile_id=p.id)])
    c = Concept(slug=kw.pop("slug", "photosynthesis"), name="Photosynthesis", subject="science")
    db.add(c)
    await db.flush()
    it = Item(concept_id=c.id, item_type=item_type, bloom_tier=2, difficulty="medium",
              item_difficulty=3, language="en", stem_markdown="What gas do plants release?",
              explanation="Oxygen.", expected_answer="oxygen", model_id="m", prompt_version="v",
              payload_json={"kind": item_type})
    db.add(it)
    await db.flush()
    return p, it


async def test_grader_logs_usage_after_the_call_never_during_it(client):
    async with SessionLocal() as db:
        staged_during_call = []
        cli = _grader_client(observe=lambda _kw: staged_during_call.append(list(db.new)), fail_first=True)
        item = SimpleNamespace(item_type="short_answer", stem_markdown="Q?", expected_answer="oxygen")
        out = await grader.grade_free_text(item, "oxygen", "en", client=cli, db=db, profile_id=None)
        assert out.correct is True
        assert staged_during_call == [[], []]  # nothing staged while either call was in flight
        rows = [o for o in db.new if isinstance(o, GenerationUsage)]
        assert len(rows) == 2  # the failed-validation attempt was billed too
        assert all(r.model == settings.model_id and r.est_cost_usd > 0 for r in rows)


async def test_free_text_grading_logs_cost_and_releases_the_connection(client):
    seen = {}
    async with SessionLocal() as db:
        profile, item = await _seed(db)

        def observe(_kw):
            seen["in_transaction"] = db.in_transaction()
            seen["pending"] = list(db.new) + list(db.dirty)

        client_mod.set_client(_grader_client(observe=observe))
        try:
            res = await gamification.grade_and_reward(
                db, profile, item, AnswerIn(item_id=item.id, submitted_value="oxygen", latency_ms=8000), None
            )
            await db.commit()
        finally:
            client_mod.set_client(None)
    assert res.is_correct is True
    assert seen == {"in_transaction": False, "pending": []}
    async with SessionLocal() as db:
        row = await db.scalar(select(GenerationUsage))
        assert row.profile_id == profile.id and row.est_cost_usd > 0
        # And the admin dashboard now shows real spend.
    tok = (await client.post(f"{API}/admin/auth/login",
                             json={"username": "admin", "password": "admin12345"})).json()["access_token"]
    dash = (await client.get(f"{API}/admin/dashboard", headers={"Authorization": f"Bearer {tok}"})).json()
    assert dash["anthropic_cost_usd"] > 0


async def test_grading_does_not_hold_a_pooled_connection_during_the_model_call(tmp_path, monkeypatch):
    """The reviewer's pool-exhaustion PoC, shrunk to a one-connection pool: while one answer waits
    for the grader, another request must still get a connection (it used to wait pool_timeout)."""
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'pool.db'}", pool_size=1, max_overflow=0, pool_timeout=2
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with sm() as db:
            profile, item = await _seed(db)
            await db.commit()

        async def slow_grader(item, submitted, language, **kw):
            async with sm() as other:  # "another request" needs the pool's only connection
                assert await asyncio.wait_for(other.scalar(select(func.count(Profile.id))), 5) == 1
            return GraderOutput(correct=True, partial_credit=1.0, explanation="ok")

        monkeypatch.setattr(grader, "grade_free_text", slow_grader)
        async with sm() as db:
            profile = await db.get(Profile, profile.id)
            item = await db.get(Item, item.id)
            res = await gamification.grade_and_reward(
                db, profile, item, AnswerIn(item_id=item.id, submitted_value="oxygen"), None
            )
            await db.commit()
        assert res.is_correct is True and res.explanation == "ok"
    finally:
        await engine.dispose()


async def test_answer_route_releases_the_connection_and_keeps_409_on_double_submit(client, monkeypatch):
    """Through the real route: the session is out of its transaction during the grader call, and a
    second copy of a quiz answer still gets 409 (the unique index; no second XP)."""
    from app.api.v1.routes import answers as answers_route
    from app.db.session import get_db
    from app.main import app
    from tests.test_progress_resume import _new_profile, _seed_quiz

    sessions = []

    async def tracking_get_db():
        async for s in get_db():
            sessions.append(s)
            yield s

    observed = []

    async def fake_grade(item, submitted, language, **kw):
        observed.append(sessions[-1].in_transaction())
        return GraderOutput(correct=True, partial_credit=1.0, explanation="ok")

    monkeypatch.setattr(grader, "grade_free_text", fake_grade)
    app.dependency_overrides[get_db] = tracking_get_db
    try:
        headers, pid = await _new_profile(client)
        quiz_id, item_ids = await _seed_quiz("ft-quiz", pid, n=1)
        async with SessionLocal() as db:
            it = await db.get(Item, item_ids[0])
            it.item_type = "short_answer"
            it.expected_answer = "a"
            it.payload_json = {"kind": "short_answer"}
            await db.commit()
        attempt = (await client.post(f"{API}/quizzes/{quiz_id}/attempts", headers=headers, json={})).json()
        body = {"item_id": item_ids[0], "attempt_id": attempt["attempt_id"], "submitted_value": "a"}
        assert (await client.post(f"{API}/answers", headers=headers, json=body)).status_code == 200
        assert observed == [False]
        assert (await client.post(f"{API}/answers", headers=headers, json=body)).status_code == 409
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert answers_route  # imported for clarity: the route under test


# --------------------------------------------------------------------------- daily budget
async def _spend(usd: float, when: datetime | None = None) -> None:
    async with SessionLocal() as db:
        row = GenerationUsage(provider="anthropic", model="claude-opus-4-8", est_cost_usd=usd)
        if when is not None:
            row.created_at = when
        db.add(row)
        await db.commit()


async def test_ensure_ai_budget_raises_503_once_todays_spend_hits_the_cap(client, monkeypatch):
    monkeypatch.setattr(settings, "daily_budget_usd", 100.0)
    await _spend(500.0, datetime.now(UTC) - timedelta(days=1))  # yesterday doesn't count
    await _spend(60.0)
    async with SessionLocal() as db:
        await cost_guard.ensure_ai_budget(db)  # 60 < 100
        assert await cost_guard.spent_today_usd(db) == pytest.approx(60.0)
    await _spend(40.0)
    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await cost_guard.ensure_ai_budget(db)
    assert exc.value.status_code == 503 and exc.value.detail == "daily_budget"

    monkeypatch.setattr(settings, "daily_budget_usd", 0.0)  # 0 disables the cap
    async with SessionLocal() as db:
        await cost_guard.ensure_ai_budget(db)


async def test_default_daily_budget_is_100_usd():
    assert settings.daily_budget_usd == 100.0


async def test_free_text_falls_back_to_deterministic_grading_when_over_budget(client, monkeypatch):
    monkeypatch.setattr(settings, "daily_budget_usd", 10.0)
    await _spend(10.0)
    called = []

    async def fake_grade(*a, **kw):
        called.append(1)
        return GraderOutput(correct=True, partial_credit=1.0, explanation="AI")

    monkeypatch.setattr(grader, "grade_free_text", fake_grade)
    async with SessionLocal() as db:
        profile, item = await _seed(db)
        right = await gamification.grade_and_reward(
            db, profile, item, AnswerIn(item_id=item.id, submitted_value=" Oxygen "), None
        )
        wrong = await gamification.grade_and_reward(
            db, profile, item, AnswerIn(item_id=item.id, submitted_value="it breathes out air"), None
        )
    assert called == []  # the model was never called
    assert right.is_correct is True and wrong.is_correct is False
    assert right.explanation == "Oxygen."  # the item's own explanation, not an AI one

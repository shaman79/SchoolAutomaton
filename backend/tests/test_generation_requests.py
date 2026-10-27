"""Starting a generation and reporting on it, as the loading screen sees it: one generation per
request however often "start" is sent, failures the screen can explain in the child's language, a
Retry that really retries, no pooled connection held by a waiting stream, and a health endpoint the
deploy script can wait on."""

from __future__ import annotations

import asyncio

import anthropic
import httpx
import pytest
from fastapi import BackgroundTasks, HTTPException
from fastapi.dependencies.models import Dependant
from sqlalchemy import select, update

from app.api.v1.routes import requests as req_routes
from app.core.tasks import task_registry
from app.db.session import SessionLocal, get_db
from app.llm.client import GenerationError
from app.models import LearningRequest
from app.sanitization import ratelimit
from app.schemas.enums import GradeBand, Mode, Subject
from app.schemas.intent import StructuredIntent

_INTENT = StructuredIntent(
    subject=Subject.SCIENCE, topic="photosynthesis", mode=Mode.STUDY, grade_band=GradeBand.G3_5,
    language="en",
).model_dump(mode="json")


async def _seed(request_id: str, status: str = "queued") -> None:
    async with SessionLocal() as db:
        db.add(
            LearningRequest(
                request_id=request_id, decision_type="proceed", mode="study",
                structured_intent_json=_INTENT, status=status, prompt_version="t", model_id="m",
            )
        )
        await db.commit()


async def _row(request_id: str) -> LearningRequest:
    async with SessionLocal() as db:
        return await db.scalar(
            select(LearningRequest).where(LearningRequest.request_id == request_id)
        )


@pytest.fixture(autouse=True)
def _fresh_limits():
    ratelimit.limiter.reset()


def _count_generations(monkeypatch, *, fail_with: BaseException | None = None) -> list[str]:
    calls: list[str] = []

    async def fake_run(request_id: str) -> None:
        calls.append(request_id)
        await asyncio.sleep(0)
        if fail_with is not None:
            raise fail_with

    monkeypatch.setattr(req_routes, "run_generation", fake_run)
    return calls


@pytest.mark.asyncio
async def test_start_twice_runs_one_generation(client, monkeypatch):
    """A double tap, a reload of the loading screen, or a Retry racing the first call each used to
    start another paid generation (9 of 10 concurrent calls did)."""
    calls = _count_generations(monkeypatch)
    await _seed("dup")
    for _ in range(3):
        resp = await client.post("/api/v1/requests/dup/generate")
        assert resp.status_code == 202
    assert resp.json()["status"] == "generating"
    assert calls == ["dup"]


@pytest.mark.asyncio
async def test_a_racing_start_that_read_queued_does_not_start_another(client, monkeypatch):
    """The race itself: the second call read 'queued' before the first one's claim committed. Its
    claim (a conditional UPDATE) then changes no row, so it starts nothing."""
    calls = _count_generations(monkeypatch)
    await _seed("race")
    async with SessionLocal() as late:
        stale = await late.scalar(
            select(LearningRequest).where(LearningRequest.request_id == "race")
        )
        assert stale.status == "queued"
        assert (await client.post("/api/v1/requests/race/generate")).status_code == 202
        background = BackgroundTasks()
        out = await req_routes.start_generation("race", background, profile=None, db=late)
    assert out["status"] == "generating"
    assert not background.tasks
    assert calls == ["race"]


def _api_error(cls, status: int):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx.Response(status, request=req), body=None)


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (anthropic.APITimeoutError(request=httpx.Request("POST", "https://x")), "busy"),
        (_api_error(anthropic.RateLimitError, 429), "busy"),
        (_api_error(anthropic.InternalServerError, 529), "busy"),
        (_api_error(anthropic.AuthenticationError, 401), "unavailable"),
        (GenerationError("The AI service is not configured: ANTHROPIC_API_KEY is missing"),
         "unavailable"),
        (HTTPException(503, detail="daily_budget"), "budget"),
        (GenerationError("failed after 3 attempts: bad JSON"), "failed"),
        (ValueError("anything else"), "failed"),
    ],
)
def test_failure_code(exc, code):
    assert req_routes._failure_code(exc) == code


def test_failure_code_looks_through_wrapped_causes():
    try:
        try:
            raise anthropic.APITimeoutError(request=httpx.Request("POST", "https://x"))
        except anthropic.APITimeoutError as inner:
            raise GenerationError("section failed") from inner
    except GenerationError as outer:
        assert req_routes._failure_code(outer) == "busy"


@pytest.mark.asyncio
async def test_failure_is_explained_and_retry_really_retries(client, monkeypatch):
    secret = "Traceback-ish detail sk-ant-secret"
    _count_generations(monkeypatch, fail_with=anthropic.APITimeoutError(
        request=httpx.Request("POST", f"https://x/{secret}")
    ))
    await _seed("flaky")
    assert (await client.post("/api/v1/requests/flaky/generate")).status_code == 202

    row = await _row("flaky")
    assert (row.status, row.error_code) == ("error", "busy")
    status = (await client.get("/api/v1/requests/flaky")).json()
    assert status["error_code"] == "busy"

    stream = await client.get("/api/v1/requests/flaky/stream")
    assert "event: failed" in stream.text
    assert '"code": "busy"' in stream.text
    assert secret not in stream.text  # raw exception text never reaches the child

    # Retry: the old 'failed' must not be replayed to the new loading screen, and it really runs.
    calls = _count_generations(monkeypatch)
    assert (await client.post("/api/v1/requests/flaky/generate")).json()["status"] == "queued"
    assert calls == ["flaky"]
    _q, backlog = await task_registry.subscribe("flaky")
    await task_registry.unsubscribe("flaky", _q)
    assert all(ev["event"] != "failed" for ev in backlog)
    row = await _row("flaky")
    assert row.error_code is None


@pytest.mark.asyncio
async def test_failure_reaches_the_screen_even_if_the_row_cannot_be_marked(client, monkeypatch):
    """Marking the row needs the database; if that fails, the loading screen must still hear it's
    over — and Retry must still be able to start it again."""
    _count_generations(monkeypatch, fail_with=RuntimeError("model said no"))

    async def broken_mark(*_a, **_k):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(req_routes, "_mark_failed", broken_mark)
    await _seed("stuck")
    await client.post("/api/v1/requests/stuck/generate")
    assert task_registry.is_done("stuck")
    assert (await _row("stuck")).status == "generating"  # couldn't be marked

    calls = _count_generations(monkeypatch)
    assert (await client.post("/api/v1/requests/stuck/generate")).json()["status"] == "queued"
    assert calls == ["stuck"]


def _depends_on(dependant: Dependant, target) -> bool:
    return any(d.call is target or _depends_on(d, target) for d in dependant.dependencies)


def test_waiting_routes_hold_no_request_session():
    """A request-scoped session lives as long as its response. The progress stream stays open for
    the whole generation, so with it about fifteen children on the loading screen used up the
    connection pool and every other request failed."""
    stream = next(
        r for r in req_routes.router.routes
        if getattr(r, "path", "").endswith("/{request_id}/stream")
    )
    assert not _depends_on(stream.dependant, get_db)


@pytest.mark.asyncio
async def test_health_reports_work_a_restart_would_cut_off(client):
    body = (await client.get("/api/v1/health")).json()
    assert body == {"status": "ok", "db": "ok", "active_generations": 0}
    with task_registry.working("generate:x"), task_registry.working("section:1:2"):
        assert (await client.get("/api/v1/health")).json()["active_generations"] == 2
    assert (await client.get("/api/v1/health")).json()["active_generations"] == 0


@pytest.mark.asyncio
async def test_the_claim_is_committed_before_the_generation_runs(client, monkeypatch, tmp_path):
    """On a real (file) database: FastAPI runs background tasks BEFORE the request's session is
    closed, so an uncommitted claim held SQLite's write lock through the whole generation — whose own
    first write then failed with "database is locked" (as did every other learner's save). The
    in-memory test database shares one connection and can't show this, hence the file database."""
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db import session as session_mod
    from app.db.base import Base
    from app.llm import orchestrator

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'real.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _pragmas(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=1000")  # fail fast instead of after 30 s
        cur.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    real = async_sessionmaker(engine, expire_on_commit=False)
    for mod in (session_mod, req_routes, orchestrator):
        monkeypatch.setattr(mod, "SessionLocal", real)
    async with real() as db:
        db.add(LearningRequest(request_id="lock", decision_type="proceed", mode="study",
                               structured_intent_json=_INTENT, status="queued",
                               prompt_version="t", model_id="m"))
        await db.commit()

    wrote: list[str] = []

    async def fake_run(request_id: str) -> None:  # the orchestrator's first move: a quick write
        async with real() as db:
            await db.execute(
                update(LearningRequest).where(LearningRequest.request_id == request_id)
                .values(status="generating")
            )
            await db.commit()
        wrote.append(request_id)

    monkeypatch.setattr(req_routes, "run_generation", fake_run)
    try:
        assert (await client.post("/api/v1/requests/lock/generate")).status_code == 202
        assert wrote == ["lock"], "the generation's first write was blocked by the route's claim"
    finally:
        await engine.dispose()

"""The student-prompt entrypoint: sanitize → route Decision; then async generation + SSE progress.

``POST /requests`` is the ONLY endpoint that accepts untrusted free text. The raw prompt is passed to
the sanitizer and never persisted on the request row (SPEC §3/§5)."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

import anthropic
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from ....core.config import settings
from ....core.constants import PROMPT_VERSION
from ....core.tasks import task_registry
from ....db.session import SessionLocal, get_db
from ....llm.orchestrator import run_generation
from ....models import LearningRequest, Profile
from ....sanitization import sanitize_request
from ....sanitization.ratelimit import rate_limit_dependency
from ....schemas.intent import CreateRequestIn, Decision, ProceedDecision
from ....services.cost_guard import ensure_ai_budget
from ...deps import RequestContext, get_optional_profile, get_request_context

router = APIRouter(prefix="/requests", tags=["requests"])
logger = logging.getLogger("schoolautomaton.generation")


@router.post("", response_model=Decision)
async def create_request(
    body: CreateRequestIn,
    ctx: RequestContext = Depends(get_request_context),
    profile: Profile | None = Depends(get_optional_profile),
    db: AsyncSession = Depends(get_db),
):
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty prompt")
    if len(prompt) > settings.max_prompt_chars:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Prompt exceeds {settings.max_prompt_chars} characters",
        )

    request_id = str(uuid.uuid4())
    # Hand the pooled connection back while the classifier model reads the prompt (a second or
    # two): nothing is written yet, and a classroom typing at once shouldn't queue for connections.
    await db.commit()
    decision = await sanitize_request(
        db,
        prompt,
        ctx,
        request_id,
        client_locale=body.locale,
        client_school_year=body.school_year,
    )

    is_proceed = isinstance(decision, ProceedDecision)
    lr = LearningRequest(
        request_id=request_id,
        profile_id=profile.id if profile else None,
        decision_type=decision.type.value,
        mode=decision.mode.value if is_proceed else None,
        structured_intent_json=decision.intent.model_dump(mode="json") if is_proceed else {},
        detected_language=decision.intent.language if is_proceed else "unknown",
        grade_band=decision.intent.grade_band.value if is_proceed else "unknown",
        status="queued" if is_proceed else "ready",
        prompt_version=PROMPT_VERSION,
        model_id=settings.sanitizer_model_id,
    )
    db.add(lr)
    await db.flush()
    return decision


# Why a generation failed, as a code the loading screen turns into words in the child's language. The
# English sentence published next to it is a fallback; neither ever carries raw exception text.
_FAILURE_MESSAGES = {
    "busy": "The AI is very busy right now. Please try again in a moment.",
    "unavailable": "Making lessons isn't working right now. Please try again later.",
    "budget": "Today's limit for new lessons is used up. Please try again tomorrow.",
    "failed": "Something went wrong while preparing this. Please try again.",
}


def _failure_code(exc: BaseException) -> str:
    """busy (provider overloaded / rate-limited / timed out — retrying soon may work), unavailable
    (missing or rejected API key — needs the operator), budget, or failed (anything else)."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:  # look through wrapped causes too
        seen.add(id(cur))
        if isinstance(cur, HTTPException) and cur.detail == "daily_budget":
            return "budget"
        if isinstance(cur, anthropic.APITimeoutError | anthropic.APIConnectionError | TimeoutError):
            return "busy"
        if isinstance(cur, anthropic.APIStatusError):
            code = cur.status_code
            if code in (401, 403):
                return "unavailable"
            if code == 429 or code >= 500:
                return "busy"
        low = str(cur).lower()
        if "anthropic_api_key" in low or "not configured" in low:
            return "unavailable"
        cur = cur.__cause__ or cur.__context__
    return "failed"


def _generation_key(request_id: str) -> str:
    return f"generate:{request_id}"


async def _safe_generate(request_id: str) -> None:
    """Background wrapper: run generation; on failure LOG the full error, mark the request errored
    (so a Retry, a reload or the poll fallback sees it) and tell the loading screen."""
    with task_registry.working(_generation_key(request_id)):
        try:
            await run_generation(request_id)
        except Exception as exc:  # noqa: BLE001 — degrade gracefully, surface to the loading screen
            logger.exception("Generation failed for request %s", request_id)
            code = _failure_code(exc)
            try:
                # Bounded: on a struggling server the loading screen must still hear it's over.
                await asyncio.wait_for(_mark_failed(request_id, code, exc), timeout=10)
            except Exception:  # noqa: BLE001 — Retry still works (see start_generation)
                logger.exception("Could not mark request %s as failed", request_id)
            await task_registry.publish(
                request_id, "failed", {"message": _FAILURE_MESSAGES[code], "code": code}
            )


async def _mark_failed(request_id: str, code: str, exc: BaseException) -> None:
    async with SessionLocal() as db:
        await db.execute(
            update(LearningRequest)
            .where(LearningRequest.request_id == request_id)
            .values(status="error", error_code=code, error_message=str(exc)[:500])
        )
        await db.commit()


@router.post(
    "/{request_id}/generate",
    status_code=status.HTTP_202_ACCEPTED,
    # Rate-limited: this kicks off the full (expensive) Opus generation pipeline.
    dependencies=[Depends(rate_limit_dependency)],
)
async def start_generation(
    request_id: str,
    background: BackgroundTasks,
    profile: Profile | None = Depends(get_optional_profile),
    db: AsyncSession = Depends(get_db),
):
    """Start generating — at most once. A double tap, a retry racing the first call, or a reload of
    the loading screen gets the current status back instead of starting a second (paid) generation.
    A request that failed may be started again (the Retry button)."""
    lr = await db.scalar(select(LearningRequest).where(LearningRequest.request_id == request_id))
    if lr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown request")
    if lr.decision_type != "proceed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Request is not in a proceed state")
    startable = ["queued", "error"]
    if (
        lr.status == "generating"
        and task_registry.is_done(request_id)
        and not task_registry.is_working(_generation_key(request_id))
    ):
        # It failed but the row couldn't be marked (see _safe_generate): let Retry start it again.
        startable.append("generating")
    if lr.status not in startable:
        return {"request_id": request_id, "status": lr.status}
    await ensure_ai_budget(db)
    values: dict = {"status": "generating", "error_code": None, "error_message": None}
    if profile is not None and lr.profile_id is None:
        values["profile_id"] = profile.id
    # Claim it atomically: SQLite serializes the two UPDATEs, so only one caller sees a row change.
    claimed = await db.execute(
        update(LearningRequest)
        .where(
            LearningRequest.request_id == request_id,
            LearningRequest.status.in_(startable),
        )
        .values(**values)
    )
    if claimed.rowcount != 1:
        await db.refresh(lr)
        return {"request_id": request_id, "status": lr.status}
    await task_registry.restart(request_id)
    background.add_task(_safe_generate, request_id)
    return {"request_id": request_id, "status": "queued"}


def _status_payload(lr: LearningRequest) -> dict:
    failed = lr.status == "error"
    return {
        "request_id": lr.request_id,
        "status": lr.status,
        "mode": lr.mode,
        "lesson_id": lr.lesson_id,
        "quiz_id": lr.quiz_id,
        "error_code": (lr.error_code or "failed") if failed else None,
    }


async def _load_request(request_id: str) -> LearningRequest:
    """One quick read in its own short session — never a pooled connection held for a whole stream."""
    async with SessionLocal() as db:
        lr = await db.scalar(
            select(LearningRequest).where(LearningRequest.request_id == request_id)
        )
    if lr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown request")
    return lr


@router.get("/{request_id}")
async def get_request_status(request_id: str):
    return _status_payload(await _load_request(request_id))


# How often a waiting stream wakes to notice that the child has left (closed the tab / navigated).
_STREAM_IDLE_CHECK_S = 15.0


@router.get("/{request_id}/stream")
async def stream_generation(request_id: str, request: Request):
    # No request-scoped session here (no Depends(get_db)): the stream stays open for the whole
    # generation, and a session held that long kept one of the pool's connections busy — about
    # fifteen children on the loading screen at once made every other request wait and fail.
    lr = await _load_request(request_id)
    terminal = lr.status in ("ready", "error")
    payload = _status_payload(lr)

    async def event_gen():
        # If already finished (e.g. after a restart with an empty registry), emit once and stop.
        # The terminal failure event is named 'failed' on the wire (avoids EventSource's reserved
        # native 'error' event); 'ready' is unchanged.
        if terminal and not task_registry.is_done(request_id):
            if lr.status == "error":
                code = payload["error_code"]
                data = {**payload, "message": _FAILURE_MESSAGES.get(code, ""), "code": code}
                yield {"event": "failed", "data": json.dumps(data)}
            else:
                yield {"event": lr.status, "data": json.dumps(payload)}
            return
        q, backlog = await task_registry.subscribe(request_id)
        try:
            seen_terminal = False
            for ev in backlog:
                yield {"event": ev["event"], "data": json.dumps(ev["data"])}
                if ev["event"] in ("ready", "failed"):
                    seen_terminal = True
            while not seen_terminal:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=_STREAM_IDLE_CHECK_S)
                except TimeoutError:
                    continue
                yield {"event": ev["event"], "data": json.dumps(ev["data"])}
                if ev["event"] in ("ready", "failed"):
                    break
        finally:
            await task_registry.unsubscribe(request_id, q)

    return EventSourceResponse(event_gen())

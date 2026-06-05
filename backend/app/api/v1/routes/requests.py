"""The student-prompt entrypoint: sanitize → route Decision; then async generation + SSE progress.

``POST /requests`` is the ONLY endpoint that accepts untrusted free text. The raw prompt is passed to
the sanitizer and never persisted on the request row (SPEC §3/§5)."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from ....core.config import settings
from ....core.constants import PROMPT_VERSION
from ....core.tasks import task_registry
from ....db.session import SessionLocal, get_db
from ....llm.orchestrator import run_generation
from ....models import LearningRequest, Profile
from ....sanitization import sanitize_request
from ....schemas.intent import CreateRequestIn, Decision, ProceedDecision
from ...deps import RequestContext, get_optional_profile, get_request_context

router = APIRouter(prefix="/requests", tags=["requests"])


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
    decision = await sanitize_request(db, prompt, ctx, request_id)

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


async def _safe_generate(request_id: str) -> None:
    """Background wrapper: run generation, and on any failure mark the request errored + emit SSE."""
    try:
        await run_generation(request_id)
    except Exception as exc:  # noqa: BLE001 — degrade gracefully, surface to the loading screen
        async with SessionLocal() as db:
            lr = await db.scalar(
                select(LearningRequest).where(LearningRequest.request_id == request_id)
            )
            if lr is not None:
                lr.status = "error"
                lr.error_message = str(exc)[:500]
                await db.commit()
        await task_registry.publish(
            request_id, "failed", {"message": "Generation failed. Please try again."}
        )


@router.post("/{request_id}/generate", status_code=status.HTTP_202_ACCEPTED)
async def start_generation(
    request_id: str,
    background: BackgroundTasks,
    profile: Profile | None = Depends(get_optional_profile),
    db: AsyncSession = Depends(get_db),
):
    lr = await db.scalar(select(LearningRequest).where(LearningRequest.request_id == request_id))
    if lr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown request")
    if lr.decision_type != "proceed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Request is not in a proceed state")
    if profile is not None and lr.profile_id is None:
        lr.profile_id = profile.id
    if lr.status in ("queued", "error"):
        lr.status = "queued"
        await db.flush()
        background.add_task(_safe_generate, request_id)
    return {"request_id": request_id, "status": "queued"}


def _status_payload(lr: LearningRequest) -> dict:
    return {
        "request_id": lr.request_id,
        "status": lr.status,
        "mode": lr.mode,
        "lesson_id": lr.lesson_id,
        "quiz_id": lr.quiz_id,
    }


@router.get("/{request_id}")
async def get_request_status(request_id: str, db: AsyncSession = Depends(get_db)):
    lr = await db.scalar(select(LearningRequest).where(LearningRequest.request_id == request_id))
    if lr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown request")
    return _status_payload(lr)


@router.get("/{request_id}/stream")
async def stream_generation(request_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    lr = await db.scalar(select(LearningRequest).where(LearningRequest.request_id == request_id))
    if lr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown request")
    terminal = lr.status in ("ready", "error")
    payload = _status_payload(lr)

    async def event_gen():
        # If already finished (e.g. after a restart with an empty registry), emit once and stop.
        # The terminal failure event is named 'failed' on the wire (avoids EventSource's reserved
        # native 'error' event); 'ready' is unchanged.
        if terminal and not task_registry.is_done(request_id):
            event_name = "failed" if lr.status == "error" else lr.status
            yield {"event": event_name, "data": json.dumps(payload)}
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
                ev = await q.get()
                yield {"event": ev["event"], "data": json.dumps(ev["data"])}
                if ev["event"] in ("ready", "failed"):
                    break
        finally:
            await task_registry.unsubscribe(request_id, q)

    return EventSourceResponse(event_gen())

"""The parent's own device: follow one learner with their parent code (``X-Parent-Code``) — their
overview, and tasks (lessons/tests) to give them.

A parent code opens only what is here. It can't be used to learn as the child, answer, or change
their settings (those all take the learner's resume code). A task's text is untrusted exactly like
a learner's prompt: it goes through the same sanitizer, and only the validated intent is kept."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ....core.config import settings
from ....models import Profile
from ....sanitization import ratelimit, sanitize_request
from ....schemas.family import AssignIn, AssignmentOut, AssignOut, ParentChildOut
from ....schemas.intent import ProceedDecision
from ....schemas.profile import ParentSummary
from ....services import family_service, profile_service, summary_service
from ....services.cost_guard import ensure_ai_budget
from ...deps import ParentAccess, RequestContext, client_ip_hash, get_db, get_parent_access
from .requests import request_row, start_generation

router = APIRouter(prefix="/parent", tags=["parent"])
logger = logging.getLogger("schoolautomaton.parent")

TOO_MANY_TASKS = "too_many_tasks"


def _child_context(request: Request, child: Profile) -> RequestContext:
    """A parent's request draws on the LEARNER's generation allowance (and this network's ceiling),
    like the learner's own prompt would."""
    return RequestContext(
        ip_hash=client_ip_hash(request),
        user_agent=request.headers.get("user-agent", "")[:200],
        profile_id=child.id,
    )


@router.get("/child", response_model=ParentChildOut)
async def get_child(
    access: ParentAccess = Depends(get_parent_access), db: AsyncSession = Depends(get_db)
):
    """Checks the code (adding a child on the parent's device) and opens the overview."""
    await family_service.touch(db, access.link)
    child_settings = await profile_service._get_settings(db, access.child)
    return ParentChildOut(
        school_year=child_settings.school_year, education_locale=child_settings.education_locale
    )


@router.get("/summary", response_model=ParentSummary)
async def get_summary(
    days: int = Query(default=7, ge=1, le=31),
    access: ParentAccess = Depends(get_parent_access),
    db: AsyncSession = Depends(get_db),
):
    """The same overview the learner's own device shows for parents."""
    return await summary_service.build_summary(db, access.child, days)


@router.get("/assignments", response_model=list[AssignmentOut])
async def list_assignments(
    access: ParentAccess = Depends(get_parent_access), db: AsyncSession = Depends(get_db)
):
    """The tasks given recently, newest first, finished ones included (with a test's result)."""
    return await family_service.list_assignments(db, access.child, open_only=False)


@router.post("/assignments", response_model=AssignOut)
async def give_assignment(
    body: AssignIn,
    request: Request,
    background: BackgroundTasks,
    access: ParentAccess = Depends(get_parent_access),
    db: AsyncSession = Depends(get_db),
):
    """Give the learner a task. The text is sanitized like a learner's prompt, for the learner's own
    class and curriculum; on a go-ahead the content is generated right away, so it is ready when the
    learner opens it. Any other decision (clarify / refuse / crisis) is returned as it is."""
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty prompt")
    if len(prompt) > settings.max_prompt_chars:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Prompt exceeds {settings.max_prompt_chars} characters",
        )
    child = access.child
    if len(await family_service.list_assignments(db, child, open_only=True)) >= (
        family_service.MAX_OPEN_ASSIGNMENTS
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, TOO_MANY_TASKS)
    # Before the classifier runs: no paid call (and no task) when nothing can be generated today.
    await ensure_ai_budget(db)
    child_settings = await profile_service._get_settings(db, child)
    ctx = _child_context(request, child)
    request_id = str(uuid.uuid4())
    # Hand the pooled connection back while the classifier reads the text (as POST /requests does).
    await db.commit()
    decision = await sanitize_request(
        db,
        prompt,
        ctx,
        request_id,
        client_locale=child_settings.education_locale,
        client_school_year=child_settings.school_year,
    )
    row = None
    if isinstance(decision, ProceedDecision):
        # The parent chose lesson or test; that wins over what the wording suggested.
        intent = decision.intent.model_copy(update={"mode": body.mode})
        decision = decision.model_copy(update={"mode": body.mode, "intent": intent})
    db.add(request_row(request_id, child.id, decision))
    if isinstance(decision, ProceedDecision):
        row = await family_service.add_assignment(
            db, child, request_id=request_id, mode=body.mode.value, intent=decision.intent
        )
    await db.flush()
    if row is None:
        return AssignOut(decision=decision)
    # Committed before generation starts (SPEC §9: never hold the write lock across a model call).
    await db.commit()
    try:
        await start_generation(request_id, background, profile=None, db=db)
    except HTTPException as exc:
        # E.g. the budget ran out just now. The task stays; it shows as not prepared, and starting
        # it (the learner's Start, or the parent's Try again) retries.
        logger.warning("Task %s could not start generating: %s", request_id, exc.detail)
    return AssignOut(decision=decision, assignment=await family_service.assignment_view(db, child, row))


@router.post("/assignments/{assignment_id}/retry", response_model=AssignmentOut)
async def retry_assignment(
    assignment_id: int,
    request: Request,
    background: BackgroundTasks,
    access: ParentAccess = Depends(get_parent_access),
    db: AsyncSession = Depends(get_db),
):
    """Try preparing a task again that couldn't be prepared. Starting is idempotent (at most one
    generation runs), so a double tap — or the learner pressing Start meanwhile — is harmless."""
    row = await family_service.get_assignment(db, access.child, assignment_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown task")
    ratelimit.check(_child_context(request, access.child))
    await start_generation(row.request_id, background, profile=None, db=db)
    return await family_service.assignment_view(db, access.child, row)


@router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_assignment(
    assignment_id: int,
    access: ParentAccess = Depends(get_parent_access),
    db: AsyncSession = Depends(get_db),
):
    """Take a task back: it leaves the learner's home screen (and, unopened, their history)."""
    if not await family_service.remove_assignment(db, access.child, assignment_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown task")

"""Background generation entry. Routes schedule ``run_generation(request_id)`` as a background task;
it loads the request, flips status to ``generating``, emits SSE progress via ``task_registry``,
generates a lesson or quiz (from the validated StructuredIntent), persists rows + visual assets, then
emits ``ready`` (or ``failed``).

The signature is FROZEN: ``run_generation`` takes ONLY a ``request_id`` (the central one-way-flow
invariant — it loads the validated StructuredIntent from the DB and never receives raw prompt text).
It opens its OWN AsyncSession (SessionLocal), so it is independent of any request-scoped session.
"""

from __future__ import annotations

from sqlalchemy import select

from ..core.tasks import task_registry
from ..db.session import SessionLocal
from ..models import LearningRequest
from ..schemas.enums import Mode
from ..schemas.intent import StructuredIntent


async def run_generation(request_id: str) -> None:
    """Generate a lesson or quiz for ``request_id`` and persist it, emitting SSE progress.

    Opens its own session; loads the LearningRequest; reconstructs the validated StructuredIntent
    from ``structured_intent_json`` (never raw text); branches on mode; on success sets
    status='ready' + lesson_id/quiz_id and publishes a 'ready' event. On failure the caller wrapper
    marks the request errored and emits a 'failed' event, so we let exceptions propagate.
    """
    async with SessionLocal() as db:
        lr = await db.scalar(
            select(LearningRequest).where(LearningRequest.request_id == request_id)
        )
        if lr is None:
            raise ValueError(f"Unknown request_id {request_id!r}")
        if lr.decision_type != "proceed":
            raise ValueError(f"Request {request_id!r} is not in a proceed state")

        intent = StructuredIntent.model_validate(lr.structured_intent_json)

        lr.status = "generating"
        await db.flush()
        # Commit the transition so the poll-fallback GET /requests/{id} reports 'generating'
        # (not stale 'queued') during the whole generation window (SPEC §4 #2 poll fallback).
        await db.commit()
        await task_registry.publish(
            request_id, "status", {"status": "generating", "mode": lr.mode}
        )

        # Import generators lazily so a momentarily-incomplete sibling module can't break import.
        if intent.mode == Mode.TEST or lr.mode == Mode.TEST.value:
            from .quiz_generator import generate_quiz

            quiz = await generate_quiz(db, lr, intent)
            lr.quiz_id = quiz.id
            lr.status = "ready"
            await db.flush()
            await db.commit()
            await task_registry.publish(
                request_id, "ready", {"mode": "test", "quiz_id": quiz.id}
            )
        else:
            from .lesson_generator import generate_lesson

            lesson = await generate_lesson(db, lr, intent)
            lr.lesson_id = lesson.id
            lr.status = "ready"
            await db.flush()
            await db.commit()
            await task_registry.publish(
                request_id, "ready", {"mode": "study", "lesson_id": lesson.id}
            )

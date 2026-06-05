"""Quiz generation (Opus 4.8): one structured call seeded for the learner's ZPD, then persist.

``generate_quiz(db, request, intent) -> Quiz`` consumes ONLY the validated StructuredIntent. The
single :class:`GenQuiz` call is seeded with {concept, mastery, recent_accuracy, target_success=0.83,
known_misconceptions, language, grade_band} so items land near the target success rate. Each question
is persisted as a shared :class:`Item` (server-only correctness) plus an ordered :class:`QuizQuestion`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.constants import PROMPT_VERSION, TARGET_SUCCESS_RATE
from ..core.tasks import task_registry
from ..models import Concept, Item, Misconception, Quiz, QuizQuestion
from ..schemas.enums import LayoutSlot
from ..schemas.generation import GenItem, GenQuiz, coerce_payload
from ..schemas.intent import StructuredIntent
from . import prompts
from .client import generate_structured
from .lesson_generator import (
    _ensure_misconception,
    _realize_hotspot_image,
    _slugify,
    _upsert_concept,
)

_QUIZ_MAX_TOKENS = 16000


async def _known_misconceptions(db: AsyncSession, concept_id: int | None) -> list[str]:
    if concept_id is None:
        return []
    rows = await db.scalars(
        select(Misconception.description).where(Misconception.concept_id == concept_id).limit(8)
    )
    return list(rows)


async def _persist_quiz_item(
    db: AsyncSession,
    gen: GenItem,
    *,
    quiz: Quiz,
    concept_cache: dict[str, Concept],
    misconception_cache: dict[tuple[int, str], int],
) -> Item:
    """Persist one quiz question as a shared Item, mapping distractor misconceptions to ids."""
    slug = _slugify(gen.concept_slug)
    concept = concept_cache.get(slug)
    if concept is None:
        concept = await _upsert_concept(
            db, slug, name=gen.concept_slug, subject=quiz.subject, grade=quiz.grade_band
        )
        concept_cache[slug] = concept

    distractors: list[dict[str, Any]] = []
    for d in gen.distractors:
        misconception_id: int | None = None
        if d.misconception:
            misconception_id = await _ensure_misconception(
                db, concept_id=concept.id, description=d.misconception, cache=misconception_cache
            )
        distractors.append({"text": d.text, "misconception_id": misconception_id})

    item = Item(
        source_lesson_id=None,
        lesson_section_id=None,
        concept_id=concept.id,
        item_type=gen.item_type.value,
        bloom_tier=int(gen.bloom_tier),
        difficulty=gen.difficulty.value,
        item_difficulty=max(1, min(5, gen.item_difficulty)),
        language=quiz.language,
        stem_markdown=gen.stem_markdown,
        payload_json=coerce_payload(gen.item_type, gen.payload) or (gen.payload or {}),
        expected_answer=gen.expected_answer,
        accepted_variants_json=gen.accepted_variants or None,
        distractors_json=distractors or None,
        hint_ladder_json=gen.hint_ladder or None,
        worked_solution_steps_json=gen.worked_solution_steps or None,
        explanation=gen.explanation or None,
        model_id=settings.model_id,
        prompt_version=PROMPT_VERSION,
    )
    db.add(item)
    await db.flush()
    await _realize_hotspot_image(
        db,
        item,
        gen,
        language=quiz.language,
        grade_band=quiz.grade_band,
        layout_slot=LayoutSlot.QUIZ_THUMB,
    )
    return item


async def generate_quiz(
    db: AsyncSession,
    request: Any,
    intent: StructuredIntent,
    *,
    mastery: float = 0.0,
    recent_accuracy: float = 0.0,
    client: Any = None,
) -> Quiz:
    """Generate + persist a quiz from the validated intent. Returns the Quiz row."""
    request_id: str = request.request_id

    # Anchor the quiz to the topic concept (upsert by slug) so we can seed known misconceptions.
    primary_concept = await _upsert_concept(
        db,
        intent.topic or intent.subject.value,
        name=intent.topic or intent.subject.value,
        subject=intent.subject.value,
        grade=intent.grade_band.value,
    )
    known = await _known_misconceptions(db, primary_concept.id)

    gen_quiz, _ = await generate_structured(
        system_blocks=prompts.system_pedagogy(intent.language),
        user=prompts.build_quiz_user(
            intent,
            mastery=mastery,
            recent_accuracy=recent_accuracy,
            known_misconceptions=known,
            target_success=TARGET_SUCCESS_RATE,
        ),
        output_model=GenQuiz,
        model=settings.model_id,
        max_tokens=_QUIZ_MAX_TOKENS,
        effort="high",
        use_json_mode=True,  # nested question lists exceed the constrained-decoding grammar cap
        db=db,
        request_id=request_id,
        client=client,
    )

    quiz = Quiz(
        request_id=request_id,
        title=(gen_quiz.title or intent.topic or "Quiz")[:200],
        language=intent.language,
        grade_band=intent.grade_band.value,
        subject=intent.subject.value,
        concept_id=primary_concept.id,
        quiz_type="standard",
        model_id=settings.model_id,
        prompt_version=PROMPT_VERSION,
    )
    db.add(quiz)
    await db.flush()

    concept_cache: dict[str, Concept] = {primary_concept.slug: primary_concept}
    misconception_cache: dict[tuple[int, str], int] = {}
    for ordinal, gi in enumerate(gen_quiz.questions):
        item = await _persist_quiz_item(
            db,
            gi,
            quiz=quiz,
            concept_cache=concept_cache,
            misconception_cache=misconception_cache,
        )
        db.add(
            QuizQuestion(quiz_id=quiz.id, item_id=item.id, ordinal=ordinal, points=gi.points or 10)
        )
    await db.flush()
    await task_registry.publish(
        request_id,
        "section",
        {"ordinal": 0, "kind": "quiz", "title": quiz.title, "questions": len(gen_quiz.questions)},
    )
    return quiz

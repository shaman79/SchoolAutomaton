"""Lesson generation pipeline (Opus 4.8): plan -> per-section fill -> visual specs -> persist.

``generate_lesson(db, request, intent) -> Lesson`` consumes ONLY the validated StructuredIntent
(never raw text). Pipeline:

1. **plan** (high effort): one structured call -> :class:`LessonPlan` (ordered section stubs +
   Bloom-tagged objectives + proposed concept edges + misconceptions).
2. **per-section fill** (medium effort, parallel via ``asyncio.Semaphore(4)``): one call per
   skeleton section -> :class:`GenSection` (body markdown + items + visual requests).
3. **visual specs** (low effort): one call -> visual specs across the lesson; each is realized via
   ``app.visuals.ensure_visual`` (imported lazily) and recorded as an AssetsRef.

Readability: explanation sections are checked with ``textstat.flesch_kincaid_grade`` (English) and
regenerated up to twice if measured FKGL exceeds target + tolerance. Non-English uses a sentence/
long-word proxy and stores a readability_note (no misleading FKGL).

All rows stamp MODEL_ID / PROMPT_VERSION. Concepts are upserted INSERT-OR-IGNORE on slug; distractor
``misconception`` strings map to Misconception rows whose id is stored in ``distractors_json``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.constants import PROMPT_VERSION, READABILITY_TARGETS, READABILITY_TOLERANCE
from ..core.tasks import task_registry
from ..models import (
    AssetsRef,
    Concept,
    ConceptEdge,
    Item,
    Lesson,
    LessonConcept,
    LessonSection,
    Misconception,
    SectionVisual,
)
from ..schemas.enums import LESSON_SKELETON, ItemType, LayoutSlot, SectionKind, VisualKind
from ..schemas.generation import (
    GenItem,
    GenSection,
    GenVisualSpec,
    LessonPlan,
    LessonPlanStub,
    coerce_payload,
)
from ..schemas.intent import StructuredIntent
from . import prompts
from .client import generate_structured, usage_row

logger = logging.getLogger("schoolautomaton.generation")

_SECTION_CONCURRENCY = 4
_PLAN_MAX_TOKENS = 16000
_SECTION_MAX_TOKENS = 16000
_VISUAL_MAX_TOKENS = 4000

# Schematic kinds route to Claude-SVG; the rest to Replicate raster (router decides at ensure_visual).
_SVG_KINDS = {
    VisualKind.DIAGRAM, VisualKind.CHART, VisualKind.LABELED_FIGURE, VisualKind.CYCLE,
    VisualKind.TIMELINE, VisualKind.GEOMETRY, VisualKind.NUMBER_LINE, VisualKind.FOOD_CHAIN,
    VisualKind.MAP, VisualKind.ICON,
}


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return (slug or "concept")[:120]


# --------------------------------------------------------------------------- readability


def _fkgl_english(text: str) -> float | None:
    """Flesch-Kincaid grade for English prose (None if textstat unavailable or text too short)."""
    if not text or len(text.split()) < 12:
        return None
    try:
        import textstat
    except ImportError:  # pragma: no cover - dependency guard
        return None
    try:
        return float(textstat.flesch_kincaid_grade(text))
    except Exception:  # noqa: BLE001 - textstat raises on odd input; treat as unmeasurable
        return None


def _readability_proxy(text: str) -> float | None:
    """Non-English proxy: avg sentence length + long-word share, scaled to a rough grade number."""
    if not text:
        return None
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    words = re.findall(r"\b\w+\b", text)
    if not sentences or not words:
        return None
    avg_sentence_len = len(words) / len(sentences)
    long_share = sum(1 for w in words if len(w) >= 7) / len(words)
    return round(0.39 * avg_sentence_len + 12.0 * long_share, 2)


def _is_english(language: str) -> bool:
    return (language or "en").strip().lower()[:2] == "en"


# --------------------------------------------------------------------------- concept / misconception upserts


async def _upsert_concept(db: AsyncSession, slug: str, *, name: str, subject: str, grade: str) -> Concept:
    """INSERT OR IGNORE a Concept by slug, then return the row (single-writer SQLite safe)."""
    slug = _slugify(slug)
    stmt = (
        sqlite_insert(Concept)
        .values(slug=slug, name=name[:160] or slug, subject=subject[:40], grade_introduced=grade)
        .on_conflict_do_nothing(index_elements=["slug"])
    )
    await db.execute(stmt)
    concept = await db.scalar(select(Concept).where(Concept.slug == slug))
    if concept is None:  # pragma: no cover - only if a concurrent delete raced
        concept = Concept(slug=slug, name=name[:160] or slug, subject=subject[:40], grade_introduced=grade)
        db.add(concept)
        await db.flush()
    return concept


async def _ensure_misconception(
    db: AsyncSession, *, concept_id: int, description: str, cache: dict[tuple[int, str], int]
) -> int:
    """INSERT a Misconception (idempotent within this run via ``cache``); return its id."""
    code = _slugify(description)[:80]
    key = (concept_id, code)
    if key in cache:
        return cache[key]
    existing = await db.scalar(
        select(Misconception).where(
            Misconception.concept_id == concept_id, Misconception.code == code
        )
    )
    if existing is not None:
        cache[key] = existing.id
        return existing.id
    row = Misconception(
        concept_id=concept_id,
        code=code,
        description=description[:2000],
        refutation_text=description[:2000],
    )
    db.add(row)
    await db.flush()
    cache[key] = row.id
    return row.id


# --------------------------------------------------------------------------- item persistence


async def _realize_hotspot_image(
    db: AsyncSession,
    item: Item,
    gen: GenItem,
    *,
    language: str,
    grade_band: str,
    layout_slot: LayoutSlot = LayoutSlot.INLINE_FIGURE,
) -> None:
    """Realize a hotspot item's ``image_request`` into a visual asset and link it via an item-level
    AssetsRef so the serializer can fill ``image_url``. Guarded like ``_attach_visuals`` so a visuals
    outage never breaks generation. ``item`` must already have an id (flushed)."""
    image_request = (gen.payload or {}).get("image_request")
    if gen.item_type != ItemType.HOTSPOT or not image_request:
        return
    spec = GenVisualSpec(
        section_ordinal=0,
        visual_kind=VisualKind.LABELED_FIGURE,
        layout_slot=layout_slot,
        image_prompt=image_request,
        alt_text=(gen.stem_markdown[:200] if gen.stem_markdown else "") or "hotspot image",
    )
    try:
        from ..visuals import ensure_visual  # lazy, mirrors _attach_visuals

        asset = await asyncio.wait_for(
            ensure_visual(db, spec, language=language, grade_band=grade_band),
            timeout=settings.per_visual_timeout_s,
        )
    except Exception:  # noqa: BLE001 - timeout or any error: degrade gracefully, never break generation
        return
    db.add(
        AssetsRef(
            item_id=item.id,
            visual_asset_hash=asset.hash,
            layout_slot=spec.layout_slot.value,
            alt_text=spec.alt_text,
        )
    )
    await db.flush()


async def _persist_item(
    db: AsyncSession,
    gen: GenItem,
    *,
    lesson: Lesson,
    section: LessonSection,
    concept_cache: dict[str, Concept],
    misconception_cache: dict[tuple[int, str], int],
) -> Item | None:
    """Persist one GenItem, mapping distractor misconceptions to Misconception ids.

    Returns None (and persists nothing) when the payload isn't answerable/gradeable — a broken item
    is dropped rather than shown to a learner (SPEC: never strand the learner on an unanswerable item)."""
    payload = coerce_payload(gen.item_type, gen.payload)
    if payload is None:
        logger.warning(
            "Dropping unanswerable %s item (lesson %s, section %s)",
            gen.item_type.value, lesson.id, section.id,
        )
        return None

    concept = concept_cache.get(_slugify(gen.concept_slug))
    if concept is None:
        concept = await _upsert_concept(
            db, gen.concept_slug, name=gen.concept_slug, subject=lesson.subject, grade=lesson.grade_band
        )
        concept_cache[concept.slug] = concept

    distractors: list[dict[str, Any]] = []
    for d in gen.distractors:
        misconception_id: int | None = None
        if d.misconception:
            misconception_id = await _ensure_misconception(
                db, concept_id=concept.id, description=d.misconception, cache=misconception_cache
            )
        distractors.append({"text": d.text, "misconception_id": misconception_id})

    item = Item(
        source_lesson_id=lesson.id,
        lesson_section_id=section.id,
        concept_id=concept.id,
        item_type=gen.item_type.value,
        bloom_tier=int(gen.bloom_tier),
        difficulty=gen.difficulty.value,
        item_difficulty=max(1, min(5, gen.item_difficulty)),
        language=lesson.detected_language,
        stem_markdown=gen.stem_markdown,
        payload_json=payload,
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
        language=lesson.detected_language,
        grade_band=lesson.grade_band,
        layout_slot=LayoutSlot.INLINE_FIGURE,
    )
    return item


# --------------------------------------------------------------------------- section generation


async def _generate_section(
    intent: StructuredIntent,
    stub: LessonPlanStub,
    *,
    request_id: str,
    sem: asyncio.Semaphore,
    client: Any,
) -> tuple[GenSection, list[Any]]:
    """Fill one section body via a structured call, bounded by the semaphore. Regenerate explanation
    sections (max 2) when English FKGL exceeds target + tolerance.

    Does NOT touch the DB (it runs inside ``asyncio.gather`` over a shared session, which is not
    concurrency-safe); returns the collected per-call Usage objects so the caller can log them
    serially.
    """
    target = READABILITY_TARGETS.get(intent.grade_band.value, READABILITY_TARGETS["unknown"])["fkgl"]
    user = prompts.build_section_user(
        intent, kind=stub.kind.value, title=stub.title, objective=stub.objective
    )

    usages: list[Any] = []
    async with sem:
        attempts = 3 if stub.kind == SectionKind.EXPLANATION and _is_english(intent.language) else 1
        section: GenSection | None = None
        for i in range(attempts):
            section, usage = await generate_structured(
                system_blocks=prompts.system_pedagogy(intent.language),
                user=user,
                output_model=GenSection,
                model=settings.model_id,
                max_tokens=_SECTION_MAX_TOKENS,
                effort="medium",
                use_json_mode=True,  # nested item lists exceed the constrained-decoding grammar cap
                db=None,  # logged serially by the caller (gather is not session-safe)
                request_id=request_id,
                client=client,
            )
            usages.append(usage)
            if stub.kind != SectionKind.EXPLANATION or not _is_english(intent.language):
                break
            measured = _fkgl_english(section.body_markdown)
            if measured is None or measured <= target + READABILITY_TOLERANCE or i == attempts - 1:
                break
            user = (
                prompts.build_section_user(
                    intent, kind=stub.kind.value, title=stub.title, objective=stub.objective
                )
                + f"\n\nYour previous draft read at grade {measured:.1f}; the target is {target:.1f}. "
                "Simplify: shorter sentences, more common words, fewer new terms."
            )
    assert section is not None
    return section, usages


# --------------------------------------------------------------------------- visuals


async def _queue_section_visuals(
    db: AsyncSession, section: LessonSection, specs: list[GenVisualSpec]
) -> int:
    """Persist a ``SectionVisual(status='pending')`` per requested visual so the section text can be
    delivered immediately. The actual images are realized later by ``realize_section_visuals`` (a
    background task) and the client shows placeholders until they're ready — images NEVER block the
    section from appearing."""
    count = 0
    for i, spec in enumerate(specs):
        spec_data = spec.model_dump(mode="json")
        spec_data["section_ordinal"] = 0  # normalized: realized against this single section
        db.add(
            SectionVisual(
                lesson_section_id=section.id,
                ordinal=i,
                visual_kind=spec.visual_kind.value,
                layout_slot=spec.layout_slot.value,
                alt_text=spec.alt_text or "",
                caption=spec.caption,
                spec_json=spec_data,
                status="pending",
            )
        )
        count += 1
    await db.flush()
    return count


# Strong references to in-flight visual-realization tasks: a bare ``create_task`` may be GC'd before
# it runs (the event loop only holds a weak reference). ``task_registry`` is an SSE broker, not a task
# tracker, so we keep our own set and discard each task when it finishes.
_visual_tasks: set[asyncio.Task] = set()


async def realize_section_visuals(section_id: int) -> None:
    """Generate the pending visuals for one section in the BACKGROUND (its own DB session), flipping
    each ``SectionVisual`` ``pending → ready`` (with a hash) or ``failed`` as it finishes.

    Per-asset commits make images appear incrementally and keep the SQLite write lock held only
    briefly (never across the provider network call — ``ensure_visual`` writes only after generating).
    Bounded by ``per_visual_timeout_s`` per image and an overall ``visual_phase_budget_s`` wall clock;
    anything still unfinished past the budget is marked ``failed`` so the reader stops polling it."""
    from ..db.session import SessionLocal  # lazy: avoid import-time engine coupling
    from ..visuals import ensure_visual

    loop = asyncio.get_event_loop()
    deadline = loop.time() + settings.visual_phase_budget_s
    async with SessionLocal() as db:
        section = await db.get(LessonSection, section_id)
        if section is None:
            return
        lesson = await db.get(Lesson, section.lesson_id)
        language = lesson.detected_language if lesson else "en"
        grade_band = lesson.grade_band if lesson else "unknown"

        # Capture the rows as plain tuples up front: a rollback in any iteration expires the loaded
        # ORM objects, so touching them later would trigger a lazy load (illegal on an async session).
        # Status transitions below are raw UPDATEs for the same reason.
        pending = [
            (sv.id, sv.ordinal, sv.spec_json)
            for sv in await db.scalars(
                select(SectionVisual)
                .where(
                    SectionVisual.lesson_section_id == section_id,
                    SectionVisual.status == "pending",
                )
                .order_by(SectionVisual.ordinal)
            )
        ]
        for sv_id, ordinal, spec_json in pending:
            if loop.time() >= deadline:
                logger.warning(
                    "Visual budget (%ss) reached; marking section %s visual %s failed",
                    settings.visual_phase_budget_s, section_id, ordinal,
                )
                await db.execute(
                    update(SectionVisual)
                    .where(SectionVisual.id == sv_id, SectionVisual.status == "pending")
                    .values(status="failed")
                )
                await db.commit()
                continue
            # Atomically claim the row so a duplicate/restart worker can't double-spend (the route's
            # in-process lock does not cover this background task or a multi-worker deployment).
            claimed = await db.execute(
                update(SectionVisual)
                .where(SectionVisual.id == sv_id, SectionVisual.status == "pending")
                .values(status="generating")
            )
            await db.commit()
            if not claimed.rowcount:
                continue
            spec = GenVisualSpec.model_validate(spec_json)
            try:
                asset = await asyncio.wait_for(
                    ensure_visual(db, spec, language=language, grade_band=grade_band),
                    timeout=settings.per_visual_timeout_s,
                )
                # Persist the asset (from ensure_visual) AND the status flip atomically.
                await db.execute(
                    update(SectionVisual)
                    .where(SectionVisual.id == sv_id)
                    .values(status="ready", visual_asset_hash=asset.hash)
                )
                await db.commit()
            except Exception:  # noqa: BLE001 — a visual must never strand the section; mark it failed
                logger.warning(
                    "Section visual generation failed (section=%s ordinal=%s)",
                    section_id, ordinal, exc_info=True,
                )
                await db.rollback()
                await db.execute(
                    update(SectionVisual)
                    .where(SectionVisual.id == sv_id)
                    .values(status="failed")
                )
                await db.commit()


def schedule_section_visuals(section_id: int) -> None:
    """Fire-and-forget ``realize_section_visuals`` on the running loop (orchestrator path). No-op when
    there's no loop (sync/test contexts realize explicitly). Errors are swallowed/logged so a visual
    can never break the surrounding generation."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _safe() -> None:
        try:
            await realize_section_visuals(section_id)
        except Exception:  # noqa: BLE001 — background best-effort; degrade silently
            logger.warning("Background visual realization failed (section=%s)", section_id,
                           exc_info=True)

    task = loop.create_task(_safe())
    _visual_tasks.add(task)
    task.add_done_callback(_visual_tasks.discard)


# --------------------------------------------------------------------------- orchestration


async def generate_lesson(
    db: AsyncSession,
    request: Any,
    intent: StructuredIntent,
    *,
    client: Any = None,
) -> Lesson:
    """Generate + persist a full lesson from the validated intent. Returns the Lesson row.

    ``request`` is the LearningRequest row (provides request_id). ``client`` is an injectable
    AsyncAnthropic for tests; production passes None (the shared client is used).
    """
    request_id: str = request.request_id

    # ---- Step 1: plan ----
    plan, _ = await generate_structured(
        system_blocks=prompts.system_pedagogy(intent.language),
        user=prompts.build_lesson_plan_user(intent),
        output_model=LessonPlan,
        model=settings.model_id,
        max_tokens=_PLAN_MAX_TOKENS,
        effort="high",
        use_json_mode=True,  # nested objectives/sections exceed the constrained-decoding grammar cap
        db=db,
        request_id=request_id,
        client=client,
    )
    await task_registry.publish(
        request_id,
        "plan",
        {
            "sections": [
                {"ordinal": i, "kind": s.kind.value, "title": s.title}
                for i, s in enumerate(_ordered_stubs(plan))
            ]
        },
    )

    target_band = READABILITY_TARGETS.get(intent.grade_band.value, READABILITY_TARGETS["unknown"])
    lesson = Lesson(
        request_id=request_id,
        topic=(intent.topic or plan.topic)[:200],
        detected_language=intent.language,
        education_locale=intent.education_locale,
        grade_band=intent.grade_band.value,
        subject=intent.subject.value,
        target_fkgl=float(target_band["fkgl"]),
        lexile_band=target_band["lexile"],
        objectives_json=[],  # filled after concepts are upserted
        plan_json=plan.model_dump(mode="json"),  # so sections can be generated lazily, on demand
        estimated_duration_min=plan.estimated_duration_min,
        model_id=settings.model_id,
        prompt_version=PROMPT_VERSION,
    )
    db.add(lesson)
    await db.flush()

    # ---- concepts + objectives + edges ----
    concept_cache: dict[str, Concept] = {}

    async def get_concept(slug: str, name: str | None = None) -> Concept:
        s = _slugify(slug)
        if s not in concept_cache:
            concept_cache[s] = await _upsert_concept(
                db, s, name=name or slug, subject=intent.subject.value, grade=intent.grade_band.value
            )
        return concept_cache[s]

    objectives_json: list[dict[str, Any]] = []
    for obj in plan.objectives:
        concept = await get_concept(obj.concept_slug, obj.text)
        objectives_json.append(
            {"text": obj.text, "bloom_tier": int(obj.bloom_tier), "concept_id": concept.id}
        )
        db.add(LessonConcept(lesson_id=lesson.id, concept_id=concept.id, relation="taught"))
    lesson.objectives_json = objectives_json

    for edge in plan.concept_edges:
        src = await get_concept(edge.from_slug)
        dst = await get_concept(edge.to_slug)
        if src.id == dst.id:
            continue
        await db.execute(
            sqlite_insert(ConceptEdge)
            .values(from_concept_id=src.id, to_concept_id=dst.id, edge_type=edge.edge_type)
            .on_conflict_do_nothing()
        )

    await db.flush()

    # ---- Step 2: ordered skeleton sections (rows first so items can reference them) ----
    # PROGRESSIVE GENERATION: persist all section skeletons as 'pending'; fill ONLY the first
    # section now. The rest are generated on demand (POST /lessons/{id}/sections/{ordinal}/generate)
    # as the learner advances — so an abandoned lesson never pays to generate sections never read.
    ordered_stubs = _ordered_stubs(plan)
    sections: list[LessonSection] = []
    for ordinal, stub in enumerate(ordered_stubs):
        row = LessonSection(
            lesson_id=lesson.id,
            ordinal=ordinal,
            kind=stub.kind.value,
            title=stub.title[:200] if stub.title else None,
            gen_status="pending",
        )
        db.add(row)
        sections.append(row)
    await db.flush()

    if sections:
        await _fill_section(
            db, lesson, request_id, intent, ordered_stubs[0], sections[0], client=client
        )
        await task_registry.publish(
            request_id,
            "section",
            {"ordinal": 0, "kind": sections[0].kind, "title": sections[0].title},
        )

    if not _is_english(intent.language):
        lesson.readability_note = (
            "Non-English content: FKGL is unreliable; a sentence-length / long-word proxy was used."
        )

    await db.flush()
    return lesson


async def _fill_section(
    db: AsyncSession,
    lesson: Lesson,
    request_id: str,
    intent: StructuredIntent,
    stub: LessonPlanStub,
    row: LessonSection,
    *,
    client: Any = None,
) -> LessonSection:
    """Generate one section's body + items + visuals and persist them onto ``row`` (gen_status→ready).

    Shared by the eager first-section build and the on-demand endpoint. Concepts are upserted
    idempotently (INSERT-OR-IGNORE on slug), so fresh per-call caches are safe."""
    sem = asyncio.Semaphore(1)
    gen, usages = await _generate_section(intent, stub, request_id=request_id, sem=sem, client=client)
    for usage in usages:
        db.add(usage_row(usage, request_id=request_id))

    row.body_markdown = gen.body_markdown or None
    if gen.kind == SectionKind.EXPLANATION:
        measured = (
            _fkgl_english(gen.body_markdown)
            if _is_english(intent.language)
            else _readability_proxy(gen.body_markdown)
        )
        if measured is not None:
            row.section_measured_fkgl = measured

    concept_cache: dict[str, Concept] = {}
    misconception_cache: dict[tuple[int, str], int] = {}
    for gi in gen.items:
        await _persist_item(
            db, gi, lesson=lesson, section=row,
            concept_cache=concept_cache, misconception_cache=misconception_cache,
        )
    await db.flush()

    # Queue this section's dual-coding visuals as PENDING (realized later, in the background) so the
    # section text appears immediately and images fill in as placeholders. The caller schedules
    # ``realize_section_visuals(row.id)`` AFTER it commits (so the background session sees the rows).
    await _queue_section_visuals(db, row, gen.visual_requests)

    row.gen_status = "ready"
    # Keep the lesson-level readability metric current as explanation sections fill in over time.
    samples = list(
        await db.scalars(
            select(LessonSection.section_measured_fkgl).where(
                LessonSection.lesson_id == lesson.id,
                LessonSection.kind == SectionKind.EXPLANATION.value,
                LessonSection.section_measured_fkgl.is_not(None),
            )
        )
    )
    if samples:
        lesson.measured_fkgl = round(sum(samples) / len(samples), 2)
    await db.flush()
    return row


async def generate_one_section(
    db: AsyncSession,
    lesson: Lesson,
    intent: StructuredIntent,
    ordinal: int,
    *,
    client: Any = None,
) -> LessonSection:
    """On-demand: generate the pending section at ``ordinal`` for an already-delivered lesson.

    Reconstructs the frozen plan stub from ``lesson.plan_json``; idempotent if already ready."""
    row = await db.scalar(
        select(LessonSection).where(
            LessonSection.lesson_id == lesson.id, LessonSection.ordinal == ordinal
        )
    )
    if row is None:
        raise ValueError(f"Lesson {lesson.id} has no section ordinal {ordinal}")
    if row.gen_status == "ready" and row.body_markdown is not None:
        return row
    plan = LessonPlan.model_validate(lesson.plan_json or {})
    ordered_stubs = _ordered_stubs(plan)
    stub = ordered_stubs[ordinal] if 0 <= ordinal < len(ordered_stubs) else LessonPlanStub(
        kind=SectionKind(row.kind), title=row.title
    )
    return await _fill_section(db, lesson, lesson.request_id, intent, stub, row, client=client)


def _ordered_stubs(plan: LessonPlan) -> list[LessonPlanStub]:
    """Return the plan's section stubs in canonical LESSON_SKELETON order, synthesizing any missing
    kinds so the persisted skeleton is always complete and ordered."""
    by_kind: dict[SectionKind, LessonPlanStub] = {}
    for stub in plan.sections:
        by_kind.setdefault(stub.kind, stub)
    ordered: list[LessonPlanStub] = []
    for kind in LESSON_SKELETON:
        stub = by_kind.get(kind)
        if stub is None:
            stub = LessonPlanStub(kind=kind, title=kind.value.replace("_", " ").title())
        ordered.append(stub)
    return ordered


def _collect_visual_specs(
    gen_sections: list[GenSection], ordered_stubs: list[LessonPlanStub]
) -> list[GenVisualSpec]:
    """Gather per-section visual requests, normalizing each spec's section_ordinal to skeleton order."""
    out: list[GenVisualSpec] = []
    for ordinal, gen in enumerate(gen_sections):
        for spec in gen.visual_requests:
            data = spec.model_dump()
            data["section_ordinal"] = ordinal
            out.append(GenVisualSpec.model_validate(data))
    return out


# A tiny container model for the optional batch visual-spec call.
from ..schemas.common import StrictModel  # noqa: E402 - local import keeps the contract import grouped


class _VisualSpecBatch(StrictModel):
    visuals: list[GenVisualSpec]

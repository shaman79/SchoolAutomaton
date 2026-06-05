"""ORM → public-schema serializers (read side, owned by the API spine).

The single place correctness is stripped before delivery (SPEC §5): no is_correct / answer /
correct / correct_order / tolerance reaches the client. Grading reveals the correct answer instead."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    AssetsRef,
    Item,
    Lesson,
    LessonSection,
    Quiz,
    QuizQuestion,
    VisualAsset,
)
from ...schemas.content import (
    AssetRefPublic,
    LessonObjectivePublic,
    LessonPublic,
    LessonSectionPublic,
)
from ...schemas.questions import ItemPublic
from ...schemas.quiz import QuizPublic, QuizQuestionPublic


def _strip_payload(item_type: str, payload: dict) -> dict:
    """Project a stored (full, with-correctness) payload to its public wire shape."""
    payload = payload or {}
    kind = payload.get("kind", item_type)
    if kind == "mcq":
        return {
            "kind": "mcq",
            "options": [{"id": o["id"], "text": o["text"]} for o in payload.get("options", [])],
            "multiple": payload.get("multiple", False),
        }
    if kind == "true_false":
        return {"kind": "true_false", "statement": payload.get("statement")}
    if kind == "cloze":
        return {
            "kind": "cloze",
            "text_template": payload.get("text_template", ""),
            "blanks": [{"id": b["id"], "choices": b.get("choices")} for b in payload.get("blanks", [])],
        }
    if kind == "short_answer":
        return {"kind": "short_answer", "placeholder": payload.get("placeholder")}
    if kind == "numeric":
        return {"kind": "numeric", "unit": payload.get("unit")}
    if kind == "match":
        return {
            "kind": "match",
            "left": [{"id": s["id"], "text": s["text"]} for s in payload.get("left", [])],
            "right": [{"id": s["id"], "text": s["text"]} for s in payload.get("right", [])],
        }
    if kind == "order":
        return {
            "kind": "order",
            "tokens": [{"id": t["id"], "text": t["text"]} for t in payload.get("tokens", [])],
        }
    if kind == "hotspot":
        return {
            "kind": "hotspot",
            "image_url": payload.get("image_url"),
            "image_asset_hash": payload.get("image_asset_hash"),
            "regions": [
                {"id": r["id"], "shape": r["shape"], "coords": r["coords"], "label": r.get("label")}
                for r in payload.get("regions", [])
            ],
        }
    return {"kind": kind}


async def _assets_for(
    db: AsyncSession, *, section_id: int | None = None, item_id: int | None = None
) -> list[AssetRefPublic]:
    cond = AssetsRef.lesson_section_id == section_id if section_id else AssetsRef.item_id == item_id
    rows = (
        await db.execute(
            select(AssetsRef, VisualAsset)
            .join(VisualAsset, VisualAsset.hash == AssetsRef.visual_asset_hash)
            .where(cond)
        )
    ).all()
    out: list[AssetRefPublic] = []
    for ref, va in rows:
        out.append(
            AssetRefPublic(
                hash=va.hash,
                url=f"/api/v1/assets/{va.hash}",
                asset_type=va.asset_type,
                layout_slot=ref.layout_slot,
                alt_text=ref.alt_text,
                caption=ref.caption,
                svg_inline=va.svg_inline if va.asset_type == "svg" else None,
                label_overlay=ref.label_overlay_json,
            )
        )
    return out


async def item_public(db: AsyncSession, item: Item, *, with_assets: bool = True) -> ItemPublic:
    payload = _strip_payload(item.item_type, item.payload_json)
    if item.item_type == "hotspot" and with_assets:
        assets = await _assets_for(db, item_id=item.id)
        if assets and not payload.get("image_url"):
            payload["image_url"] = assets[0].url
            payload["image_asset_hash"] = assets[0].hash
    return ItemPublic(
        id=item.id,
        item_type=item.item_type,
        bloom_tier=item.bloom_tier,
        points=getattr(item, "points", 10) or 10,
        stem_markdown=item.stem_markdown,
        payload=payload,
        hint_available=bool(item.hint_ladder_json),
    )


async def lesson_section_public(db: AsyncSession, s: LessonSection) -> LessonSectionPublic:
    """Serialize one lesson section (pending sections carry no body/items yet)."""
    item_rows = (
        await db.execute(select(Item).where(Item.lesson_section_id == s.id).order_by(Item.id))
    ).scalars().all()
    return LessonSectionPublic(
        ordinal=s.ordinal,
        kind=s.kind,
        title=s.title,
        body_markdown=s.body_markdown,
        gated=s.gated,
        gen_status=getattr(s, "gen_status", "ready"),
        assets=await _assets_for(db, section_id=s.id),
        items=[await item_public(db, it) for it in item_rows],
    )


async def lesson_public(db: AsyncSession, lesson: Lesson) -> LessonPublic:
    objectives = [
        LessonObjectivePublic(
            text=o.get("text", ""),
            bloom_tier=o.get("bloom_tier", 1),
            concept_id=o.get("concept_id"),
        )
        for o in (lesson.objectives_json or [])
    ]
    sections_rows = (
        await db.execute(
            select(LessonSection)
            .where(LessonSection.lesson_id == lesson.id)
            .order_by(LessonSection.ordinal)
        )
    ).scalars().all()

    sections = [await lesson_section_public(db, s) for s in sections_rows]

    return LessonPublic(
        id=lesson.id,
        request_id=lesson.request_id,
        topic=lesson.topic,
        language=lesson.detected_language,
        grade_band=lesson.grade_band,
        subject=lesson.subject,
        objectives=objectives,
        measured_fkgl=lesson.measured_fkgl,
        lexile_band=lesson.lexile_band,
        estimated_duration_min=lesson.estimated_duration_min,
        sections=sections,
    )


async def quiz_public(db: AsyncSession, quiz: Quiz) -> QuizPublic:
    rows = (
        await db.execute(
            select(QuizQuestion, Item)
            .join(Item, Item.id == QuizQuestion.item_id)
            .where(QuizQuestion.quiz_id == quiz.id)
            .order_by(QuizQuestion.ordinal)
        )
    ).all()
    questions = [
        QuizQuestionPublic(
            question_id=qq.id,
            ordinal=qq.ordinal,
            points=qq.points,
            item=await item_public(db, item),
        )
        for qq, item in rows
    ]
    return QuizPublic(
        id=quiz.id,
        request_id=quiz.request_id,
        title=quiz.title,
        language=quiz.language,
        grade_band=quiz.grade_band,
        subject=quiz.subject,
        quiz_type=quiz.quiz_type,
        questions=questions,
    )

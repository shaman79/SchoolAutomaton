"""Concept graph, misconceptions, lessons (skeleton sections), the shared reviewable Item pool, and
per-(profile,item) FSRS cards. Items are shared by lessons and quizzes and carry ONE FSRS card per
learner (SPEC). Correct answers/explanations live here but are server-only at delivery."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, utcnow


class Concept(Base):
    __tablename__ = "concepts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    subject: Mapped[str] = mapped_column(String(40), index=True)
    grade_introduced: Mapped[str | None] = mapped_column(String(12), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConceptEdge(Base):
    __tablename__ = "concept_edges"
    __table_args__ = (UniqueConstraint("from_concept_id", "to_concept_id", "edge_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), index=True)
    to_concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), index=True)
    edge_type: Mapped[str] = mapped_column(String(16))  # prerequisite|related


class Misconception(Base):
    __tablename__ = "misconceptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), index=True)
    code: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text)
    refutation_text: Mapped[str] = mapped_column(Text)


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), index=True)
    topic: Mapped[str] = mapped_column(String(200))
    detected_language: Mapped[str] = mapped_column(String(12))
    # Learner-selected education-system locale (BCP-47, e.g. 'en-US'); None = generic. Stamped so
    # re-render / grading reproduce the same curriculum framing the lesson was generated under.
    education_locale: Mapped[str | None] = mapped_column(String(12), nullable=True)
    grade_band: Mapped[str] = mapped_column(String(12))
    subject: Mapped[str] = mapped_column(String(40))
    target_fkgl: Mapped[float] = mapped_column(Float)
    measured_fkgl: Mapped[float | None] = mapped_column(Float, nullable=True)
    readability_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    lexile_band: Mapped[str | None] = mapped_column(String(24), nullable=True)
    objectives_json: Mapped[list] = mapped_column(JSON)  # [{text, bloom_tier, concept_id}]
    # Frozen LessonPlan (stubs + objectives + concept graph) so sections can be generated lazily,
    # on demand, after the lesson is first delivered (progressive generation).
    plan_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    estimated_duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_id: Mapped[str] = mapped_column(String(48))
    prompt_version: Mapped[str] = mapped_column(String(20))
    content_cache_key: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LessonConcept(Base):
    __tablename__ = "lesson_concepts"
    __table_args__ = (UniqueConstraint("lesson_id", "concept_id", "relation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), index=True)
    concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), index=True)
    relation: Mapped[str] = mapped_column(String(28))  # taught|prerequisite|misconception_addressed


class LessonSection(Base):
    __tablename__ = "lesson_sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(28))  # SectionKind
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    body_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    gated: Mapped[bool] = mapped_column(Boolean, default=False)
    # Progressive generation: 'pending' (skeleton only) | 'ready' (filled) | 'error'. Defaults to
    # 'ready' so pre-existing rows + non-lazy paths behave exactly as before.
    gen_status: Mapped[str] = mapped_column(String(12), default="ready")
    section_measured_fkgl: Mapped[float | None] = mapped_column(Float, nullable=True)


class Item(Base):
    """The reviewable unit — shared across lessons (pretest/practice/checks) and quizzes.

    correct_answer / accepted_variants / distractors / worked_solution / explanation are SERVER-ONLY
    at delivery; the public ItemPublic schema omits them until grading reveals them."""

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_lesson_id: Mapped[int | None] = mapped_column(ForeignKey("lessons.id"), nullable=True)
    lesson_section_id: Mapped[int | None] = mapped_column(
        ForeignKey("lesson_sections.id"), nullable=True, index=True
    )
    concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), index=True)
    skill_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    item_type: Mapped[str] = mapped_column(String(16))  # ItemType
    bloom_tier: Mapped[int] = mapped_column(Integer)     # 1..6
    difficulty: Mapped[str] = mapped_column(String(8))   # easy|medium|hard
    item_difficulty: Mapped[int] = mapped_column(Integer, default=3)  # 1..5 adaptive
    language: Mapped[str] = mapped_column(String(12))
    stem_markdown: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[dict] = mapped_column(JSON)  # options[]/pairs[]/regions[]/blanks[]
    expected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted_variants_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    distractors_json: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{text, misconception_id}]
    hint_ladder_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    worked_solution_steps_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    p_correct: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_id: Mapped[str] = mapped_column(String(48))
    prompt_version: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ItemFsrsCard(Base):
    """Per-(profile,item) FSRS card. ``fsrs_card_json`` (py-fsrs Card.to_json()) is authoritative;
    the denormalized columns are read-only projections for indexing/scheduling queries."""

    __tablename__ = "item_fsrs_cards"
    __table_args__ = (UniqueConstraint("profile_id", "item_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    state: Mapped[int] = mapped_column(Integer, default=0)  # 0 New 1 Learning 2 Review 3 Relearning
    stability: Mapped[float | None] = mapped_column(Float, nullable=True)
    difficulty: Mapped[float | None] = mapped_column(Float, nullable=True)
    due: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    last_review: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reps: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    fsrs_card_json: Mapped[str] = mapped_column(Text)  # SOURCE OF TRUTH (raw to_json string)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SectionVisual(Base):
    """A lesson section's dual-coding visual, realized ASYNCHRONOUSLY so it never blocks the section
    text from appearing. Created ``pending`` when the section is filled; a background task generates
    the image (``ensure_visual``) and flips it to ``ready`` (with ``visual_asset_hash``) or ``failed``.

    The client renders a placeholder (reserved aspect ratio + alt text) while ``pending``/``generating``
    and swaps in the real asset on ``ready``. Distinct from :class:`AssetsRef`, which stays synchronous
    for hotspot/item images (a hotspot is unanswerable without its image)."""

    __tablename__ = "section_visuals"
    __table_args__ = (UniqueConstraint("lesson_section_id", "ordinal"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_section_id: Mapped[int] = mapped_column(
        ForeignKey("lesson_sections.id"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)  # order of the visual within the section
    visual_kind: Mapped[str] = mapped_column(String(24))  # VisualKind
    layout_slot: Mapped[str] = mapped_column(String(24))  # LayoutSlot
    alt_text: Mapped[str] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    spec_json: Mapped[dict] = mapped_column(JSON)  # the GenVisualSpec to realize (kid-safe, derived)
    # pending (queued) | generating (a worker claimed it) | ready (asset linked) | failed
    status: Mapped[str] = mapped_column(String(12), default="pending")
    visual_asset_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AssetsRef(Base):
    """Join between content (a section or item) and the content-addressed visual cache."""

    __tablename__ = "assets_refs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_section_id: Mapped[int | None] = mapped_column(
        ForeignKey("lesson_sections.id"), nullable=True, index=True
    )
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"), nullable=True, index=True)
    visual_asset_hash: Mapped[str] = mapped_column(ForeignKey("visual_assets.hash"), index=True)
    layout_slot: Mapped[str] = mapped_column(String(24))  # LayoutSlot
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    alt_text: Mapped[str] = mapped_column(Text)
    label_overlay_json: Mapped[list | None] = mapped_column(JSON, nullable=True)

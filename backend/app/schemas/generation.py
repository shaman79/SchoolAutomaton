"""Claude Opus 4.8 structured-output targets for generation + grading.

These models carry FULL correctness (answers, correct pairs/order, distractor→misconception). They are
persisted to ``items``/``lessons``; the public ``questions.py`` shapes are produced by stripping
correctness before delivery. All inherit ``StrictModel`` → ``additionalProperties:false`` (required by
4.8). Numeric/length bounds are enforced here + in prompts (4.8 strips schema min/max — SPEC §5)."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import Field

from .common import StrictModel
from .enums import BloomTier, Difficulty, ItemType, LayoutSlot, SectionKind, VisualKind
from .questions import MatchSidePublic, OrderTokenPublic


# --------------------------------------------------------------------------- generation payloads (w/ correctness)
class GenMcqOption(StrictModel):
    id: str
    text: str
    is_correct: bool = False


class GenMcqPayload(StrictModel):
    kind: Literal["mcq"] = "mcq"
    options: list[GenMcqOption]
    multiple: bool = False


class GenTrueFalsePayload(StrictModel):
    kind: Literal["true_false"] = "true_false"
    statement: str | None = None
    answer: bool


class GenClozeBlank(StrictModel):
    id: str
    answer: str
    choices: list[str] | None = None


class GenClozePayload(StrictModel):
    kind: Literal["cloze"] = "cloze"
    text_template: str
    blanks: list[GenClozeBlank]


class GenShortAnswerPayload(StrictModel):
    kind: Literal["short_answer"] = "short_answer"
    placeholder: str | None = None


class GenNumericPayload(StrictModel):
    kind: Literal["numeric"] = "numeric"
    answer: float
    tolerance: float = 0.0
    unit: str | None = None


class GenMatchPair(StrictModel):
    left_id: str
    right_id: str


class GenMatchPayload(StrictModel):
    kind: Literal["match"] = "match"
    left: list[MatchSidePublic]
    right: list[MatchSidePublic]
    correct: list[GenMatchPair]


class GenOrderPayload(StrictModel):
    kind: Literal["order"] = "order"
    tokens: list[OrderTokenPublic]
    correct_order: list[str]  # token ids in the correct sequence


class GenHotspotRegion(StrictModel):
    id: str
    shape: Literal["rect", "circle", "poly"]
    coords: list[float]
    label: str | None = None
    is_correct: bool = False


class GenHotspotPayload(StrictModel):
    kind: Literal["hotspot"] = "hotspot"
    image_request: str | None = None  # description for the visual pipeline (never raw student text)
    regions: list[GenHotspotRegion]


GenQuestionPayload = Annotated[
    GenMcqPayload | GenTrueFalsePayload | GenClozePayload | GenShortAnswerPayload | GenNumericPayload | GenMatchPayload | GenOrderPayload | GenHotspotPayload,
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------- generated item
class GenDistractor(StrictModel):
    text: str
    misconception: str | None = None  # short description; mapped to a misconception_id at persist


class GenItem(StrictModel):
    item_type: ItemType
    concept_slug: str
    bloom_tier: BloomTier
    difficulty: Difficulty = Difficulty.MEDIUM
    item_difficulty: int = Field(default=3, description="1..5 adaptive difficulty")
    stem_markdown: str
    # A plain object the model fills per item_type (shapes are described in the prompt). Kept loose
    # so the structured-output grammar stays small (a discriminated union of 8 payloads × lists made
    # the compiled grammar exceed Anthropic's size cap). It is validated/canonicalized in Python via
    # ``coerce_payload`` after generation.
    payload: dict[str, Any] = Field(default_factory=dict)
    expected_answer: str | None = None        # for short_answer / numeric canonical form
    accepted_variants: list[str] = Field(default_factory=list)
    distractors: list[GenDistractor] = Field(default_factory=list)
    hint_ladder: list[str] = Field(default_factory=list)
    worked_solution_steps: list[str] = Field(default_factory=list)
    explanation: str = ""
    points: int = 10


# Re-impose the per-type payload shape in Python (the schema is loosened to keep the grammar small).
_PAYLOAD_MODELS: dict[ItemType, type[StrictModel]] = {
    ItemType.MCQ: GenMcqPayload,
    ItemType.TRUE_FALSE: GenTrueFalsePayload,
    ItemType.CLOZE: GenClozePayload,
    ItemType.SHORT_ANSWER: GenShortAnswerPayload,
    ItemType.NUMERIC: GenNumericPayload,
    ItemType.MATCH: GenMatchPayload,
    ItemType.ORDER: GenOrderPayload,
    ItemType.HOTSPOT: GenHotspotPayload,
}


def _is_answerable(item_type: ItemType, d: dict[str, Any]) -> bool:
    """Semantic integrity: can a learner ANSWER this item AND can we GRADE it correctly?

    The schema is loosened (free-form dict) to keep the structured-output grammar small, which lets
    the model emit incomplete payloads — an MCQ with no option marked is_correct (everything grades
    wrong), a match with fewer right tokens than left prompts (impossible to complete), an order whose
    correct_order isn't a permutation of its tokens (never gradeable correct). We reject those so a
    broken item is dropped rather than shown to a learner."""
    if item_type == ItemType.MCQ:
        opts = d.get("options") or []
        return len(opts) >= 2 and any(o.get("is_correct") for o in opts)
    if item_type == ItemType.CLOZE:
        blanks = d.get("blanks") or []
        if not blanks or not all(str(b.get("answer") or "").strip() for b in blanks):
            return False
        # The template MUST mark every blank with a {{blank_id}} placeholder (and no stray markers),
        # mirroring the frontend regex — otherwise the blank renders no input and the learner is stuck
        # on an unanswerable question. Drop the item rather than ship it broken.
        markers = set(re.findall(r"\{\{\s*([\w-]+)\s*\}\}", str(d.get("text_template") or "")))
        ids = {str(b.get("id")) for b in blanks}
        return bool(markers) and markers == ids
    if item_type == ItemType.MATCH:
        left, right, correct = d.get("left") or [], d.get("right") or [], d.get("correct") or []
        left_ids = {x.get("id") for x in left}
        right_ids = {x.get("id") for x in right}
        if len(left) < 1 or len(right) < len(left) or not correct:
            return False  # need at least one token per prompt to be completable
        covered: set = set()
        for p in correct:
            if p.get("left_id") not in left_ids or p.get("right_id") not in right_ids:
                return False  # correct pair references a non-existent id → ungradeable
            covered.add(p.get("left_id"))
        return covered == left_ids  # every prompt has a correct match
    if item_type == ItemType.ORDER:
        toks = [t.get("id") for t in (d.get("tokens") or [])]
        order = d.get("correct_order") or []
        return len(toks) >= 2 and set(order) == set(toks) and len(order) == len(toks)
    if item_type == ItemType.HOTSPOT:
        regions = d.get("regions") or []
        return bool(regions) and any(r.get("is_correct") for r in regions) and bool(d.get("image_request"))
    # true_false (answer is a required field) and numeric (answer required) are validated by the
    # schema above; short_answer is graded against the item's expected_answer / the LLM grader.
    return True


def coerce_payload(item_type: ItemType, payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Validate + canonicalize a model payload, returning the canonical dict — or None if it is
    malformed OR not answerable/gradeable (the caller then DROPS the item rather than ship a broken
    question the learner can't answer or that grades a correct answer wrong)."""
    data = dict(payload or {})
    data.setdefault("kind", item_type.value)
    model = _PAYLOAD_MODELS.get(item_type)
    if model is None:
        return data or None
    try:
        canonical = model.model_validate(data).model_dump(mode="json")
    except Exception:  # noqa: BLE001 — malformed payload
        return None
    return canonical if _is_answerable(item_type, canonical) else None


# --------------------------------------------------------------------------- lesson generation
class GenObjective(StrictModel):
    text: str                       # "I can ..." statement
    bloom_tier: BloomTier
    concept_slug: str


class GenVisualSpec(StrictModel):
    section_ordinal: int
    visual_kind: VisualKind
    layout_slot: LayoutSlot = LayoutSlot.INLINE_FIGURE
    # Exactly one of these is used depending on SVG-vs-raster routing:
    svg_request: str | None = None   # instruction for the Claude-SVG generator
    image_prompt: str | None = None  # subject description for Replicate (kid-safe rewrite)
    alt_text: str
    caption: str | None = None


class GenConceptEdge(StrictModel):
    from_slug: str
    to_slug: str
    edge_type: Literal["prerequisite", "related"]


class LessonPlanStub(StrictModel):
    kind: SectionKind
    title: str
    objective: str | None = None
    needs_image: bool = False
    visual_kind: VisualKind | None = None
    concept_slug: str | None = None


class LessonPlan(StrictModel):
    """Step 1 of lesson generation: ordered section stubs + objectives + concept graph proposal."""

    topic: str
    language: str
    grade_band: str
    subject: str
    objectives: list[GenObjective]
    sections: list[LessonPlanStub]
    concept_edges: list[GenConceptEdge] = Field(default_factory=list)
    misconceptions: list[str] = Field(default_factory=list)
    estimated_duration_min: int | None = None


class GenSection(StrictModel):
    """Step 2: the filled body for one section of the plan."""

    kind: SectionKind
    title: str
    body_markdown: str = ""
    visual_requests: list[GenVisualSpec] = Field(default_factory=list)
    items: list[GenItem] = Field(default_factory=list)


# --------------------------------------------------------------------------- quiz generation
class GenQuiz(StrictModel):
    title: str
    language: str
    questions: list[GenItem]


# --------------------------------------------------------------------------- LLM grading (free-text/numeric)
class GraderOutput(StrictModel):
    correct: bool
    partial_credit: float = Field(default=0.0, description="0..1")
    concept_tags: list[str] = Field(default_factory=list)
    misconception: str | None = None
    explanation: str = ""
    encouragement_focus: Literal["effort", "strategy", "progress"] = "strategy"

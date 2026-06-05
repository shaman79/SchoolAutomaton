"""Claude Opus 4.8 structured-output targets for generation + grading.

These models carry FULL correctness (answers, correct pairs/order, distractor→misconception). They are
persisted to ``items``/``lessons``; the public ``questions.py`` shapes are produced by stripping
correctness before delivery. All inherit ``StrictModel`` → ``additionalProperties:false`` (required by
4.8). Numeric/length bounds are enforced here + in prompts (4.8 strips schema min/max — SPEC §5)."""

from __future__ import annotations

from typing import Annotated, Literal

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
    payload: GenQuestionPayload
    expected_answer: str | None = None        # for short_answer / numeric canonical form
    accepted_variants: list[str] = Field(default_factory=list)
    distractors: list[GenDistractor] = Field(default_factory=list)
    hint_ladder: list[str] = Field(default_factory=list)
    worked_solution_steps: list[str] = Field(default_factory=list)
    explanation: str = ""
    points: int = 10


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

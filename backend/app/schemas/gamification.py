"""Grading result + gamification response schemas (the reward layer's public contract)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from .common import AppModel
from .enums import NodeState
from .intent import CrisisResource
from .questions import check_submitted_value


# --------------------------------------------------------------------------- grading
class MisconceptionInfo(AppModel):
    description: str
    refutation: str


class FeedbackBlock(AppModel):
    """Growth-mindset feedback: praises strategy/process, never innate ability (SPEC pedagogy)."""

    text: str
    encouragement_focus: Literal["effort", "strategy", "progress"] = "strategy"


class BadgeAward(AppModel):
    code: str
    title: str
    tier: int = 1


class LevelUp(AppModel):
    from_level: int
    to_level: int


class AnswerSupport(AppModel):
    """Shown INSTEAD of a grade when a typed answer trips the deterministic self-harm net (the same
    one that screens prompts). Mirrors ``CrisisDecision``: localized message, curated human help lines
    (learner's country + global fallback) and the AI disclosure. Never LLM counseling."""

    message: str
    resources: list[CrisisResource] = []
    disclosure: str


class StreakInfo(AppModel):
    """The daily streak. In the gamification snapshot ``current`` is the streak as it stands now
    (0 once a gap can no longer be bridged — the stored length is only replaced when the learner
    is next active); in a settle result it includes today. ``frozen``: this settle bridged a missed
    day with a freeze or the repair window (never set in a snapshot)."""

    current: int = 0
    longest: int = 0
    freeze_inventory: int = 0
    is_perfect: bool = True
    frozen: bool = False


class GradeResult(AppModel):
    """Returned by POST /answers and POST /review/{item_id}. Reveals the correct answer HERE.

    When ``support`` is set the answer was NOT graded and nothing was saved (no answer row, no FSRS
    review, no XP): ``is_correct`` is false, ``partial_credit``/``xp_awarded`` are 0,
    ``correct_answer``/``explanation`` are null and ``fsrs_rating`` (1) carries no meaning."""

    is_correct: bool
    partial_credit: float = 0.0
    correct_answer: Any | None = None     # revealed at grading time, not at delivery
    fsrs_rating: int                       # 1..4 (derived server-side)
    next_due: datetime | None = None
    explanation: str | None = None
    misconception: MisconceptionInfo | None = None
    feedback: FeedbackBlock
    xp_awarded: int = 0
    combo_multiplier: float = 1.0
    mastery_delta: float = 0.0
    new_badges: list[BadgeAward] = []
    level_up: LevelUp | None = None
    support: AnswerSupport | None = None
    # The streak after this answer counted toward today (lets the header update without a refetch);
    # null when nothing was recorded (``support``) or for a replayed answer.
    streak: StreakInfo | None = None


# --------------------------------------------------------------------------- snapshots
class BadgeInfo(AppModel):
    code: str
    title: str
    description: str | None = None
    tier: int = 1
    unlocked_at: datetime | None = None
    progress_numerator: int = 0
    progress_denominator: int = 1
    icon_url: str | None = None


class GamificationSnapshot(AppModel):
    level: int
    total_xp: int
    xp_to_next: int
    level_progress_pct: float
    streak: StreakInfo
    daily_goal: str
    daily_progress_xp: int
    badges: list[BadgeInfo] = []


class MasteryChange(AppModel):
    concept_id: int
    name: str
    before: float
    after: float
    state: NodeState


class ResultsSummary(AppModel):
    """Returned by POST /attempts/{id}/complete."""

    score: int
    max_score: int
    accuracy: float
    xp_awarded: int
    combo_max: int
    new_badges: list[BadgeAward] = []
    streak: StreakInfo
    mastery_changes: list[MasteryChange] = []
    level_up: LevelUp | None = None


# --------------------------------------------------------------------------- review + tree
class ReviewComposition(AppModel):
    current: float = 0.55
    related: float = 0.25
    prereq: float = 0.20


class ReviewDueResponse(AppModel):
    items: list[Any] = []        # list[ItemPublic]; Any avoids a cross-module import cycle
    composition: ReviewComposition = ReviewComposition()


class ReviewRatingIn(AppModel):
    rating: int | None = None    # 1..4 explicit, OR provide the grading fields below
    submitted_value: Any | None = None  # same bounds as AnswerIn.submitted_value (422 beyond)
    used_hint: bool = False
    latency_ms: int | None = Field(default=None, ge=0)

    @field_validator("submitted_value")
    @classmethod
    def _bounded(cls, v: Any) -> Any:
        return check_submitted_value(v)


class TreeNode(AppModel):
    concept_id: int
    title: str
    subject: str
    mastery: float
    state: NodeState
    prereq_ids: list[int] = []
    related_ids: list[int] = []
    last_reviewed: datetime | None = None
    decay_due_at: datetime | None = None


class TreeEdge(AppModel):
    from_id: int
    to_id: int
    type: str  # prerequisite|related


class TreeResponse(AppModel):
    nodes: list[TreeNode] = []
    edges: list[TreeEdge] = []

"""Shared enumerations — the common vocabulary across sanitizer, generators, services and API.

These are part of the frozen contract (SPEC §5/§6). Implementation modules import from here;
they must not redefine these values locally.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class AgeBand(StrEnum):
    """Coarse developmental band used to gate mechanics and calibrate content."""

    EARLY_PRIMARY = "early_primary"      # ~5-7   (K-G2)
    PRIMARY = "primary"                  # ~8-11  (G3-G5)
    LOWER_SECONDARY = "lower_secondary"  # ~11-14 (G6-G8)
    UPPER_SECONDARY = "upper_secondary"  # ~14-18 (G9-G12)
    ADULT = "adult"                      # 18+
    UNKNOWN = "unknown"


class GradeBand(StrEnum):
    """Reading-level / curriculum band. Drives readability targets and Bloom weighting."""

    K = "K"
    G1_2 = "G1-2"
    G3_5 = "G3-5"
    G6_8 = "G6-8"
    G9_12 = "G9-12"
    ADULT = "adult"
    UNKNOWN = "unknown"


class Mode(StrEnum):
    """What the student asked for."""

    STUDY = "study"
    TEST = "test"


class DecisionType(StrEnum):
    """Outcome of the sanitization pipeline (the Decision tagged union discriminator)."""

    PROCEED = "proceed"
    CLARIFY = "clarify"
    REFUSE = "refuse"
    CRISIS = "crisis"


class Subject(StrEnum):
    """Allowlisted high-level subjects. `OTHER` keeps the allowlist open without losing the gate."""

    MATH = "math"
    SCIENCE = "science"
    BIOLOGY = "biology"
    CHEMISTRY = "chemistry"
    PHYSICS = "physics"
    GEOGRAPHY = "geography"
    HISTORY = "history"
    LANGUAGE_ARTS = "language_arts"
    FOREIGN_LANGUAGE = "foreign_language"
    SOCIAL_STUDIES = "social_studies"
    COMPUTER_SCIENCE = "computer_science"
    ARTS = "arts"
    MUSIC = "music"
    HEALTH = "health"
    ECONOMICS = "economics"
    PHILOSOPHY = "philosophy"
    OTHER = "other"


class SafetyFlag(StrEnum):
    """Child-safety categories raised by the classifier/safety layer."""

    SELF_HARM = "self_harm"
    SEXUAL = "sexual"
    VIOLENCE = "violence"
    ILLEGAL_DANGEROUS = "illegal_dangerous"
    HATE_HARASSMENT = "hate_harassment"
    PII_SOLICITATION = "pii_solicitation"
    ACADEMIC_INTEGRITY = "academic_integrity"


class ItemType(StrEnum):
    """The typed reviewable units / question kinds."""

    MCQ = "mcq"
    TRUE_FALSE = "true_false"
    CLOZE = "cloze"                # fill-in-the-blank
    SHORT_ANSWER = "short_answer"  # LLM-graded free text
    NUMERIC = "numeric"            # tolerant numeric grading
    MATCH = "match"               # drag-drop pairing
    ORDER = "order"               # sequencing / ordering
    HOTSPOT = "hotspot"           # click/tap a region on an image


class BloomTier(IntEnum):
    """Bloom's revised taxonomy levels (difficulty spine)."""

    REMEMBER = 1
    UNDERSTAND = 2
    APPLY = 3
    ANALYZE = 4
    EVALUATE = 5
    CREATE = 6


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class SectionKind(StrEnum):
    """The fixed, ordered lesson skeleton (SPEC pedagogy framework)."""

    HOOK = "hook"
    OBJECTIVES = "objectives"
    PRIOR_KNOWLEDGE = "prior_knowledge"
    PRETEST = "pretest"
    EXPLANATION = "explanation"
    WORKED_EXAMPLE = "worked_example"
    FADED_EXAMPLE = "faded_example"
    PRACTICE = "practice"
    INTERLEAVED_REVIEW = "interleaved_review"
    ELABORATION = "elaboration"
    MISCONCEPTION_CHECK = "misconception_check"
    SUMMARY = "summary"


# Canonical render order of the lesson skeleton.
LESSON_SKELETON: tuple[SectionKind, ...] = (
    SectionKind.HOOK,
    SectionKind.OBJECTIVES,
    SectionKind.PRIOR_KNOWLEDGE,
    SectionKind.PRETEST,
    SectionKind.EXPLANATION,
    SectionKind.WORKED_EXAMPLE,
    SectionKind.FADED_EXAMPLE,
    SectionKind.PRACTICE,
    SectionKind.INTERLEAVED_REVIEW,
    SectionKind.ELABORATION,
    SectionKind.MISCONCEPTION_CHECK,
    SectionKind.SUMMARY,
)

# Sections that contain interactive items (used for gating + SSE).
INTERACTIVE_SECTIONS: frozenset[SectionKind] = frozenset(
    {SectionKind.PRETEST, SectionKind.PRACTICE, SectionKind.INTERLEAVED_REVIEW,
     SectionKind.MISCONCEPTION_CHECK}
)


class VisualKind(StrEnum):
    """What kind of visual a lesson/visual-spec step requests; routes to SVG vs raster vs video."""

    DIAGRAM = "diagram"
    CHART = "chart"
    LABELED_FIGURE = "labeled_figure"
    CYCLE = "cycle"
    TIMELINE = "timeline"
    GEOMETRY = "geometry"
    NUMBER_LINE = "number_line"
    FOOD_CHAIN = "food_chain"
    MAP = "map"
    ILLUSTRATION = "illustration"
    SCENE = "scene"
    CHARACTER = "character"
    PHOTO = "photo"
    ICON = "icon"
    DECORATIVE = "decorative"


class AssetType(StrEnum):
    SVG = "svg"
    RASTER = "raster"
    SVG_ICON = "svg_icon"
    VIDEO = "video"


class LayoutSlot(StrEnum):
    """Where a visual sits; derives Replicate aspect/MP/model tier and the Tailwind aspect class."""

    HERO = "HERO"                              # 16:9
    INLINE_FIGURE = "INLINE_FIGURE"            # 4:3 / 1:1
    QUIZ_THUMB = "QUIZ_THUMB"                  # 1:1 small
    PORTRAIT_CHARACTER = "PORTRAIT_CHARACTER"  # 3:4
    FULL_BLEED_MOBILE = "FULL_BLEED_MOBILE"    # 9:16


class NodeState(StrEnum):
    """Knowledge-tree node state, derived from mastery + FSRS due."""

    LOCKED = "locked"
    AVAILABLE = "available"
    LEARNING = "learning"
    MASTERED = "mastered"
    NEEDS_REVIEW = "needs_review"


class FsrsRating(IntEnum):
    """py-fsrs rating. Derived deterministically server-side (SPEC §4 #6)."""

    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


class XpReason(StrEnum):
    FIRST_TRY_CORRECT = "first_try_correct"
    SPACED_RETENTION = "spaced_retention"
    MASTERY_GAIN = "mastery_gain"
    COMEBACK = "comeback"
    COMBO_BONUS = "combo_bonus"
    DAILY_GOAL = "daily_goal"
    BADGE = "badge"


class QuizType(StrEnum):
    STANDARD = "standard"
    TIMED_SPRINT = "timed_sprint"
    BOSS_REVIEW = "boss_review"
    NO_HINT = "no_hint"
    EXPLAIN_IT = "explain_it"


class RequestStatus(StrEnum):
    QUEUED = "queued"
    GENERATING = "generating"
    READY = "ready"
    ERROR = "error"


class DailyGoal(StrEnum):
    CASUAL = "casual"      # ~5 min / ~50 XP
    REGULAR = "regular"    # ~10 min / ~100 XP
    SERIOUS = "serious"    # ~15 min / ~150 XP
    INTENSE = "intense"    # ~20 min / ~200 XP

"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from __future__ import annotations

from .admin import AdminUser, AppSetting, GenerationUsage
from .content import (
    AssetsRef,
    Concept,
    ConceptEdge,
    Item,
    ItemFsrsCard,
    Lesson,
    LessonConcept,
    LessonSection,
    Misconception,
    SectionVisual,
)
from .gamification import BadgeDefinition, ProfileBadge, SkillMastery, XpEvent
from .learning import LearningRequest, SanitizationAudit
from .profile import Profile, ProfileSettings, StreakState
from .quiz import Answer, Quiz, QuizAttempt, QuizQuestion
from .visual import VisualAsset

__all__ = [
    "AdminUser",
    "AppSetting",
    "GenerationUsage",
    "AssetsRef",
    "Concept",
    "ConceptEdge",
    "Item",
    "ItemFsrsCard",
    "Lesson",
    "LessonConcept",
    "LessonSection",
    "Misconception",
    "SectionVisual",
    "BadgeDefinition",
    "ProfileBadge",
    "SkillMastery",
    "XpEvent",
    "LearningRequest",
    "SanitizationAudit",
    "Profile",
    "ProfileSettings",
    "StreakState",
    "Answer",
    "Quiz",
    "QuizAttempt",
    "QuizQuestion",
    "VisualAsset",
]

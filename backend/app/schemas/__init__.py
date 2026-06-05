"""Pydantic schemas — the shared contract between sanitizer, generators, services and API.

Anti-drift seam (SPEC §6): the sanitizer and generators import the SAME models from here, and FastAPI's
OpenAPI (built from these) generates ``frontend/src/types/api.ts`` via ``openapi-typescript``."""

from __future__ import annotations

from . import enums
from .admin import (
    AdminLoginIn,
    AuditRecord,
    ContentRecord,
    DashboardOut,
    SettingItem,
    SettingUpdateIn,
    TokenOut,
)
from .common import AppModel, ErrorResponse, Page, StrictModel
from .content import (
    AssetRefPublic,
    LessonObjectivePublic,
    LessonPublic,
    LessonSectionPublic,
)
from .gamification import (
    BadgeAward,
    BadgeInfo,
    FeedbackBlock,
    GamificationSnapshot,
    GradeResult,
    LevelUp,
    MasteryChange,
    MisconceptionInfo,
    ResultsSummary,
    ReviewComposition,
    ReviewDueResponse,
    ReviewRatingIn,
    StreakInfo,
    TreeEdge,
    TreeNode,
    TreeResponse,
)
from .generation import (
    GenItem,
    GenObjective,
    GenQuiz,
    GenSection,
    GenVisualSpec,
    GraderOutput,
    LessonPlan,
    LessonPlanStub,
)
from .intent import (
    ClarifyDecision,
    CreateRequestIn,
    CrisisDecision,
    CrisisResource,
    Decision,
    ProceedDecision,
    RefuseDecision,
    StructuredIntent,
)
from .profile import (
    CreateProfileIn,
    ProfileCreateOut,
    ProfileEnvelope,
    ProfilePublic,
    ProfileSettingsPublic,
    ProfileSettingsUpdate,
    ResumeIn,
)
from .questions import AnswerIn, ItemPublic, QuestionPayload
from .quiz import AttemptStartOut, QuizPublic, QuizQuestionPublic

__all__ = [
    "enums",
    # common
    "AppModel", "StrictModel", "Page", "ErrorResponse",
    # intent / decision
    "StructuredIntent", "Decision", "ProceedDecision", "ClarifyDecision",
    "RefuseDecision", "CrisisDecision", "CrisisResource", "CreateRequestIn",
    # generation
    "LessonPlan", "LessonPlanStub", "GenSection", "GenItem", "GenObjective",
    "GenVisualSpec", "GenQuiz", "GraderOutput",
    # content public
    "LessonPublic", "LessonSectionPublic", "LessonObjectivePublic", "AssetRefPublic",
    # questions
    "ItemPublic", "QuestionPayload", "AnswerIn",
    # quiz public
    "QuizPublic", "QuizQuestionPublic", "AttemptStartOut",
    # gamification
    "GradeResult", "ResultsSummary", "GamificationSnapshot", "StreakInfo", "BadgeInfo",
    "BadgeAward", "LevelUp", "MasteryChange", "MisconceptionInfo", "FeedbackBlock",
    "ReviewDueResponse", "ReviewComposition", "ReviewRatingIn", "TreeResponse", "TreeNode", "TreeEdge",
    # profile
    "ProfileEnvelope", "ProfilePublic", "ProfileSettingsPublic", "ProfileSettingsUpdate",
    "CreateProfileIn", "ResumeIn", "ProfileCreateOut",
    # admin
    "AdminLoginIn", "TokenOut", "DashboardOut", "AuditRecord", "SettingItem",
    "SettingUpdateIn", "ContentRecord",
]

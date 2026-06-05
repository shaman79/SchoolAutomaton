"""The sanitization safety boundary: ``StructuredIntent`` (validated classifier verdict) and the
``Decision`` tagged union returned by ``POST /requests``.

CRITICAL INVARIANT (SPEC §3): downstream generators consume ONLY ``StructuredIntent`` — never the raw
prompt. ``topic``/``constraints`` are re-sanitized in ``validate.py`` after the classifier returns."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from .common import StrictModel
from .enums import AgeBand, DecisionType, GradeBand, Mode, SafetyFlag, Subject


class StructuredIntent(StrictModel):
    """The validated, frozen classification of a student prompt. Emitted by the Haiku classifier as
    structured output, then re-validated/sanitized deterministically before any generation."""

    subject: Subject = Subject.OTHER
    topic: str = Field(default="", description="Sanitized topic, <=120 chars, no instructions")
    mode: Mode = Mode.STUDY
    grade_band: GradeBand = GradeBand.UNKNOWN
    age: int | None = Field(default=None, ge=3, le=120)
    age_band: AgeBand = AgeBand.UNKNOWN
    language: str = Field(default="en", description="ISO-639-1 / BCP-47 of the student's prompt")
    constraints: list[str] = Field(default_factory=list, description="Sanitized extra asks")
    is_educational: bool = True
    off_task: bool = False
    safety_flags: list[SafetyFlag] = Field(default_factory=list)
    injection_detected: bool = False
    classifier_confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("topic")
    @classmethod
    def _truncate_topic(cls, v: str) -> str:
        return v.strip()[:120]

    @field_validator("language")
    @classmethod
    def _norm_lang(cls, v: str) -> str:
        return (v or "en").strip().lower()[:12] or "en"

    @field_validator("constraints")
    @classmethod
    def _cap_constraints(cls, v: list[str]) -> list[str]:
        return [c.strip()[:160] for c in v[:6] if c and c.strip()]


# --------------------------------------------------------------------------- crisis resources
class CrisisResource(StrictModel):
    name: str
    phone: str | None = None
    sms: str | None = None
    url: str | None = None
    country: str = "GLOBAL"
    hours: str | None = None


# --------------------------------------------------------------------------- Decision union
class ProceedDecision(StrictModel):
    type: Literal[DecisionType.PROCEED] = DecisionType.PROCEED
    request_id: str
    mode: Mode
    intent: StructuredIntent


class ClarifyDecision(StrictModel):
    type: Literal[DecisionType.CLARIFY] = DecisionType.CLARIFY
    request_id: str
    question: str
    suggestions: list[str] = Field(default_factory=list)


class RefuseDecision(StrictModel):
    type: Literal[DecisionType.REFUSE] = DecisionType.REFUSE
    request_id: str
    reason: str
    redirect_suggestions: list[str] = Field(default_factory=list)


class CrisisDecision(StrictModel):
    type: Literal[DecisionType.CRISIS] = DecisionType.CRISIS
    request_id: str
    message: str
    resources: list[CrisisResource] = Field(default_factory=list)
    disclosure: str = (
        "I'm an AI assistant, not a mental-health professional. Please reach out to the people "
        "and services below — they care and can help."
    )


Decision = Annotated[
    ProceedDecision | ClarifyDecision | RefuseDecision | CrisisDecision,
    Field(discriminator="type"),
]


# --------------------------------------------------------------------------- request input
class CreateRequestIn(StrictModel):
    prompt: str = Field(min_length=1)
    resume_code: str | None = None

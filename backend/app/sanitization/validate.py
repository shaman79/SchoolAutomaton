"""Layer 3 — deterministic validate + route (SPEC §5). This is the real breakout containment: we do
NOT trust the classifier alone. We re-validate every field against the frozen enums, RE-SANITIZE the
topic/constraints (running them back through Layer-1 preprocessing), then build the ``Decision`` tagged
union.

Routing (in priority order):
  1. ``self_harm`` flag                -> CrisisDecision (localized resources, no LLM counseling)
  2. other safety flags                -> RefuseDecision (+ redirect)
  3. not educational OR off-task       -> RefuseDecision (+ redirect)
  4. classifier_confidence < 0.5       -> ClarifyDecision
  5. otherwise                         -> ProceedDecision with CLEAN fields only

``injection_detected`` never blocks by itself: we proceed with sanitized fields and keep the flag.
The returned Decision carries ONLY a validated ``StructuredIntent`` — never raw text.
"""

from __future__ import annotations

import re

from ..schemas.enums import DecisionType, GradeBand, Mode, SafetyFlag, Subject
from ..schemas.intent import (
    ClarifyDecision,
    CrisisDecision,
    Decision,
    ProceedDecision,
    RefuseDecision,
    StructuredIntent,
)
from . import safety
from .preprocess import preprocess

CONFIDENCE_CLARIFY_THRESHOLD = 0.5

_REFUSAL_REASON = (
    "I can only help with school and learning topics, and I keep things safe for everyone. "
    "Let's find a great subject to study instead!"
)
_CLARIFY_QUESTION = (
    "I want to help! Could you tell me a bit more about what you'd like to learn, and roughly what "
    "grade or age level?"
)
_CLARIFY_SUGGESTIONS = (
    "Photosynthesis for 5th grade",
    "Quiz me on fractions",
    "Explain the water cycle",
)


# Instruction / injection lead-ins to strip from the *topic* so no imperative ever survives into a
# generator prompt. These are deterministic, allowlist-safe (they only remove leading command verbs
# and known override phrases — the remaining noun phrase is the study subject).
_INJECTION_PHRASE_RE = re.compile(
    r"\b(ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}?"
    r"\b(instruction|prompt|rule|direction|command|context|message|guideline)s?\b"
    r"|you\s+are\s+(now|from\s+now\s+on)\b[^.\n]*"
    r"|\b(system\s*prompt|reveal\s+your\s+(prompt|rules|instructions)|"
    r"repeat\s+the\s+(above|text\s+above))\b[^.\n]*",
    re.IGNORECASE,
)
_ROLE_MARKER_RE = re.compile(
    r"^\s*(assistant|system|user|human|ai)\s*[:>\]]\s*", re.IGNORECASE | re.MULTILINE
)
_LEADING_IMPERATIVE_RE = re.compile(
    r"^\s*(please\s+)?(can\s+you\s+)?(help\s+me\s+)?"
    r"(teach|tell|show|explain|quiz|test|give|i\s+want\s+to\s+learn|"
    r"i\s+would\s+like\s+to\s+learn|learn)\b"
    r"\s*(me|us)?\s*(about|on|the|a|an)?\s*",
    re.IGNORECASE,
)


def _resanitize_text(value: str) -> str:
    """Run a string back through Layer-1 preprocessing (NFKC + strip invisibles/bidi/controls)."""
    return preprocess(value or "").clean_text


def _scrub_topic(value: str) -> str:
    """Strip any instruction/injection lead-ins from the topic, leaving only the study subject.

    Deterministic defense-in-depth: even though generators consume only StructuredIntent, the topic
    string must not carry an imperative the generator could echo. We remove override phrases and a
    leading command verb, then collapse leftover punctuation/connectors.
    """
    cleaned = _resanitize_text(value)
    cleaned = _ROLE_MARKER_RE.sub(" ", cleaned)
    cleaned = _INJECTION_PHRASE_RE.sub(" ", cleaned)
    # Remove a single leading imperative ("teach me about ...").
    cleaned = _LEADING_IMPERATIVE_RE.sub("", cleaned)
    # Drop leftover connector words / 'and also' joins from removed clauses.
    cleaned = re.sub(r"\b(also|and|then|plus)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,!?;:-")
    return cleaned[:120]


def _coerce_enum(value, enum_cls, default):
    """Best-effort coerce a (possibly model-emitted) value to an allowlisted enum member."""
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except (ValueError, KeyError, TypeError):
        return default


def revalidate_intent(intent: StructuredIntent) -> StructuredIntent:
    """Re-check enums + re-sanitize free-text fields. Returns a fresh, clean StructuredIntent.

    Re-construction through the frozen Pydantic model re-applies its validators (topic truncation,
    language normalization, constraint capping) and re-enforces ``additionalProperties:false``.
    """
    subject = _coerce_enum(intent.subject, Subject, Subject.OTHER)
    mode = _coerce_enum(intent.mode, Mode, Mode.STUDY)
    grade_band = _coerce_enum(intent.grade_band, GradeBand, GradeBand.UNKNOWN)

    clean_flags: list[SafetyFlag] = []
    for flag in intent.safety_flags or []:
        coerced = _coerce_enum(flag, SafetyFlag, None)
        if coerced is not None and coerced not in clean_flags:
            clean_flags.append(coerced)

    clean_topic = _scrub_topic(intent.topic)
    clean_constraints = [
        scrubbed
        for scrubbed in (_scrub_topic(c) for c in (intent.constraints or []))
        if scrubbed
    ]

    return StructuredIntent(
        subject=subject,
        topic=clean_topic,
        mode=mode,
        grade_band=grade_band,
        age=intent.age,
        age_band=intent.age_band,
        language=intent.language,
        constraints=clean_constraints,
        is_educational=bool(intent.is_educational),
        off_task=bool(intent.off_task),
        safety_flags=clean_flags,
        injection_detected=bool(intent.injection_detected),
        classifier_confidence=float(intent.classifier_confidence),
    )


def build_decision(
    intent: StructuredIntent,
    request_id: str,
    *,
    country: str | None = None,
) -> Decision:
    """Deterministically route a (raw, unvalidated) classifier verdict to a Decision.

    Always re-validates the intent first. The country hint (optional) localizes crisis resources.
    """
    clean = revalidate_intent(intent)

    # 1) Crisis — self-harm always wins, regardless of anything else.
    if safety.is_crisis(clean.safety_flags):
        card = safety.crisis_card_copy(clean.language)
        message = card["message"] or (
            "It sounds like you might be going through something really hard. You're not alone, and "
            "help is available."
        )
        return CrisisDecision(
            request_id=request_id,
            message=message,
            resources=safety.select_crisis_resources(clean.language, country),
            disclosure=safety.crisis_disclosure(clean.language),
        )

    # Apply age/grade context to avoid over-blocking legitimate older-student topics.
    effective_flags = safety.filter_safety_flags(clean)

    # 2) Other safety flags -> refuse + redirect.
    if effective_flags:
        return RefuseDecision(
            request_id=request_id,
            reason=_REFUSAL_REASON,
            redirect_suggestions=safety.refusal_redirect_suggestions(clean),
        )

    # 3) Not educational or off-task -> refuse + redirect.
    if (not clean.is_educational) or clean.off_task:
        return RefuseDecision(
            request_id=request_id,
            reason=_REFUSAL_REASON,
            redirect_suggestions=safety.refusal_redirect_suggestions(clean),
        )

    # 4) Low confidence -> clarify.
    if clean.classifier_confidence < CONFIDENCE_CLARIFY_THRESHOLD:
        return ClarifyDecision(
            request_id=request_id,
            question=_CLARIFY_QUESTION,
            suggestions=list(_CLARIFY_SUGGESTIONS),
        )

    # 5) Proceed — with CLEAN fields only. If injection was detected we proceed anyway, but the
    #    free-text topic/constraints are NOT trusted: scrubbing is best-effort against arbitrary
    #    payloads, so we drop them entirely and let the generator key off the (enum) subject. The
    #    injection_detected flag is preserved for the generator + audit.
    if clean.injection_detected:
        proceed_intent = clean.model_copy(
            update={"topic": "", "constraints": []}
        )
    else:
        proceed_intent = clean

    return ProceedDecision(
        request_id=request_id,
        type=DecisionType.PROCEED,
        mode=proceed_intent.mode,
        intent=proceed_intent,
    )

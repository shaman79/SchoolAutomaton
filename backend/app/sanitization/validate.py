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

from ..schemas.enums import (
    AgeBand,
    DecisionType,
    GradeBand,
    Mode,
    SafetyFlag,
    Subject,
    grade_band_for_school_year,
    normalize_school_year,
)
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

# Localized by the DETECTED prompt language (falls back to English). Keep generic + friendly.
_REFUSAL_REASON: dict[str, str] = {
    "en": "I can only help with school and learning topics, and I keep things safe for everyone. "
    "Let's find a great subject to study instead!",
    "cs": "Pomáhám jen se školními a vzdělávacími tématy a dbám na to, aby bylo všechno bezpečné. "
    "Pojďme najít skvělé téma ke studiu!",
}
_CLARIFY_QUESTION: dict[str, str] = {
    "en": "I want to help! Could you tell me a bit more about what you'd like to learn, and roughly "
    "what grade or age level?",
    "cs": "Pomůžu ti! Můžeš mi prozradit trochu víc o tom, co se chceš naučit, a do jaké chodíš "
    "třídy?",
}
# When the learner's class setting is known, don't ask for the grade again.
_CLARIFY_QUESTION_CLASS_KNOWN: dict[str, str] = {
    "en": "I want to help! Could you tell me a bit more about what you'd like to learn?",
    "cs": "Pomůžu ti! Můžeš mi prozradit trochu víc o tom, co se chceš naučit?",
}
# No grade in the suggestions: a tapped chip becomes the prompt, and a stated grade would override
# the learner's own class setting (the prompt always wins).
_CLARIFY_SUGGESTIONS: dict[str, tuple[str, ...]] = {
    "en": ("The water cycle", "Quiz me on fractions", "Basics of optics"),
    "cs": ("Koloběh vody", "Vyzkoušej mě ze zlomků", "Vyjmenovaná slova po B"),
}


def _loc(table: dict, language: str | None):
    """Pick a localized string/tuple by language (2-letter), falling back to English."""
    return table.get((language or "en")[:2].lower(), table["en"])


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
    # A stated exact school year is authoritative over the coarse band (keeps the two consistent).
    school_year = normalize_school_year(intent.school_year)
    if school_year is not None:
        grade_band = grade_band_for_school_year(school_year)

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
        school_year=school_year,
        age=intent.age,
        age_band=intent.age_band,
        language=intent.language,
        # education_locale is NOT a classification — it is the learner's setting, admitted only on the
        # proceed branch of build_decision from the trusted client locale. Force None here so any value
        # the (tool-use) classifier hallucinated into the schema is dropped.
        education_locale=None,
        constraints=clean_constraints,
        is_educational=bool(intent.is_educational),
        off_task=bool(intent.off_task),
        safety_flags=clean_flags,
        injection_detected=bool(intent.injection_detected),
        classifier_confidence=float(intent.classifier_confidence),
    )


def _apply_class_setting(intent: StructuredIntent, client_school_year: int | None) -> StructuredIntent:
    """Fill in the learner's class setting ("Moje třída") when the prompt itself names no level.

    The prompt always wins: the setting is used only when the classifier found no school year AND its
    band is either unknown (with no stated age or age band) or already the setting's own band — so a
    learner who explicitly asks for another level ("pro 7. třídu", "high school") still gets exactly
    that. One exception to the refinement: G9-12 spans the 9th grade of basic school (RVP ZV) AND
    upper-secondary school, so a 9th grader asking for "střední škola" level must not be narrowed back
    to 9. třída — the setting never refines G9-12 to year 9."""
    year = normalize_school_year(client_school_year)
    if year is None or intent.school_year is not None:
        return intent
    band = grade_band_for_school_year(year)
    unstated = (
        intent.grade_band == GradeBand.UNKNOWN
        and intent.age is None
        and intent.age_band == AgeBand.UNKNOWN
    )
    refines = intent.grade_band == band and not (band == GradeBand.G9_12 and year == 9)
    if unstated or refines:
        return intent.model_copy(update={"school_year": year, "grade_band": band})
    return intent


def build_decision(
    intent: StructuredIntent,
    request_id: str,
    *,
    country: str | None = None,
    client_locale: str | None = None,
    client_school_year: int | None = None,
) -> Decision:
    """Deterministically route a (raw, unvalidated) classifier verdict to a Decision.

    Always re-validates the intent first. ``client_locale`` is the learner's trusted education-system
    setting (e.g. 'en-GB'): on the PROCEED branch it pins ``education_locale`` + the output ``language``
    (decision 1a). It also derives the crisis-resource ``country`` when not given. It is applied AFTER
    safety routing so crisis/refuse/clarify copy stays keyed on the genuinely DETECTED language (never
    mislocalizing a child's crisis resources to the device setting). ``client_school_year`` (the
    learner's class setting) is likewise merged on the proceed branch only — see _apply_class_setting.
    """
    # Pure helpers live with the curriculum registry; lazy import avoids any import-time coupling.
    from ..llm.prompts.curriculum import base_language, country_of, normalize_education_locale

    edu_locale = normalize_education_locale(client_locale)
    if country is None:
        country = country_of(edu_locale)

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

    lang = clean.language

    # 2) Other safety flags -> refuse + redirect.
    if effective_flags:
        return RefuseDecision(
            request_id=request_id,
            reason=_loc(_REFUSAL_REASON, lang),
            redirect_suggestions=safety.refusal_redirect_suggestions(clean),
        )

    # 3) Not educational or off-task -> refuse + redirect.
    if (not clean.is_educational) or clean.off_task:
        return RefuseDecision(
            request_id=request_id,
            reason=_loc(_REFUSAL_REASON, lang),
            redirect_suggestions=safety.refusal_redirect_suggestions(clean),
        )

    # 4) Low confidence -> clarify.
    if clean.classifier_confidence < CONFIDENCE_CLARIFY_THRESHOLD:
        class_known = normalize_school_year(client_school_year) is not None
        return ClarifyDecision(
            request_id=request_id,
            question=_loc(_CLARIFY_QUESTION_CLASS_KNOWN if class_known else _CLARIFY_QUESTION, lang),
            suggestions=list(_loc(_CLARIFY_SUGGESTIONS, lang)),
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

    # Apply the learner's education-system setting (decision 1a: it drives BOTH the curriculum and the
    # output language). Done here, on the proceed path only, so the override never touches the
    # crisis/refuse/clarify localization above.
    if edu_locale:
        proceed_intent = proceed_intent.model_copy(
            update={
                "education_locale": edu_locale,
                "language": base_language(edu_locale) or proceed_intent.language,
            }
        )
    proceed_intent = _apply_class_setting(proceed_intent, client_school_year)

    return ProceedDecision(
        request_id=request_id,
        type=DecisionType.PROCEED,
        mode=proceed_intent.mode,
        intent=proceed_intent,
    )

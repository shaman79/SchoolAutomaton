"""Layer 4 — child-safety helpers + crisis-resource selection + AI-disclosure copy (SPEC §5).

This module is deterministic and does NO LLM counseling. It turns the classifier's ``safety_flags``
into a routing intent (crisis vs refuse), selects localized crisis resources from
``app/data/crisis_resources.yaml`` (country + global fallback), supplies localized card/disclosure
copy, and uses ``grade_band``/``age`` to AVOID over-blocking legitimate older-student topics
(WWII, human reproduction, chemistry) that merely brush a safety category.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from ..schemas.enums import AgeBand, GradeBand, SafetyFlag
from ..schemas.intent import CrisisResource, StructuredIntent

_CRISIS_PATH = Path(__file__).resolve().parent.parent / "data" / "crisis_resources.yaml"

# Hard flags that always refuse regardless of age (no legitimate study framing for a child-facing app).
_ALWAYS_REFUSE: frozenset[SafetyFlag] = frozenset(
    {
        SafetyFlag.SEXUAL,
        SafetyFlag.HATE_HARASSMENT,
        SafetyFlag.PII_SOLICITATION,
        SafetyFlag.ILLEGAL_DANGEROUS,
    }
)

# Flags where age/grade context can legitimately permit the topic as academic study.
# (e.g. "violence in WWII" for an upper-secondary history student is educational, not a safety block.)
_CONTEXT_SENSITIVE: frozenset[SafetyFlag] = frozenset(
    {SafetyFlag.VIOLENCE}
)

# Older-student bands where curricular topics that brush "violence" are normal study material.
_OLDER_BANDS: frozenset[GradeBand] = frozenset(
    {GradeBand.G6_8, GradeBand.G9_12, GradeBand.ADULT}
)
_OLDER_AGE_BANDS: frozenset[AgeBand] = frozenset(
    {AgeBand.LOWER_SECONDARY, AgeBand.UPPER_SECONDARY, AgeBand.ADULT}
)
_OLDER_MIN_AGE = 11


@lru_cache(maxsize=1)
def _load_crisis_doc() -> dict:
    try:
        with _CRISIS_PATH.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _lang_key(language: str, mapping: dict) -> str:
    """Pick the best language key from a localized mapping, falling back to 'en'."""
    lang = (language or "en").strip().lower()
    if lang in mapping:
        return lang
    short = lang.split("-")[0]
    if short in mapping:
        return short
    return "en"


def is_crisis(safety_flags: list[SafetyFlag]) -> bool:
    """Self-harm is the only crisis route (localized resources, never LLM counseling)."""
    return SafetyFlag.SELF_HARM in safety_flags


def _is_older_student(intent: StructuredIntent) -> bool:
    if intent.grade_band in _OLDER_BANDS:
        return True
    if intent.age_band in _OLDER_AGE_BANDS:
        return True
    return intent.age is not None and intent.age >= _OLDER_MIN_AGE


def filter_safety_flags(intent: StructuredIntent) -> list[SafetyFlag]:
    """Drop *context-sensitive* flags when an older student is plainly studying the topic.

    Self-harm and the always-refuse categories are never relaxed. Only flags like ``violence`` are
    cleared, and only when (a) the student is older AND (b) the prompt is marked educational and not
    off-task — i.e. legitimate curriculum (WWII, reproduction in biology, chemistry safety).
    """
    if not intent.safety_flags:
        return []
    older = _is_older_student(intent)
    educational = intent.is_educational and not intent.off_task
    kept: list[SafetyFlag] = []
    for flag in intent.safety_flags:
        if flag in _CONTEXT_SENSITIVE and older and educational:
            continue  # legitimate older-student academic topic — do not over-block
        kept.append(flag)
    return kept


def select_crisis_resources(language: str, country: str | None = None) -> list[CrisisResource]:
    """Localized country resources (if known) followed by the always-on global fallback."""
    doc = _load_crisis_doc()
    out: list[CrisisResource] = []
    countries = doc.get("countries", {}) or {}
    if country:
        for entry in countries.get(country.upper(), []) or []:
            out.append(CrisisResource(**entry))
    for entry in doc.get("global", []) or []:
        out.append(CrisisResource(**entry))
    return out


def crisis_card_copy(language: str) -> dict[str, str]:
    """Return {title, message, nudge} localized for the crisis card."""
    doc = _load_crisis_doc()
    cards = doc.get("card", {}) or {}
    key = _lang_key(language, cards)
    card = cards.get(key, {}) or {}
    return {
        "title": str(card.get("title", "Help is available")),
        "message": str(card.get("message", "")).strip(),
        "nudge": str(card.get("nudge", "")).strip(),
    }


def crisis_disclosure(language: str) -> str:
    """Localized 'I'm an AI, not a professional' wording for the crisis card."""
    doc = _load_crisis_doc()
    disc = doc.get("disclosure", {}) or {}
    key = _lang_key(language, disc)
    return str(disc.get(key, "")).strip() or (
        "I'm an AI assistant, not a mental-health professional. Please reach out to the people and "
        "services below — they care and can help."
    )


def ai_disclosure(language: str) -> str:
    """Localized generic AI-interaction disclosure (CA SB 243 style)."""
    doc = _load_crisis_doc()
    disc = doc.get("ai_disclosure", {}) or {}
    key = _lang_key(language, disc)
    return str(disc.get(key, "")).strip() or (
        "Heads up: you're chatting with an AI study helper, not a human teacher or counselor."
    )


def refusal_redirect_suggestions(intent: StructuredIntent) -> list[str]:
    """Friendly, on-task alternatives offered when a prompt is refused (growth-mindset framing)."""
    return [
        "Ask about a school subject like math, science, history, or languages.",
        "Try: 'Teach me about the water cycle for 4th grade.'",
        "Try: 'Quiz me on multiplication facts.'",
    ]

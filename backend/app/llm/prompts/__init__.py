"""Prompt assembly for the LLM generation layer.

* :func:`system_pedagogy` returns the byte-identical cached English SYSTEM_PEDAGOGY prefix (same for
  every language; the output language is pinned by :func:`language_directive` in the user message).
* The ``build_*`` helpers assemble the VOLATILE trailing user message for each generation step. All
  volatile data (topic, language, mastery, grade band, date) lives here only — never in the cached
  prefix.
"""

from __future__ import annotations

import json

from ...core.constants import READABILITY_TARGETS, TARGET_SUCCESS_RATE
from ...schemas.enums import LESSON_SKELETON
from ...schemas.intent import StructuredIntent
from .pedagogy import SYSTEM_PEDAGOGY, SYSTEM_PEDAGOGY_EN

__all__ = [
    "SYSTEM_PEDAGOGY",
    "SYSTEM_PEDAGOGY_EN",
    "system_pedagogy",
    "language_directive",
    "build_lesson_plan_user",
    "build_section_user",
    "build_visual_spec_user",
    "build_quiz_user",
    "build_grader_user",
]


def system_pedagogy(language: str) -> str:  # noqa: ARG001 — language is pinned in the user message
    """Return the byte-identical cached English system prefix (same for every output language).

    Kept byte-identical across all calls so the ephemeral cache prefix stays warm (SPEC invariant #4).
    The requested output language is applied via :func:`language_directive` in the volatile tail.
    """
    return SYSTEM_PEDAGOGY_EN


def language_directive(language: str) -> str:
    """One-line instruction (volatile tail) pinning the OUTPUT language. The cached system prefix is
    always English, so the language is requested here for every language including English."""
    lang = (language or "en").strip().lower()
    return (
        f"Respond entirely in '{lang}'. Write every student-facing value in '{lang}'. "
        "JSON keys stay English."
    )


def _intent_context(intent: StructuredIntent) -> str:
    """Render the validated-intent context block (volatile; no raw student text)."""
    target = READABILITY_TARGETS.get(intent.grade_band.value, READABILITY_TARGETS["unknown"])
    constraints = "; ".join(intent.constraints) if intent.constraints else "(none)"
    return (
        f"subject: {intent.subject.value}\n"
        f"topic: {intent.topic}\n"
        f"grade_band: {intent.grade_band.value}\n"
        f"language: {intent.language}\n"
        f"target_FKGL: {target['fkgl']}\n"
        f"max_words_per_sentence: {target['max_sentence_words']}\n"
        f"max_new_terms: {target['max_new_terms']}\n"
        f"extra_constraints: {constraints}"
    )


def build_lesson_plan_user(intent: StructuredIntent) -> str:
    """Step 1 prompt: ask for the ordered LessonPlan (section stubs + objectives + edges)."""
    skeleton = ", ".join(k.value for k in LESSON_SKELETON)
    return (
        "Plan a complete lesson for the validated intent below. Produce a LessonPlan.\n\n"
        f"{_intent_context(intent)}\n\n"
        f"{language_directive(intent.language)}\n\n"
        "Requirements:\n"
        f"- sections: one stub PER skeleton kind, in this exact order: {skeleton}. "
        "Give each a short title; set needs_image and visual_kind where a visual helps.\n"
        "- objectives: 3 to 5 Bloom-tagged 'I can ...' statements, each with a concept_slug "
        "(lowercase-hyphen slug derived from the concept).\n"
        "- concept_edges: propose prerequisite and related edges between concept slugs you use.\n"
        "- misconceptions: list 1 to 4 common misconceptions for this topic as short strings.\n"
        "- Use stable lowercase-hyphen concept slugs consistently across objectives, edges, and "
        "later sections."
    )


def build_section_user(intent: StructuredIntent, *, kind: str, title: str, objective: str | None) -> str:
    """Step 2 prompt: fill ONE section body (+ items for interactive sections)."""
    obj = objective or "(derive from the topic)"
    return (
        f"Fill the '{kind}' section of the lesson for the validated intent below. Produce a "
        "GenSection.\n\n"
        f"{_intent_context(intent)}\n\n"
        f"section_kind: {kind}\n"
        f"section_title: {title}\n"
        f"section_objective: {obj}\n\n"
        f"{language_directive(intent.language)}\n\n"
        "Requirements:\n"
        "- body_markdown: clear, dual-coded prose at or below the target reading level. Keep "
        "sentences within the word cap; define new terms inline.\n"
        "- For pretest/practice/interleaved_review/misconception_check sections, include items "
        "(GenItem). Each item: item_type, concept_slug, bloom_tier (1-6), difficulty, "
        "item_difficulty (integer 1-5), stem_markdown, a typed payload, distractors (each with a "
        "misconception string or null), a hint_ladder (1-3 hints), worked_solution_steps, and an "
        "explanation. MCQ has exactly one correct option unless multiple-select.\n"
        "- visual_requests: 0 to 2 GenVisualSpec entries where a visual aids understanding; give "
        "alt_text for each.\n"
        "- Never reveal the answer inside a stem."
    )


def build_visual_spec_user(intent: StructuredIntent, section_titles: list[str]) -> str:
    """Step 3 prompt: one call producing visual specs across the lesson (volatile tail)."""
    sections = json.dumps(section_titles, ensure_ascii=False)
    return (
        "Propose the visuals for this lesson. For each section that benefits, emit a GenVisualSpec "
        "with section_ordinal (0-based index into the section list), visual_kind, layout_slot, "
        "alt_text, an optional caption, and EITHER svg_request (schematic kinds) OR image_prompt "
        "(representational kinds, written as a kid-safe subject description derived only from the "
        "topic).\n\n"
        f"{_intent_context(intent)}\n\n"
        f"section_titles (ordered): {sections}\n\n"
        f"{language_directive(intent.language)}"
    )


def build_quiz_user(
    intent: StructuredIntent,
    *,
    mastery: float,
    recent_accuracy: float,
    known_misconceptions: list[str],
    target_success: float = TARGET_SUCCESS_RATE,
) -> str:
    """Quiz prompt seeded so items land in the learner's ZPD (volatile tail only)."""
    misc = "; ".join(known_misconceptions) if known_misconceptions else "(none recorded)"
    return (
        "Generate an interactive quiz for the validated intent below. Produce a GenQuiz with a "
        "title, language, and a list of questions (GenItem).\n\n"
        f"{_intent_context(intent)}\n\n"
        f"mastery: {mastery:.2f}\n"
        f"recent_accuracy: {recent_accuracy:.2f}\n"
        f"target_success: {target_success:.2f}\n"
        f"known_misconceptions: {misc}\n\n"
        f"{language_directive(intent.language)}\n\n"
        "Requirements:\n"
        "- 6 to 10 questions spanning the appropriate Bloom tiers for the grade band, placed so a "
        f"learner at mastery {mastery:.2f} succeeds about {target_success:.2f} of the time.\n"
        "- Mix item types. MCQ has exactly one correct option unless multiple-select; provide "
        "plausible distractors, each with a misconception string or null.\n"
        "- Each item: item_type, concept_slug, bloom_tier (1-6), difficulty, item_difficulty "
        "(integer 1-5), stem_markdown, typed payload, hint_ladder (1-3), worked_solution_steps, and "
        "an explanation. Target the listed known misconceptions where relevant.\n"
        "- Never reveal the answer inside a stem."
    )


def build_grader_user(
    *,
    stem_markdown: str,
    item_type: str,
    expected_answer: str | None,
    submitted_value: str,
    language: str,
    accepted_variants: list[str] | None = None,
) -> str:
    """Free-text/numeric grader prompt (volatile tail). Server-only correctness."""
    expected = expected_answer if expected_answer is not None else "(use subject judgement)"
    variants_line = ""
    if accepted_variants:
        joined = "; ".join(str(v) for v in accepted_variants)
        variants_line = f"accepted_variants (any of these is fully correct): {joined}\n"
    return (
        "Grade the learner's free-text answer. Produce a GraderOutput (correct, partial_credit 0-1, "
        "concept_tags, misconception or null, explanation, encouragement_focus).\n\n"
        f"item_type: {item_type}\n"
        f"question: {stem_markdown}\n"
        f"reference_answer: {expected}\n"
        f"{variants_line}"
        f"learner_answer: {submitted_value}\n\n"
        f"{language_directive(language)}\n\n"
        "Be fair and generous with equivalent phrasings, units, and rounding. Use growth-mindset "
        "wording in the explanation: name a strategy or a concrete next step, never a bare 'wrong'."
    )

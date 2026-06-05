"""LLM grading for free-text answers (Opus 4.8 structured output).

Only ``short_answer`` / ``numeric`` / ``explain``-style items go through the LLM grader; mcq /
true_false / cloze / match / order / hotspot are graded deterministically by the services layer.

``grade_free_text(item, submitted_value, language) -> GraderOutput`` returns the server-only verdict
(correct, partial_credit, concept_tags, misconception, explanation, encouragement_focus). The grader
reads ONLY structured item fields (stem, expected answer, type) and the learner's submitted value —
never the original raw prompt.
"""

from __future__ import annotations

from typing import Any

from ..core.config import settings
from ..schemas.generation import GraderOutput
from . import prompts
from .client import generate_structured

# Item types eligible for LLM grading; everything else is graded deterministically server-side.
LLM_GRADED_TYPES = frozenset({"short_answer", "numeric", "explain"})


def _coerce_submitted(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(str(v) for v in value.values())
    if isinstance(value, list | tuple):
        return " ".join(str(v) for v in value)
    return str(value)


def _item_field(item: Any, name: str, default: Any = None) -> Any:
    """Read a field from either an ORM Item row or a mapping/schema."""
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


async def grade_free_text(
    item: Any,
    submitted_value: Any,
    language: str,
    *,
    client: Any = None,
    db: Any = None,
    request_id: str | None = None,
) -> GraderOutput:
    """Grade a free-text / numeric answer via Opus 4.8. ``item`` is an Item row (or compatible mapping)."""
    item_type = str(_item_field(item, "item_type", "short_answer"))
    user = prompts.build_grader_user(
        stem_markdown=str(_item_field(item, "stem_markdown", "")),
        item_type=item_type,
        expected_answer=_item_field(item, "expected_answer"),
        submitted_value=_coerce_submitted(submitted_value),
        language=language,
        accepted_variants=_item_field(item, "accepted_variants_json"),
    )
    result, _ = await generate_structured(
        system_blocks=prompts.system_pedagogy(language),
        user=user,
        output_model=GraderOutput,
        model=settings.model_id,
        max_tokens=2000,
        effort="medium",
        db=db,
        request_id=request_id,
        client=client,
    )
    # Clamp partial_credit to [0, 1] defensively (4.8 strips schema bounds).
    if result.partial_credit < 0 or result.partial_credit > 1:
        result.partial_credit = max(0.0, min(1.0, result.partial_credit))
    return result


# Frozen-interface alias (SPEC §6 names it ``grade_answer``).
grade_answer = grade_free_text

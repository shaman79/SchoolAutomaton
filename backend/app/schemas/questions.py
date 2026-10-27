"""The wire contract for interactive questions — PUBLIC delivery shape (no correctness) + answer
submission. Mirrored exactly in ``frontend/src/types/question.ts`` (F2). The discriminator is
``payload.kind`` so openapi-typescript renders a clean exhaustive TS union.

Stored/generation payloads (WITH correctness) are defined in ``generation.py``; the public payloads
here are produced by stripping correctness server-side before delivery (SPEC §5 — answers are
server-only until grading)."""

from __future__ import annotations

import json
import math
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator

from .common import StrictModel
from .enums import ItemType


# --------------------------------------------------------------------------- per-type public payloads
class McqOptionPublic(StrictModel):
    id: str
    text: str  # markdown


class McqPayload(StrictModel):
    kind: Literal["mcq"] = "mcq"
    options: list[McqOptionPublic]
    multiple: bool = False  # multi-select?


class TrueFalsePayload(StrictModel):
    kind: Literal["true_false"] = "true_false"
    statement: str | None = None  # if null, the stem IS the statement


class ClozeBlankPublic(StrictModel):
    id: str
    # choices present => drag/select-into-blank; absent => free type-in
    choices: list[str] | None = None


class ClozePayload(StrictModel):
    kind: Literal["cloze"] = "cloze"
    text_template: str  # uses {{blank_id}} markers
    blanks: list[ClozeBlankPublic]


class ShortAnswerPayload(StrictModel):
    kind: Literal["short_answer"] = "short_answer"
    placeholder: str | None = None


class NumericPayload(StrictModel):
    kind: Literal["numeric"] = "numeric"
    unit: str | None = None


class MatchSidePublic(StrictModel):
    id: str
    text: str


class MatchPayload(StrictModel):
    kind: Literal["match"] = "match"
    left: list[MatchSidePublic]
    right: list[MatchSidePublic]  # delivered shuffled


class OrderTokenPublic(StrictModel):
    id: str
    text: str


class OrderPayload(StrictModel):
    kind: Literal["order"] = "order"
    tokens: list[OrderTokenPublic]  # delivered shuffled; learner arranges


class HotspotRegionPublic(StrictModel):
    id: str
    shape: Literal["rect", "circle", "poly"]
    coords: list[float]  # rect:[x,y,w,h] circle:[cx,cy,r] poly:[x1,y1,...] (0..1 normalized)
    label: str | None = None


class HotspotPayload(StrictModel):
    kind: Literal["hotspot"] = "hotspot"
    image_url: str | None = None       # /api/v1/assets/{hash}
    image_asset_hash: str | None = None
    regions: list[HotspotRegionPublic]


QuestionPayload = Annotated[
    McqPayload | TrueFalsePayload | ClozePayload | ShortAnswerPayload | NumericPayload | MatchPayload | OrderPayload | HotspotPayload,
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------- public item + answer
class ItemPublic(StrictModel):
    """A question/reviewable item as delivered to the client — correctness omitted."""

    id: int
    item_type: ItemType
    bloom_tier: int
    points: int = 10
    stem_markdown: str
    payload: QuestionPayload
    hint_available: bool = False


# --------------------------------------------------------------------------- answer size bounds
# A submitted answer is stored verbatim and free text is sent to the (paid) AI grader, so every
# submission is bounded; anything larger is a 422.
MAX_ANSWER_TEXT_CHARS = 2000  # any one string: free text, a cloze blank, an option/token id
MAX_ANSWER_BYTES = 8 * 1024  # the whole value serialized as compact UTF-8 JSON
MAX_ANSWER_DEPTH = 3  # nested lists/objects (a match answer, list -> {left_id,right_id}, uses 2)
MAX_ANSWER_ITEMS = 200  # list elements + object entries, in total


def check_submitted_value(value: Any) -> Any:
    """Validate an answer's size/shape bounds (shared by ``AnswerIn`` and ``ReviewRatingIn``).

    Walks iteratively (no recursion on hostile nesting) and fails fast; raises ``ValueError``, which
    Pydantic turns into a 422."""
    stack: list[tuple[Any, int]] = [(value, 0)]
    entries = 0
    while stack:
        node, depth = stack.pop()
        if isinstance(node, str):
            if len(node) > MAX_ANSWER_TEXT_CHARS:
                raise ValueError(f"answer text must be at most {MAX_ANSWER_TEXT_CHARS} characters")
        elif node is None or isinstance(node, bool | int):
            continue
        elif isinstance(node, float):
            if not math.isfinite(node):
                raise ValueError("answer numbers must be finite")
        elif isinstance(node, list | dict):
            if depth >= MAX_ANSWER_DEPTH:
                raise ValueError("answer is nested too deeply")
            entries += len(node)
            if entries > MAX_ANSWER_ITEMS:
                raise ValueError(f"answer has more than {MAX_ANSWER_ITEMS} parts")
            children = list(node.keys()) + list(node.values()) if isinstance(node, dict) else node
            stack.extend((child, depth + 1) for child in children)
        else:
            raise ValueError("unsupported answer value")
    size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if size > MAX_ANSWER_BYTES:
        raise ValueError(f"answer must be at most {MAX_ANSWER_BYTES} bytes")
    return value


class AnswerIn(StrictModel):
    """Answer submission. ``submitted_value`` shape depends on item_type (see ANSWER_VALUE_DOC):
    mcq: str | list[str] (option id(s)); true_false: bool; cloze: {blank_id: str};
    short_answer: str; numeric: number; match: list[{left_id,right_id}];
    order: list[str] (token ids in chosen order); hotspot: str (region id).

    Bounded (422 beyond): each string <= 2000 chars, the whole value <= 8 KB as JSON, nesting <= 3,
    <= 200 parts."""

    item_id: int
    attempt_id: int | None = None
    submitted_value: Any
    used_hint: bool = False
    latency_ms: int | None = Field(default=None, ge=0)

    @field_validator("submitted_value")
    @classmethod
    def _bounded(cls, v: Any) -> Any:
        return check_submitted_value(v)


# Human-readable doc of the per-type submitted_value contract (kept next to the schema on purpose).
ANSWER_VALUE_DOC: dict[str, str] = {
    "mcq": "option id (str) or list of option ids (str[]) when multiple=true",
    "true_false": "boolean",
    "cloze": "object mapping blank id -> filled string",
    "short_answer": "string",
    "numeric": "number",
    "match": "array of {left_id, right_id} pairs",
    "order": "array of token ids in the chosen order",
    "hotspot": "selected region id (str)",
}

"""The wire contract for interactive questions — PUBLIC delivery shape (no correctness) + answer
submission. Mirrored exactly in ``frontend/src/types/question.ts`` (F2). The discriminator is
``payload.kind`` so openapi-typescript renders a clean exhaustive TS union.

Stored/generation payloads (WITH correctness) are defined in ``generation.py``; the public payloads
here are produced by stripping correctness server-side before delivery (SPEC §5 — answers are
server-only until grading)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

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


class AnswerIn(StrictModel):
    """Answer submission. ``submitted_value`` shape depends on item_type (see ANSWER_VALUE_DOC):
    mcq: str | list[str] (option id(s)); true_false: bool; cloze: {blank_id: str};
    short_answer: str; numeric: number; match: list[{left_id,right_id}];
    order: list[str] (token ids in chosen order); hotspot: str (region id)."""

    item_id: int
    attempt_id: int | None = None
    submitted_value: Any
    used_hint: bool = False
    latency_ms: int | None = Field(default=None, ge=0)


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

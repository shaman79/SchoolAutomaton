"""Public lesson delivery schemas (LessonReader). Answers/explanations are excluded from items."""

from __future__ import annotations

from .common import AppModel
from .enums import BloomTier, LayoutSlot, SectionKind
from .questions import ItemPublic


class AssetRefPublic(AppModel):
    hash: str
    url: str                      # /api/v1/assets/{hash}
    asset_type: str               # svg|raster|svg_icon|video
    layout_slot: LayoutSlot
    alt_text: str
    caption: str | None = None
    svg_inline: str | None = None  # present for asset_type=svg (sanitized server-side)
    label_overlay: list | None = None


class LessonObjectivePublic(AppModel):
    text: str
    bloom_tier: BloomTier
    concept_id: int | None = None


class LessonSectionPublic(AppModel):
    ordinal: int
    kind: SectionKind
    title: str | None = None
    body_markdown: str | None = None
    gated: bool = False
    gen_status: str = "ready"  # pending|ready|error — progressive (lazy) generation
    assets: list[AssetRefPublic] = []
    items: list[ItemPublic] = []


class LessonPublic(AppModel):
    id: int
    request_id: str
    topic: str
    language: str
    grade_band: str
    subject: str
    objectives: list[LessonObjectivePublic] = []
    measured_fkgl: float | None = None
    lexile_band: str | None = None
    estimated_duration_min: int | None = None
    sections: list[LessonSectionPublic] = []

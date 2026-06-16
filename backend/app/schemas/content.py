"""Public lesson delivery schemas (LessonReader). Answers/explanations are excluded from items."""

from __future__ import annotations

from .common import AppModel
from .enums import BloomTier, LayoutSlot, SectionKind
from .questions import ItemPublic


class AssetRefPublic(AppModel):
    hash: str | None = None       # null while a section visual is still pending/generating
    url: str | None = None        # /api/v1/assets/{hash}; null until ready
    asset_type: str | None = None  # svg|raster|svg_icon|video; null until ready
    layout_slot: LayoutSlot
    alt_text: str
    caption: str | None = None
    svg_inline: str | None = None  # present for asset_type=svg (sanitized server-side)
    label_overlay: list | None = None
    # Async section visuals: 'pending'|'generating' → render a placeholder; 'ready' → render the asset;
    # 'failed' → fall back to alt text. Defaults 'ready' so synchronous (hotspot/legacy) paths are
    # unchanged.
    status: str = "ready"


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

"""Shared Pydantic base + generic API envelopes.

``StrictModel`` forbids extra fields → emits ``additionalProperties:false`` in JSON Schema, which is
required for Claude Opus 4.8 structured outputs (SPEC §5). Numeric/length bounds are enforced with
field validators (not schema min/max, which 4.8 strips)."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class StrictModel(BaseModel):
    """Base for every schema. Forbids unknown keys; keeps enum members as enums."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False, populate_by_name=True)


class AppModel(BaseModel):
    """Looser base for API response envelopes built from ORM rows (allows from_attributes)."""

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class Page(AppModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    page_size: int = 50


class ErrorResponse(AppModel):
    detail: str
    code: str | None = None

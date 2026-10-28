"""Anthropic per-token prices — the ONE place ``generation_usage.est_cost_usd`` is computed from.

USD per million tokens, Anthropic first-party API rates, taken from
https://platform.claude.com/docs/en/about-claude/pricing (checked 2026-10-27; Opus 5.5 / Opus 5 / Haiku 5.5 from the claude-api model-migration guide, 2026-10-28). Update this table
when a configured model (``SA_MODEL_ID`` / ``SA_SANITIZER_MODEL_ID``) changes; an unknown model gets
``None`` (cost unknown) rather than a guess.

``cache_write`` is the 5-minute-TTL write price (1.25× input) — the only cache TTL this app uses
(``cache_control: {type: 'ephemeral'}``). Thinking tokens are billed (and reported) as output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input: float
    cache_write: float
    cache_read: float
    output: float


MODEL_PRICES: dict[str, ModelPrice] = {
    "claude-opus-4-8": ModelPrice(input=5.00, cache_write=6.25, cache_read=0.50, output=25.00),
    "claude-haiku-4-5": ModelPrice(input=1.00, cache_write=1.25, cache_read=0.10, output=5.00),
    # Opus 5.5 / Opus 5 (a server-side refusal fallback can be served by Opus 5 or 4.8).
    "claude-opus-5-5": ModelPrice(input=4.00, cache_write=5.00, cache_read=0.20, output=20.00),
    "claude-opus-5": ModelPrice(input=5.00, cache_write=6.25, cache_read=0.50, output=25.00),
    # Haiku 5.5, prompts <= 100K tokens (this app's are far below; > 100K bills $0.50 / $2.50).
    "claude-haiku-5-5": ModelPrice(input=0.10, cache_write=0.125, cache_read=0.01, output=0.50),
}

_DATE_SUFFIX = re.compile(r"-\d{8}$")  # e.g. claude-haiku-4-5-20251001 → claude-haiku-4-5


def price_for(model: str | None) -> ModelPrice | None:
    if not model:
        return None
    return MODEL_PRICES.get(model) or MODEL_PRICES.get(_DATE_SUFFIX.sub("", model))


def estimate_cost_usd(
    model: str | None,
    *,
    input_tokens: int | None = 0,
    cache_creation_tokens: int | None = 0,
    cache_read_tokens: int | None = 0,
    output_tokens: int | None = 0,
) -> float | None:
    """Estimated USD cost of one call, or ``None`` when the model's price isn't known."""
    price = price_for(model)
    if price is None:
        return None
    total = (
        (input_tokens or 0) * price.input
        + (cache_creation_tokens or 0) * price.cache_write
        + (cache_read_tokens or 0) * price.cache_read
        + (output_tokens or 0) * price.output
    ) / 1_000_000
    return round(total, 6)

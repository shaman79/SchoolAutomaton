"""Global daily AI budget (``SA_DAILY_BUDGET_USD``, default 100; 0 disables).

Spend is today's (UTC) sum of ``generation_usage.est_cost_usd`` — every logged model call, priced by
``core.pricing``. Rows whose model has no known price carry ``NULL`` and don't count.

* :func:`ensure_ai_budget` — call before starting paid generation (lesson/quiz generation start,
  on-demand section fills); raises ``HTTPException(503, detail="daily_budget")`` once the cap is hit.
* :func:`ai_budget_exceeded` — the non-raising check, for paths with a free fallback (free-text
  grading falls back to deterministic grading instead of failing).

Both only READ, so they are safe to call anywhere (no write lock is taken).
"""

from __future__ import annotations

from datetime import UTC, datetime, time

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..models import GenerationUsage

BUDGET_DETAIL = "daily_budget"


async def spent_today_usd(db: AsyncSession, now: datetime | None = None) -> float:
    """Estimated USD spent on AI calls since 00:00 UTC today."""
    now = now or datetime.now(UTC)
    start = datetime.combine(now.astimezone(UTC).date(), time.min, tzinfo=UTC)
    total = await db.scalar(
        select(func.coalesce(func.sum(GenerationUsage.est_cost_usd), 0.0)).where(
            GenerationUsage.created_at >= start
        )
    )
    return float(total or 0.0)


async def ai_budget_exceeded(db: AsyncSession, now: datetime | None = None) -> bool:
    budget = float(settings.daily_budget_usd or 0.0)
    if budget <= 0:
        return False  # 0 (or negative) disables the cap
    return await spent_today_usd(db, now) >= budget


async def ensure_ai_budget(db: AsyncSession) -> None:
    """Raise ``HTTPException(503, detail="daily_budget")`` when today's AI budget is used up."""
    if await ai_budget_exceeded(db):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=BUDGET_DETAIL)

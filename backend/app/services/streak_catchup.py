"""Count earlier activity toward the daily streak — run at startup, idempotent.

Before the "anything finished counts" rule (owner decision 2026-10-28) only a finished quiz moved the
streak, so the days a learner spent answering lesson-practice questions were never counted: on the
day the rule went live, a child who had learned every day through lessons would have seen their
streak drop to 0. This replays every graded answer and finished quiz AFTER the stored last active day
through the same rules (:func:`gamification.settle_streak`), in order, as if each had been counted
when it happened.

Idempotent: since the rule, each graded answer and finished quiz settles the streak when it happens,
so nothing is ever again after the stored last active day and a later run changes nothing. (Lesson
parts finished without an answer left no dated record and can't be counted.)"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Answer, Profile, QuizAttempt, StreakState
from .gamification import settle_streak

logger = logging.getLogger("schoolautomaton.streaks")


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def _first_moment_of_each_day(db: AsyncSession) -> dict[int, dict[date, datetime]]:
    """profile id -> {UTC day: the first graded answer or finished quiz that day}."""
    days: dict[int, dict[date, datetime]] = {}
    for profile_col, moment_col in (
        (Answer.profile_id, Answer.created_at),
        (QuizAttempt.profile_id, QuizAttempt.completed_at),
    ):
        rows = await db.execute(
            select(profile_col, func.min(moment_col))
            .where(profile_col.is_not(None), moment_col.is_not(None))
            .group_by(profile_col, func.date(moment_col))
        )
        for profile_id, first in rows.all():
            moment = _aware(first)
            per_day = days.setdefault(profile_id, {})
            day = moment.astimezone(UTC).date()
            if day not in per_day or moment < per_day[day]:
                per_day[day] = moment
    return days


async def catch_up_streaks(db: AsyncSession) -> int:
    """Settle the streak for activity after each learner's stored last active day. Returns how many
    learners' streaks moved. The caller commits."""
    moved = 0
    for profile_id, per_day in sorted((await _first_moment_of_each_day(db)).items()):
        streak = await db.get(StreakState, profile_id)
        last = streak.last_active_date if streak is not None else None
        pending = sorted(m for day, m in per_day.items() if last is None or day > last)
        if not pending:
            continue
        profile = await db.get(Profile, profile_id)
        if profile is None:
            continue
        seen_at = profile.last_active_at
        for moment in pending:
            await settle_streak(db, profile, moment)
        # settle_streak stamps "last active" with the replayed moment; keep the real latest one.
        if seen_at is not None and _aware(seen_at) > _aware(profile.last_active_at):
            profile.last_active_at = seen_at
        moved += 1
    await db.flush()
    return moved

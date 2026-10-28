"""Count earlier activity toward the daily streak — run at startup, idempotent.

Before the "anything finished counts" rule (owner decision 2026-10-28) only a finished quiz moved the
streak, so the days a learner spent answering lesson-practice questions were never counted: on the
day the rule went live, a child who had learned every day through lessons would have seen their
streak drop to 0. This replays the graded answers and finished quizzes after the stored last active
day through the same rules, as if each had been counted when it happened.

Exactly as live settling would have gone: within a day only the first activity can change the
streak (later ones are "same day") and the last one sets the 48 h repair window, so each day is
replayed at its first and last moment. Later activity on the stored last day itself moves the window
too. All in memory (:func:`gamification.apply_streak_step`, which settle_streak uses) — a few queries
whatever the history's length, so a large first catch-up can't hold up startup.

Idempotent: since the rule, each graded answer and finished quiz settles the streak when it happens,
so a later run finds nothing new. (Lesson parts finished without an answer left no dated record and
can't be counted.)"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.constants import STREAK_REPAIR_WINDOW_HOURS
from ..models import Answer, Profile, ProfileSettings, QuizAttempt, StreakState
from .gamification import apply_streak_step, rest_day_cap

logger = logging.getLogger("schoolautomaton.streaks")

_WINDOW = timedelta(hours=STREAK_REPAIR_WINDOW_HOURS)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def _activity_by_day(db: AsyncSession) -> dict[int, dict[date, tuple[datetime, datetime]]]:
    """profile id -> {UTC day: (first, last) graded answer or finished quiz that day}."""
    days: dict[int, dict[date, tuple[datetime, datetime]]] = {}
    for profile_col, moment_col in (
        (Answer.profile_id, Answer.created_at),
        (QuizAttempt.profile_id, QuizAttempt.completed_at),
    ):
        rows = await db.execute(
            select(profile_col, func.min(moment_col), func.max(moment_col))
            .where(profile_col.is_not(None), moment_col.is_not(None))
            .group_by(profile_col, func.date(moment_col))
        )
        for profile_id, first, last in rows.all():
            first, last = _aware(first), _aware(last)
            per_day = days.setdefault(profile_id, {})
            day = first.astimezone(UTC).date()
            if day in per_day:
                known_first, known_last = per_day[day]
                first, last = min(first, known_first), max(last, known_last)
            per_day[day] = (first, last)
    return days


def _moments_to_replay(
    streak: StreakState | None, per_day: dict[date, tuple[datetime, datetime]]
) -> list[datetime]:
    last = streak.last_active_date if streak is not None else None
    moments: list[datetime] = []
    for day, (first, latest) in sorted(per_day.items()):
        if last is not None and day < last:
            continue  # already counted (or before it)
        if last is not None and day == last:
            # The stored last day itself: later activity that day only moves the repair window.
            window = streak.repair_window_expires_at if streak is not None else None
            if window is None or latest + _WINDOW > _aware(window):
                moments.append(latest)
            continue
        moments.append(first)  # decides the day
        if latest > first:
            moments.append(latest)  # the same day: sets the repair window
    return moments


async def catch_up_streaks(db: AsyncSession) -> int:
    """Settle the streak for activity it hasn't counted yet. Returns how many learners' streaks
    moved. The caller commits."""
    activity = await _activity_by_day(db)
    if not activity:
        return 0
    streaks = {s.profile_id: s for s in await db.scalars(select(StreakState))}
    settings = {s.profile_id: s for s in await db.scalars(select(ProfileSettings))}
    profiles = {p.id: p for p in await db.scalars(select(Profile))}
    moved = 0
    for profile_id, per_day in sorted(activity.items()):
        profile = profiles.get(profile_id)
        if profile is None:
            continue
        streak = streaks.get(profile_id)
        moments = _moments_to_replay(streak, per_day)
        if not moments:
            continue
        if streak is None:
            streak = StreakState(profile_id=profile_id)
            db.add(streak)
            await db.flush()  # the column defaults: the starting freezes
        rest_cap = rest_day_cap(profile, settings.get(profile_id))
        for moment in moments:
            apply_streak_step(streak, now=moment, rest_cap=rest_cap)
        if profile.last_active_at is None or moments[-1] > _aware(profile.last_active_at):
            profile.last_active_at = moments[-1]
        moved += 1
    await db.flush()
    return moved

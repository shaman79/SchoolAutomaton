"""The learner's class drives the young-learner mechanics that used to be dead code.

``profile.age_band`` had no input anywhere in the app, so it stayed 'unknown' and the early-primary
mechanics never applied: the smaller daily new-item cap (DAILY_NEW_CAP) and the weekly rest day
(REST_DAYS_PER_WEEK_YOUNG). The class setting now derives the band."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import Profile, StreakState
from app.schemas.enums import AgeBand, age_band_for_school_year
from app.services import gamification


@pytest.mark.parametrize(
    "year,band",
    [(0, AgeBand.EARLY_PRIMARY), (2, AgeBand.EARLY_PRIMARY), (3, AgeBand.PRIMARY),
     (5, AgeBand.PRIMARY), (6, AgeBand.LOWER_SECONDARY), (8, AgeBand.LOWER_SECONDARY),
     (9, AgeBand.UPPER_SECONDARY), (13, AgeBand.UPPER_SECONDARY)],
)
def test_age_band_for_school_year(year, band):
    assert age_band_for_school_year(year) is band


@pytest.mark.asyncio
async def test_class_setting_sets_the_profile_age_band(client):
    r = await client.post("/api/v1/profiles", json={"locale": "cs", "school_year": 1})
    assert r.status_code == 201, r.text
    assert r.json()["profile"]["age_band"] == "early_primary"
    h = {"X-Resume-Code": r.json()["resume_code"]}

    await client.patch("/api/v1/profiles/me/settings", headers=h, json={"school_year": 7})
    assert (await client.get("/api/v1/profiles/me", headers=h)).json()["profile"]["age_band"] == "lower_secondary"
    # Unrelated settings leave it alone; clearing the class clears the derived band.
    await client.patch("/api/v1/profiles/me/settings", headers=h, json={"sound": False})
    assert (await client.get("/api/v1/profiles/me", headers=h)).json()["profile"]["age_band"] == "lower_secondary"
    await client.patch("/api/v1/profiles/me/settings", headers=h, json={"school_year": None})
    assert (await client.get("/api/v1/profiles/me", headers=h)).json()["profile"]["age_band"] == "unknown"


async def _streak_after_two_missed_days(client, school_year: int) -> int:
    """Active on a Tuesday, away Wednesday + Thursday, back on Friday (same week), one freeze left."""
    code = (await client.post("/api/v1/profiles", json={"school_year": school_year})).json()["resume_code"]
    from app.db.session import SessionLocal
    from app.services import profile_service

    async with SessionLocal() as db:
        profile = await profile_service.get_by_code(db, code)
        streak = await db.scalar(select(StreakState).where(StreakState.profile_id == profile.id))
        streak.freeze_inventory = 1
        tuesday = datetime(2026, 9, 22, 16, 0, tzinfo=UTC)
        await gamification.settle_streak(db, profile, tuesday)
        info = await gamification.settle_streak(db, profile, tuesday + timedelta(days=3))
        await db.commit()
        assert isinstance(profile, Profile)
        return info.current


@pytest.mark.asyncio
async def test_youngest_learners_keep_their_weekly_rest_day(client):
    # A first grader: the rest day + the one freeze bridge both missed days.
    assert await _streak_after_two_missed_days(client, school_year=1) == 2
    # A 4th grader has no rest day by default: the freeze covers one day, the streak restarts.
    assert await _streak_after_two_missed_days(client, school_year=4) == 1

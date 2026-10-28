"""Daily streak rules — owner decision: "anything finished counts, keep the time in UTC".

* What counts: a graded answer (lesson practice, quiz question, review card), a finished lesson part
  (the reveal boundary moved forward) and a finished quiz — one streak update per request, idempotent
  per UTC day. Not: an ungraded crisis response, a refused request (404/409/422), opening a lesson.
* Forgiveness, in order: rest days (a fresh allowance every ISO week; each missed day is charged to
  its own week), freezes, the 48 h repair window. Nothing is spent on a gap that can't be bridged.
* The snapshot shows the streak as it stands NOW (0 once the gap can't be bridged) without writing,
  through the same pure helper settle_streak uses — so the two can never disagree.

Every date here is fixed; the wall clock is never consulted for anything asserted."""

from __future__ import annotations

import itertools
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import (
    Answer,
    BadgeDefinition,
    Lesson,
    Profile,
    ProfileBadge,
    ProfileSettings,
    QuizAttempt,
    StreakState,
)
from app.schemas.questions import AnswerIn
from app.services import gamification, profile_service, progress_service
from app.services.gamification import STREAK_BRIDGED, STREAK_BROKEN, next_streak_step
from app.services.streak_catchup import catch_up_streaks
from tests.test_cost_tracking import _seed
from tests.test_progress_resume import _new_profile, _seed_lesson, _seed_quiz

API = "/api/v1"
TUE = datetime(2026, 9, 22, 18, 0, tzinfo=UTC)  # ISO week 39 (Mon 21 Sep .. Sun 27 Sep)
DAY = timedelta(days=1)


class _Clock:
    now: datetime = TUE


@pytest.fixture
def clock(monkeypatch):
    """Pin "now" for the request paths (they take no ``now``): the services' ``datetime.now``."""

    class _Fixed(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D102
            return _Clock.now if tz is None else _Clock.now.astimezone(tz)

    for module in (gamification, progress_service, profile_service):
        monkeypatch.setattr(module, "datetime", _Fixed)
    _Clock.now = TUE
    return _Clock


def _state(**kw) -> StreakState:
    """A transient streak row with every field set (column defaults only apply on flush)."""
    fields = {
        "profile_id": 1,
        "current_streak_len": 0,
        "longest_streak": 0,
        "last_active_date": None,
        "freeze_inventory": 0,
        "freezes_used_in_current_streak": 0,
        "rest_days_used_this_week": 0,
        "is_perfect": True,
        "repair_window_expires_at": None,
    }
    fields.update(kw)
    return StreakState(**fields)


async def _set_streak(db, profile_id: int, **kw) -> StreakState:
    streak = await db.get(StreakState, profile_id)
    for key, value in kw.items():
        setattr(streak, key, value)
    await db.flush()
    return streak


async def _streak_row(pid: int) -> tuple[int, date | None]:
    async with SessionLocal() as db:
        s = await db.get(StreakState, pid)
        return s.current_streak_len, s.last_active_date


async def _header_streak(client, headers) -> int:
    r = await client.get(f"{API}/profiles/me/gamification", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["streak"]["current"]


# --------------------------------------------------------------------------- what counts
async def test_lesson_only_days_build_a_streak(client, clock):
    headers, pid = await _new_profile(client)
    lesson_id, _ = await _seed_lesson("streak-lesson", pid, ready=4, total=4)
    url = f"{API}/lessons/{lesson_id}/progress"

    for day, part in enumerate((1, 2, 3)):
        clock.now = TUE + day * DAY
        assert (await client.put(url, headers=headers, json={"revealed_up_to": 0})).json()["streak"] is None
        r = await client.put(url, headers=headers, json={"revealed_up_to": part})
        assert r.status_code == 200, r.text
        assert r.json()["streak"]["current"] == day + 1  # a finished part counts for the day
        assert await _header_streak(client, headers) == day + 1

    # Same day again: no new part, no update — and a re-report of an old boundary isn't one either.
    assert (await client.put(url, headers=headers, json={"revealed_up_to": 3})).json()["streak"] is None
    # The next day, only opening the lesson (no part finished) does not count — but yesterday's
    # streak still shows.
    clock.now = TUE + 3 * DAY
    assert (await client.put(url, headers=headers, json={"revealed_up_to": 0})).json()["streak"] is None
    assert await _streak_row(pid) == (3, (TUE + 2 * DAY).date())
    assert await _header_streak(client, headers) == 3


async def test_every_kind_of_graded_answer_counts(client, clock):
    headers, pid = await _new_profile(client)
    _, lesson_item = await _seed_lesson("streak-answers", pid)
    quiz_id, (quiz_item, *_) = await _seed_quiz("streak-quiz", pid, n=2)

    # Day 1: a WRONG lesson-practice answer — finished is finished, right or wrong.
    r = await client.post(f"{API}/answers", headers=headers, json={"item_id": lesson_item, "submitted_value": "b"})
    assert r.status_code == 200, r.text
    assert r.json()["is_correct"] is False
    assert r.json()["streak"]["current"] == 1

    # Day 2: a quiz question inside an attempt (the quiz itself isn't finished).
    clock.now = TUE + DAY
    attempt = (await client.post(f"{API}/quizzes/{quiz_id}/attempts", headers=headers, json={})).json()
    r = await client.post(f"{API}/answers", headers=headers, json={
        "item_id": quiz_item, "attempt_id": attempt["attempt_id"], "submitted_value": "a",
    })
    assert r.status_code == 200, r.text
    assert r.json()["streak"]["current"] == 2

    # Day 3: a review card, rated.
    clock.now = TUE + 2 * DAY
    r = await client.post(f"{API}/review/{lesson_item}", headers=headers, json={"rating": 3})
    assert r.status_code == 200, r.text
    assert r.json()["streak"]["current"] == 3
    assert await _header_streak(client, headers) == 3


async def test_an_ungraded_crisis_response_does_not_count(client):
    async with SessionLocal() as db:
        profile, item = await _seed(db, item_type="short_answer")
        yesterday = TUE - DAY
        await _set_streak(db, profile.id, current_streak_len=4, longest_streak=4,
                          last_active_date=yesterday.date(), repair_window_expires_at=yesterday + 2 * DAY)
        await db.commit()
        res = await gamification.grade_and_reward(
            db, profile, item, AnswerIn(item_id=item.id, submitted_value="I want to kill myself"), None,
            now=TUE,
        )
        await db.commit()
    assert res.support is not None and res.streak is None
    assert await _streak_row(profile.id) == (4, yesterday.date())  # today was not counted


async def test_refused_requests_do_not_count(client, clock):
    headers, pid = await _new_profile(client)
    quiz_id, (i1, i2) = await _seed_quiz("streak-refused", pid, n=2)
    attempt = (await client.post(f"{API}/quizzes/{quiz_id}/attempts", headers=headers, json={})).json()
    answer = {"item_id": i1, "attempt_id": attempt["attempt_id"], "submitted_value": "a"}
    assert (await client.post(f"{API}/answers", headers=headers, json=answer)).status_code == 200
    r = await client.post(f"{API}/attempts/{attempt['attempt_id']}/complete", headers=headers)
    assert r.status_code == 200 and r.json()["streak"]["current"] == 1

    clock.now = TUE + DAY
    refused = [
        await client.post(f"{API}/answers", headers=headers, json={**answer, "item_id": i2}),  # 409 done
        await client.post(f"{API}/answers", headers=headers, json={"item_id": 999999, "submitted_value": "a"}),
        await client.post(f"{API}/answers", headers=headers, json={"submitted_value": "a"}),
        await client.post(f"{API}/review/{i2}", headers=headers, json={"rating": 3}),  # never graded
    ]
    assert [r.status_code for r in refused] == [409, 404, 422, 404]
    assert await _streak_row(pid) == (1, TUE.date())


async def test_one_streak_update_per_request(client, clock, monkeypatch):
    calls: list[datetime] = []
    real = gamification.settle_streak

    async def spy(db, profile, now=None):
        calls.append(now)
        return await real(db, profile, now)

    monkeypatch.setattr(gamification, "settle_streak", spy)
    headers, pid = await _new_profile(client)
    lesson_id, lesson_item = await _seed_lesson("streak-once", pid)
    quiz_id, (quiz_item,) = await _seed_quiz("streak-once-quiz", pid, n=1)

    async def count(request) -> int:
        calls.clear()
        r = await request
        assert r.status_code in (200, 201), r.text
        return len(calls)

    url = f"{API}/lessons/{lesson_id}/progress"
    assert await count(client.put(url, headers=headers, json={"revealed_up_to": 0})) == 0  # opening
    assert await count(client.put(url, headers=headers, json={"revealed_up_to": 1})) == 1
    assert await count(client.post(f"{API}/answers", headers=headers,
                                   json={"item_id": lesson_item, "submitted_value": "a"})) == 1
    attempt = (await client.post(f"{API}/quizzes/{quiz_id}/attempts", headers=headers, json={})).json()
    aid = attempt["attempt_id"]
    assert await count(client.post(f"{API}/answers", headers=headers,
                                   json={"item_id": quiz_item, "attempt_id": aid, "submitted_value": "a"})) == 1
    assert await count(client.post(f"{API}/attempts/{aid}/complete", headers=headers)) == 1


async def test_days_are_utc_days(client):
    """The same instant counts on the same UTC day whatever offset it is expressed in."""
    async with SessionLocal() as db:
        profile, _ = await _seed(db)
        await gamification.settle_streak(db, profile, datetime(2026, 9, 22, 10, 0, tzinfo=UTC))
        prague = timezone(timedelta(hours=2))
        # 00:30 in Prague on the 23rd is still the 22nd in UTC: same day, no advance.
        same = await gamification.settle_streak(db, profile, datetime(2026, 9, 23, 0, 30, tzinfo=prague))
        assert same.current == 1
        # 22:30 in New York on the 22nd is already the 23rd in UTC: the next day.
        new_york = timezone(timedelta(hours=-4))
        nxt = await gamification.settle_streak(db, profile, datetime(2026, 9, 22, 22, 30, tzinfo=new_york))
        assert nxt.current == 2
        assert (await db.get(StreakState, profile.id)).last_active_date == date(2026, 9, 23)


# --------------------------------------------------------------------------- forgiveness
async def test_skipping_monday_still_renews_the_rest_day_budget(client):
    """One rest day a week, used on a Wednesday. Away the next Monday: the new ISO week's rest day
    covers it — the old Monday-only reset never ran because the learner wasn't there on Monday."""
    async with SessionLocal() as db:
        profile, _ = await _seed(db)
        (await db.get(ProfileSettings, profile.id)).rest_days_per_week = 1
        await _set_streak(db, profile.id, freeze_inventory=0)  # only rest days can bridge here

        async def on(day: int, hour: int = 18):
            return await gamification.settle_streak(db, profile, TUE + day * DAY + timedelta(hours=hour - 18))

        await on(0)                                   # Tue 22 Sep -> 1
        info = await on(2)                            # Thu 24 (Wed = rest day) -> 2
        assert (info.current, info.frozen) == (2, False)
        for day in (3, 4, 5):                         # Fri, Sat, Sun 27
            info = await on(day)
        assert info.current == 5
        # Tue 29 Sep, ISO week 40, after the 48 h repair window from Sunday 18:00 has closed.
        info = await on(7, hour=19)
        assert (info.current, info.frozen, info.is_perfect) == (6, False, True)
        streak = await db.get(StreakState, profile.id)
        assert streak.rest_days_used_this_week == 1
        # Coming back again the same day refunds nothing.
        await on(7, hour=20)
        assert streak.rest_days_used_this_week == 1
        # The allowance is per week, not per gap: skipping Wednesday 30 in the same week breaks it.
        info = await on(9, hour=21)                   # Thu 1 Oct, past Tuesday's repair window
        assert info.current == 1


def _at(month: int, day: int, hour: int) -> datetime:
    return datetime(2026, month, day, hour, 0, tzinfo=UTC)


def test_each_missed_day_uses_the_rest_day_of_its_own_week():
    """Away Sun 27 (ISO week 39) and Mon 28 (week 40) with one rest day a week: one rest day from
    each week covers the gap — it used to be one allowance per gap, so this broke the streak (or
    spent a freeze)."""
    state = {"current_streak_len": 6, "longest_streak": 6, "last_active_date": date(2026, 9, 26)}
    back_tuesday = _at(9, 29, 19)
    step = next_streak_step(_state(freeze_inventory=0, **state), now=back_tuesday, rest_cap=1)
    assert (step.outcome, step.current, step.rest_days_used) == (STREAK_BRIDGED, 7, 1)
    step = next_streak_step(_state(freeze_inventory=2, **state), now=back_tuesday, rest_cap=1)
    assert (step.freeze_inventory, step.frozen, step.is_perfect) == (2, False, True)


def test_a_week_whose_rest_day_is_spent_does_not_borrow_the_next_weeks():
    """Rest day used on Wed 23; away Sat 26 and Sun 27 (both week 39), back Mon 28 (week 40)."""
    step = next_streak_step(
        _state(current_streak_len=3, longest_streak=3, last_active_date=date(2026, 9, 25),
               rest_days_used_this_week=1, freeze_inventory=0),
        now=_at(9, 28, 19), rest_cap=1,
    )
    assert step.outcome == STREAK_BROKEN


async def test_a_rest_day_in_each_of_two_weeks_keeps_the_streak(client):
    async with SessionLocal() as db:
        profile, _ = await _seed(db)
        (await db.get(ProfileSettings, profile.id)).rest_days_per_week = 1
        await _set_streak(db, profile.id, freeze_inventory=0)
        for day in range(21, 27):  # Mon 21 .. Sat 26 Sep
            await gamification.settle_streak(db, profile, _at(9, day, 18))
        info = await gamification.settle_streak(db, profile, _at(9, 28, 8))  # rested Sun 27
        assert info.current == 7
        for day in (29, 30):
            info = await gamification.settle_streak(db, profile, _at(9, day, 8))
        info = await gamification.settle_streak(db, profile, _at(10, 2, 18))  # rested Thu 1 Oct
        assert (info.current, info.frozen) == (10, False)


def _day_by_day(last: date, today: date, rest_cap: int, rest_used: int) -> tuple[int, int]:
    """Reference rule: each missed day takes a rest day from its own ISO week while one is left.
    Returns (missed days covered, rest days used in today's week)."""
    used = {last.isocalendar()[:2]: rest_used}
    covered = 0
    day = last + timedelta(days=1)
    while day < today:
        week = day.isocalendar()[:2]
        if used.get(week, 0) < rest_cap:
            used[week] = used.get(week, 0) + 1
            covered += 1
        day += timedelta(days=1)
    return covered, used.get(today.isocalendar()[:2], 0)


def test_rest_days_match_a_day_by_day_count_on_every_gap():
    monday = date(2026, 9, 21)
    for start, gap, rest_cap in itertools.product(range(7), range(1, 24), range(3)):
        for rest_used in range(rest_cap + 1):
            last = monday + timedelta(days=start)
            today = last + timedelta(days=gap)
            covered, used_today = _day_by_day(last, today, rest_cap, rest_used)
            step = next_streak_step(
                _state(current_streak_len=4, longest_streak=4, last_active_date=last,
                       rest_days_used_this_week=rest_used, freeze_inventory=0),
                now=datetime(today.year, today.month, today.day, 12, tzinfo=UTC), rest_cap=rest_cap,
            )
            case = (last, today, rest_cap, rest_used)
            if covered == gap - 1:
                assert step.outcome != STREAK_BROKEN, case
                assert step.rest_days_used == used_today, case
            else:
                assert step.outcome == STREAK_BROKEN, case


def test_forgiveness_order_is_rest_days_then_freezes_then_repair():
    last = date(2026, 9, 22)  # a Tuesday
    # Two missed days (Wed, Thu): the rest day takes one, a freeze the other.
    step = next_streak_step(
        _state(current_streak_len=5, longest_streak=5, last_active_date=last, freeze_inventory=2),
        now=datetime(2026, 9, 25, 9, 0, tzinfo=UTC), rest_cap=1,
    )
    assert (step.outcome, step.current, step.rest_days_used, step.freeze_inventory) == (STREAK_BRIDGED, 6, 1, 1)
    assert step.frozen and not step.is_perfect

    # One missed day, a freeze in stock and the repair window still open: the freeze goes first.
    open_window = datetime(2026, 9, 24, 17, 0, tzinfo=UTC)
    state = {
        "current_streak_len": 5, "longest_streak": 5, "last_active_date": last,
        "repair_window_expires_at": open_window + timedelta(hours=1),
    }
    step = next_streak_step(_state(freeze_inventory=1, **state), now=open_window, rest_cap=0)
    assert (step.current, step.freeze_inventory, step.freezes_used) == (6, 0, 1)
    # No freeze left: the repair window bridges the single missed day.
    step = next_streak_step(_state(freeze_inventory=0, **state), now=open_window, rest_cap=0)
    assert (step.outcome, step.current, step.frozen, step.is_perfect) == (STREAK_BRIDGED, 6, True, False)
    # Window closed: broken.
    late = open_window + timedelta(hours=2)
    assert next_streak_step(_state(freeze_inventory=0, **state), now=late, rest_cap=0).outcome == STREAK_BROKEN


def test_an_unbridgeable_gap_spends_nothing():
    step = next_streak_step(
        _state(current_streak_len=9, longest_streak=9, last_active_date=date(2026, 9, 1), freeze_inventory=2),
        now=TUE, rest_cap=1,
    )
    assert step.outcome == STREAK_BROKEN
    assert (step.current, step.longest, step.freeze_inventory, step.is_perfect) == (1, 9, 2, True)


# --------------------------------------------------------------------------- the snapshot
async def test_snapshot_shows_the_streak_while_bridgeable_and_0_after(client):
    async with SessionLocal() as db:
        profile, _ = await _seed(db)
        last = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)  # Monday
        streak = await _set_streak(db, profile.id, current_streak_len=7, longest_streak=7,
                                   last_active_date=last.date(), freeze_inventory=2,
                                   repair_window_expires_at=last + 2 * DAY)

        async def shown(now: datetime) -> int:
            return (await profile_service.build_snapshot(db, profile, now=now)).streak.current

        assert await shown(last + timedelta(hours=1)) == 7    # today
        assert await shown(last + DAY) == 7                   # yesterday
        assert await shown(last + 3 * DAY) == 7               # 2 missed days, 2 freezes left
        assert await shown(last + 4 * DAY) == 0               # 3 missed days: can't be bridged
        assert await shown(last + 14 * DAY) == 0              # away two weeks
        # Without freezes: the repair window keeps it visible for its 48 h, then it's 0.
        streak.freeze_inventory = 0
        await db.flush()
        assert await shown(last + 2 * DAY - timedelta(minutes=1)) == 7
        assert await shown(last + 2 * DAY + timedelta(minutes=1)) == 0
        # Reading never writes: the stored streak is untouched until the learner is next active.
        snap = await profile_service.build_snapshot(db, profile, now=last + 14 * DAY)
        assert not db.dirty and not db.new
        assert (streak.current_streak_len, streak.freeze_inventory, streak.last_active_date) == (7, 0, last.date())
        assert (snap.streak.longest, snap.streak.frozen) == (7, False)  # the personal best stays


async def test_snapshot_and_settle_agree(client):
    """For every combination: what the snapshot shows now, plus today (on a new day), is exactly what
    settling at that moment produces — 0 + 1 = a fresh start, N + 1 = carried on. (The snapshot's
    streak is ``streak_info_as_of``; the test above covers it inside ``build_snapshot``.)"""
    async with SessionLocal() as db:
        profile, _ = await _seed(db)
        settings = await db.get(ProfileSettings, profile.id)
        checked = 0
        grid = itertools.product(
            (1, 30),                    # stored streak length (30 = the long-streak freeze cap)
            (date(2026, 9, 24), date(2026, 9, 27)),  # last active on a Thursday / a Sunday
            (0, 1, 2, 3, 4, 9),         # days since then
            (0, 1, 3),                  # freezes in stock (3 > the short-streak cap of 2)
            ((0, 0), (1, 0), (1, 1)),   # (rest days per week, already used this week)
            ("none", "open", "closed"),  # repair window
        )
        for length, last, gap, freezes, (rest_cap, rest_used), window in grid:
            now = datetime.combine(last + gap * DAY, datetime.min.time(), UTC) + timedelta(hours=12)
            expires = {"none": None, "open": now + timedelta(hours=1), "closed": now - timedelta(hours=1)}
            settings.rest_days_per_week = rest_cap
            streak = await _set_streak(
                db, profile.id, current_streak_len=length, longest_streak=length, last_active_date=last,
                freeze_inventory=freezes, freezes_used_in_current_streak=0,
                rest_days_used_this_week=rest_used, is_perfect=True, repair_window_expires_at=expires[window],
            )
            shown = (await gamification.streak_info_as_of(db, profile, streak, now)).current
            settled = (await gamification.settle_streak(db, profile, now)).current
            case = (length, last, gap, freezes, rest_cap, rest_used, window)
            assert settled == shown + (1 if gap else 0), case
            checked += 1
        assert checked == 648


# --------------------------------------------------------------------------- badges
async def _resilient_unlocked(db, pid: int) -> bool:
    row = await db.scalar(
        select(ProfileBadge)
        .join(BadgeDefinition, BadgeDefinition.id == ProfileBadge.badge_id)
        .where(ProfileBadge.profile_id == pid, BadgeDefinition.code == "resilient")
    )
    return row is not None and row.unlocked_at is not None


async def _after_a_long_break(db, profile: Profile) -> None:
    """A 6-day streak that ended two weeks ago (too long ago to bridge)."""
    await _set_streak(db, profile.id, current_streak_len=6, longest_streak=6,
                      last_active_date=(TUE - 14 * DAY).date(), freeze_inventory=2)


async def test_the_comeback_badge_is_awarded_once_when_answers_settle_every_time(client):
    async with SessionLocal() as db:
        profile, item = await _seed(db, item_type="true_false")
        item.payload_json = {"kind": "true_false", "answer": True}
        await _after_a_long_break(db, profile)

        async def answer(now: datetime):
            return await gamification.grade_and_reward(
                db, profile, item, AnswerIn(item_id=item.id, submitted_value=True), None, now=now
            )

        first = await answer(TUE)
        assert first.streak.current == 1
        assert "resilient" in [b.code for b in first.new_badges]  # settled before the badges ran
        for now in (TUE + timedelta(minutes=5), TUE + DAY, TUE + 2 * DAY):
            assert "resilient" not in [b.code for b in (await answer(now)).new_badges]
        assert (await db.get(StreakState, profile.id)).current_streak_len == 3


async def test_the_comeback_badge_reaches_a_lesson_only_learner(client):
    headers, pid = await _new_profile(client)
    lesson_id, _ = await _seed_lesson("streak-badge-lesson", pid)
    async with SessionLocal() as db:
        profile = await db.get(Profile, pid)
        lesson = await db.get(Lesson, lesson_id)
        await _after_a_long_break(db, profile)
        state = await progress_service.save_lesson_progress(db, profile, lesson, 1, now=TUE)
        assert state.streak is not None and state.streak.current == 1
        assert await _resilient_unlocked(db, pid)
        # ...and the reply says so: it is awarded only once, so this is the one chance to show it.
        assert [b.code for b in state.new_badges] == ["resilient"]
        again = await progress_service.save_lesson_progress(db, profile, lesson, 2, now=TUE)
        assert again.new_badges == []


async def test_finishing_a_quiz_still_counts(client, clock):
    headers, pid = await _new_profile(client)
    quiz_id, _ = await _seed_quiz("streak-finish", pid, n=1)
    attempt = (await client.post(f"{API}/quizzes/{quiz_id}/attempts", headers=headers, json={})).json()
    r = await client.post(f"{API}/attempts/{attempt['attempt_id']}/complete", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["streak"]["current"] == 1
    assert await _streak_row(pid) == (1, TUE.date())


async def test_finishing_a_finished_quiz_again_records_nothing(client, clock):
    """A stale second tab taps Finish the next day: the same summary comes back, but no new
    completion time, no streak day and no badges."""
    headers, pid = await _new_profile(client)
    quiz_id, (i1, i2) = await _seed_quiz("streak-refinish", pid, n=2)
    aid = (await client.post(f"{API}/quizzes/{quiz_id}/attempts", headers=headers, json={})).json()["attempt_id"]
    for item in (i1, i2):
        r = await client.post(f"{API}/answers", headers=headers,
                              json={"item_id": item, "attempt_id": aid, "submitted_value": "a"})
        assert r.status_code == 200, r.text
    first = await client.post(f"{API}/attempts/{aid}/complete", headers=headers)
    assert first.status_code == 200 and first.json()["streak"]["current"] == 1
    async with SessionLocal() as db:
        finished_at = (await db.get(QuizAttempt, aid)).completed_at

    clock.now = TUE + DAY
    again = await client.post(f"{API}/attempts/{aid}/complete", headers=headers)
    assert again.status_code == 200, again.text
    body = again.json()
    assert (body["score"], body["max_score"], body["new_badges"]) == (2, 2, [])
    assert body["streak"]["current"] == 1  # as it stands now: yesterday's day, nothing added
    assert await _streak_row(pid) == (1, TUE.date())
    async with SessionLocal() as db:
        assert (await db.get(QuizAttempt, aid)).completed_at == finished_at


# --------------------------------------------------------------------------- the day the rule went live
LAST_QUIZ = datetime(2026, 10, 20, 17, 0, tzinfo=UTC)


async def _lesson_answers(pid: int, item_id: int, moments) -> None:
    async with SessionLocal() as db:
        for moment in moments:
            db.add(Answer(profile_id=pid, item_id=item_id, attempt_id=None, submitted_value_json="a",
                          is_correct=True, fsrs_rating=3, created_at=moment))
        await db.commit()


async def test_lesson_days_before_the_new_rule_are_counted_once(client):
    """Only a finished quiz used to move the streak: a child learning through lessons every day would
    have seen 0 the day the new rule went live. Their lesson days are counted at startup."""
    headers, pid = await _new_profile(client)
    _, item_id = await _seed_lesson("catch-up-lessons", pid)
    async with SessionLocal() as db:
        await _set_streak(db, pid, current_streak_len=4, longest_streak=4,
                          last_active_date=LAST_QUIZ.date(), freeze_inventory=2,
                          repair_window_expires_at=LAST_QUIZ + timedelta(hours=48))
        await db.commit()
    await _lesson_answers(pid, item_id, [LAST_QUIZ + d * DAY for d in range(1, 8)])  # 21..27 Oct

    async with SessionLocal() as db:
        seen_at = (await db.get(Profile, pid)).last_active_at
        assert await catch_up_streaks(db) == 1
        await db.commit()
    assert await _streak_row(pid) == (11, date(2026, 10, 27))
    async with SessionLocal() as db:
        profile = await db.get(Profile, pid)
        assert profile.last_active_at == seen_at  # not moved back to a replayed day
        assert (await profile_service.build_snapshot(db, profile, now=_at(10, 28, 7))).streak.current == 11
        # Idempotent: nothing is after the stored last active day any more.
        assert await catch_up_streaks(db) == 0
    assert await _streak_row(pid) == (11, date(2026, 10, 27))


async def test_a_lesson_only_learner_gets_their_streak(client):
    headers, pid = await _new_profile(client)
    _, item_id = await _seed_lesson("catch-up-only-lessons", pid)
    await _lesson_answers(pid, item_id, [_at(10, day, 16) for day in (25, 26, 26, 27)])
    async with SessionLocal() as db:
        assert await catch_up_streaks(db) == 1
        await db.commit()
    assert await _streak_row(pid) == (3, date(2026, 10, 27))


async def test_a_failing_catch_up_never_stops_the_app_from_starting(monkeypatch):
    from app import main
    from app.services import streak_catchup

    async def boom(_db):
        raise RuntimeError("bad row")

    monkeypatch.setattr(streak_catchup, "catch_up_streaks", boom)
    await main._catch_up_streaks()  # logged, not raised


async def test_the_catch_up_keeps_the_repair_window_a_later_lesson_set(client):
    """No freezes left. Wed 21: lessons at 08:00 and 20:00; Thu 22: nothing; Fri 23 16:00 and daily
    after. Counted live, the 20:00 answer moved the 48 h window past Fri 16:00 and Thursday was
    forgiven. Replaying only each day's first answer broke the streak at Friday."""
    headers, pid = await _new_profile(client)
    _, item_id = await _seed_lesson("catch-up-window", pid)
    async with SessionLocal() as db:
        await _set_streak(db, pid, current_streak_len=4, longest_streak=4,
                          last_active_date=LAST_QUIZ.date(), freeze_inventory=0,
                          repair_window_expires_at=LAST_QUIZ + timedelta(hours=48))
        await db.commit()
    moments = [_at(10, 21, 8), _at(10, 21, 20), _at(10, 23, 16)] + [_at(10, d, 16) for d in range(24, 28)]
    await _lesson_answers(pid, item_id, moments)
    async with SessionLocal() as db:
        assert await catch_up_streaks(db) == 1
        await db.commit()
    assert await _streak_row(pid) == (10, date(2026, 10, 27))


async def test_a_lesson_after_the_last_quiz_that_day_still_moves_the_window(client):
    """Quiz Tue 27 at 08:00 (the stored day), lessons that evening at 20:00, away Wed 28, back Thu 29
    at 15:00: counted live, the 20:00 answer keeps Thursday inside the repair window."""
    headers, pid = await _new_profile(client)
    _, item_id = await _seed_lesson("catch-up-same-day", pid)
    quiz = _at(10, 27, 8)
    async with SessionLocal() as db:
        await _set_streak(db, pid, current_streak_len=4, longest_streak=4, last_active_date=quiz.date(),
                          freeze_inventory=0, repair_window_expires_at=quiz + timedelta(hours=48))
        await db.commit()
    await _lesson_answers(pid, item_id, [_at(10, 27, 20)])
    async with SessionLocal() as db:
        assert await catch_up_streaks(db) == 1
        await db.commit()
        profile = await db.get(Profile, pid)
        assert (await gamification.settle_streak(db, profile, _at(10, 29, 15))).current == 5
        assert await catch_up_streaks(db) == 0


async def test_the_catch_up_matches_counting_every_activity_live(client):
    """Random histories (several sessions on some days, gaps, rest days): replaying each day's
    first and last moment ends exactly where settling every activity as it happened does."""
    import random

    rng = random.Random(20261028)
    for case in range(40):
        headers, pid = await _new_profile(client)
        _, item_id = await _seed_lesson(f"catch-up-live-{case}", pid)
        rest_cap = rng.choice([0, 1, 2])
        async with SessionLocal() as db:
            (await db.get(ProfileSettings, pid)).rest_days_per_week = rest_cap
            await db.commit()
        moments, day = [], _at(9, 1, 0)
        for _ in range(rng.randint(5, 30)):
            day += timedelta(days=rng.choice([1, 1, 1, 2, 2, 3, 5]))
            for _ in range(rng.choice([1, 1, 2, 3])):
                moments.append(day + timedelta(hours=rng.randint(0, 23), minutes=rng.randint(0, 59)))
        moments.sort()
        await _lesson_answers(pid, item_id, moments)

        live = _state(profile_id=pid, freeze_inventory=2)
        for moment in moments:
            gamification.apply_streak_step(live, now=moment, rest_cap=rest_cap)
        async with SessionLocal() as db:
            assert await catch_up_streaks(db) >= 1
            await db.commit()
            row = await db.get(StreakState, pid)
            fields = ("current_streak_len", "longest_streak", "last_active_date", "freeze_inventory",
                      "freezes_used_in_current_streak", "rest_days_used_this_week", "is_perfect")
            assert [getattr(row, f) for f in fields] == [getattr(live, f) for f in fields], case
            assert row.repair_window_expires_at.replace(tzinfo=UTC) == live.repair_window_expires_at


async def test_the_catch_up_costs_a_few_queries_whatever_the_history(client):
    """It runs before the app answers health checks: one query per replayed day for every learner
    could hold a big first deploy past the health gate."""
    from sqlalchemy import event

    from app.db.session import engine

    for n in range(3):
        headers, pid = await _new_profile(client)
        _, item_id = await _seed_lesson(f"catch-up-cost-{n}", pid)
        await _lesson_answers(pid, item_id, [_at(9, 1, 9) + timedelta(days=d, hours=h)
                                              for d in range(60) for h in (0, 5)])
    statements: list[str] = []

    def count(*_args, **_kwargs):
        statements.append("x")

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        async with SessionLocal() as db:
            assert await catch_up_streaks(db) == 3
            await db.commit()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)
    assert len(statements) <= 12, len(statements)

"""Resume-where-you-left-off over the real ASGI app: a learner who refreshes, takes a break, or moves
to another device (same resume code) gets back to the exact question / lesson part, with their
already-graded answers replayed — and nothing else revealed, re-graded or re-rewarded."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import (
    Answer,
    Concept,
    Item,
    ItemFsrsCard,
    LearningRequest,
    Lesson,
    LessonSection,
    Profile,
    Quiz,
    QuizQuestion,
)

API = "/api/v1"


async def _new_profile(client) -> tuple[dict, int]:
    code = (await client.post(f"{API}/profiles", json={})).json()["resume_code"]
    headers = {"X-Resume-Code": code}
    pid = (await client.get(f"{API}/profiles/me", headers=headers)).json()["profile"]["id"]
    return headers, pid


def _mcq(concept_id: int, correct: str, *, section_id: int | None = None) -> Item:
    return Item(
        concept_id=concept_id, lesson_section_id=section_id, item_type="mcq", bloom_tier=2,
        difficulty="medium", item_difficulty=3, language="en", stem_markdown="Pick one",
        explanation="Because.", model_id="m", prompt_version="v",
        payload_json={
            "kind": "mcq", "multiple": False,
            "options": [
                {"id": "a", "text": "Apple", "is_correct": correct == "a"},
                {"id": "b", "text": "Banana", "is_correct": correct == "b"},
            ],
        },
    )


async def _seed_quiz(request_id: str, pid: int | None, n: int = 3) -> tuple[int, list[int]]:
    """A ready quiz of ``n`` MCQs (correct answer always 'a'), owned by ``pid``'s request."""
    async with SessionLocal() as db:
        concept = Concept(slug=f"c-{request_id}", name="C", subject="science")
        db.add(concept)
        await db.flush()
        items = [_mcq(concept.id, "a") for _ in range(n)]
        db.add_all(items)
        quiz = Quiz(request_id=request_id, title=f"Quiz {request_id}", language="en",
                    grade_band="G3-5", subject="science", model_id="m", prompt_version="v")
        db.add(quiz)
        await db.flush()
        db.add_all(
            QuizQuestion(quiz_id=quiz.id, item_id=it.id, ordinal=i + 1, points=10)
            for i, it in enumerate(items)
        )
        db.add(LearningRequest(
            request_id=request_id, profile_id=pid, decision_type="proceed", mode="test",
            status="ready", quiz_id=quiz.id, structured_intent_json={}, prompt_version="v",
            model_id="m",
        ))
        await db.commit()
        return quiz.id, [it.id for it in items]


async def _seed_lesson(
    request_id: str, pid: int | None, *, ready: int = 3, total: int = 4, item_in: int = 1
) -> tuple[int, int]:
    """A lesson of ``total`` sections, the first ``ready`` generated, with one MCQ (correct 'a') in
    section ``item_in``. Returns (lesson_id, item_id)."""
    async with SessionLocal() as db:
        concept = Concept(slug=f"c-{request_id}", name="C", subject="science")
        db.add(concept)
        lesson = Lesson(
            request_id=request_id, topic=f"Lesson {request_id}", detected_language="en",
            grade_band="G3-5", subject="science", target_fkgl=5.0, objectives_json=[],
            model_id="m", prompt_version="v",
        )
        db.add(lesson)
        await db.flush()
        sections = [
            LessonSection(
                lesson_id=lesson.id, ordinal=i, kind="explanation", title=f"Part {i}",
                body_markdown="text" if i < ready else None,
                gen_status="ready" if i < ready else "pending",
            )
            for i in range(total)
        ]
        db.add_all(sections)
        await db.flush()
        item = _mcq(concept.id, "a", section_id=sections[item_in].id)
        db.add(item)
        db.add(LearningRequest(
            request_id=request_id, profile_id=pid, decision_type="proceed", mode="study",
            status="ready", lesson_id=lesson.id, structured_intent_json={}, prompt_version="v",
            model_id="m",
        ))
        await db.commit()
        return lesson.id, item.id


async def _reward_state(pid: int, item_ids: list[int]) -> tuple[int, int, int]:
    """(total XP, answer rows, FSRS reps) — everything a replay must leave untouched."""
    async with SessionLocal() as db:
        xp = await db.scalar(select(Profile.total_xp).where(Profile.id == pid))
        answers = await db.scalar(
            select(func.count()).select_from(Answer).where(Answer.profile_id == pid)
        )
        reps = await db.scalar(
            select(func.coalesce(func.sum(ItemFsrsCard.reps), 0)).where(
                ItemFsrsCard.profile_id == pid, ItemFsrsCard.item_id.in_(item_ids)
            )
        )
        return xp, answers, reps


@pytest.mark.asyncio
async def test_quiz_attempt_resumes_at_the_exact_question(client):
    headers, pid = await _new_profile(client)
    quiz_id, (i1, i2, i3) = await _seed_quiz("resume-quiz", pid)

    r = await client.post(f"{API}/quizzes/{quiz_id}/attempts", headers=headers, json={})
    assert r.status_code == 201, r.text
    started = r.json()
    attempt_id = started["attempt_id"]
    assert started["resumed"] is False
    assert started["current_index"] == 0
    assert started["answers"] == []

    def answer(item_id, value):
        return client.post(f"{API}/answers", headers=headers, json={
            "item_id": item_id, "attempt_id": attempt_id, "submitted_value": value,
        })

    def move_to(index):
        return client.put(
            f"{API}/attempts/{attempt_id}/position", headers=headers, json={"current_index": index}
        )

    # Q1 right → Next → Q2 wrong (feedback on screen, "Next" not pressed yet) … then the tab dies.
    assert (await answer(i1, "a")).status_code == 200
    assert (await move_to(1)).json() == {"current_index": 1}
    assert (await answer(i2, "b")).status_code == 200
    before = await _reward_state(pid, [i1, i2, i3])

    # Coming back (refresh / new tab / other device with the same code): same attempt, same spot.
    r = await client.post(f"{API}/quizzes/{quiz_id}/attempts", headers=headers, json={})
    assert r.status_code == 201, r.text
    resumed = r.json()
    assert resumed["attempt_id"] == attempt_id
    assert resumed["resumed"] is True
    assert resumed["current_index"] == 1
    by_item = {a["item_id"]: a for a in resumed["answers"]}
    assert set(by_item) == {i1, i2}  # the unanswered Q3 reveals nothing
    assert by_item[i1]["submitted_value"] == "a"
    assert by_item[i1]["result"]["is_correct"] is True
    assert by_item[i2]["submitted_value"] == "b"
    assert by_item[i2]["result"]["is_correct"] is False
    assert by_item[i2]["result"]["correct_answer"] == "a"
    assert by_item[i2]["result"]["explanation"] == "Because."
    assert by_item[i2]["result"]["feedback"]["text"]
    # Replaying is a pure read: no extra XP, answer rows or FSRS reviews.
    assert await _reward_state(pid, [i1, i2, i3]) == before

    # The position only moves forward and never past the last question.
    assert (await move_to(2)).json() == {"current_index": 2}
    assert (await move_to(0)).json() == {"current_index": 2}
    assert (await move_to(99)).json() == {"current_index": 2}
    assert (await move_to(-1)).status_code == 422

    # Another learner can neither move this attempt nor see its answers.
    other, _ = await _new_profile(client)
    r = await client.put(
        f"{API}/attempts/{attempt_id}/position", headers=other, json={"current_index": 1}
    )
    assert r.status_code == 404
    theirs = (await client.post(f"{API}/quizzes/{quiz_id}/attempts", headers=other, json={})).json()
    assert theirs["attempt_id"] != attempt_id
    assert theirs["resumed"] is False and theirs["answers"] == []
    assert (await client.put(f"{API}/attempts/{attempt_id}/position", json={"current_index": 1})).status_code == 401

    # Once finished, the attempt is closed; opening the quiz again starts a clean one.
    r = await client.post(f"{API}/attempts/{attempt_id}/complete", headers=headers, json={})
    assert r.status_code == 200, r.text
    assert (await move_to(2)).status_code == 409
    fresh = (await client.post(f"{API}/quizzes/{quiz_id}/attempts", headers=headers, json={})).json()
    assert fresh["attempt_id"] != attempt_id
    assert fresh["resumed"] is False
    assert fresh["current_index"] == 0 and fresh["answers"] == []


@pytest.mark.asyncio
async def test_quiz_resume_never_lands_behind_an_answered_question(client):
    """A lost position update must not park the learner on a question they already passed."""
    headers, pid = await _new_profile(client)
    quiz_id, (i1, i2, _i3) = await _seed_quiz("resume-heal", pid)
    attempt_id = (
        await client.post(f"{API}/quizzes/{quiz_id}/attempts", headers=headers, json={})
    ).json()["attempt_id"]
    for item_id in (i1, i2):  # answered, but no position was ever saved
        r = await client.post(f"{API}/answers", headers=headers, json={
            "item_id": item_id, "attempt_id": attempt_id, "submitted_value": "a",
        })
        assert r.status_code == 200, r.text

    resumed = (
        await client.post(f"{API}/quizzes/{quiz_id}/attempts", headers=headers, json={})
    ).json()
    assert resumed["current_index"] == 1  # on Q2 (answered, feedback showing), not back on Q1


@pytest.mark.asyncio
async def test_quiz_in_progress_cannot_be_reviewed(client):
    """The review reveals every correct answer, so it has to wait until the attempt is finished —
    otherwise a learner mid-quiz could read the answers to the questions still ahead of them."""
    headers, pid = await _new_profile(client)
    quiz_id, (i1, _i2, _i3) = await _seed_quiz("review-open", pid)
    review_url = f"{API}/quizzes/{quiz_id}/review"

    async def history_row():
        rows = (await client.get(f"{API}/profiles/me/requests", headers=headers)).json()
        return next(row for row in rows if row["request_id"] == "review-open")

    async def start():
        r = await client.post(f"{API}/quizzes/{quiz_id}/attempts", headers=headers, json={})
        return r.json()["attempt_id"]

    def answer(attempt_id, value):
        return client.post(f"{API}/answers", headers=headers, json={
            "item_id": i1, "attempt_id": attempt_id, "submitted_value": value,
        })

    first = await start()
    assert (await answer(first, "a")).status_code == 200

    # One question answered, two to go: nothing is reviewable and the list doesn't offer it.
    assert (await client.get(review_url, headers=headers)).status_code == 404
    assert (await history_row())["attempted"] is False

    # Finished → the whole quiz can be reviewed, unanswered questions included.
    await client.post(f"{API}/attempts/{first}/complete", headers=headers, json={})
    r = await client.get(review_url, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["attempt_id"] == first and body["total"] == 3
    assert [it["correct_answer"] for it in body["items"]] == ["a", "a", "a"]
    assert (await history_row())["attempted"] is True

    # A second go, in progress: the review still shows the finished attempt, never the open one.
    second = await start()
    assert second != first
    assert (await answer(second, "b")).status_code == 200
    body = (await client.get(review_url, headers=headers)).json()
    assert body["attempt_id"] == first
    assert body["items"][0]["submitted_value"] == "a"


@pytest.mark.asyncio
async def test_lesson_progress_restores_boundary_and_answers(client):
    headers, pid = await _new_profile(client)
    lesson_id, item_id = await _seed_lesson("resume-lesson", pid, ready=3, total=4, item_in=1)
    url = f"{API}/lessons/{lesson_id}/progress"

    def reveal(n):
        return client.put(url, headers=headers, json={"revealed_up_to": n})

    # Opening the lesson reports 0: nothing saved yet, so it starts at the top (and opening isn't a
    # finished part, so nothing counts toward the streak).
    r = await reveal(0)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "lesson_id": lesson_id, "revealed_up_to": 0, "completed": False, "answers": [],
        "streak": None, "new_badges": [],
    }

    # Revealing moves the boundary forward only.
    assert (await reveal(2)).json()["revealed_up_to"] == 2
    assert (await reveal(1)).json()["revealed_up_to"] == 2
    # Section 3 isn't generated yet, so it can't have been revealed — and the lesson isn't done.
    capped = (await reveal(9)).json()
    assert capped["revealed_up_to"] == 2 and capped["completed"] is False
    assert (await reveal(-1)).status_code == 422

    # The learner answers the practice question in part 1 (lesson-embedded ⇒ no attempt).
    r = await client.post(
        f"{API}/answers", headers=headers, json={"item_id": item_id, "submitted_value": "b"}
    )
    assert r.status_code == 200, r.text
    before = await _reward_state(pid, [item_id])

    # Coming back (opening reports 0 again): same boundary, and the answered question is answered.
    state = (await reveal(0)).json()
    assert state["revealed_up_to"] == 2
    assert len(state["answers"]) == 1
    replayed = state["answers"][0]
    assert replayed["item_id"] == item_id
    assert replayed["submitted_value"] == "b"
    assert replayed["result"]["is_correct"] is False
    assert replayed["result"]["correct_answer"] == "a"
    assert replayed["result"]["explanation"] == "Because."
    assert await _reward_state(pid, [item_id]) == before  # nothing re-graded / re-rewarded

    # Per learner: someone else opening the same lesson starts at the top with nothing answered.
    other, _ = await _new_profile(client)
    theirs = (await client.put(url, headers=other, json={"revealed_up_to": 0})).json()
    assert theirs["revealed_up_to"] == 0 and theirs["answers"] == []

    # Reaching the last part completes the lesson.
    async with SessionLocal() as db:
        last = await db.scalar(
            select(LessonSection).where(
                LessonSection.lesson_id == lesson_id, LessonSection.ordinal == 3
            )
        )
        last.gen_status = "ready"
        last.body_markdown = "text"
        await db.commit()
    done = (await reveal(3)).json()
    assert done["revealed_up_to"] == 3 and done["completed"] is True

    assert (await client.put(url, json={"revealed_up_to": 1})).status_code == 401
    r = await client.put(f"{API}/lessons/999999/progress", headers=headers, json={"revealed_up_to": 1})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_lesson_resume_never_lands_behind_an_answered_section(client):
    """Sessions from before progress was saved (or a lost update) still resume at the part the
    learner demonstrably reached — they answered a question in it."""
    headers, pid = await _new_profile(client)
    lesson_id, item_id = await _seed_lesson("resume-legacy", pid, ready=4, total=4, item_in=2)
    r = await client.post(
        f"{API}/answers", headers=headers, json={"item_id": item_id, "submitted_value": "a"}
    )
    assert r.status_code == 200, r.text

    state = (
        await client.put(
            f"{API}/lessons/{lesson_id}/progress", headers=headers, json={"revealed_up_to": 0}
        )
    ).json()
    assert state["revealed_up_to"] == 2
    assert [a["item_id"] for a in state["answers"]] == [item_id]


@pytest.mark.asyncio
async def test_history_and_continue_report_progress(client):
    headers, pid = await _new_profile(client)

    async def continue_pick():
        r = await client.get(f"{API}/profiles/me/continue", headers=headers)
        assert r.status_code == 200, r.text
        return r.json()

    async def history():
        rows = (await client.get(f"{API}/profiles/me/requests", headers=headers)).json()
        return {row["request_id"]: row for row in rows}

    assert await continue_pick() is None  # nothing started yet

    lesson_id, _ = await _seed_lesson("cont-lesson", pid, ready=4, total=4)
    quiz_id, (i1, _i2, _i3) = await _seed_quiz("cont-quiz", pid)
    rows = await history()
    assert rows["cont-lesson"]["progress"] is None  # created but never opened
    assert rows["cont-quiz"]["progress"] is None

    # Read two parts of the lesson, then leave.
    await client.put(
        f"{API}/lessons/{lesson_id}/progress", headers=headers, json={"revealed_up_to": 1}
    )
    pick = await continue_pick()
    assert pick["request_id"] == "cont-lesson" and pick["mode"] == "study"
    assert pick["progress"]["position"] == 2 and pick["progress"]["total"] == 4
    assert pick["progress"]["completed"] is False

    # Then start the quiz, answer Q1 and move on to Q2 — now the quiz is the most recent.
    attempt_id = (
        await client.post(f"{API}/quizzes/{quiz_id}/attempts", headers=headers, json={})
    ).json()["attempt_id"]
    await client.post(f"{API}/answers", headers=headers, json={
        "item_id": i1, "attempt_id": attempt_id, "submitted_value": "a",
    })
    await client.put(
        f"{API}/attempts/{attempt_id}/position", headers=headers, json={"current_index": 1}
    )
    pick = await continue_pick()
    assert pick["request_id"] == "cont-quiz" and pick["mode"] == "test"
    assert pick["progress"]["position"] == 2 and pick["progress"]["total"] == 3

    rows = await history()
    assert rows["cont-lesson"]["progress"]["position"] == 2
    assert rows["cont-quiz"]["progress"]["position"] == 2
    assert rows["cont-quiz"]["progress"]["completed"] is False

    # Finishing the quiz hands "continue" back to the unfinished lesson …
    await client.post(f"{API}/attempts/{attempt_id}/complete", headers=headers, json={})
    assert (await continue_pick())["request_id"] == "cont-lesson"
    assert (await history())["cont-quiz"]["progress"]["completed"] is True

    # … and finishing that leaves nothing to continue.
    await client.put(
        f"{API}/lessons/{lesson_id}/progress", headers=headers, json={"revealed_up_to": 3}
    )
    assert await continue_pick() is None
    assert (await history())["cont-lesson"]["progress"]["completed"] is True

    # Another learner sees none of it.
    other, _ = await _new_profile(client)
    assert (await client.get(f"{API}/profiles/me/continue", headers=other)).json() is None
    assert (await client.get(f"{API}/profiles/me/continue")).status_code == 401


@pytest.mark.asyncio
async def test_continue_skips_finished_sessions_even_if_more_recent(client):
    headers, pid = await _new_profile(client)
    unfinished_id, _ = await _seed_lesson("cont-old", pid, ready=4, total=4)
    finished_id, _ = await _seed_lesson("cont-new", pid, ready=4, total=4)
    quiz_id, _ = await _seed_quiz("cont-done-quiz", pid)

    await client.put(
        f"{API}/lessons/{unfinished_id}/progress", headers=headers, json={"revealed_up_to": 2}
    )
    # Afterwards: read another lesson to the end, and take a whole quiz.
    await client.put(
        f"{API}/lessons/{finished_id}/progress", headers=headers, json={"revealed_up_to": 3}
    )
    attempt_id = (
        await client.post(f"{API}/quizzes/{quiz_id}/attempts", headers=headers, json={})
    ).json()["attempt_id"]
    await client.post(f"{API}/attempts/{attempt_id}/complete", headers=headers, json={})

    pick = (await client.get(f"{API}/profiles/me/continue", headers=headers)).json()
    assert pick["request_id"] == "cont-old"
    assert pick["progress"]["position"] == 3 and pick["progress"]["total"] == 4


@pytest.mark.asyncio
async def test_existing_database_gains_the_resume_columns():
    """Upgrading in place: an older quiz_attempts table (no position columns) is migrated additively,
    so learners keep their history."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.db.session import _ensure_sqlite_columns

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE quiz_attempts (id INTEGER PRIMARY KEY, quiz_id INTEGER)"))
        await conn.execute(text("INSERT INTO quiz_attempts (id, quiz_id) VALUES (1, 7)"))
        await _ensure_sqlite_columns(conn)
        await _ensure_sqlite_columns(conn)  # idempotent
        row = (
            await conn.execute(text("SELECT current_index, last_active_at FROM quiz_attempts"))
        ).one()
    await engine.dispose()
    assert tuple(row) == (0, None)


@pytest.mark.asyncio
async def test_a_double_submit_racing_past_the_check_is_a_409_not_a_500(client, monkeypatch):
    """Two copies of one quiz answer arriving at once both passed the "already answered?" check; the
    second then hit the unique (attempt, item) index and the request died with a 500. Same answer,
    same outcome as the check: a clean 409, and nothing of the second copy is kept."""
    from sqlalchemy.ext.asyncio import AsyncSession

    headers, pid = await _new_profile(client)
    quiz_id, (i1, i2, i3) = await _seed_quiz("race-quiz", pid)
    attempt_id = (
        await client.post(f"{API}/quizzes/{quiz_id}/attempts", headers=headers, json={})
    ).json()["attempt_id"]
    body = {"item_id": i1, "attempt_id": attempt_id, "submitted_value": "a"}
    assert (await client.post(f"{API}/answers", headers=headers, json=body)).status_code == 200
    rewarded = await _reward_state(pid, [i1, i2, i3])

    real_scalar = AsyncSession.scalar

    async def already_check_misses(self, stmt, *args, **kwargs):  # the racing copy's view
        sql = str(stmt)
        if sql.startswith("SELECT answers.id") and "answers.attempt_id" in sql:
            return None
        return await real_scalar(self, stmt, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "scalar", already_check_misses)
    r = await client.post(f"{API}/answers", headers=headers, json=body)
    monkeypatch.undo()

    assert r.status_code == 409, r.text
    assert await _reward_state(pid, [i1, i2, i3]) == rewarded

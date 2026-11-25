"""Lessons and quizzes can't be opened by walking their sequential ids.

Found on production (Nov 2026): GET /lessons/{id} and its sections answered anyone, so every
learner's lessons could be read by counting 1, 2, 3 … Content is still shared on purpose (the
recommendations offer other learners' lessons), so what opens it is knowing its learning session
(the request id), the creator's resume code, or having opened it before — the last two keep tabs
running the previous frontend (which sends only the resume code) working."""

from __future__ import annotations

import pytest

from tests.test_progress_resume import _new_profile, _seed_lesson, _seed_quiz

API = "/api/v1"


def _with(headers: dict | None, session: str | None) -> dict:
    out = dict(headers or {})
    if session:
        out["X-Learning-Session"] = session
    return out


async def _lesson_calls(client, lesson_id: int, item_id: int, headers: dict) -> dict[str, int]:
    """Status of every lesson call a reader makes, for one caller."""
    return {
        "lesson": (await client.get(f"{API}/lessons/{lesson_id}", headers=headers)).status_code,
        "section": (await client.get(f"{API}/lessons/{lesson_id}/sections/0", headers=headers)).status_code,
        "generate": (await client.post(f"{API}/lessons/{lesson_id}/sections/0/generate", headers=headers)).status_code,
        "progress": (await client.put(f"{API}/lessons/{lesson_id}/progress", headers=headers,
                                      json={"revealed_up_to": 0})).status_code,
        "answer": (await client.post(f"{API}/answers", headers=headers,
                                     json={"item_id": item_id, "submitted_value": "a"})).status_code,
    }


async def _quiz_calls(client, quiz_id: int, headers: dict) -> dict[str, int]:
    return {
        "quiz": (await client.get(f"{API}/quizzes/{quiz_id}", headers=headers)).status_code,
        "attempt": (await client.post(f"{API}/quizzes/{quiz_id}/attempts", headers=headers, json={})).status_code,
    }


@pytest.mark.asyncio
async def test_a_stranger_cannot_open_a_lesson_by_its_id(client):
    owner, pid = await _new_profile(client)
    stranger, _ = await _new_profile(client)
    lesson_id, item_id = await _seed_lesson("acc-lesson", pid, ready=1, total=2, item_in=0)
    # Same answer as for an id that doesn't exist, so ids can't be probed either.
    assert (await _lesson_calls(client, lesson_id, item_id, stranger)) == {
        "lesson": 404, "section": 404, "generate": 404, "progress": 404, "answer": 404,
    }
    missing = await client.get(f"{API}/lessons/{lesson_id + 1000}", headers=stranger)
    denied = await client.get(f"{API}/lessons/{lesson_id}", headers=stranger)
    assert missing.json() == denied.json()
    # Without any profile only the reads are possible at all — and they are closed too.
    assert (await client.get(f"{API}/lessons/{lesson_id}")).status_code == 404
    assert (await client.get(f"{API}/lessons/{lesson_id}/sections/0")).status_code == 404


@pytest.mark.asyncio
async def test_a_stranger_cannot_open_or_start_a_quiz_by_its_id(client):
    _owner, pid = await _new_profile(client)
    stranger, _ = await _new_profile(client)
    quiz_id, _ = await _seed_quiz("acc-quiz", pid)
    assert await _quiz_calls(client, quiz_id, stranger) == {"quiz": 404, "attempt": 404}
    assert (await client.get(f"{API}/quizzes/{quiz_id}")).status_code == 404


@pytest.mark.asyncio
async def test_the_creator_keeps_access_with_just_the_resume_code(client):
    """What the previous frontend sends: an open tab keeps working through the deploy."""
    owner, pid = await _new_profile(client)
    lesson_id, item_id = await _seed_lesson("own-lesson", pid, ready=1, total=2, item_in=0)
    quiz_id, _ = await _seed_quiz("own-quiz", pid)
    assert set((await _lesson_calls(client, lesson_id, item_id, owner)).values()) == {200}
    assert await _quiz_calls(client, quiz_id, owner) == {"quiz": 200, "attempt": 201}


@pytest.mark.asyncio
async def test_the_learning_session_opens_shared_content(client):
    """A recommended lesson / quiz of another learner opens by its request id."""
    _owner, pid = await _new_profile(client)
    classmate, _ = await _new_profile(client)
    lesson_id, item_id = await _seed_lesson("shared-lesson", pid, ready=1, total=2, item_in=0)
    quiz_id, _ = await _seed_quiz("shared-quiz", pid)
    assert set((await _lesson_calls(client, lesson_id, item_id, _with(classmate, "shared-lesson"))).values()) == {200}
    assert await _quiz_calls(client, quiz_id, _with(classmate, "shared-quiz")) == {"quiz": 200, "attempt": 201}
    # Reading needs no profile at all with the session.
    assert (await client.get(f"{API}/lessons/{lesson_id}", headers=_with(None, "shared-lesson"))).status_code == 200


@pytest.mark.asyncio
async def test_another_contents_session_does_not_open_it(client):
    _owner, pid = await _new_profile(client)
    stranger, spid = await _new_profile(client)
    lesson_id, item_id = await _seed_lesson("target", pid, ready=1, total=2, item_in=0)
    await _seed_lesson("strangers-own", spid, ready=1, total=2)
    quiz_id, _ = await _seed_quiz("target-quiz", pid)
    wrong = _with(stranger, "strangers-own")
    assert set((await _lesson_calls(client, lesson_id, item_id, wrong)).values()) == {404}
    assert await _quiz_calls(client, quiz_id, wrong) == {"quiz": 404, "attempt": 404}
    # Junk in the header is ignored, not queried or echoed.
    assert (await client.get(f"{API}/lessons/{lesson_id}", headers=_with(stranger, "x' OR 1=1 --"))).status_code == 404


@pytest.mark.asyncio
async def test_once_opened_it_stays_open_for_that_learner(client):
    """A recommended lesson the learner is in keeps opening from "Continue" or an old tab."""
    _owner, pid = await _new_profile(client)
    classmate, _ = await _new_profile(client)
    lesson_id, item_id = await _seed_lesson("opened", pid, ready=1, total=2, item_in=0)
    quiz_id, _ = await _seed_quiz("opened-quiz", pid)
    await client.put(f"{API}/lessons/{lesson_id}/progress", headers=_with(classmate, "opened"),
                     json={"revealed_up_to": 0})
    await client.post(f"{API}/quizzes/{quiz_id}/attempts", headers=_with(classmate, "opened-quiz"), json={})
    assert set((await _lesson_calls(client, lesson_id, item_id, classmate)).values()) == {200}
    assert await _quiz_calls(client, quiz_id, classmate) == {"quiz": 200, "attempt": 201}


@pytest.mark.asyncio
async def test_history_hands_out_the_session_that_opens_each_lesson(client):
    owner, pid = await _new_profile(client)
    lesson_id, _ = await _seed_lesson("hist-lesson", pid, ready=1, total=2)
    sessions = (await client.get(f"{API}/profiles/me/requests", headers=owner)).json()
    entry = next(s for s in sessions if s["lesson_id"] == lesson_id)
    # On another device without the resume code (e.g. a link), the session alone opens it.
    assert (await client.get(f"{API}/lessons/{lesson_id}", headers=_with(None, entry["request_id"]))).status_code == 200

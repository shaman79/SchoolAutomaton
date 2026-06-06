"""End-to-end profile slice over the real ASGI app (no AI needed)."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_create_resume_me_settings(client):
    # Create
    r = await client.post("/api/v1/profiles", json={"locale": "cs", "age_band": "primary"})
    assert r.status_code == 201, r.text
    data = r.json()
    code = data["resume_code"]
    assert "-" in code and len(code) == 9  # XXXX-XXXX
    assert data["profile"]["level"] == 1
    assert data["settings"]["locale"] == "cs"

    # Resume
    r = await client.post("/api/v1/profiles/resume", json={"resume_code": code})
    assert r.status_code == 200, r.text
    env = r.json()
    assert env["gamification"]["level"] == 1
    assert env["gamification"]["streak"]["current"] == 0

    # Me (auth header)
    r = await client.get("/api/v1/profiles/me", headers={"X-Resume-Code": code})
    assert r.status_code == 200

    # Bad code
    r = await client.get("/api/v1/profiles/me", headers={"X-Resume-Code": "ZZZZ-ZZZZ"})
    assert r.status_code == 401

    # Update settings
    r = await client.patch(
        "/api/v1/profiles/me/settings",
        headers={"X-Resume-Code": code},
        json={"reduced_motion": True, "font": "opendyslexic", "daily_goal": "serious"},
    )
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["reduced_motion"] is True
    assert s["font"] == "opendyslexic"
    assert s["daily_goal"] == "serious"


@pytest.mark.asyncio
async def test_my_requests_history(client):
    # Create a profile and learn its internal id.
    code = (await client.post("/api/v1/profiles", json={})).json()["resume_code"]
    me = (await client.get("/api/v1/profiles/me", headers={"X-Resume-Code": code})).json()
    pid = me["profile"]["id"]

    # Seed a ready study request + lesson and a clarify (non-content) request that must NOT appear.
    from app.db.session import SessionLocal
    from app.models import LearningRequest, Lesson

    async with SessionLocal() as db:
        lesson = Lesson(
            request_id="hist-1", topic="Optika", detected_language="cs", grade_band="G6-8",
            subject="physics", target_fkgl=6.0, objectives_json=[], model_id="m", prompt_version="v",
        )
        db.add(lesson)
        await db.flush()
        lesson_id = lesson.id
        db.add(LearningRequest(
            request_id="hist-1", profile_id=pid, decision_type="proceed", mode="study",
            status="ready", lesson_id=lesson_id, structured_intent_json={}, detected_language="cs",
            grade_band="G6-8", prompt_version="v", model_id="m",
        ))
        db.add(LearningRequest(
            request_id="hist-clarify", profile_id=pid, decision_type="clarify", mode=None,
            status="ready", structured_intent_json={}, prompt_version="v", model_id="m",
        ))
        # A failed generation must NOT clutter "My lessons" (it only lingers for Retry).
        db.add(LearningRequest(
            request_id="hist-failed", profile_id=pid, decision_type="proceed", mode="study",
            status="error", structured_intent_json={}, detected_language="cs",
            grade_band="G6-8", prompt_version="v", model_id="m",
        ))
        await db.commit()

    r = await client.get("/api/v1/profiles/me/requests", headers={"X-Resume-Code": code})
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 1  # only the ready content request — not the clarify, not the failed one
    assert {it["request_id"] for it in items} == {"hist-1"}
    assert items[0]["request_id"] == "hist-1"
    assert items[0]["mode"] == "study"
    assert items[0]["lesson_id"] == lesson_id
    assert items[0]["title"] == "Optika"
    assert items[0]["subject"] == "physics"

    # Requires a resume code.
    assert (await client.get("/api/v1/profiles/me/requests")).status_code == 401


@pytest.mark.asyncio
async def test_recommendations_seeded_and_home(client):
    code = (await client.post("/api/v1/profiles", json={})).json()["resume_code"]
    me = (await client.get("/api/v1/profiles/me", headers={"X-Resume-Code": code})).json()
    pid = me["profile"]["id"]

    from app.db.session import SessionLocal
    from app.models import LearningRequest, Lesson, Quiz

    def _lesson(topic, subject):
        return Lesson(
            request_id="x", topic=topic, detected_language="en", grade_band="G3-5",
            subject=subject, target_fkgl=6.0, objectives_json=[], model_id="m", prompt_version="v",
        )

    async with SessionLocal() as db:
        seed_l = _lesson("Photosynthesis in plants", "biology")
        b_l = _lesson("Animal cells", "biology")
        c_l = _lesson("Adding fractions", "math")
        db.add_all([seed_l, b_l, c_l])
        await db.flush()
        a_q = Quiz(
            request_id="rec-a", title="Photosynthesis and sunlight", language="en",
            grade_band="G3-5", subject="biology", model_id="m", prompt_version="v",
        )
        db.add(a_q)
        await db.flush()

        def _req(rid, *, mode, lesson_id=None, quiz_id=None):
            return LearningRequest(
                request_id=rid, profile_id=pid, decision_type="proceed", mode=mode,
                status="ready", lesson_id=lesson_id, quiz_id=quiz_id, structured_intent_json={},
                detected_language="en", grade_band="G3-5", prompt_version="v", model_id="m",
            )

        db.add_all([
            _req("rec-seed", mode="study", lesson_id=seed_l.id),
            _req("rec-a", mode="test", quiz_id=a_q.id),
            _req("rec-b", mode="study", lesson_id=b_l.id),
            _req("rec-c", mode="study", lesson_id=c_l.id),
        ])
        await db.commit()

    # Seeded by the just-finished session: excludes itself, ranks the topic+subject match first.
    r = await client.get(
        "/api/v1/profiles/me/recommendations?request_id=rec-seed",
        headers={"X-Resume-Code": code},
    )
    assert r.status_code == 200, r.text
    ids = [it["request_id"] for it in r.json()]
    assert "rec-seed" not in ids
    assert ids[0] == "rec-a"  # highest topic overlap + same subject
    assert "rec-b" in ids

    # No seed (home screen): the learner's own recent ready sessions.
    r = await client.get("/api/v1/profiles/me/recommendations", headers={"X-Resume-Code": code})
    assert r.status_code == 200, r.text
    home_ids = {it["request_id"] for it in r.json()}
    assert {"rec-seed", "rec-a", "rec-b", "rec-c"} <= home_ids

    # Requires a resume code.
    assert (await client.get("/api/v1/profiles/me/recommendations")).status_code == 401


@pytest.mark.asyncio
async def test_quiz_review_reveals_answers(client):
    from datetime import UTC, datetime

    code = (await client.post("/api/v1/profiles", json={})).json()["resume_code"]
    me = (await client.get("/api/v1/profiles/me", headers={"X-Resume-Code": code})).json()
    pid = me["profile"]["id"]

    from app.db.session import SessionLocal
    from app.models import Answer, Concept, Item, Quiz, QuizAttempt, QuizQuestion

    def _mcq_item(concept_id, correct_id):
        return Item(
            concept_id=concept_id, item_type="mcq", bloom_tier=2, difficulty="medium",
            item_difficulty=3, language="en", stem_markdown="Pick one", explanation="Because.",
            payload_json={
                "kind": "mcq", "multiple": False,
                "options": [
                    {"id": "a", "text": "Apple", "is_correct": correct_id == "a"},
                    {"id": "b", "text": "Banana", "is_correct": correct_id == "b"},
                ],
            },
            model_id="m", prompt_version="v",
        )

    async with SessionLocal() as db:
        concept = Concept(slug="fruit", name="Fruit", subject="science")
        db.add(concept)
        await db.flush()
        i1 = _mcq_item(concept.id, "a")
        i2 = _mcq_item(concept.id, "b")
        db.add_all([i1, i2])
        await db.flush()
        quiz = Quiz(
            request_id="rev-1", title="Fruit quiz", language="en", grade_band="G3-5",
            subject="science", model_id="m", prompt_version="v",
        )
        db.add(quiz)
        await db.flush()
        quiz_id = quiz.id
        db.add_all([
            QuizQuestion(quiz_id=quiz_id, item_id=i1.id, ordinal=1, points=10),
            QuizQuestion(quiz_id=quiz_id, item_id=i2.id, ordinal=2, points=10),
        ])
        attempt = QuizAttempt(
            profile_id=pid, quiz_id=quiz_id, max_score=20, score=10, accuracy=0.5,
            completed_at=datetime.now(UTC),
        )
        db.add(attempt)
        await db.flush()
        # i1 answered correctly, i2 answered incorrectly.
        db.add_all([
            Answer(attempt_id=attempt.id, profile_id=pid, item_id=i1.id, submitted_value_json="a",
                   is_correct=True, partial_credit=1.0, fsrs_rating=4, xp_awarded=10),
            Answer(attempt_id=attempt.id, profile_id=pid, item_id=i2.id, submitted_value_json="a",
                   is_correct=False, partial_credit=0.0, fsrs_rating=1, xp_awarded=0),
        ])
        await db.commit()

    r = await client.get(f"/api/v1/quizzes/{quiz_id}/review", headers={"X-Resume-Code": code})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "Fruit quiz"
    assert body["total"] == 2
    assert body["correct_count"] == 1
    items = body["items"]
    assert [it["ordinal"] for it in items] == [1, 2]
    assert items[0]["is_correct"] is True
    assert items[0]["submitted_value"] == "a"
    assert items[0]["correct_answer"] == "a"
    assert items[0]["explanation"] == "Because."
    # The wrong one reveals the different correct answer.
    assert items[1]["is_correct"] is False
    assert items[1]["correct_answer"] == "b"
    # Public payload still carries no is_correct flags.
    assert all("is_correct" not in opt for opt in items[0]["item"]["payload"]["options"])

    # A quiz the learner never attempted → 404.
    async with SessionLocal() as db:
        empty = Quiz(request_id="rev-empty", title="x", language="en", grade_band="G3-5",
                     subject="science", model_id="m", prompt_version="v")
        db.add(empty)
        await db.flush()
        empty_id = empty.id
        await db.commit()
    r = await client.get(f"/api/v1/quizzes/{empty_id}/review", headers={"X-Resume-Code": code})
    assert r.status_code == 404

    # Requires a resume code.
    assert (await client.get(f"/api/v1/quizzes/{quiz_id}/review")).status_code == 401


@pytest.mark.asyncio
async def test_answer_endpoint_validates_attempt_ownership(client):
    code_a = (await client.post("/api/v1/profiles", json={})).json()["resume_code"]
    code_b = (await client.post("/api/v1/profiles", json={})).json()["resume_code"]
    pid_a = (await client.get("/api/v1/profiles/me", headers={"X-Resume-Code": code_a})).json()["profile"]["id"]

    from app.db.session import SessionLocal
    from app.models import Concept, Item, Quiz, QuizAttempt, QuizQuestion

    def _mcq():
        return Item(
            concept_id=concept.id, item_type="mcq", bloom_tier=2, difficulty="medium",
            item_difficulty=3, language="en", stem_markdown="q", model_id="m", prompt_version="v",
            payload_json={"kind": "mcq", "multiple": False,
                          "options": [{"id": "a", "text": "A", "is_correct": True}]},
        )

    async with SessionLocal() as db:
        concept = Concept(slug="s", name="S", subject="science")
        db.add(concept)
        await db.flush()
        i1 = _mcq()
        i2 = _mcq()  # NOT part of the quiz
        db.add_all([i1, i2])
        await db.flush()
        quiz = Quiz(request_id="aq", title="Q", language="en", grade_band="G3-5", subject="science",
                    model_id="m", prompt_version="v")
        db.add(quiz)
        await db.flush()
        db.add(QuizQuestion(quiz_id=quiz.id, item_id=i1.id, ordinal=1, points=10))
        attempt = QuizAttempt(profile_id=pid_a, quiz_id=quiz.id)
        db.add(attempt)
        await db.flush()
        i1_id, i2_id, attempt_id = i1.id, i2.id, attempt.id
        await db.commit()

    def _answer(item_id):
        return {"item_id": item_id, "attempt_id": attempt_id, "submitted_value": "a"}

    # Another learner cannot answer into A's attempt.
    r = await client.post("/api/v1/answers", headers={"X-Resume-Code": code_b}, json=_answer(i1_id))
    assert r.status_code == 404, r.text

    # An item that isn't part of the attempt's quiz is rejected.
    r = await client.post("/api/v1/answers", headers={"X-Resume-Code": code_a}, json=_answer(i2_id))
    assert r.status_code == 400, r.text

    # The owner answering a legitimate item succeeds.
    r = await client.post("/api/v1/answers", headers={"X-Resume-Code": code_a}, json=_answer(i1_id))
    assert r.status_code == 200, r.text

    # Idempotency (DI-02): the same item can't be answered twice in one attempt (no double XP).
    r = await client.post("/api/v1/answers", headers={"X-Resume-Code": code_a}, json=_answer(i1_id))
    assert r.status_code == 409, r.text

    # Answer-key oracle (SEC-1): a quiz-bank item cannot be graded via the lesson path (attempt_id
    # omitted) — that would reveal its correct answer/explanation without a real attempt.
    r = await client.post(
        "/api/v1/answers", headers={"X-Resume-Code": code_a},
        json={"item_id": i1_id, "submitted_value": "a"},
    )
    assert r.status_code == 400, r.text

    # After completion, further writes to the attempt are blocked.
    r = await client.post(f"/api/v1/attempts/{attempt_id}/complete", headers={"X-Resume-Code": code_a}, json={})
    assert r.status_code == 200, r.text
    r = await client.post("/api/v1/answers", headers={"X-Resume-Code": code_a}, json=_answer(i1_id))
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_reap_stuck_requests_marks_generating_as_error(client):
    """A request left 'generating' across a restart (its in-process task + in-memory broker are gone)
    must be reaped to 'error' so the loading screen can offer Retry instead of hanging."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.main import _reap_stuck_requests
    from app.models import LearningRequest

    async with SessionLocal() as db:
        db.add_all([
            LearningRequest(
                request_id="stuck-gen", profile_id=None, decision_type="proceed", mode="study",
                status="generating", structured_intent_json={}, prompt_version="v", model_id="m",
            ),
            LearningRequest(
                request_id="done-ok", profile_id=None, decision_type="proceed", mode="study",
                status="ready", structured_intent_json={}, prompt_version="v", model_id="m",
            ),
        ])
        await db.commit()

    async with SessionLocal() as db:
        await _reap_stuck_requests(db)
        await db.commit()

    async with SessionLocal() as db:
        stuck = await db.scalar(
            select(LearningRequest).where(LearningRequest.request_id == "stuck-gen")
        )
        done = await db.scalar(
            select(LearningRequest).where(LearningRequest.request_id == "done-ok")
        )
        assert stuck.status == "error" and stuck.error_message  # reaped
        assert done.status == "ready"  # untouched


@pytest.mark.asyncio
async def test_resume_normalization(client):
    r = await client.post("/api/v1/profiles", json={})
    code = r.json()["resume_code"]
    # lowercase + no dash should still resolve (Crockford normalization)
    r = await client.post(
        "/api/v1/profiles/resume", json={"resume_code": code.lower().replace("-", "")}
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_admin_login_and_dashboard(client):
    r = await client.post(
        "/api/v1/admin/auth/login", json={"username": "admin", "password": "admin12345"}
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    r = await client.get("/api/v1/admin/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert "requests_24h" in r.json()

    # No token → 401
    assert (await client.get("/api/v1/admin/dashboard")).status_code == 401


@pytest.mark.asyncio
async def test_request_prompt_too_long_is_413(client):
    r = await client.post("/api/v1/requests", json={"prompt": "x" * 5000})
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_request_without_ai_fails_closed(client):
    # The LLM is authoritative for intent. With no configured key the pipeline FAILS CLOSED
    # (HTTP 503) — it never falls back to keyword-guessing the intent.
    r = await client.post("/api/v1/requests", json={"prompt": "teach me photosynthesis, grade 5"})
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_request_proceeds_with_ai(client, monkeypatch):
    # With the LLM available (mocked), a clear prompt proceeds; the raw prompt is never echoed.
    from app.schemas.intent import StructuredIntent

    monkeypatch.setattr("app.core.config.settings.anthropic_api_key", "test-key")

    async def fake_classify(*, system_blocks, user, output_model):
        return (
            StructuredIntent(subject="science", topic="photosynthesis", grade_band="G3-5",
                             language="en", classifier_confidence=0.95),
            None,
        )

    import app.llm.client as cl

    monkeypatch.setattr(cl, "classify", fake_classify, raising=False)

    prompt = "teach me about photosynthesis, grade 5"
    r = await client.post("/api/v1/requests", json={"prompt": prompt})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "proceed"
    assert "request_id" in body
    assert prompt not in r.text  # raw prompt never echoed back

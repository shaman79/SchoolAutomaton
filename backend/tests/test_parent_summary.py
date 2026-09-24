"""Parent overview (GET /profiles/me/summary): activity counts + topics judged in words."""

from __future__ import annotations

import os
from datetime import timedelta

os.environ.setdefault("SA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("APP_SECRET", "test-secret-please-ignore")
os.environ.setdefault("SA_ENV", "test")

import pytest  # noqa: E402

from app.db.base import utcnow  # noqa: E402
from app.models import Answer, ItemFsrsCard, Misconception  # noqa: E402
from app.schemas.questions import AnswerIn  # noqa: E402
from app.services import gamification, summary_service  # noqa: E402
from app.services.summary_service import topic_status  # noqa: E402

from .test_gamification import _make_concept, _make_item, _make_profile, db  # noqa: E402,F401

_MCQ = {
    "kind": "mcq",
    "multiple": False,
    "options": [
        {"id": "a", "text": "Right", "is_correct": True},
        {"id": "b", "text": "Wrong", "is_correct": False},
    ],
}


@pytest.mark.parametrize(
    "answers,correct,mastery,status",
    [
        (4, 4, 0.2, "confident"),  # reliably right
        (1, 1, 0.9, "confident"),  # mastered, even on few answers
        (2, 2, 0.1, "mostly"),  # too few answers to call it solid
        (5, 3, 0.3, "mostly"),
        (5, 1, 0.3, "practice"),
        (3, 0, None, "practice"),
        (2, 0, 0.95, "practice"),  # fresh-review mastery never hides wrong answers
    ],
)
def test_topic_status(answers, correct, mastery, status):
    assert topic_status(answers, correct, mastery) == status


async def _answer(db, profile, item, value):
    await gamification.grade_and_reward(
        db, profile, item, AnswerIn(item_id=item.id, submitted_value=value, latency_ms=5000), None
    )


@pytest.mark.asyncio
async def test_summary_counts_the_week_and_judges_topics(db):
    profile = await _make_profile(db)
    fractions = await _make_concept(db, slug="zlomky", subject="math")
    spelling = await _make_concept(db, slug="vyjmenovana-slova", subject="language_arts")
    for _ in range(4):
        await _answer(db, profile, await _make_item(db, fractions.id, "mcq", _MCQ), "a")
    for value in ("b", "b", "a"):
        await _answer(db, profile, await _make_item(db, spelling.id, "mcq", _MCQ), value)
    # A wrong idea met this week is surfaced once, however often it was hit.
    misc = Misconception(concept_id=spelling.id, code="m1", description="Po B se vždy píše Y.",
                         refutation_text="…")
    db.add(misc)
    await db.flush()
    for a in (await db.execute(Answer.__table__.select().where(Answer.is_correct.is_(False)))).all():
        await db.execute(
            Answer.__table__.update().where(Answer.id == a.id).values(detected_misconception_id=misc.id)
        )
    # An answer from long ago is outside the window.
    old = await _make_item(db, fractions.id, "mcq", _MCQ)
    await _answer(db, profile, old, "b")
    await db.execute(
        Answer.__table__.update().where(Answer.item_id == old.id)
        .values(created_at=utcnow() - timedelta(days=30))
    )

    s = await summary_service.build_summary(db, profile, 7)
    assert s.answers == 7 and s.correct == 5
    assert s.active_days == 1
    by_title = {t.title: t for t in s.topics}
    assert by_title["Zlomky"].status == "confident"
    assert by_title["Vyjmenovana-Slova"].status == "practice"
    assert s.topics[0].title == "Vyjmenovana-Slova"  # what needs attention comes first
    assert s.misconceptions == ["Po B se vždy píše Y."]
    assert s.due_reviews == 0  # nothing is due minutes after practising...
    await db.execute(
        ItemFsrsCard.__table__.update().where(ItemFsrsCard.item_id == old.id)
        .values(due=utcnow() - timedelta(days=1))
    )
    assert (await summary_service.build_summary(db, profile, 7)).due_reviews == 1  # ...until it is


@pytest.mark.asyncio
async def test_summary_endpoint_for_a_new_learner(client):
    code = (await client.post("/api/v1/profiles", json={"locale": "cs"})).json()["resume_code"]
    r = await client.get("/api/v1/profiles/me/summary", headers={"X-Resume-Code": code})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["days"] == 7 and body["answers"] == 0 and body["topics"] == []
    assert (await client.get("/api/v1/profiles/me/summary")).status_code in (401, 403)

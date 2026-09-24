"""Parent overview (GET /profiles/me/summary): what the learner did in the last few days, and a
verbal judgement per practised topic ("zvládá s jistotou / většinou / potřebuje procvičit") instead
of raw percentages. Read-only; mastery comes from the FSRS-derived ``skill_mastery`` rows (SPEC §4 #5)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.constants import MASTERY_MASTERED_THRESHOLD
from ..db.base import utcnow
from ..models import (
    Answer,
    Concept,
    Item,
    ItemFsrsCard,
    LearningRequest,
    Misconception,
    Profile,
    QuizAttempt,
    SkillMastery,
)
from ..schemas.profile import ParentSummary, TopicProgress

# Below this many answers a perfect week counts as solid only if FSRS mastery agrees.
_MIN_ANSWERS_FOR_ACCURACY = 3
_CONFIDENT_ACCURACY = 0.85
_MOSTLY_ACCURACY = 0.6
_MAX_TOPICS = 12
_MAX_MISCONCEPTIONS = 5
_STATUS_ORDER = {"practice": 0, "mostly": 1, "confident": 2}


def topic_status(answers: int, correct: int, mastery: float | None) -> str:
    """Verbal band for one topic. The week's accuracy leads: right after a review FSRS retrievability is
    ~1 whatever the answer was, so mastery alone would flatter a topic just answered wrongly. Mastery
    only lets a short but flawless run count as solid."""
    accuracy = correct / answers if answers else 0.0
    if accuracy >= _CONFIDENT_ACCURACY and (
        answers >= _MIN_ANSWERS_FOR_ACCURACY or (mastery or 0.0) >= MASTERY_MASTERED_THRESHOLD
    ):
        return "confident"
    if accuracy >= _MOSTLY_ACCURACY:
        return "mostly"
    return "practice"


async def build_summary(db: AsyncSession, profile: Profile, days: int = 7) -> ParentSummary:
    now = utcnow()
    since = now - timedelta(days=days)

    answers = (
        await db.execute(
            select(Answer.created_at, Answer.is_correct, Item.concept_id, Answer.detected_misconception_id)
            .join(Item, Item.id == Answer.item_id)
            .where(Answer.profile_id == profile.id, Answer.created_at >= since)
        )
    ).all()

    lessons = (
        await db.execute(
            select(func.count(LearningRequest.id)).where(
                LearningRequest.profile_id == profile.id,
                LearningRequest.decision_type == "proceed",
                LearningRequest.status == "ready",
                LearningRequest.created_at >= since,
            )
        )
    ).scalar_one()
    quizzes_completed = (
        await db.execute(
            select(func.count(QuizAttempt.id)).where(
                QuizAttempt.profile_id == profile.id,
                QuizAttempt.completed_at.is_not(None),
                QuizAttempt.completed_at >= since,
            )
        )
    ).scalar_one()
    due_reviews = (
        await db.execute(
            select(func.count(ItemFsrsCard.id)).where(
                ItemFsrsCard.profile_id == profile.id,
                ItemFsrsCard.due.is_not(None),
                ItemFsrsCard.due <= now,
            )
        )
    ).scalar_one()

    per_concept: dict[int, list[int]] = {}
    misconception_ids: list[int] = []
    active: set = set()
    for created_at, is_correct, concept_id, misc_id in answers:
        active.add(created_at.date())
        tally = per_concept.setdefault(concept_id, [0, 0])
        tally[0] += 1
        tally[1] += 1 if is_correct else 0
        if misc_id is not None and misc_id not in misconception_ids:
            misconception_ids.append(misc_id)
    # Lessons read without answering still count as an active day.
    for (created_at,) in (
        await db.execute(
            select(LearningRequest.created_at).where(
                LearningRequest.profile_id == profile.id,
                LearningRequest.decision_type == "proceed",
                LearningRequest.created_at >= since,
            )
        )
    ).all():
        active.add(created_at.date())

    topics: list[TopicProgress] = []
    if per_concept:
        rows = (
            await db.execute(
                select(Concept, SkillMastery.mastery)
                .outerjoin(
                    SkillMastery,
                    (SkillMastery.concept_id == Concept.id) & (SkillMastery.profile_id == profile.id),
                )
                .where(Concept.id.in_(per_concept))
            )
        ).all()
        for concept, mastery in rows:
            n, ok = per_concept[concept.id]
            topics.append(
                TopicProgress(
                    concept_id=concept.id,
                    title=concept.name,
                    subject=concept.subject,
                    answers=n,
                    correct=ok,
                    status=topic_status(n, ok, mastery),
                )
            )
        # What needs attention first; within a band, the most practised topics first.
        topics.sort(key=lambda t: (_STATUS_ORDER[t.status], -t.answers, t.title))

    misconceptions: list[str] = []
    if misconception_ids:
        by_id = {
            m.id: m.description
            for m in (
                await db.execute(select(Misconception).where(Misconception.id.in_(misconception_ids)))
            ).scalars()
        }
        for mid in misconception_ids:
            desc = by_id.get(mid)
            if desc and desc not in misconceptions:
                misconceptions.append(desc)

    return ParentSummary(
        days=days,
        active_days=len(active),
        lessons=int(lessons or 0),
        quizzes_completed=int(quizzes_completed or 0),
        answers=len(answers),
        correct=sum(1 for a in answers if a[1]),
        due_reviews=int(due_reviews or 0),
        topics=topics[:_MAX_TOPICS],
        misconceptions=misconceptions[:_MAX_MISCONCEPTIONS],
    )

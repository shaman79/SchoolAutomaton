"""Suggest existing lessons/quizzes to re-open or explore next.

Reuse over regeneration: surface ready lessons/quizzes the learner (or the shared catalog) already
has. Used two ways, with DIFFERENT rules:

  - **After finishing a quiz/lesson** (seeded by that session) → "more like this": ONLY genuinely
    related content — *same subject*, *close grade band (level)*, ranked by topic overlap. A math
    quiz must never be offered as related to a language lesson. Better to show fewer (or none) than
    to surface an unrelated subject.
  - **On the home screen** (no seed) → "explore": popular ready content *across* subjects at the
    learner's usual level — varied, similar-level, frequently-used — so the strip stays useful.

Privacy: topics are the *academic* topic (e.g. "Photosynthesis"), never the raw student prompt (which
is discarded/hashed per the one-way-flow invariant), so cross-profile reuse is safe.
"""

from __future__ import annotations

import re
from collections import Counter

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import LearningRequest, Lesson, Profile, Quiz
from ..schemas.profile import LearningSessionSummary

# Tiny tokenizer for topic-overlap scoring: lowercase word-ish tokens, drop very short ones so
# stop-words ("of", "the", "a") don't inflate similarity.
_WORD_RE = re.compile(r"[\w]+", re.UNICODE)

# Ordered developmental bands → ordinal, so "level closeness" is a distance, not just equality.
_GRADE_ORDER: dict[str, int] = {"K": 0, "G1-2": 1, "G3-5": 2, "G6-8": 3, "G9-12": 4, "adult": 5}


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return {w for w in (m.group(0).lower() for m in _WORD_RE.finditer(text)) if len(w) >= 3}


def _overlap(a: set[str], b: set[str]) -> float:
    """Jaccard similarity of two token sets (0..1)."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b) if inter else 0.0


def _grade_proximity(a: str | None, b: str | None) -> float:
    """Level closeness: 1.0 same band, decaying with distance, 0 beyond two bands. Unknown/missing on
    either side → a neutral 0.4 (we can't tell, so neither reward nor punish)."""
    oa, ob = _GRADE_ORDER.get(a or ""), _GRADE_ORDER.get(b or "")
    if oa is None or ob is None:
        return 0.4
    return {0: 1.0, 1: 0.6, 2: 0.25}.get(abs(oa - ob), 0.0)


def _summary(lr: LearningRequest, title: str | None, subject: str | None) -> LearningSessionSummary:
    return LearningSessionSummary(
        request_id=lr.request_id,
        mode=lr.mode,
        status=lr.status,
        lesson_id=lr.lesson_id,
        quiz_id=lr.quiz_id,
        title=title,
        subject=subject,
        created_at=lr.created_at,
    )


async def suggest(
    db: AsyncSession,
    profile: Profile,
    *,
    request_id: str | None = None,
    subject: str | None = None,
    limit: int = 6,
) -> list[LearningSessionSummary]:
    seed_subject = subject
    seed_topic: str | None = None
    seed_grade: str | None = None
    seed_lesson_id: int | None = None
    seed_quiz_id: int | None = None
    exclude_rid: str | None = None

    # Seed from the just-finished session (own request) to get its subject + topic + level.
    if request_id:
        seed = await db.scalar(
            select(LearningRequest).where(LearningRequest.request_id == request_id)
        )
        if seed is not None:
            exclude_rid = seed.request_id
            seed_grade = seed.grade_band
            if seed.lesson_id is not None:
                seed_lesson_id = seed.lesson_id
                lz = await db.get(Lesson, seed.lesson_id)
                if lz is not None:
                    seed_subject = seed_subject or lz.subject
                    seed_topic = lz.topic
                    seed_grade = lz.grade_band or seed_grade
            elif seed.quiz_id is not None:
                seed_quiz_id = seed.quiz_id
                qz = await db.get(Quiz, seed.quiz_id)
                if qz is not None:
                    seed_subject = seed_subject or qz.subject
                    seed_topic = qz.title
                    seed_grade = qz.grade_band or seed_grade

    has_seed = bool(seed_subject or seed_topic)

    # The learner's usual level (for the no-seed home ranking): their most recent ready level.
    learner_level: str | None = None
    if not has_seed:
        learner_level = await db.scalar(
            select(LearningRequest.grade_band)
            .where(LearningRequest.profile_id == profile.id, LearningRequest.status == "ready")
            .order_by(LearningRequest.created_at.desc())
            .limit(1)
        )

    stmt = (
        select(LearningRequest, Lesson, Quiz)
        .outerjoin(Lesson, Lesson.id == LearningRequest.lesson_id)
        .outerjoin(Quiz, Quiz.id == LearningRequest.quiz_id)
        .where(
            LearningRequest.decision_type == "proceed",
            LearningRequest.status == "ready",
            or_(LearningRequest.lesson_id.is_not(None), LearningRequest.quiz_id.is_not(None)),
        )
    )
    if exclude_rid is not None:
        stmt = stmt.where(LearningRequest.request_id != exclude_rid)
    # Bounded recent pool; the fine-grained subject/level/topic ranking happens in Python.
    stmt = stmt.order_by(LearningRequest.created_at.desc()).limit(200)
    rows = (await db.execute(stmt)).all()

    # Popularity (home only): how often a (subject, topic) appears in the recent pool — a
    # recency-weighted "frequently used" signal.
    pop: Counter[tuple[str | None, str]] = Counter()
    if not has_seed:
        for lr, lesson, quiz in rows:
            subj = lesson.subject if lesson else (quiz.subject if quiz else None)
            ttl = (lesson.topic if lesson else (quiz.title if quiz else "")) or ""
            pop[(subj, ttl.strip().lower())] += 1

    seed_tok = _tokens(seed_topic)
    scored: list[tuple[float, LearningSessionSummary]] = []
    seen: set[tuple[str, str | None]] = set()
    for lr, lesson, quiz in rows:
        c_subject = lesson.subject if lesson else (quiz.subject if quiz else None)
        c_title = lesson.topic if lesson else (quiz.title if quiz else None)
        c_grade = (
            lesson.grade_band if lesson else (quiz.grade_band if quiz else None)
        ) or lr.grade_band
        is_own = lr.profile_id == profile.id

        # Never recommend the very thing just finished.
        if seed_lesson_id is not None and lr.lesson_id == seed_lesson_id:
            continue
        if seed_quiz_id is not None and lr.quiz_id == seed_quiz_id:
            continue

        dedupe_key = ((c_title or "").strip().lower(), lr.mode)
        if dedupe_key in seen:
            continue

        if has_seed:
            # "More like this": same subject is REQUIRED — for OWN content too (the previous bug
            # surfaced the learner's own math quiz as related to a biology lesson). Then rank by topic
            # overlap + level closeness, dropping anything with no relevance at all (different level
            # AND no topic overlap) so the strip stays genuinely related.
            if seed_subject and c_subject != seed_subject:
                continue
            relevance = _overlap(seed_tok, _tokens(c_title)) + 0.6 * _grade_proximity(
                seed_grade, c_grade
            )
            if relevance <= 0.0:
                continue
            score = relevance + (0.1 if is_own else 0.0)  # nudge familiar own content up
        else:
            # Home: various subjects, biased to the learner's usual level and to popular topics.
            freq = pop.get((c_subject, (c_title or "").strip().lower()), 1)
            score = (
                2.0 * _grade_proximity(learner_level, c_grade)  # similar level dominates
                + 0.5 * min(freq, 4)  # frequently used (capped so it can't swamp level)
                + (0.1 if is_own else 0.0)
            )

        seen.add(dedupe_key)
        scored.append((score, _summary(lr, c_title, c_subject)))

    # Primary: score (desc). Secondary: recency — rows arrived newest-first, so a stable sort on
    # score alone preserves that as the tiebreak.
    scored.sort(key=lambda s: s[0], reverse=True)
    return [summary for _, summary in scored[:limit]]

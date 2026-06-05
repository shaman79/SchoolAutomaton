"""Suggest existing lessons/quizzes to re-open or explore next.

Reuse over regeneration: rather than always paying to build new content, surface ready lessons/quizzes
the learner (or the shared catalog) already has, ranked by topic similarity to a seed session. Used
two ways:
  - after finishing a quiz/lesson  → "more like this" (seeded by that session's subject + topic),
  - on the home screen (no seed)   → the learner's own recent sessions to jump back into.

Privacy: topics are the *academic* topic (e.g. "Photosynthesis"), never the raw student prompt (which
is discarded/hashed per the one-way-flow invariant), so cross-profile same-subject reuse is safe. With
no seed we stay conservative and only recommend the learner's own content.
"""

from __future__ import annotations

import re

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import LearningRequest, Lesson, Profile, Quiz
from ..schemas.profile import LearningSessionSummary

# Tiny tokenizer for topic-overlap scoring: lowercase word-ish tokens, drop very short ones so
# stop-words ("of", "the", "a") don't inflate similarity.
_WORD_RE = re.compile(r"[\w]+", re.UNICODE)


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return {w for w in (m.group(0).lower() for m in _WORD_RE.finditer(text)) if len(w) >= 3}


def _overlap(a: set[str], b: set[str]) -> float:
    """Jaccard similarity of two token sets (0..1)."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


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
    exclude_rid: str | None = None

    # Seed from the just-finished session (own request) to get its subject + topic.
    if request_id:
        seed = await db.scalar(
            select(LearningRequest).where(LearningRequest.request_id == request_id)
        )
        if seed is not None:
            exclude_rid = seed.request_id
            if seed.lesson_id is not None:
                lz = await db.get(Lesson, seed.lesson_id)
                if lz is not None:
                    seed_subject = seed_subject or lz.subject
                    seed_topic = lz.topic
            elif seed.quiz_id is not None:
                qz = await db.get(Quiz, seed.quiz_id)
                if qz is not None:
                    seed_subject = seed_subject or qz.subject
                    seed_topic = qz.title

    has_seed = bool(seed_subject or seed_topic)

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
    if not has_seed:
        # No seed (home screen): only the learner's own past sessions.
        stmt = stmt.where(LearningRequest.profile_id == profile.id)
    # Bounded recent pool; the fine-grained subject/topic filtering + ranking happens in Python.
    stmt = stmt.order_by(LearningRequest.created_at.desc()).limit(200)
    rows = (await db.execute(stmt)).all()

    seed_tok = _tokens(seed_topic)

    scored: list[tuple[float, LearningSessionSummary]] = []
    seen: set[tuple[str, str | None]] = set()
    for lr, lesson, quiz in rows:
        c_subject = lesson.subject if lesson else (quiz.subject if quiz else None)
        c_title = lesson.topic if lesson else (quiz.title if quiz else None)
        is_own = lr.profile_id == profile.id

        # When seeded, keep cross-profile candidates only if they share the seed subject (own content
        # is always eligible so a learner can revisit anything related).
        if has_seed and seed_subject and not is_own and c_subject != seed_subject:
            continue

        # De-dupe near-identical entries (same topic + mode) so the strip isn't repetitive.
        dedupe_key = ((c_title or "").strip().lower(), lr.mode)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        score = _overlap(seed_tok, _tokens(c_title))
        if seed_subject and c_subject == seed_subject:
            score += 0.5
        if is_own:
            score += 0.15  # nudge own content up: easy to resume, familiar

        scored.append(
            (
                score,
                LearningSessionSummary(
                    request_id=lr.request_id,
                    mode=lr.mode,
                    status=lr.status,
                    lesson_id=lr.lesson_id,
                    quiz_id=lr.quiz_id,
                    title=c_title,
                    subject=c_subject,
                    created_at=lr.created_at,
                ),
            )
        )

    # Primary: similarity score (desc). Secondary: recency — rows arrived newest-first, so a stable
    # sort on score alone preserves that as the tiebreak.
    scored.sort(key=lambda s: s[0], reverse=True)
    return [summary for _, summary in scored[:limit]]

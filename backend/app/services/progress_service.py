"""Resume-where-you-left-off: position bookkeeping + replay of already-graded answers.

The server is the source of truth for a learner's position, so a refresh, a break, or a switch of
device (the resume code carries the profile) lands them exactly where they were:

  - quiz:   ``quiz_attempts.current_index`` + the open attempt's graded ``answers``
  - lesson: ``lesson_progress.revealed_up_to`` + the learner's graded answers to that lesson's items

Nothing here grades or schedules: replaying an answer never touches FSRS/XP (SPEC invariant #3), and it
only re-reveals what the grading endpoint already revealed to this same learner (SPEC §5)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    Answer,
    Item,
    Lesson,
    LessonProgress,
    LessonSection,
    Misconception,
    Profile,
    Quiz,
    QuizAttempt,
    QuizQuestion,
)
from ..schemas.gamification import GradeResult, MisconceptionInfo
from ..schemas.profile import LearningSessionSummary
from ..schemas.progress import LessonProgressOut, RestoredAnswer, SessionProgress
from . import gamification


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite hands datetimes back naive; they were stored as UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def restore_answer(
    db: AsyncSession, profile: Profile, item: Item, answer: Answer
) -> RestoredAnswer:
    """Rebuild the public GradeResult for a stored answer — a pure read, no reward side-effects.

    Per-moment extras (new badges, level-up, combo, next due) are not replayed; a free-text answer
    falls back to the item's own explanation (the grader's wording isn't stored)."""
    language = item.language or profile.primary_language or "en"
    misconception: MisconceptionInfo | None = None
    if answer.detected_misconception_id is not None:
        m = await db.get(Misconception, answer.detected_misconception_id)
        if m is not None:
            misconception = MisconceptionInfo(description=m.description, refutation=m.refutation_text)
    partial = answer.partial_credit or 0.0
    return RestoredAnswer(
        item_id=item.id,
        submitted_value=answer.submitted_value_json,
        result=GradeResult(
            is_correct=answer.is_correct,
            partial_credit=partial,
            correct_answer=gamification._reveal_correct_answer(item),
            fsrs_rating=answer.fsrs_rating,
            explanation=item.explanation or None,
            misconception=misconception,
            feedback=gamification._feedback(answer.is_correct, partial, language, "strategy"),
            xp_awarded=answer.xp_awarded or 0,
            mastery_delta=answer.mastery_delta or 0.0,
        ),
    )


# --------------------------------------------------------------------------- quiz attempts
async def _question_item_ids(db: AsyncSession, quiz_id: int) -> list[int]:
    """The quiz's item ids in delivery order (the order ``quiz_public`` serves them in)."""
    return list(
        (
            await db.execute(
                select(QuizQuestion.item_id)
                .where(QuizQuestion.quiz_id == quiz_id)
                .order_by(QuizQuestion.ordinal)
            )
        ).scalars().all()
    )


async def _resume_index(db: AsyncSession, attempt: QuizAttempt, item_ids: list[int]) -> int:
    """The saved position, but never behind the furthest question already answered — so a lost
    position update self-heals instead of parking the learner on an old question."""
    index_of = {item_id: i for i, item_id in enumerate(item_ids)}
    answered = (
        await db.execute(select(Answer.item_id).where(Answer.attempt_id == attempt.id))
    ).scalars().all()
    furthest = max((index_of[i] for i in answered if i in index_of), default=0)
    return min(max(attempt.current_index or 0, furthest), max(0, len(item_ids) - 1))


async def attempt_resume_state(
    db: AsyncSession, profile: Profile, attempt: QuizAttempt
) -> tuple[int, list[RestoredAnswer]]:
    """(index to resume at, replayed answers) for an open attempt."""
    item_ids = await _question_item_ids(db, attempt.quiz_id)
    rows = (
        await db.execute(
            select(Answer, Item)
            .join(Item, Item.id == Answer.item_id)
            .where(Answer.attempt_id == attempt.id, Answer.item_id.in_(item_ids))
            .order_by(Answer.id)
        )
    ).all()
    latest: dict[int, RestoredAnswer] = {}
    for answer, item in rows:
        latest[item.id] = await restore_answer(db, profile, item, answer)
    return await _resume_index(db, attempt, item_ids), list(latest.values())


async def save_attempt_position(
    db: AsyncSession, attempt: QuizAttempt, current_index: int, now: datetime | None = None
) -> int:
    """Record the question the learner moved to. Forward-only and clamped to the last question, so a
    stale tab or an out-of-order request can never drag the position back."""
    total = (
        await db.scalar(
            select(func.count()).select_from(QuizQuestion).where(QuizQuestion.quiz_id == attempt.quiz_id)
        )
    ) or 0
    attempt.current_index = min(max(attempt.current_index or 0, current_index), max(0, total - 1))
    attempt.last_active_at = now or datetime.now(UTC)
    await db.flush()
    return attempt.current_index


# --------------------------------------------------------------------------- lessons
async def _lesson_row(db: AsyncSession, profile_id: int, lesson_id: int) -> LessonProgress | None:
    return await db.scalar(
        select(LessonProgress).where(
            LessonProgress.profile_id == profile_id, LessonProgress.lesson_id == lesson_id
        )
    )


async def _lesson_state(
    db: AsyncSession, profile: Profile, lesson: Lesson, saved: int
) -> LessonProgressOut:
    sections = (
        await db.execute(
            select(LessonSection.id, LessonSection.ordinal, LessonSection.gen_status)
            .where(LessonSection.lesson_id == lesson.id)
            .order_by(LessonSection.ordinal)
        )
    ).all()
    ordinal_of = {section_id: ordinal for section_id, ordinal, _ in sections}
    last_ordinal = max(ordinal_of.values(), default=0)
    # Sections are generated on demand, in order: nothing past the first un-generated one can have
    # been revealed, whatever a client reports.
    generated_up_to = 0
    for _, ordinal, gen_status in sections:
        if gen_status != "ready":
            break
        generated_up_to = ordinal

    answers: list[RestoredAnswer] = []
    answered_up_to = 0
    if ordinal_of:
        rows = (
            await db.execute(
                select(Answer, Item)
                .join(Item, Item.id == Answer.item_id)
                .where(
                    Answer.profile_id == profile.id,
                    Answer.attempt_id.is_(None),
                    Item.lesson_section_id.in_(list(ordinal_of)),
                )
                .order_by(Answer.id)
            )
        ).all()
        seen: set[int] = set()
        for answer, item in rows:
            # A lesson item is first answered IN the lesson (its FSRS card is created by that answer);
            # any later row is a spaced review of it, which is not what the reader showed.
            if item.id in seen:
                continue
            seen.add(item.id)
            answers.append(await restore_answer(db, profile, item, answer))
            answered_up_to = max(answered_up_to, ordinal_of[item.lesson_section_id])

    # Never behind a section the learner demonstrably reached (they answered a question in it).
    revealed = min(max(saved, answered_up_to), generated_up_to)
    return LessonProgressOut(
        lesson_id=lesson.id,
        revealed_up_to=revealed,
        completed=bool(ordinal_of) and revealed >= last_ordinal,
        answers=answers,
    )


async def save_lesson_progress(
    db: AsyncSession,
    profile: Profile,
    lesson: Lesson,
    revealed_up_to: int,
    now: datetime | None = None,
) -> LessonProgressOut:
    """Record that the learner has revealed (at least) ``revealed_up_to`` and is active in the lesson
    now. Forward-only and clamped to the sections generated so far; returns the merged state."""
    now = now or datetime.now(UTC)
    # INSERT OR IGNORE then read back: two tabs opening the same lesson must not race into the
    # (profile, lesson) unique constraint.
    await db.execute(
        sqlite_insert(LessonProgress)
        .values(
            profile_id=profile.id,
            lesson_id=lesson.id,
            revealed_up_to=0,
            created_at=now,
            last_active_at=now,
        )
        .on_conflict_do_nothing(index_elements=["profile_id", "lesson_id"])
    )
    row = await _lesson_row(db, profile.id, lesson.id)
    state = await _lesson_state(db, profile, lesson, max(row.revealed_up_to or 0, revealed_up_to))
    row.revealed_up_to = state.revealed_up_to
    row.last_active_at = now
    if state.completed and row.completed_at is None:
        row.completed_at = now
    await db.flush()
    return state


# --------------------------------------------------------------------------- overview
async def lesson_progress_map(
    db: AsyncSession, profile: Profile, lesson_ids: set[int]
) -> dict[int, SessionProgress]:
    """Progress per lesson id, for the lessons this learner has opened."""
    if not lesson_ids:
        return {}
    rows = (
        await db.execute(
            select(LessonProgress).where(
                LessonProgress.profile_id == profile.id, LessonProgress.lesson_id.in_(lesson_ids)
            )
        )
    ).scalars().all()
    if not rows:
        return {}
    ordinals: dict[int, list[int]] = {}
    for lesson_id, ordinal in (
        await db.execute(
            select(LessonSection.lesson_id, LessonSection.ordinal).where(
                LessonSection.lesson_id.in_([r.lesson_id for r in rows])
            )
        )
    ).all():
        ordinals.setdefault(lesson_id, []).append(ordinal)
    out: dict[int, SessionProgress] = {}
    for row in rows:
        ords = ordinals.get(row.lesson_id, [])
        if not ords:
            continue
        out[row.lesson_id] = SessionProgress(
            position=max(1, sum(1 for o in ords if o <= row.revealed_up_to)),
            total=len(ords),
            completed=row.completed_at is not None,
            last_active_at=_aware(row.last_active_at),
        )
    return out


async def quiz_progress_map(
    db: AsyncSession, profile: Profile, quiz_ids: set[int]
) -> dict[int, SessionProgress]:
    """Progress per quiz id from the learner's LATEST attempt: an open one is in progress at its saved
    question; a finished one is completed (opening the quiz again starts a fresh attempt)."""
    if not quiz_ids:
        return {}
    attempts = (
        await db.execute(
            select(QuizAttempt)
            .where(QuizAttempt.profile_id == profile.id, QuizAttempt.quiz_id.in_(quiz_ids))
            .order_by(QuizAttempt.id)
        )
    ).scalars().all()
    latest = {a.quiz_id: a for a in attempts}  # ordered by id, so the last write per quiz wins
    if not latest:
        return {}
    totals = dict(
        (
            await db.execute(
                select(QuizQuestion.quiz_id, func.count())
                .where(QuizQuestion.quiz_id.in_(list(latest)))
                .group_by(QuizQuestion.quiz_id)
            )
        ).all()
    )
    out: dict[int, SessionProgress] = {}
    for quiz_id, attempt in latest.items():
        total = totals.get(quiz_id, 0)
        if not total:
            continue
        done = attempt.completed_at is not None
        if done:
            position = total
        else:
            item_ids = await _question_item_ids(db, quiz_id)
            position = await _resume_index(db, attempt, item_ids) + 1
        out[quiz_id] = SessionProgress(
            position=position,
            total=total,
            completed=done,
            last_active_at=_aware(attempt.completed_at or attempt.last_active_at or attempt.started_at),
        )
    return out


async def continue_candidate(db: AsyncSession, profile: Profile) -> LearningSessionSummary | None:
    """The unfinished lesson/quiz this learner was most recently active in — the home screen's
    "Continue where you left off". None when nothing is in progress.

    Built from the learner's own progress rows (not their request history), so it also covers a
    lesson/quiz they opened from the shared catalog; the route id is the content's originating
    request."""
    candidates: list[tuple[datetime, LearningSessionSummary]] = []

    lesson_row = (
        await db.execute(
            select(LessonProgress, Lesson)
            .join(Lesson, Lesson.id == LessonProgress.lesson_id)
            .where(LessonProgress.profile_id == profile.id, LessonProgress.completed_at.is_(None))
            .order_by(LessonProgress.last_active_at.desc())
            .limit(1)
        )
    ).first()
    if lesson_row is not None:
        row, lesson = lesson_row
        progress = (await lesson_progress_map(db, profile, {lesson.id})).get(lesson.id)
        if progress is not None and not progress.completed:
            candidates.append(
                (
                    _aware(row.last_active_at),
                    LearningSessionSummary(
                        request_id=lesson.request_id,
                        mode="study",
                        status="ready",
                        lesson_id=lesson.id,
                        title=lesson.topic,
                        subject=lesson.subject,
                        created_at=lesson.created_at,
                        progress=progress,
                    ),
                )
            )

    attempt_row = (
        await db.execute(
            select(QuizAttempt, Quiz)
            .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
            .where(QuizAttempt.profile_id == profile.id, QuizAttempt.completed_at.is_(None))
            .order_by(func.coalesce(QuizAttempt.last_active_at, QuizAttempt.started_at).desc())
            .limit(1)
        )
    ).first()
    if attempt_row is not None:
        attempt, quiz = attempt_row
        item_ids = await _question_item_ids(db, quiz.id)
        if item_ids:
            active_at = _aware(attempt.last_active_at or attempt.started_at)
            candidates.append(
                (
                    active_at,
                    LearningSessionSummary(
                        request_id=quiz.request_id,
                        mode="test",
                        status="ready",
                        quiz_id=quiz.id,
                        title=quiz.title,
                        subject=quiz.subject,
                        created_at=quiz.created_at,
                        progress=SessionProgress(
                            position=await _resume_index(db, attempt, item_ids) + 1,
                            total=len(item_ids),
                            last_active_at=active_at,
                        ),
                    ),
                )
            )

    if not candidates:
        return None
    return max(candidates, key=lambda c: c[0])[1]

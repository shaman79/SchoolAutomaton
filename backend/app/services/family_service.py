"""A parent following a learner: the parent code's lifecycle, and the tasks (assignments) a parent
gives — their state read from the learner's own progress, never stored twice (see models/family.py).

A task is an ordinary learning request owned by the learner. Everything that reads "the learner's
own requests" as the learner's own activity must leave out tasks the learner hasn't opened yet —
the parent made them, the child didn't (``own_request_filter`` / ``assigned_engagement``)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.security import decrypt_secret, encrypt_secret, generate_parent_code, hash_parent_code
from ..db.base import utcnow
from ..models import (
    Answer,
    Assignment,
    LearningRequest,
    Lesson,
    LessonProgress,
    ParentLink,
    Profile,
    Quiz,
    QuizAttempt,
    QuizQuestion,
)
from ..schemas.family import AssignmentOut, AssignmentResult, ParentCodeOut
from ..schemas.intent import StructuredIntent
from . import progress_service

# A parent opening the overview is recorded at most this often (it is shown to the learner as "last
# opened", and a write on every read would only add SQLite lock traffic).
LAST_USED_RESOLUTION = timedelta(minutes=10)
# Tasks waiting at once per learner: enough for a week of homework, not a backlog that buries the
# home screen (or a runaway that generates content nobody opens).
MAX_OPEN_ASSIGNMENTS = 10
# Tasks older than this quietly drop off both lists (stale homework), and no longer count as open.
TASK_LIFETIME = timedelta(days=60)
# The parent's list: the most recent tasks, finished ones included.
PARENT_LIST_LIMIT = 30


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite hands datetimes back naive; they were stored as UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# --------------------------------------------------------------------------- parent code
async def get_link(db: AsyncSession, profile: Profile) -> ParentLink | None:
    return await db.scalar(select(ParentLink).where(ParentLink.profile_id == profile.id))


def code_out(link: ParentLink | None) -> ParentCodeOut | None:
    """The code for the learner's own device to show again. None when there is none — or when it
    can no longer be decrypted (the server's APP_SECRET changed): the device then offers to make a
    new one, which replaces it."""
    if link is None:
        return None
    code = decrypt_secret(link.code_encrypted)
    if not code:
        return None
    return ParentCodeOut(
        code=code, created_at=_aware(link.created_at), last_used_at=_aware(link.last_used_at)
    )


async def new_code(db: AsyncSession, profile: Profile) -> ParentCodeOut:
    """Make the learner's parent code — replacing any earlier one, which stops working at once."""
    for _ in range(12):
        code = generate_parent_code()
        code_hash = hash_parent_code(code)
        if not await db.scalar(select(ParentLink.id).where(ParentLink.code_hash == code_hash)):
            break
    else:  # pragma: no cover — 50 bits; twelve collisions in a row means something else is wrong
        raise RuntimeError("Could not allocate a unique parent code")
    now = utcnow()
    link = await get_link(db, profile)
    if link is None:
        link = ParentLink(profile_id=profile.id)
        db.add(link)
    link.code_hash = code_hash
    link.code_encrypted = encrypt_secret(code)
    link.created_at = now
    link.last_used_at = None
    await db.flush()
    return ParentCodeOut(code=code, created_at=now, last_used_at=None)


async def remove_code(db: AsyncSession, profile: Profile) -> None:
    link = await get_link(db, profile)
    if link is not None:
        await db.delete(link)
        await db.flush()


async def touch(db: AsyncSession, link: ParentLink, now: datetime | None = None) -> None:
    now = now or utcnow()
    last = _aware(link.last_used_at)
    if last is None or now - last >= LAST_USED_RESOLUTION:
        link.last_used_at = now
        await db.flush()


# --------------------------------------------------------------------------- tasks
async def add_assignment(
    db: AsyncSession, profile: Profile, *, request_id: str, mode: str, intent: StructuredIntent
) -> Assignment:
    row = Assignment(
        profile_id=profile.id,
        request_id=request_id,
        mode=mode,
        title=intent.topic[:160],
        subject=intent.subject.value,
        created_at=utcnow(),
    )
    db.add(row)
    await db.flush()
    return row


def _status(lr: LearningRequest | None, progress, done: bool) -> str:
    if done:
        return "done"
    if progress is not None:
        return "started"
    if lr is not None and lr.status == "ready" and (lr.lesson_id or lr.quiz_id):
        return "ready"
    if lr is not None and lr.status == "generating":
        return "preparing"
    # error — or still "queued": its generation never started (e.g. the daily budget ran out in
    # between). Either way, starting it (the learner's Start or the parent's Try again) retries.
    return "failed"


async def _views(
    db: AsyncSession, profile: Profile, rows: list[Assignment]
) -> list[AssignmentOut]:
    if not rows:
        return []
    requests = {
        lr.request_id: (lr, lesson, quiz)
        for lr, lesson, quiz in (
            await db.execute(
                select(LearningRequest, Lesson, Quiz)
                .outerjoin(Lesson, Lesson.id == LearningRequest.lesson_id)
                .outerjoin(Quiz, Quiz.id == LearningRequest.quiz_id)
                .where(LearningRequest.request_id.in_([a.request_id for a in rows]))
            )
        ).all()
    }
    lesson_ids = {lr.lesson_id for lr, _, _ in requests.values() if lr.lesson_id is not None}
    quiz_ids = {lr.quiz_id for lr, _, _ in requests.values() if lr.quiz_id is not None}
    lesson_progress = await progress_service.lesson_progress_map(db, profile, lesson_ids)
    quiz_progress = await progress_service.quiz_progress_map(db, profile, quiz_ids)

    # A test counts as done once ANY attempt was finished (opening it again starts a new attempt,
    # which must not undo the task); its result is the latest finished attempt's.
    finished: dict[int, QuizAttempt] = {}
    if quiz_ids:
        for attempt in (
            await db.execute(
                select(QuizAttempt)
                .where(
                    QuizAttempt.profile_id == profile.id,
                    QuizAttempt.quiz_id.in_(quiz_ids),
                    QuizAttempt.completed_at.is_not(None),
                )
                .order_by(QuizAttempt.id)
            )
        ).scalars():
            finished[attempt.quiz_id] = attempt
    correct: dict[int, int] = {}
    totals: dict[int, int] = {}
    if finished:
        correct = dict(
            (
                await db.execute(
                    select(Answer.attempt_id, func.count())
                    .where(
                        Answer.attempt_id.in_([a.id for a in finished.values()]),
                        Answer.is_correct.is_(True),
                    )
                    .group_by(Answer.attempt_id)
                )
            ).all()
        )
        totals = dict(
            (
                await db.execute(
                    select(QuizQuestion.quiz_id, func.count())
                    .where(QuizQuestion.quiz_id.in_(list(finished)))
                    .group_by(QuizQuestion.quiz_id)
                )
            ).all()
        )

    out: list[AssignmentOut] = []
    for a in rows:
        lr, lesson, quiz = requests.get(a.request_id, (None, None, None))
        progress = None
        result = None
        done = False
        if lr is not None and lr.lesson_id is not None:
            progress = lesson_progress.get(lr.lesson_id)
            done = progress is not None and progress.completed
        elif lr is not None and lr.quiz_id is not None:
            progress = quiz_progress.get(lr.quiz_id)
            attempt = finished.get(lr.quiz_id)
            if attempt is not None:
                done = True
                total = totals.get(lr.quiz_id, 0)
                result = AssignmentResult(
                    correct=min(correct.get(attempt.id, 0), total), total=total
                )
        out.append(
            AssignmentOut(
                id=a.id,
                request_id=a.request_id,
                mode=a.mode,
                title=(lesson.topic if lesson else (quiz.title if quiz else None)) or a.title,
                subject=(lesson.subject if lesson else (quiz.subject if quiz else None)) or a.subject,
                created_at=_aware(a.created_at),
                status=_status(lr, progress, done),
                progress=progress,
                result=result,
            )
        )
    return out


async def list_assignments(
    db: AsyncSession, profile: Profile, *, open_only: bool, now: datetime | None = None
) -> list[AssignmentOut]:
    """The learner's tasks from the last ``TASK_LIFETIME``. ``open_only`` (the learner's home
    screen): not finished yet, oldest first — the order they were given. Otherwise (the parent's
    list): the most recent first, finished ones included."""
    since = (now or utcnow()) - TASK_LIFETIME
    stmt = select(Assignment).where(
        Assignment.profile_id == profile.id,
        Assignment.removed_at.is_(None),
        Assignment.created_at >= since,
    )
    if open_only:
        stmt = stmt.order_by(Assignment.created_at, Assignment.id)
    else:
        stmt = stmt.order_by(Assignment.created_at.desc(), Assignment.id.desc()).limit(
            PARENT_LIST_LIMIT
        )
    views = await _views(db, profile, list((await db.execute(stmt)).scalars()))
    return [v for v in views if v.status != "done"] if open_only else views


async def assignment_view(db: AsyncSession, profile: Profile, row: Assignment) -> AssignmentOut:
    return (await _views(db, profile, [row]))[0]


async def get_assignment(
    db: AsyncSession, profile: Profile, assignment_id: int
) -> Assignment | None:
    """One of this learner's tasks that hasn't been taken back (None for anyone else's)."""
    return await db.scalar(
        select(Assignment).where(
            Assignment.id == assignment_id,
            Assignment.profile_id == profile.id,
            Assignment.removed_at.is_(None),
        )
    )


async def remove_assignment(db: AsyncSession, profile: Profile, assignment_id: int) -> bool:
    """The parent takes a task back. False when it isn't this learner's (or doesn't exist)."""
    row = await db.scalar(
        select(Assignment).where(Assignment.id == assignment_id, Assignment.profile_id == profile.id)
    )
    if row is None:
        return False
    if row.removed_at is None:
        row.removed_at = utcnow()
        await db.flush()
    return True


# --------------------------------------------------------------------------- "the learner's own"
def own_request_filter(profile: Profile) -> ColumnElement[bool]:
    """Requests the learner made themselves (not tasks a parent gave them)."""
    return LearningRequest.request_id.not_in(
        select(Assignment.request_id).where(Assignment.profile_id == profile.id)
    )


async def assigned_engagement(
    db: AsyncSession, profile: Profile, since: datetime
) -> tuple[int, set[date]]:
    """For the overview: (tasks the learner first opened since ``since``, the days they were in a
    task since then). A task only becomes the learner's activity once they open it."""
    assigned = select(Assignment.request_id).where(Assignment.profile_id == profile.id)
    first_open: dict[int, datetime] = {}
    days: set[date] = set()
    for lr_id, opened, active in (
        await db.execute(
            select(LearningRequest.id, LessonProgress.created_at, LessonProgress.last_active_at)
            .join(LessonProgress, LessonProgress.lesson_id == LearningRequest.lesson_id)
            .where(
                LearningRequest.request_id.in_(assigned),
                LearningRequest.profile_id == profile.id,
                LessonProgress.profile_id == profile.id,
            )
        )
    ).all():
        first_open[lr_id] = _aware(opened)
        for moment in (_aware(opened), _aware(active)):
            if moment is not None and moment >= since:
                days.add(moment.date())
    for lr_id, started in (
        await db.execute(
            select(LearningRequest.id, func.min(QuizAttempt.started_at))
            .join(QuizAttempt, QuizAttempt.quiz_id == LearningRequest.quiz_id)
            .where(
                LearningRequest.request_id.in_(assigned),
                LearningRequest.profile_id == profile.id,
                QuizAttempt.profile_id == profile.id,
            )
            .group_by(LearningRequest.id)
        )
    ).all():
        first_open[lr_id] = _aware(started)
        if started is not None and _aware(started) >= since:
            days.add(_aware(started).date())
    opened_in_window = sum(1 for moment in first_open.values() if moment is not None and moment >= since)
    return opened_in_window, days

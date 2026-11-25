"""Parent code + tasks (assignments) I/O schemas — see models/family.py."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import AppModel, StrictModel
from .enums import Mode
from .intent import Decision
from .progress import SessionProgress


class ParentCodeOut(AppModel):
    """The learner's parent code, for their own device to show (and share) again."""

    code: str
    created_at: datetime | None = None
    last_used_at: datetime | None = None  # when a parent last opened the overview with it


class ParentChildOut(AppModel):
    """What a parent's device needs to know about the learner it follows (no identity — the name
    the parent gives the child stays on the parent's device)."""

    school_year: int | None = None
    education_locale: str | None = None


# A task's state, as the learner and the parent see it:
#   preparing — being generated; ready — waiting, not opened yet; started — opened, not finished;
#   done — read to the end / test finished; failed — couldn't be prepared (starting it retries).
AssignmentStatus = Literal["preparing", "ready", "started", "done", "failed"]


class AssignmentResult(AppModel):
    """A finished test's result: correct answers out of the questions."""

    correct: int
    total: int


class AssignmentOut(AppModel):
    id: int
    request_id: str
    mode: str  # study|test
    title: str
    subject: str | None = None
    created_at: datetime | None = None
    status: AssignmentStatus
    progress: SessionProgress | None = None  # the learner's position once opened
    result: AssignmentResult | None = None  # test, once finished


class AssignIn(StrictModel):
    """A parent gives a task: what to learn (free text — sanitized like a learner's prompt) and
    whether it should be a lesson or a test."""

    prompt: str = Field(min_length=1)
    mode: Mode


class AssignOut(AppModel):
    """The sanitizer's decision on the parent's text; ``assignment`` is set when it went ahead."""

    decision: Decision
    assignment: AssignmentOut | None = None

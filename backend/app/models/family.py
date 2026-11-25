"""A parent following a learner from their own device: the view-only parent code, and the tasks a
parent gives (lessons/tests that wait on the learner's home screen).

The parent code is a separate credential from the learner's resume code. It opens the learner's
overview and lets the parent give tasks — it can't be used to learn as the child, answer, or change
their settings. Like the resume code it is looked up by sha256 hash; a Fernet copy lets the
learner's OWN device (resume code) show it again, e.g. for a second parent."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, utcnow


class ParentLink(Base):
    __tablename__ = "parent_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # One code per learner: "make a new code" replaces it (the old one stops working at once).
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), unique=True, index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    code_encrypted: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # When a parent last opened the overview with it (shown to the learner; coarse, see services).
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Assignment(Base):
    """A lesson/test a parent gave the learner. The content is an ordinary learning request owned by
    the learner (sanitized + generated exactly like their own prompt); this row marks it as a task.
    Its state (preparing / ready / started / done) is read from the request and the learner's own
    progress rows, never stored twice."""

    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), index=True)
    request_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(8))  # study|test
    # The classifier's sanitized topic (never the parent's raw text) — shown until the content's own
    # title exists.
    title: Mapped[str] = mapped_column(String(160), default="")
    subject: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    # The parent took it back: gone from the learner's home screen and the parent's list.
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

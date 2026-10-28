"""Gamification orchestration — the reward layer that wraps every learning signal (SPEC §7).

Implemented by the **B4 agent**. Keep these signatures (routes depend on them). Orchestrates:
grade (deterministic or LLM via app.llm.grader) → derive FSRS rating → srs_service.review →
mastery recompute → XP (leveling.item_xp + combo) → persist Answer/XpEvent rows → streak settle →
badge eval. Combo math lives in ``leveling.combo_multiplier`` (pure) — reuse it, don't fork.

Design refs: gamification_design (XP/combo/streaks), pedagogy_framework (rating, mastery, feedback)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.constants import (
    DAILY_GOAL_XP,
    MASTERY_MASTERED_THRESHOLD,
    REST_DAYS_PER_WEEK_YOUNG,
    STREAK_FREEZE_CAP_DEFAULT,
    STREAK_FREEZE_CAP_LONG,
    STREAK_LONG_THRESHOLD_DAYS,
    STREAK_REPAIR_WINDOW_HOURS,
)
from ..models import (
    Answer,
    Concept,
    ConceptEdge,
    Item,
    ItemFsrsCard,
    Misconception,
    Profile,
    ProfileSettings,
    QuizAttempt,
    QuizQuestion,
    SkillMastery,
    StreakState,
    XpEvent,
)
from ..schemas.enums import AgeBand, FsrsRating, NodeState, XpReason
from ..schemas.gamification import (
    AnswerSupport,
    FeedbackBlock,
    GradeResult,
    LevelUp,
    MasteryChange,
    MisconceptionInfo,
    ResultsSummary,
    StreakInfo,
)
from ..schemas.questions import AnswerIn
from . import badges, leveling, mastery, srs_service

# Free-text item types graded by the LLM (B2's app.llm.grader); the rest are deterministic.
_LLM_GRADED = frozenset({"short_answer", "numeric", "explain"})
# Types whose answer the child TYPES (free text + cloze blanks) — screened for crisis before grading.
_TYPED_TEXT = _LLM_GRADED | {"cloze"}

logger = logging.getLogger("schoolautomaton.safety")


class CardNotDue(Exception):
    """A due-only review (POST /review/{id}) found the learner's card no longer due — typically a
    concurrent copy of the same review got there first. Nothing of this attempt may be kept."""


def uses_llm_grader(item: Item, submitted: Any) -> bool:
    """Will grading this submission call the (paid) AI grader? Free-text types with a non-blank
    answer do; blank answers short-circuit to incorrect and everything else is deterministic."""
    return item.item_type in _LLM_GRADED and not _is_blank_submission(submitted)


def card_is_due(card: ItemFsrsCard, now: datetime) -> bool:
    """FSRS says this card may be reviewed now (new cards always may)."""
    if card.state == 0 or card.due is None:
        return True
    due = card.due if card.due.tzinfo else card.due.replace(tzinfo=UTC)
    return due <= now


async def _claim_due_card(
    db: AsyncSession, card: ItemFsrsCard, next_due: datetime, now: datetime
) -> None:
    """Atomically move a DUE card's due date forward, or raise :class:`CardNotDue`.

    A conditional UPDATE, so of two concurrent reviews of one due card exactly one wins: SQLite runs
    one writer at a time and the loser's WHERE sees the winner's new (future) due date. Without it,
    a burst of parallel copies of one review would each award XP."""
    result = await db.execute(
        update(ItemFsrsCard)
        .where(
            ItemFsrsCard.id == card.id,
            or_(ItemFsrsCard.state == 0, ItemFsrsCard.due.is_(None), ItemFsrsCard.due <= now),
        )
        .values(due=next_due)
        .execution_options(synchronize_session=False)
    )
    if cast(CursorResult, result).rowcount != 1:
        raise CardNotDue()


# --------------------------------------------------------------------------- deterministic grading
def _norm_text(value: Any) -> str:
    return str(value).strip().casefold()


def _accepted_variants(item: Item) -> set[str]:
    """Normalized set of an item's documented accepted answer variants (alternate correct forms)."""
    raw = getattr(item, "accepted_variants_json", None) or []
    return {_norm_text(v) for v in raw if v is not None}


def _is_blank_submission(value: Any) -> bool:
    """A genuinely empty answer (None or whitespace-only string). Note: numeric 0 / False are NOT
    blank — only missing or empty text — so a valid 0 still gets graded."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def _grade_deterministic(item: Item, submitted: Any) -> tuple[bool, float, str | None]:
    """Grade a closed-form item against the STORED full payload (with correctness).

    Returns (is_correct, partial_credit, detected_distractor_text). Tolerant to missing/None
    submissions (always graded incorrect, never raising)."""
    payload = item.payload_json or {}
    kind = payload.get("kind", item.item_type)

    if kind == "mcq":
        correct_ids = {o["id"] for o in payload.get("options", []) if o.get("is_correct")}
        multiple = bool(payload.get("multiple"))
        chosen = submitted if isinstance(submitted, list) else ([] if submitted is None else [submitted])
        chosen_set = {str(c) for c in chosen}
        if multiple:
            is_correct = chosen_set == correct_ids and bool(correct_ids)
            inter = len(chosen_set & correct_ids)
            wrong = len(chosen_set - correct_ids)
            denom = max(1, len(correct_ids))
            partial = max(0.0, (inter - wrong) / denom)
        else:
            is_correct = len(chosen_set) == 1 and chosen_set.issubset(correct_ids)
            partial = 1.0 if is_correct else 0.0
        distractor = None
        if not is_correct:
            picked = next((str(c) for c in chosen if str(c) not in correct_ids), None)
            if picked is not None:
                distractor = next(
                    (o.get("text") for o in payload.get("options", []) if o.get("id") == picked), None
                )
        return is_correct, (1.0 if is_correct else partial), distractor

    if kind == "true_false":
        answer = bool(payload.get("answer"))
        is_correct = isinstance(submitted, bool) and submitted == answer
        return is_correct, (1.0 if is_correct else 0.0), None

    if kind == "cloze":
        blanks = payload.get("blanks", [])
        if not blanks:
            return False, 0.0, None
        sub = submitted if isinstance(submitted, dict) else {}
        variants = _accepted_variants(item)
        hits = 0
        for b in blanks:
            expected = {_norm_text(b.get("answer"))} | variants
            given = _norm_text(sub.get(b.get("id"), ""))
            if given and given in expected:
                hits += 1
        partial = hits / len(blanks)
        return (hits == len(blanks)), partial, None

    if kind == "match":
        correct_pairs = {(p["left_id"], p["right_id"]) for p in payload.get("correct", [])}
        if not correct_pairs:
            return False, 0.0, None
        sub_pairs = set()
        if isinstance(submitted, list):
            for p in submitted:
                if isinstance(p, dict) and "left_id" in p and "right_id" in p:
                    sub_pairs.add((str(p["left_id"]), str(p["right_id"])))
        hits = len(sub_pairs & correct_pairs)
        partial = hits / len(correct_pairs)
        return (sub_pairs == correct_pairs), partial, None

    if kind == "order":
        correct_order = [str(t) for t in payload.get("correct_order", [])]
        if not correct_order:
            return False, 0.0, None
        given = [str(t) for t in submitted] if isinstance(submitted, list) else []
        in_place = sum(1 for i, t in enumerate(given) if i < len(correct_order) and t == correct_order[i])
        partial = in_place / len(correct_order)
        return (given == correct_order), partial, None

    if kind == "hotspot":
        correct_ids = {r["id"] for r in payload.get("regions", []) if r.get("is_correct")}
        is_correct = submitted is not None and str(submitted) in correct_ids
        return is_correct, (1.0 if is_correct else 0.0), None

    # Unknown / closed-form fallback: compare against expected_answer OR any accepted variant.
    if item.expected_answer is not None:
        given = _norm_text(submitted)
        is_correct = given == _norm_text(item.expected_answer) or given in _accepted_variants(item)
        return is_correct, (1.0 if is_correct else 0.0), None
    return False, 0.0, None


def _grade_free_text_deterministic(
    item: Item, submitted: Any
) -> tuple[bool, float, str | None, str, str]:
    """Deterministic safety net for free text: numeric tolerance / casefolded text equality (or an
    accepted variant). Used when the AI grader fails or today's AI budget is spent."""
    payload = item.payload_json or {}
    if (payload.get("kind") or item.item_type) == "numeric":
        try:
            ans = float(payload.get("answer"))
            tol = float(payload.get("tolerance", 0.0) or 0.0)
            ok = abs(float(submitted) - ans) <= tol
        except (TypeError, ValueError):
            ok = False
        return ok, (1.0 if ok else 0.0), None, (item.explanation or ""), "strategy"
    given = _norm_text(submitted)
    ok = (item.expected_answer is not None and given == _norm_text(item.expected_answer)) or (
        given != "" and given in _accepted_variants(item)
    )
    return ok, (1.0 if ok else 0.0), None, (item.explanation or ""), "strategy"


async def _release_connection(db: AsyncSession) -> None:
    """End the request's transaction before a slow model call, so its pooled connection goes back
    to the pool for the call's duration (a class answering free text at once used to hold every
    pooled connection and stall all other requests).

    Grading writes nothing before the model call — only reads have happened — so this commit
    normally just ends a read transaction (anything a caller did stage is flushed in one short burst
    here rather than held across the call). ``expire_on_commit=False`` keeps the loaded profile and
    item usable afterwards; the next query opens a fresh transaction."""
    if db.in_transaction():
        await db.commit()


async def _grade_free_text(
    db: AsyncSession, profile: Profile, item: Item, submitted: Any, language: str
) -> tuple[bool, float, str | None, str, str]:
    """Grade short_answer/numeric/explain via the LLM grader (B2). Imported LAZILY so this module
    imports even while B2's grader is mid-write. Falls back to deterministic numeric/text on any
    failure — and, without calling the model, once today's AI budget is spent — so grading never
    hard-fails for the learner."""
    from . import cost_guard  # noqa: PLC0415

    if await cost_guard.ai_budget_exceeded(db):
        return _grade_free_text_deterministic(item, submitted)
    await _release_connection(db)
    result: tuple[bool, float, str | None, str, str]
    try:
        from ..llm import grader as llm_grader  # noqa: PLC0415  (lazy by design)

        # The grader stages its usage rows on ``db`` after the call returns (never during it).
        out = await llm_grader.grade_free_text(
            item, submitted, language=language, db=db, profile_id=profile.id
        )
        result = (
            bool(out.correct),
            float(out.partial_credit),
            out.misconception,
            out.explanation or (item.explanation or ""),
            out.encouragement_focus,
        )
    except Exception:
        result = _grade_free_text_deterministic(item, submitted)
    if profile in db:
        # The profile was read before the (seconds-long) call; re-read it so the XP added below
        # builds on any XP this learner earned meanwhile (e.g. a second tab).
        await db.refresh(profile)
    return result


# --------------------------------------------------------------------------- reveal / feedback
def _reveal_correct_answer(item: Item) -> Any:
    """The correct answer to surface AT grading time (never at delivery — SPEC §5)."""
    payload = item.payload_json or {}
    kind = payload.get("kind", item.item_type)
    if kind == "mcq":
        ids = [o["id"] for o in payload.get("options", []) if o.get("is_correct")]
        return ids if payload.get("multiple") else (ids[0] if ids else None)
    if kind == "true_false":
        return bool(payload.get("answer"))
    if kind == "cloze":
        return {b["id"]: b.get("answer") for b in payload.get("blanks", [])}
    if kind == "match":
        return payload.get("correct", [])
    if kind == "order":
        return payload.get("correct_order", [])
    if kind == "hotspot":
        return [r["id"] for r in payload.get("regions", []) if r.get("is_correct")]
    if kind == "numeric":
        return payload.get("answer", item.expected_answer)
    return item.expected_answer


_FEEDBACK = {
    "correct": {
        "en": "Nice work — your approach paid off. Keep using that strategy.",
        "cs": "Skvělá práce — tvůj postup se vyplatil. Drž se ho.",
    },
    "partial": {
        "en": "You're on the right track — refine your method and try the rest.",
        "cs": "Jsi na správné cestě — uprav postup a zkus zbytek.",
    },
    "incorrect": {
        "en": "Not yet — review the worked steps and try a different approach.",
        "cs": "Ještě ne — projdi si postup a zkus to jinak.",
    },
}


def _feedback(is_correct: bool, partial: float, language: str, focus: str) -> FeedbackBlock:
    """Growth-mindset feedback: praises strategy/process, never innate ability (SPEC pedagogy)."""
    lang = language if language in ("en", "cs") else "en"
    if is_correct:
        key = "correct"
    elif partial > 0.0:
        key = "partial"
    else:
        key = "incorrect"
    text = _FEEDBACK[key][lang]
    safe_focus = focus if focus in ("effort", "strategy", "progress") else "strategy"
    return FeedbackBlock(text=text, encouragement_focus=safe_focus)


# --------------------------------------------------------------------------- card / mastery helpers
async def _get_or_create_card(
    db: AsyncSession, profile: Profile, item: Item, now: datetime
) -> ItemFsrsCard:
    card = await db.scalar(
        select(ItemFsrsCard).where(
            ItemFsrsCard.profile_id == profile.id, ItemFsrsCard.item_id == item.id
        )
    )
    if card is None:
        # INSERT OR IGNORE, then read back: the same answer arriving twice at once (a double tap on
        # Check, two tabs) raced to create this card, and the loser's plain INSERT hit the unique
        # (profile, item) constraint and failed the whole answer.
        await db.execute(
            sqlite_insert(ItemFsrsCard)
            .values(
                profile_id=profile.id,
                item_id=item.id,
                state=0,
                fsrs_card_json=srs_service.new_card(now),
                due=now,
            )
            .on_conflict_do_nothing(index_elements=["profile_id", "item_id"])
        )
        card = await db.scalar(
            select(ItemFsrsCard).where(
                ItemFsrsCard.profile_id == profile.id, ItemFsrsCard.item_id == item.id
            )
        )
    return card


async def _answer_evidence(
    db: AsyncSession, profile: Profile, concept_id: int
) -> tuple[set[str], dict[int, bool]]:
    """From this learner's graded answers on the concept: the distinct UTC days ('YYYY-MM-DD') with
    a correct answer, and whether each item's latest answer was correct. One query, newest first."""
    rows = (
        await db.execute(
            select(Answer.item_id, Answer.is_correct, func.date(Answer.created_at))
            .join(Item, Item.id == Answer.item_id)
            .where(Answer.profile_id == profile.id, Item.concept_id == concept_id)
            .order_by(Answer.created_at.desc(), Answer.id.desc())
        )
    ).all()
    correct_days: set[str] = set()
    latest: dict[int, bool] = {}
    for item_id, is_correct, day in rows:
        latest.setdefault(item_id, bool(is_correct))
        if is_correct:
            correct_days.add(day)
    return correct_days, latest


async def _recompute_mastery(
    db: AsyncSession,
    profile: Profile,
    concept_id: int,
    now: datetime,
    *,
    item_id: int | None = None,
    answered_correct: bool = False,
) -> tuple[SkillMastery, float, float, NodeState]:
    """Recompute SkillMastery for one concept from its cards' FSRS retrievability (SPEC §4 #5).

    ``item_id`` / ``answered_correct``: the answer being graded right now — its Answer row is
    written after mastery is recomputed, so it is folded in here (it counts toward the
    correct-on-two-days rule and is that item's latest answer). Returns (row, before, after,
    node_state)."""
    retention = profile.desired_retention
    cards = (
        await db.execute(
            select(ItemFsrsCard)
            .join(Item, Item.id == ItemFsrsCard.item_id)
            .where(ItemFsrsCard.profile_id == profile.id, Item.concept_id == concept_id)
        )
    ).scalars().all()

    correct_days, latest_correct = await _answer_evidence(db, profile, concept_id)
    if item_id is not None:
        latest_correct[item_id] = answered_correct
        if answered_correct:
            correct_days.add(now.astimezone(UTC).date().isoformat())

    views: list[mastery.CardView] = []
    mastered_due: list[datetime] = []
    for c in cards:
        state = srs_service.card_state(c.fsrs_card_json)
        r = srs_service.get_retrievability(c.fsrs_card_json, now, desired_retention=retention)
        views.append(mastery.CardView(
            state=state, retrievability=r, last_correct=latest_correct.get(c.item_id, False)
        ))
        if state == 2 and c.due is not None:  # Review-state cards drive decay timing
            mastered_due.append(c.due if c.due.tzinfo else c.due.replace(tzinfo=UTC))

    after = mastery.concept_mastery(views, correct_days=len(correct_days))
    decay_due_at = min(mastered_due) if (mastered_due and mastery.is_mastered(after)) else None

    prereqs_met = await _prereqs_met(db, profile, concept_id)
    state = mastery.node_state(after, prereqs_met=prereqs_met, decay_due_at=decay_due_at, now=now)

    row = await db.scalar(
        select(SkillMastery).where(
            SkillMastery.profile_id == profile.id, SkillMastery.concept_id == concept_id
        )
    )
    before = row.mastery if row is not None else 0.0
    if row is None:
        row = SkillMastery(profile_id=profile.id, concept_id=concept_id)
        db.add(row)
    row.mastery = after
    row.node_state = state.value
    row.decay_due_at = decay_due_at
    row.last_reviewed = now
    row.recent_accuracy = await _recent_accuracy(db, profile, concept_id)
    await db.flush()
    return row, before, after, state


async def _prereqs_met(db: AsyncSession, profile: Profile, concept_id: int) -> bool:
    """All prerequisite concepts (edges from→to=concept) are mastered? Vacuously true if none."""
    prereq_ids = (
        await db.execute(
            select(ConceptEdge.from_concept_id).where(
                ConceptEdge.to_concept_id == concept_id, ConceptEdge.edge_type == "prerequisite"
            )
        )
    ).scalars().all()
    if not prereq_ids:
        return True
    for pid in prereq_ids:
        m = await db.scalar(
            select(SkillMastery.mastery).where(
                SkillMastery.profile_id == profile.id, SkillMastery.concept_id == pid
            )
        )
        if m is None or m < MASTERY_MASTERED_THRESHOLD:
            return False
    return True


async def _recent_accuracy(db: AsyncSession, profile: Profile, concept_id: int) -> float | None:
    """Rolling accuracy over the learner's recent answers on this concept (ZPD signal)."""
    rows = (
        await db.execute(
            select(Answer.is_correct)
            .join(Item, Item.id == Answer.item_id)
            .where(Answer.profile_id == profile.id, Item.concept_id == concept_id)
            .order_by(Answer.id.desc())
            .limit(10)
        )
    ).scalars().all()
    if not rows:
        return None
    return round(sum(1 for r in rows if r) / len(rows), 3)


# --------------------------------------------------------------------------- XP helpers
async def _add_xp(
    db: AsyncSession,
    profile: Profile,
    amount: int,
    reason: XpReason,
    *,
    concept_id: int | None = None,
    item_id: int | None = None,
    metadata: dict | None = None,
) -> int:
    """Append an immutable XpEvent and bump the denormalized profiles.total_xp. Never decrements."""
    amount = max(0, int(amount))
    if amount <= 0:
        return 0
    db.add(
        XpEvent(
            profile_id=profile.id,
            amount=amount,
            reason=reason.value,
            concept_id=concept_id,
            item_id=item_id,
            metadata_json=metadata,
        )
    )
    profile.total_xp = (profile.total_xp or 0) + amount
    return amount


async def _is_first_try(db: AsyncSession, profile: Profile, item_id: int) -> bool:
    """No prior answer for this (profile,item) → this is a first-try attempt."""
    prior = await db.scalar(
        select(func.count())
        .select_from(Answer)
        .where(Answer.profile_id == profile.id, Answer.item_id == item_id)
    )
    return not prior


async def _attempt_combo(db: AsyncSession, attempt_id: int | None) -> int:
    """Consecutive first-try-correct answers in the current attempt (for the combo multiplier)."""
    if attempt_id is None:
        return 0
    rows = (
        await db.execute(
            select(Answer.is_correct, Answer.used_hint, Answer.is_first_try)
            .where(Answer.attempt_id == attempt_id)
            .order_by(Answer.id.desc())
        )
    ).all()
    combo = 0
    for is_correct, used_hint, is_first_try in rows:
        if is_correct and not used_hint and is_first_try:
            combo += 1
        else:
            break
    return combo


# --------------------------------------------------------------------------- crisis screening
def _typed_text(item: Item, submitted: Any) -> str:
    """The text the learner TYPED into this answer (free text, cloze blanks); '' for answer types
    that are picked rather than typed (option/region/token ids are generated, not the child's)."""
    kind = (item.payload_json or {}).get("kind")
    if item.item_type not in _TYPED_TEXT and kind not in _TYPED_TEXT:
        return ""
    parts: list[str] = []
    stack = [submitted]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            parts.append(node)
        elif isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, list | tuple):
            stack.extend(node)
    return " | ".join(parts)


async def _crisis_support_result(
    db: AsyncSession, profile: Profile, item: Item, submitted: Any
) -> GradeResult | None:
    """Screen a typed answer with the prompt path's deterministic self-harm net. On a hit, return
    the support result INSTEAD of grading: the answer never reaches the AI grader and nothing is
    saved (no answer row, no FSRS review, no XP) — the caller returns it as is."""
    text = _typed_text(item, submitted)
    if not text.strip():
        return None
    from ..sanitization import safety  # noqa: PLC0415

    if not safety.typed_text_signals_crisis(text):
        return None
    prefs = await db.get(ProfileSettings, profile.id)
    found = safety.answer_crisis_support(
        text, education_locale=prefs.education_locale if prefs is not None else None
    )
    # No answer text in the log — only that the card was shown, and for which item.
    logger.warning("Crisis support shown instead of grading an answer (item %s)", item.id)
    return GradeResult(
        is_correct=False,
        partial_credit=0.0,
        correct_answer=None,
        fsrs_rating=int(FsrsRating.AGAIN),  # required by the schema; meaningless here
        next_due=None,
        explanation=None,
        misconception=None,
        feedback=FeedbackBlock(text=found.nudge or found.message, encouragement_focus="effort"),
        xp_awarded=0,
        combo_multiplier=1.0,
        mastery_delta=0.0,
        new_badges=[],
        level_up=None,
        support=AnswerSupport(
            message=found.message, resources=found.resources, disclosure=found.disclosure
        ),
    )


# --------------------------------------------------------------------------- public orchestration
async def grade_and_reward(
    db: AsyncSession,
    profile: Profile,
    item: Item,
    answer: AnswerIn,
    attempt_id: int | None,
    now: datetime | None = None,
    *,
    only_if_due: bool = False,
) -> GradeResult:
    """Grade one answer and apply all reward/scheduling side-effects. Returns the public GradeResult
    (reveals the correct answer here, never at delivery).

    ``only_if_due`` (the spaced-review path): apply the review only if the learner's card is still
    due when it is written, else raise :class:`CardNotDue` (the caller rolls back) — so repeated or
    parallel copies of one review can't farm XP.

    A typed answer that trips the self-harm net is not graded at all: the result carries
    ``support`` (localized crisis resources) and nothing is persisted."""
    now = now or datetime.now(UTC)
    # Feedback should match the CONTENT language (a Czech lesson gets Czech feedback), falling back
    # to the learner's UI language, then English.
    language = item.language or profile.primary_language or "en"
    item_type = item.item_type

    # 0) Child safety first: a typed answer is screened like a prompt before anything else happens.
    support = await _crisis_support_result(db, profile, item, answer.submitted_value)
    if support is not None:
        return support

    # 1) Grade (deterministic for closed-form; LLM for free-text/explain).
    misconception_text: str | None = None
    if item_type in _LLM_GRADED:
        # A blank/whitespace submission is wrong by definition — short-circuit so an empty answer can
        # never be talked into "correct" by the generous LLM grader (and we skip a wasted call).
        if _is_blank_submission(answer.submitted_value):
            is_correct, partial, misconception_text, explanation, focus = (
                False, 0.0, None, item.explanation or "", "strategy"
            )
        else:
            is_correct, partial, misconception_text, explanation, focus = await _grade_free_text(
                db, profile, item, answer.submitted_value, language
            )
    else:
        is_correct, partial, distractor_text = _grade_deterministic(item, answer.submitted_value)
        explanation = item.explanation or ""
        focus = "strategy"
        misconception_text = distractor_text if not is_correct else None

    first_try = await _is_first_try(db, profile, item.id)

    # 2) Derive FSRS rating + advance the card (FSRS is the single scheduler).
    rating = srs_service.derive_rating(is_correct, answer.used_hint, answer.latency_ms, item_type)
    card = await _get_or_create_card(db, profile, item, now)
    prev_state = srs_service.card_state(card.fsrs_card_json)
    new_json, next_due = srs_service.review(
        card.fsrs_card_json, rating, now, desired_retention=profile.desired_retention
    )
    if only_if_due:
        await _claim_due_card(db, card, next_due, now)
    card.fsrs_card_json = new_json
    card.state = srs_service.card_state(new_json)
    card.due = next_due
    card.last_review = now
    card.reps = (card.reps or 0) + 1
    if rating == FsrsRating.AGAIN:
        card.lapses = (card.lapses or 0) + 1
    # Project denormalized stability/difficulty for indexing (authoritative json untouched).
    from fsrs import Card as _FsrsCard  # noqa: PLC0415

    _c = _FsrsCard.from_json(new_json)
    card.stability = _c.stability
    card.difficulty = _c.difficulty
    await db.flush()

    # 3) Mastery before failure-state was recorded → recompute concept mastery + node_state.
    failed_before = await _concept_was_failed(db, profile, item.concept_id) if is_correct else False
    sm_row, mastery_before, mastery_after, node_state = await _recompute_mastery(
        db, profile, item.concept_id, now, item_id=item.id, answered_correct=is_correct
    )
    mastery_delta = round(mastery_after - mastery_before, 4)

    # 4) Resolve a misconception row from the matched distractor text (best-effort).
    misconception_info, misconception_id = await _resolve_misconception(
        db, item.concept_id, misconception_text, item=item
    )

    # 5) XP — diminishing returns on mastery, combo multiplier on consecutive first-try-correct.
    xp_awarded = 0
    combo_mult = 1.0
    if is_correct:
        base_xp = leveling.item_xp(item.item_difficulty or 3, mastery_before)
        combo_n = await _attempt_combo(db, attempt_id)
        combo_mult = leveling.combo_multiplier(combo_n + (1 if first_try and not answer.used_hint else 0))
        reason = XpReason.FIRST_TRY_CORRECT if first_try else XpReason.SPACED_RETENTION
        if prev_state == 0 and not first_try:
            reason = XpReason.SPACED_RETENTION
        gained = round(base_xp * combo_mult)
        xp_before_total = profile.total_xp or 0
        xp_awarded = await _add_xp(
            db, profile, gained, reason, concept_id=item.concept_id, item_id=item.id,
            metadata={"combo": combo_mult, "rating": rating},
        )
        # Mastery-gain + comeback bonuses wrap genuine learning signals (design gamification_design).
        if mastery_before < MASTERY_MASTERED_THRESHOLD <= mastery_after:
            xp_awarded += await _add_xp(
                db, profile, 25, XpReason.MASTERY_GAIN, concept_id=item.concept_id, item_id=item.id
            )
            if failed_before:
                xp_awarded += await _add_xp(
                    db, profile, 25, XpReason.COMEBACK, concept_id=item.concept_id, item_id=item.id
                )
        level_before = leveling.level_from_xp(xp_before_total)
        level_after = leveling.level_from_xp(profile.total_xp or 0)
        level_up = LevelUp(from_level=level_before, to_level=level_after) if level_after > level_before else None
    else:
        level_up = None

    # 6) Persist the immutable Answer row.
    db.add(
        Answer(
            attempt_id=attempt_id,
            profile_id=profile.id,
            item_id=item.id,
            submitted_value_json=answer.submitted_value,
            is_correct=is_correct,
            partial_credit=partial,
            used_hint=answer.used_hint,
            is_first_try=first_try,
            latency_ms=answer.latency_ms,
            fsrs_rating=rating,
            detected_misconception_id=misconception_id,
            xp_awarded=xp_awarded,
            mastery_delta=mastery_delta,
            created_at=now,  # the grading time: mastery's correct-on-two-days rule counts these days
        )
    )
    await db.flush()

    # A graded answer counts toward today's streak — settled after grading, with the other writes,
    # and before the badges so a streak badge sees today.
    streak = await settle_streak(db, profile, now)

    # 7) Badge evaluation against the just-updated state.
    new_badges = await badges.evaluate_badges(
        db,
        profile,
        {
            "type": "answer",
            "item_id": item.id,
            "concept_id": item.concept_id,
            "attempt_id": attempt_id,
            "is_correct": is_correct,
            "first_try": first_try,
            "used_hint": answer.used_hint,
            "item_type": item_type,
            "mastery_after": mastery_after,
            "mastery_before": mastery_before,
            "node_state": node_state.value,
            "failed_before": failed_before,
            "language": language,
            "now": now,
        },
    )

    return GradeResult(
        is_correct=is_correct,
        partial_credit=partial,
        correct_answer=_reveal_correct_answer(item),
        fsrs_rating=rating,
        next_due=next_due,
        explanation=explanation or None,
        misconception=misconception_info,
        feedback=_feedback(is_correct, partial, language, focus),
        xp_awarded=xp_awarded,
        combo_multiplier=combo_mult,
        mastery_delta=mastery_delta,
        new_badges=new_badges,
        level_up=level_up,
        streak=streak,
    )


async def review_with_rating(
    db: AsyncSession,
    profile: Profile,
    item: Item,
    rating: int,
    *,
    used_hint: bool = False,
    latency_ms: int | None = None,
    now: datetime | None = None,
    only_if_due: bool = False,
) -> GradeResult:
    """Advance an item's FSRS card from an EXPLICIT self-rating (1..4) — the rating-only review path.

    Used by POST /review/{item_id} when the learner submits a rating with no answer value. Skips
    correctness grading; ``correct`` is derived from rating>=GOOD (Again/Hard are not 'correct' for
    XP, matching derive_rating's Again=incorrect mapping but honoring the explicit rating for FSRS).
    ``only_if_due``: as in :func:`grade_and_reward`."""
    now = now or datetime.now(UTC)
    rating = max(1, min(4, int(rating)))
    is_correct = rating >= int(FsrsRating.GOOD)
    partial = 1.0 if is_correct else 0.0

    first_try = await _is_first_try(db, profile, item.id)

    card = await _get_or_create_card(db, profile, item, now)
    prev_state = srs_service.card_state(card.fsrs_card_json)
    new_json, next_due = srs_service.review(
        card.fsrs_card_json, rating, now, desired_retention=profile.desired_retention
    )
    if only_if_due:
        await _claim_due_card(db, card, next_due, now)
    card.fsrs_card_json = new_json
    card.state = srs_service.card_state(new_json)
    card.due = next_due
    card.last_review = now
    card.reps = (card.reps or 0) + 1
    if rating == FsrsRating.AGAIN:
        card.lapses = (card.lapses or 0) + 1
    from fsrs import Card as _FsrsCard  # noqa: PLC0415

    _c = _FsrsCard.from_json(new_json)
    card.stability = _c.stability
    card.difficulty = _c.difficulty
    await db.flush()

    failed_before = await _concept_was_failed(db, profile, item.concept_id) if is_correct else False
    _sm_row, mastery_before, mastery_after, node_state = await _recompute_mastery(
        db, profile, item.concept_id, now, item_id=item.id, answered_correct=is_correct
    )
    mastery_delta = round(mastery_after - mastery_before, 4)

    xp_awarded = 0
    level_up = None
    if is_correct:
        base_xp = leveling.item_xp(item.item_difficulty or 3, mastery_before)
        reason = XpReason.FIRST_TRY_CORRECT if first_try else XpReason.SPACED_RETENTION
        if prev_state == 0 and not first_try:
            reason = XpReason.SPACED_RETENTION
        xp_before_total = profile.total_xp or 0
        xp_awarded = await _add_xp(
            db, profile, base_xp, reason, concept_id=item.concept_id, item_id=item.id,
            metadata={"rating": rating, "rating_only": True},
        )
        if mastery_before < MASTERY_MASTERED_THRESHOLD <= mastery_after:
            xp_awarded += await _add_xp(
                db, profile, 25, XpReason.MASTERY_GAIN, concept_id=item.concept_id, item_id=item.id
            )
            if failed_before:
                xp_awarded += await _add_xp(
                    db, profile, 25, XpReason.COMEBACK, concept_id=item.concept_id, item_id=item.id
                )
        level_before = leveling.level_from_xp(xp_before_total)
        level_after = leveling.level_from_xp(profile.total_xp or 0)
        level_up = LevelUp(from_level=level_before, to_level=level_after) if level_after > level_before else None

    db.add(
        Answer(
            attempt_id=None,
            profile_id=profile.id,
            item_id=item.id,
            submitted_value_json=None,
            is_correct=is_correct,
            partial_credit=partial,
            used_hint=used_hint,
            is_first_try=first_try,
            latency_ms=latency_ms,
            fsrs_rating=rating,
            detected_misconception_id=None,
            xp_awarded=xp_awarded,
            mastery_delta=mastery_delta,
            created_at=now,  # the grading time: mastery's correct-on-two-days rule counts these days
        )
    )
    await db.flush()

    streak = await settle_streak(db, profile, now)  # a rated review card counts, as in grade_and_reward

    new_badges = await badges.evaluate_badges(
        db,
        profile,
        {
            "type": "answer",
            "item_id": item.id,
            "concept_id": item.concept_id,
            "attempt_id": None,
            "is_correct": is_correct,
            "first_try": first_try,
            "used_hint": used_hint,
            "item_type": item.item_type,
            "mastery_after": mastery_after,
            "mastery_before": mastery_before,
            "node_state": node_state.value,
            "failed_before": failed_before,
            "language": profile.primary_language or "en",
            "now": now,
        },
    )

    language = profile.primary_language or "en"
    return GradeResult(
        is_correct=is_correct,
        partial_credit=partial,
        correct_answer=_reveal_correct_answer(item),
        fsrs_rating=rating,
        next_due=next_due,
        explanation=item.explanation or None,
        misconception=None,
        feedback=_feedback(is_correct, partial, language, "strategy"),
        xp_awarded=xp_awarded,
        combo_multiplier=1.0,
        mastery_delta=mastery_delta,
        new_badges=new_badges,
        level_up=level_up,
        streak=streak,
    )


async def _concept_was_failed(db: AsyncSession, profile: Profile, concept_id: int) -> bool:
    """Has the learner ever answered any item of this concept incorrectly? (comeback signal)."""
    cnt = await db.scalar(
        select(func.count())
        .select_from(Answer)
        .join(Item, Item.id == Answer.item_id)
        .where(
            Answer.profile_id == profile.id,
            Item.concept_id == concept_id,
            Answer.is_correct.is_(False),
        )
    )
    return bool(cnt)


async def _resolve_misconception(
    db: AsyncSession, concept_id: int, text: str | None, *, item: Item | None = None
) -> tuple[MisconceptionInfo | None, int | None]:
    """Map a chosen wrong option / LLM misconception string to a Misconception row.

    The generator stores each distractor with its misconception id (``distractors_json``), so a chosen
    MCQ option maps exactly — that is what lets the feedback say WHY this particular answer is wrong.
    The old text match of an option's text against misconception descriptions almost never hit; it
    remains only as the fallback for free-text (LLM-graded) misconception strings."""
    if not text:
        return None, None
    if item is not None:
        wanted = _norm_text(text)
        for d in getattr(item, "distractors_json", None) or []:
            mid = d.get("misconception_id") if isinstance(d, dict) else None
            if mid and _norm_text(d.get("text", "")) == wanted:
                row = await db.get(Misconception, mid)
                if row is not None:
                    return MisconceptionInfo(description=row.description, refutation=row.refutation_text), row.id
    rows = (
        await db.execute(select(Misconception).where(Misconception.concept_id == concept_id))
    ).scalars().all()
    needle = _norm_text(text)
    for m in rows:
        if needle and (needle in _norm_text(m.description) or needle in _norm_text(m.code)):
            return MisconceptionInfo(description=m.description, refutation=m.refutation_text), m.id
    return None, None


# --------------------------------------------------------------------------- attempt finalize
async def finalize_attempt(db: AsyncSession, profile: Profile, attempt_id: int) -> ResultsSummary:
    """Finalize a quiz attempt: compute score/accuracy, end-of-session badge eval + streak settle.

    Finishing it again (a double tap, a stale second tab the next day) returns the same summary and
    records nothing: no new completion time, no streak day, no badges."""
    now = datetime.now(UTC)
    attempt = await db.get(QuizAttempt, attempt_id)
    if attempt is None:
        raise ValueError("attempt not found")
    already_finished = attempt.completed_at is not None

    rows = (
        await db.execute(
            select(Answer, Item)
            .join(Item, Item.id == Answer.item_id)
            .where(Answer.attempt_id == attempt_id)
            .order_by(Answer.id)
        )
    ).all()

    # Dedup to the LATEST answer per item: a refresh/resume can append a second Answer row for the
    # same item, which must not double-count toward accuracy/score/mastery. rows are ordered by
    # Answer.id asc, so the last write per item wins.
    latest: dict[int, tuple[Answer, Item]] = {}
    for a, it in rows:
        latest[a.item_id] = (a, it)
    deduped = sorted(latest.values(), key=lambda r: r[0].id)

    # Accuracy/score denominator is the WHOLE quiz so SKIPPED questions count as incorrect (this is
    # what the /review endpoint already does). Fall back to the answered count when the quiz has no
    # registered questions (e.g. unit-test fixtures that don't create QuizQuestion rows).
    q_total = (
        await db.scalar(
            select(func.count())
            .select_from(QuizQuestion)
            .where(QuizQuestion.quiz_id == attempt.quiz_id)
        )
    ) or 0
    correct = sum(1 for a, _ in deduped if a.is_correct)
    total = q_total or len(deduped)
    accuracy = round(correct / total, 4) if total else 0.0
    # Score is "questions correct out of total" — SAME unit as max_score, so the score/max fraction is
    # meaningful. The XP total (combo- and bonus-scaled, a different unit) is surfaced separately.
    score = correct
    max_score = total
    xp_awarded = sum(a.xp_awarded for a, _ in rows)  # all rows: mirrors what was added to total_xp

    # Max combo of consecutive first-try-correct within the attempt.
    combo_max = 0
    run = 0
    for a, _ in deduped:
        if a.is_correct and not a.used_hint and a.is_first_try:
            run += 1
            combo_max = max(combo_max, run)
        else:
            run = 0

    # Per-concept mastery movement (deduped so a re-answer doesn't double-sum the delta), plus whether
    # the concept was ever answered correctly this attempt.
    delta_by_concept: dict[int, float] = {}
    correct_by_concept: dict[int, bool] = {}
    for a, it in deduped:
        delta_by_concept[it.concept_id] = delta_by_concept.get(it.concept_id, 0.0) + (
            a.mastery_delta or 0.0
        )
        correct_by_concept[it.concept_id] = correct_by_concept.get(it.concept_id, False) or bool(
            a.is_correct
        )

    # "What grew" = concepts the learner actually answered correctly AND whose mastery rose this
    # attempt. Without this gate a WRONG answer would masquerade as growth: any answer creates an FSRS
    # card whose retrievability ≈ 1.0 right after review, so before≈0 → after≈1 even for a miss.
    mastery_changes: list[MasteryChange] = []
    for cid in dict.fromkeys(it.concept_id for _, it in deduped):
        if not correct_by_concept.get(cid) or delta_by_concept.get(cid, 0.0) <= 1e-4:
            continue
        sm = await db.scalar(
            select(SkillMastery).where(
                SkillMastery.profile_id == profile.id, SkillMastery.concept_id == cid
            )
        )
        if sm is None:
            continue
        concept = await db.get(Concept, cid)
        before = max(0.0, min(1.0, round(sm.mastery - delta_by_concept.get(cid, 0.0), 4)))
        mastery_changes.append(
            MasteryChange(
                concept_id=cid,
                name=concept.name if concept else str(cid),
                before=before,
                after=sm.mastery,
                state=NodeState(sm.node_state) if sm.node_state in NodeState._value2member_map_ else NodeState.LEARNING,
            )
        )

    if already_finished:
        row = await db.get(StreakState, profile.id)
        return ResultsSummary(
            score=score,
            max_score=max_score,
            accuracy=accuracy,
            xp_awarded=xp_awarded,
            combo_max=combo_max,
            new_badges=[],
            streak=await streak_info_as_of(db, profile, row, now) if row is not None else StreakInfo(),
            mastery_changes=mastery_changes,
            level_up=None,
        )

    attempt.completed_at = now
    attempt.score = score
    attempt.max_score = max_score
    attempt.accuracy = accuracy
    attempt.xp_awarded = xp_awarded
    attempt.combo_max = combo_max
    await db.flush()

    streak = await settle_streak(db, profile, now)
    new_badges = await badges.evaluate_badges(
        db,
        profile,
        {
            "type": "attempt_complete",
            "attempt_id": attempt_id,
            "accuracy": accuracy,
            "combo_max": combo_max,
            "now": now,
        },
    )

    # Per-answer XP (and thus level-ups) are awarded live in grade_and_reward; the session summary
    # reports the aggregate, so there is no additional level transition to surface here.
    return ResultsSummary(
        score=score,
        max_score=attempt.max_score,
        accuracy=accuracy,
        xp_awarded=xp_awarded,
        combo_max=combo_max,
        new_badges=new_badges,
        streak=streak,
        mastery_changes=mastery_changes,
        level_up=None,
    )


# --------------------------------------------------------------------------- streaks
# What counts toward the daily streak: the learner FINISHED something — a graded answer (lesson
# practice, quiz question, review card), a lesson part (the reveal boundary moved forward) or a whole
# quiz. Each such request settles the streak once; settling is idempotent within a UTC day. Days are
# UTC dates: the app serves learners in any time zone, and one rule keeps every server and test equal.
#
# ``next_streak_step`` is the ONE place that decides how a day counts and how a gap is forgiven;
# ``settle_streak`` (writes) and ``effective_streak_len`` (the read-only snapshot) both use it, so what
# the header shows can never disagree with what the next activity will do.

STREAK_FIRST = "first"          # first ever activity
STREAK_SAME_DAY = "same_day"    # today already counted (or a clock that went backwards)
STREAK_NEXT_DAY = "next_day"    # active yesterday
STREAK_BRIDGED = "bridged"      # missed day(s) covered by rest days / freezes / the repair window
STREAK_BROKEN = "broken"        # the gap can't be bridged: a new streak starts at 1


def _freeze_cap(streak_len: int) -> int:
    return STREAK_FREEZE_CAP_LONG if streak_len >= STREAK_LONG_THRESHOLD_DAYS else STREAK_FREEZE_CAP_DEFAULT


def rest_day_cap(profile: Profile, settings: ProfileSettings | None) -> int:
    """Rest days per ISO week that don't break the streak. Every profile has a settings row whose
    rest_days_per_week defaults to 0, so the young-learner rest day is a floor, not a fallback for a
    missing row (which never happens)."""
    configured = (settings.rest_days_per_week or 0) if settings is not None else 0
    young = profile.age_band == AgeBand.EARLY_PRIMARY.value
    return max(configured, REST_DAYS_PER_WEEK_YOUNG if young else 0)


def _utc_day(moment: datetime) -> date:
    return _aware(moment).astimezone(UTC).date()


def _iso_week(day: date) -> tuple[int, int]:
    iso = day.isocalendar()
    return iso[0], iso[1]


@dataclass(frozen=True)
class StreakStep:
    """What the streak becomes when the learner finishes something at a given moment."""

    outcome: str  # one of the STREAK_* outcomes above
    current: int
    longest: int
    last_active_date: date
    freeze_inventory: int
    freezes_used: int
    rest_days_used: int
    is_perfect: bool
    frozen: bool  # a freeze or the repair window bridged a missed day in this step


def next_streak_step(streak: StreakState, *, now: datetime, rest_cap: int) -> StreakStep:
    """Pure: the streak after an activity at ``now`` (its UTC day), given the stored ``streak`` row,
    which it only reads.

    Bounded, mostly-invisible forgiveness (design gamification_design), applied in this order to the
    missed days of a gap: 1) rest days — ``rest_cap`` per ISO week, each missed day drawing on the
    allowance of its OWN week (a missed Sunday and Monday are one rest day in each of two weeks);
    the stored count is for the week of the last active day, 2) the freeze inventory (cap 2, or 5
    for >=30-day streaks), 3) the 48 h repair window for a single missed day. Nothing is spent on a
    gap that can't be bridged. Never loss-framed; ``is_perfect`` = no freeze or repair needed in
    this streak."""
    today = _utc_day(now)
    last = streak.last_active_date
    current = streak.current_streak_len or 0
    longest = streak.longest_streak or 0
    inventory = streak.freeze_inventory or 0
    freezes_used = streak.freezes_used_in_current_streak or 0
    rest_used = streak.rest_days_used_this_week or 0
    perfect = streak.is_perfect is not False  # unset on a not-yet-flushed row = perfect

    def step(outcome: str, cur: int, **changes: Any) -> StreakStep:
        fields: dict[str, Any] = {
            "last_active_date": today,
            "freeze_inventory": inventory,
            "freezes_used": freezes_used,
            "rest_days_used": rest_used,
            "is_perfect": perfect,
            "frozen": False,
        }
        fields.update(changes)
        return StreakStep(outcome=outcome, current=cur, longest=max(longest, cur), **fields)

    if last is None:
        return step(STREAK_FIRST, 1, freezes_used=0, rest_days_used=0, is_perfect=True)
    if today <= last:
        return step(STREAK_SAME_DAY, current, last_active_date=last)

    missed = (today - last).days - 1
    same_week = _iso_week(today) == _iso_week(last)
    if missed == 0:
        return step(STREAK_NEXT_DAY, current + 1, rest_days_used=rest_used if same_week else 0)

    # Rest days: every missed day is charged to its own ISO week's allowance.
    if same_week:
        use_rest = min(missed, max(0, rest_cap - rest_used))
        rest_this_week = rest_used + use_rest
    else:
        tail = 6 - last.weekday()  # missed days left in the last active day's week
        head = today.weekday()  # missed days in today's week, before today
        whole_weeks = (missed - tail - head) // 7  # weeks missed entirely in between
        rest_this_week = min(head, rest_cap)
        use_rest = (
            min(tail, max(0, rest_cap - rest_used)) + whole_weeks * rest_cap + rest_this_week
        )
    left = missed - use_rest
    use_freeze = min(left, max(0, min(inventory, _freeze_cap(current) - freezes_used)))
    left -= use_freeze
    expires = streak.repair_window_expires_at
    repaired = left == 1 and missed == 1 and expires is not None and _aware(now) <= _aware(expires)
    if left and not repaired:
        return step(STREAK_BROKEN, 1, freezes_used=0, rest_days_used=0, is_perfect=True)
    forgiven = bool(use_freeze) or repaired
    return step(
        STREAK_BRIDGED,
        current + 1,
        freeze_inventory=inventory - use_freeze,
        freezes_used=freezes_used + use_freeze,
        rest_days_used=rest_this_week,
        is_perfect=perfect and not forgiven,
        frozen=forgiven,
    )


def effective_streak_len(streak: StreakState, *, now: datetime, rest_cap: int) -> int:
    """The streak as it stands at ``now``, before the learner does anything more today — read-only.

    The stored length while the last active day is today or yesterday, or while the gap could still
    be bridged (rest days, freezes, repair window) if they came back right now; otherwise 0. (The
    stored length itself is only replaced at the next activity.)"""
    if next_streak_step(streak, now=now, rest_cap=rest_cap).outcome == STREAK_BROKEN:
        return 0
    return streak.current_streak_len or 0


async def streak_info_as_of(
    db: AsyncSession, profile: Profile, streak: StreakState, now: datetime | None = None
) -> StreakInfo:
    """The snapshot's StreakInfo, with the effective length (:func:`effective_streak_len`).
    Writes nothing."""
    settings = await db.get(ProfileSettings, profile.id)
    current = effective_streak_len(
        streak, now=now or datetime.now(UTC), rest_cap=rest_day_cap(profile, settings)
    )
    return StreakInfo(
        current=current,
        longest=streak.longest_streak or 0,
        freeze_inventory=streak.freeze_inventory or 0,
        is_perfect=streak.is_perfect is not False,
    )


async def settle_streak(
    db: AsyncSession, profile: Profile, now: datetime | None = None
) -> StreakInfo:
    """Count an activity at ``now`` toward the daily streak (rules: :func:`next_streak_step`):
    advance it on a new UTC day, silently forgive a bridgeable gap, or start again at 1. Idempotent
    within a UTC day. Quick writes only — call it after any slow work (grading), together with the
    request's other writes, at most once per request."""
    now = _aware(now or datetime.now(UTC))

    streak = await db.scalar(select(StreakState).where(StreakState.profile_id == profile.id))
    if streak is None:
        streak = StreakState(profile_id=profile.id)
        db.add(streak)
        await db.flush()
    settings = await db.scalar(
        select(ProfileSettings).where(ProfileSettings.profile_id == profile.id)
    )
    nxt = next_streak_step(streak, now=now, rest_cap=rest_day_cap(profile, settings))

    streak.current_streak_len = nxt.current
    streak.longest_streak = nxt.longest
    streak.last_active_date = nxt.last_active_date
    streak.freeze_inventory = nxt.freeze_inventory
    streak.freezes_used_in_current_streak = nxt.freezes_used
    streak.rest_days_used_this_week = nxt.rest_days_used
    streak.is_perfect = nxt.is_perfect
    # The repair window runs 48 h from the latest activity (never moved backwards).
    expires = now + timedelta(hours=STREAK_REPAIR_WINDOW_HOURS)
    if streak.repair_window_expires_at is None or expires > _aware(streak.repair_window_expires_at):
        streak.repair_window_expires_at = expires
    profile.last_active_at = now
    await db.flush()

    return StreakInfo(
        current=nxt.current,
        longest=nxt.longest,
        freeze_inventory=nxt.freeze_inventory,
        is_perfect=nxt.is_perfect,
        frozen=nxt.frozen,
    )


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# Daily-goal target XP lookup (used by the snapshot endpoint; kept here next to XP logic).
def daily_goal_target_xp(daily_goal: str) -> int:
    return DAILY_GOAL_XP.get(daily_goal, DAILY_GOAL_XP["regular"])

"""Gamification orchestration — the reward layer that wraps every learning signal (SPEC §7).

Implemented by the **B4 agent**. Keep these signatures (routes depend on them). Orchestrates:
grade (deterministic or LLM via app.llm.grader) → derive FSRS rating → srs_service.review →
mastery recompute → XP (leveling.item_xp + combo) → badge eval → streak settle → persist
Answer/XpEvent rows. Combo math lives in ``leveling.combo_multiplier`` (pure) — reuse it, don't fork.

Design refs: gamification_design (XP/combo/streaks), pedagogy_framework (rating, mastery, feedback)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
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
    SkillMastery,
    StreakState,
    XpEvent,
)
from ..schemas.enums import FsrsRating, NodeState, XpReason
from ..schemas.gamification import (
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


# --------------------------------------------------------------------------- deterministic grading
def _norm_text(value: Any) -> str:
    return str(value).strip().casefold()


def _accepted_variants(item: Item) -> set[str]:
    """Normalized set of an item's documented accepted answer variants (alternate correct forms)."""
    raw = getattr(item, "accepted_variants_json", None) or []
    return {_norm_text(v) for v in raw if v is not None}


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


async def _grade_free_text(
    item: Item, submitted: Any, language: str
) -> tuple[bool, float, str | None, str, str]:
    """Grade short_answer/numeric/explain via the LLM grader (B2). Imported LAZILY so this module
    imports even while B2's grader is mid-write. Falls back to deterministic numeric/text on any
    failure so grading never hard-fails for the learner."""
    try:
        from ..llm import grader as llm_grader  # noqa: PLC0415  (lazy by design)

        out = await llm_grader.grade_free_text(item, submitted, language=language)
        return (
            bool(out.correct),
            float(out.partial_credit),
            out.misconception,
            out.explanation or (item.explanation or ""),
            out.encouragement_focus,
        )
    except Exception:
        # Deterministic safety net: numeric tolerance / casefolded text equality.
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
        card = ItemFsrsCard(
            profile_id=profile.id,
            item_id=item.id,
            state=0,
            fsrs_card_json=srs_service.new_card(now),
            due=now,
        )
        db.add(card)
        await db.flush()
    return card


async def _recompute_mastery(
    db: AsyncSession, profile: Profile, concept_id: int, now: datetime
) -> tuple[SkillMastery, float, float, NodeState]:
    """Recompute SkillMastery for one concept from its cards' FSRS retrievability (SPEC §4 #5).

    Returns (row, before, after, node_state)."""
    retention = profile.desired_retention
    cards = (
        await db.execute(
            select(ItemFsrsCard)
            .join(Item, Item.id == ItemFsrsCard.item_id)
            .where(ItemFsrsCard.profile_id == profile.id, Item.concept_id == concept_id)
        )
    ).scalars().all()

    views: list[mastery.CardView] = []
    mastered_due: list[datetime] = []
    for c in cards:
        state = srs_service.card_state(c.fsrs_card_json)
        r = srs_service.get_retrievability(c.fsrs_card_json, now, desired_retention=retention)
        views.append(mastery.CardView(state=state, retrievability=r))
        if state == 2 and c.due is not None:  # Review-state cards drive decay timing
            mastered_due.append(c.due if c.due.tzinfo else c.due.replace(tzinfo=UTC))

    after = mastery.concept_mastery(views)
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


# --------------------------------------------------------------------------- public orchestration
async def grade_and_reward(
    db: AsyncSession,
    profile: Profile,
    item: Item,
    answer: AnswerIn,
    attempt_id: int | None,
    now: datetime | None = None,
) -> GradeResult:
    """Grade one answer and apply all reward/scheduling side-effects. Returns the public GradeResult
    (reveals the correct answer here, never at delivery)."""
    now = now or datetime.now(UTC)
    # Feedback should match the CONTENT language (a Czech lesson gets Czech feedback), falling back
    # to the learner's UI language, then English.
    language = item.language or profile.primary_language or "en"
    item_type = item.item_type

    # 1) Grade (deterministic for closed-form; LLM for free-text/explain).
    misconception_text: str | None = None
    if item_type in _LLM_GRADED:
        is_correct, partial, misconception_text, explanation, focus = await _grade_free_text(
            item, answer.submitted_value, language
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
        db, profile, item.concept_id, now
    )
    mastery_delta = round(mastery_after - mastery_before, 4)

    # 4) Resolve a misconception row from the matched distractor text (best-effort).
    misconception_info, misconception_id = await _resolve_misconception(
        db, item.concept_id, misconception_text
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
        )
    )
    await db.flush()

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
) -> GradeResult:
    """Advance an item's FSRS card from an EXPLICIT self-rating (1..4) — the rating-only review path.

    Used by POST /review/{item_id} when the learner submits a rating with no answer value. Skips
    correctness grading; ``correct`` is derived from rating>=GOOD (Again/Hard are not 'correct' for
    XP, matching derive_rating's Again=incorrect mapping but honoring the explicit rating for FSRS)."""
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
        db, profile, item.concept_id, now
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
        )
    )
    await db.flush()

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
    db: AsyncSession, concept_id: int, text: str | None
) -> tuple[MisconceptionInfo | None, int | None]:
    """Best-effort map a matched distractor / LLM misconception string to a Misconception row."""
    if not text:
        return None, None
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
    """Finalize a quiz attempt: compute score/accuracy, end-of-session badge eval + streak settle."""
    now = datetime.now(UTC)
    attempt = await db.get(QuizAttempt, attempt_id)
    if attempt is None:
        raise ValueError("attempt not found")

    rows = (
        await db.execute(
            select(Answer, Item)
            .join(Item, Item.id == Answer.item_id)
            .where(Answer.attempt_id == attempt_id)
            .order_by(Answer.id)
        )
    ).all()

    correct = sum(1 for a, _ in rows if a.is_correct)
    total = len(rows)
    accuracy = round(correct / total, 4) if total else 0.0
    score = sum(a.xp_awarded for a, _ in rows)
    xp_awarded = sum(a.xp_awarded for a, _ in rows)

    # Max combo of consecutive first-try-correct within the attempt.
    combo_max = 0
    run = 0
    for a, _ in rows:
        if a.is_correct and not a.used_hint and a.is_first_try:
            run += 1
            combo_max = max(combo_max, run)
        else:
            run = 0

    # Sum the per-answer mastery movement keyed by concept so `before` reflects pre-attempt mastery.
    delta_by_concept: dict[int, float] = {}
    for a, it in rows:
        delta_by_concept[it.concept_id] = delta_by_concept.get(it.concept_id, 0.0) + (
            a.mastery_delta or 0.0
        )

    # Per-concept mastery changes touched by this attempt (before = after - aggregated delta).
    mastery_changes: list[MasteryChange] = []
    for cid in dict.fromkeys(it.concept_id for _, it in rows):
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

    attempt.completed_at = now
    attempt.score = score
    attempt.max_score = attempt.max_score or score
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
def _freeze_cap(streak_len: int) -> int:
    return STREAK_FREEZE_CAP_LONG if streak_len >= STREAK_LONG_THRESHOLD_DAYS else STREAK_FREEZE_CAP_DEFAULT


async def settle_streak(
    db: AsyncSession, profile: Profile, now: datetime | None = None
) -> StreakInfo:
    """Apply freezes / rest-days silently before breaking a streak; advance it on activity.

    Bounded, mostly-invisible forgiveness (design gamification_design): freeze inventory (earned
    through play, cap 2 / 5 for >=30-day streaks), rest_days_per_week, and a 48h repair window.
    Never loss-framed. is_perfect = no freezes ever used."""
    now = now or datetime.now(UTC)
    today: date = now.date()

    streak = await db.scalar(select(StreakState).where(StreakState.profile_id == profile.id))
    if streak is None:
        streak = StreakState(profile_id=profile.id)
        db.add(streak)
        await db.flush()

    settings = await db.scalar(
        select(ProfileSettings).where(ProfileSettings.profile_id == profile.id)
    )
    rest_cap = (
        settings.rest_days_per_week
        if settings is not None
        else (REST_DAYS_PER_WEEK_YOUNG if profile.age_band == "early_primary" else 0)
    )

    # Reset the weekly rest-day budget at the start of a new week BEFORE consuming any for today's
    # return, so a Monday return can't both spend and immediately refund its allowance.
    if today.weekday() == 0:
        streak.rest_days_used_this_week = 0

    last = streak.last_active_date
    frozen = False

    if last is None:
        streak.current_streak_len = 1
        streak.is_perfect = True
        streak.freezes_used_in_current_streak = 0
        streak.rest_days_used_this_week = 0
    elif last == today:
        pass  # already counted today; no change.
    else:
        gap_days = (today - last).days
        if gap_days == 1:
            streak.current_streak_len += 1
        else:
            # One or more missed days — try silent forgiveness before breaking.
            missed = gap_days - 1
            covered = 0
            # 1) Weekly rest-day allowance.
            while covered < missed and streak.rest_days_used_this_week < rest_cap:
                streak.rest_days_used_this_week += 1
                covered += 1
            # 2) Freeze inventory.
            cap = _freeze_cap(streak.current_streak_len)
            while covered < missed and streak.freeze_inventory > 0 and streak.freezes_used_in_current_streak < cap:
                streak.freeze_inventory -= 1
                streak.freezes_used_in_current_streak += 1
                streak.is_perfect = False
                frozen = True
                covered += 1
            # 3) 48h repair window for a single fully-missed day.
            within_repair = (
                streak.repair_window_expires_at is not None
                and now <= _aware(streak.repair_window_expires_at)
            )
            if covered >= missed or (missed <= 1 and within_repair):
                streak.current_streak_len += 1
                if covered < missed and within_repair:
                    # The 48h repair window bridged a real missed day → no longer a perfect streak.
                    frozen = True
                    streak.is_perfect = False
            else:
                streak.current_streak_len = 1
                streak.is_perfect = True
                streak.freezes_used_in_current_streak = 0
                streak.rest_days_used_this_week = 0

    streak.last_active_date = today
    streak.longest_streak = max(streak.longest_streak, streak.current_streak_len)
    streak.repair_window_expires_at = now + timedelta(hours=STREAK_REPAIR_WINDOW_HOURS)
    profile.last_active_at = now
    await db.flush()

    return StreakInfo(
        current=streak.current_streak_len,
        longest=streak.longest_streak,
        freeze_inventory=streak.freeze_inventory,
        is_perfect=streak.is_perfect,
        frozen=frozen,
    )


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# Daily-goal target XP lookup (used by the snapshot endpoint; kept here next to XP logic).
def daily_goal_target_xp(daily_goal: str) -> int:
    return DAILY_GOAL_XP.get(daily_goal, DAILY_GOAL_XP["regular"])

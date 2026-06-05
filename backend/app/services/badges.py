"""Mastery-anchored badge evaluation (SPEC gamification). Implemented by the **B4 agent**.

Badge definitions are seeded from ``app/data/badges.yaml``; each ``criterion_key`` maps to an
evaluator run after a learning event against xp_events + skill_mastery + answers. Keep this signature.

Every badge wraps a genuine LEARNING signal (design gamification_design) — never raw activity
counters. Locked badges expose progress via ProfileBadge.progress_numerator/denominator; tiered
badges (tree_grower) advance ``tier`` as thresholds are crossed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.constants import MASTERY_MASTERED_THRESHOLD
from ..models import (
    Answer,
    BadgeDefinition,
    Concept,
    ConceptEdge,
    Item,
    Profile,
    ProfileBadge,
    SkillMastery,
)
from ..schemas.gamification import BadgeAward

# Each evaluator returns (numerator, denominator). unlocked iff numerator >= denominator.
# Tiered badges return progress toward the CURRENT tier and bump ProfileBadge.tier in the upsert.


def _i18n(blob: dict | None, language: str) -> str:
    if not isinstance(blob, dict):
        return ""
    return blob.get(language) or blob.get("en") or next(iter(blob.values()), "")


# --------------------------------------------------------------------------- evaluators
async def _mastered_concept_ids(db: AsyncSession, profile_id: int) -> list[int]:
    return list(
        (
            await db.execute(
                select(SkillMastery.concept_id).where(
                    SkillMastery.profile_id == profile_id,
                    SkillMastery.mastery >= MASTERY_MASTERED_THRESHOLD,
                )
            )
        ).scalars().all()
    )


async def _ev_first_light(db, profile, event, params) -> tuple[int, int]:
    n = await db.scalar(
        select(func.count())
        .select_from(SkillMastery)
        .where(
            SkillMastery.profile_id == profile.id,
            SkillMastery.mastery >= MASTERY_MASTERED_THRESHOLD,
        )
    )
    return (1 if (n or 0) >= 1 else 0), 1


async def _ev_root_system(db, profile, event, params) -> tuple[int, int]:
    """Master every prerequisite of some concept (and that concept too)."""
    mastered = set(await _mastered_concept_ids(db, profile.id))
    if not mastered:
        return 0, 1
    edges = (
        await db.execute(
            select(ConceptEdge.from_concept_id, ConceptEdge.to_concept_id).where(
                ConceptEdge.edge_type == "prerequisite"
            )
        )
    ).all()
    prereqs: dict[int, set[int]] = {}
    for frm, to in edges:
        prereqs.setdefault(to, set()).add(frm)
    for concept_id, reqs in prereqs.items():
        if concept_id in mastered and reqs and reqs <= mastered:
            return 1, 1
    return 0, 1


async def _ev_deep_diver(db, profile, event, params) -> tuple[int, int]:
    threshold = float(params.get("mastery", 0.9))
    n = await db.scalar(
        select(func.count())
        .select_from(SkillMastery)
        .where(SkillMastery.profile_id == profile.id, SkillMastery.mastery >= threshold)
    )
    return (1 if (n or 0) >= 1 else 0), 1


async def _ev_comeback(db, profile, event, params) -> tuple[int, int]:
    """Master a concept the learner had previously answered incorrectly."""
    mastered = await _mastered_concept_ids(db, profile.id)
    if not mastered:
        return 0, 1
    failed = (
        await db.execute(
            select(Item.concept_id)
            .join(Answer, Answer.item_id == Item.id)
            .where(Answer.profile_id == profile.id, Answer.is_correct.is_(False))
            .distinct()
        )
    ).scalars().all()
    return (1 if set(mastered) & set(failed) else 0), 1


async def _ev_spaced_master(db, profile, event, params) -> tuple[int, int]:
    """A correct answer on an item last answered >= gap_days ago — proof it stuck."""
    gap = int(params.get("gap_days", 7))
    if not (event.get("type") == "answer" and event.get("is_correct")):
        return await _badge_progress_snapshot(db, profile, "spaced_master")
    now: datetime = event.get("now") or datetime.now(UTC)
    item_id = event.get("item_id")
    prev = (
        await db.execute(
            select(Answer.created_at)
            .where(Answer.profile_id == profile.id, Answer.item_id == item_id)
            .order_by(Answer.id.desc())
            .limit(2)
        )
    ).scalars().all()
    # prev[0] is the answer just written by grade_and_reward; prev[1] is the prior one.
    if len(prev) >= 2 and prev[1] is not None:
        last = prev[1] if prev[1].tzinfo else prev[1].replace(tzinfo=UTC)
        if now - last >= timedelta(days=gap):
            return 1, 1
    return 0, 1


async def _ev_sharpshooter(db, profile, event, params) -> tuple[int, int]:
    """N first-try-correct (no-hint) answers within one attempt/session."""
    need = int(params.get("count", 10))
    attempt_id = event.get("attempt_id")
    if attempt_id is None:
        return 0, need
    n = await db.scalar(
        select(func.count())
        .select_from(Answer)
        .where(
            Answer.attempt_id == attempt_id,
            Answer.is_correct.is_(True),
            Answer.used_hint.is_(False),
        )
    )
    n = int(n or 0)
    return min(n, need), need


async def _ev_honest_explorer(db, profile, event, params) -> tuple[int, int]:
    """Used a hint, then answered correctly — rewards metacognition, not guessing."""
    need = int(params.get("count", 5))
    n = await db.scalar(
        select(func.count())
        .select_from(Answer)
        .where(
            Answer.profile_id == profile.id,
            Answer.is_correct.is_(True),
            Answer.used_hint.is_(True),
        )
    )
    n = int(n or 0)
    return min(n, need), need


async def _ev_polyglot(db, profile, event, params) -> tuple[int, int]:
    """Learn across 2+ languages (distinct item languages the learner has answered)."""
    need = int(params.get("languages", 2))
    langs = (
        await db.execute(
            select(Item.language)
            .join(Answer, Answer.item_id == Item.id)
            .where(Answer.profile_id == profile.id)
            .distinct()
        )
    ).scalars().all()
    n = len({lang for lang in langs if lang})
    return min(n, need), need


async def _ev_cross_pollinator(db, profile, event, params) -> tuple[int, int]:
    """Master concepts across 2+ distinct subject trees."""
    need = int(params.get("subjects", 2))
    subjects = (
        await db.execute(
            select(Concept.subject)
            .join(SkillMastery, SkillMastery.concept_id == Concept.id)
            .where(
                SkillMastery.profile_id == profile.id,
                SkillMastery.mastery >= MASTERY_MASTERED_THRESHOLD,
            )
            .distinct()
        )
    ).scalars().all()
    n = len({s for s in subjects if s})
    return min(n, need), need


async def _ev_curiosity(db, profile, event, params) -> tuple[int, int]:
    """Ask follow-up/"why" questions. No request log is owned by B4, so this tracks the running
    progress count carried on the profile_badge row (incremented by curiosity events when wired)."""
    need = int(params.get("count", 5))
    num, _ = await _badge_progress_snapshot(db, profile, "curiosity", denominator=need)
    if event.get("type") == "follow_up_question":
        num = min(need, num + 1)
    return num, need


async def _ev_self_beater(db, profile, event, params) -> tuple[int, int]:
    """Beat your own previous accuracy on a retest of the same quiz."""
    if event.get("type") != "attempt_complete":
        return await _badge_progress_snapshot(db, profile, "self_beater")
    from ..models import QuizAttempt  # local import keeps the module header tidy

    attempt_id = event.get("attempt_id")
    current = await db.get(QuizAttempt, attempt_id) if attempt_id is not None else None
    if current is None or current.accuracy is None:
        return await _badge_progress_snapshot(db, profile, "self_beater")
    best_prior = await db.scalar(
        select(func.max(QuizAttempt.accuracy)).where(
            QuizAttempt.profile_id == profile.id,
            QuizAttempt.quiz_id == current.quiz_id,
            QuizAttempt.id != current.id,
            QuizAttempt.completed_at.is_not(None),
        )
    )
    if best_prior is not None and current.accuracy > best_prior:
        return 1, 1
    return 0, 1


async def _ev_teacher(db, profile, event, params) -> tuple[int, int]:
    """A correct LLM-graded teach-back (explain / short_answer) answer."""
    n = await db.scalar(
        select(func.count())
        .select_from(Answer)
        .join(Item, Item.id == Answer.item_id)
        .where(
            Answer.profile_id == profile.id,
            Answer.is_correct.is_(True),
            Item.item_type.in_(("explain", "short_answer")),
        )
    )
    return (1 if (n or 0) >= 1 else 0), 1


async def _ev_resilient(db, profile, event, params) -> tuple[int, int]:
    """Return and keep learning after a streak break (current streak rebuilt from 1)."""
    from ..models import StreakState  # local import keeps the top tidy

    streak = await db.scalar(select(StreakState).where(StreakState.profile_id == profile.id))
    if streak is None:
        return 0, 1
    # Broke before (longest > current) yet is active again.
    if streak.longest_streak > streak.current_streak_len >= 1:
        return 1, 1
    return 0, 1


async def _ev_marathon_of_mastery(db, profile, event, params) -> tuple[int, int]:
    need = int(params.get("count", 50))
    n = await db.scalar(
        select(func.count())
        .select_from(SkillMastery)
        .where(
            SkillMastery.profile_id == profile.id,
            SkillMastery.mastery >= MASTERY_MASTERED_THRESHOLD,
        )
    )
    n = int(n or 0)
    return min(n, need), need


async def _ev_tree_grower(db, profile, event, params) -> tuple[int, int, int]:
    """TIERED: fraction of a subject branch mastered, against tiers (e.g. [0.25,0.5,1.0]).

    Returns (numerator, denominator, tier_reached). Picks the learner's strongest subject branch."""
    tiers = list(params.get("tiers", [0.25, 0.5, 1.0]))
    rows = (
        await db.execute(
            select(Concept.subject, SkillMastery.mastery)
            .join(SkillMastery, SkillMastery.concept_id == Concept.id)
            .where(SkillMastery.profile_id == profile.id)
        )
    ).all()
    by_subject: dict[str, list[float]] = {}
    for subject, m in rows:
        by_subject.setdefault(subject, []).append(m or 0.0)
    best_fraction = 0.0
    for masteries in by_subject.values():
        if not masteries:
            continue
        mastered = sum(1 for m in masteries if m >= MASTERY_MASTERED_THRESHOLD)
        best_fraction = max(best_fraction, mastered / len(masteries))
    tier_reached = sum(1 for t in tiers if best_fraction >= t)
    # Progress shown toward the next unmet tier (or fully met).
    if tier_reached >= len(tiers):
        return 100, 100, len(tiers)
    next_tier = tiers[tier_reached]
    return round(best_fraction * 100), round(next_tier * 100), tier_reached


_EVALUATORS = {
    "first_light": _ev_first_light,
    "root_system": _ev_root_system,
    "deep_diver": _ev_deep_diver,
    "comeback": _ev_comeback,
    "spaced_master": _ev_spaced_master,
    "sharpshooter": _ev_sharpshooter,
    "honest_explorer": _ev_honest_explorer,
    "polyglot": _ev_polyglot,
    "cross_pollinator": _ev_cross_pollinator,
    "curiosity": _ev_curiosity,
    "self_beater": _ev_self_beater,
    "teacher": _ev_teacher,
    "resilient": _ev_resilient,
    "marathon_of_mastery": _ev_marathon_of_mastery,
}


async def _badge_progress_snapshot(
    db: AsyncSession, profile: Profile, code: str, *, denominator: int = 1
) -> tuple[int, int]:
    """Read the current persisted progress for a badge (so non-triggering events don't reset it)."""
    row = (
        await db.execute(
            select(ProfileBadge)
            .join(BadgeDefinition, BadgeDefinition.id == ProfileBadge.badge_id)
            .where(ProfileBadge.profile_id == profile.id, BadgeDefinition.code == code)
        )
    ).scalar_one_or_none()
    if row is None:
        return 0, denominator
    return row.progress_numerator, row.progress_denominator or denominator


# --------------------------------------------------------------------------- public API
async def evaluate_badges(
    db: AsyncSession, profile: Profile, event: dict[str, Any]
) -> list[BadgeAward]:
    """Evaluate all badge criteria against the profile's state after ``event``; persist newly
    unlocked badges + progress, and return the ones newly unlocked this call."""
    language = event.get("language") or profile.primary_language or "en"
    defs = (await db.execute(select(BadgeDefinition))).scalars().all()
    if not defs:
        return []

    existing = {
        pb.badge_id: pb
        for pb in (
            await db.execute(
                select(ProfileBadge).where(ProfileBadge.profile_id == profile.id)
            )
        ).scalars().all()
    }

    newly: list[BadgeAward] = []
    for bdef in defs:
        evaluator = _EVALUATORS.get(bdef.criterion_key)
        params = bdef.criterion_params_json or {}
        tier_reached = 0  # for tiered badges: how many tiers are ACTUALLY achieved (0..N)
        try:
            if bdef.tiered and bdef.criterion_key == "tree_grower":
                num, den, tier_reached = await _ev_tree_grower(db, profile, event, params)
            elif evaluator is not None:
                num, den = await evaluator(db, profile, event, params)
            else:
                continue
        except Exception:
            # A flaky evaluator must never break grading/finalize for the learner.
            continue

        pb = existing.get(bdef.id)
        if pb is None:
            pb = ProfileBadge(
                profile_id=profile.id,
                badge_id=bdef.id,
                # Locked tiered badge starts at tier 0 (no tier earned yet); non-tiered uses tier 1.
                tier=(tier_reached if bdef.tiered else 1),
                progress_numerator=num,
                progress_denominator=max(1, den),
            )
            db.add(pb)
            existing[bdef.id] = pb
        else:
            pb.progress_numerator = max(pb.progress_numerator, num)
            pb.progress_denominator = max(1, den)

        now = event.get("now") or datetime.now(UTC)
        if bdef.tiered:
            # Unlocks once the first tier is reached; pb.tier tracks the HIGHEST tier actually
            # achieved (never an un-earned tier). Award on first unlock and on each genuine advance.
            prev_tier = pb.tier if pb.unlocked_at else 0
            if tier_reached >= 1 and tier_reached > prev_tier:
                pb.unlocked_at = pb.unlocked_at or now
                pb.tier = tier_reached
                newly.append(
                    BadgeAward(
                        code=bdef.code,
                        title=_i18n(bdef.title_i18n_json, language),
                        tier=tier_reached,
                    )
                )
        elif num >= den and pb.unlocked_at is None:
            pb.unlocked_at = now
            newly.append(
                BadgeAward(
                    code=bdef.code,
                    title=_i18n(bdef.title_i18n_json, language),
                    tier=1,
                )
            )

    await db.flush()
    return newly

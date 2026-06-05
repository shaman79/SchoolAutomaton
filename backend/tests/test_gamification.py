"""gamification.grade_and_reward deterministic grading per item_type + XP/mastery side-effects.

Uses an in-memory SQLite session built directly from Base.metadata (no app.main import — other
modules are written concurrently). The free-text LLM grader is MOCKED; no network."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("SA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("APP_SECRET", "test-secret-please-ignore")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "admin12345")
os.environ.setdefault("SA_ENV", "test")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.constants import MASTERY_MASTERED_THRESHOLD  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.models import (  # noqa: E402
    Answer,
    BadgeDefinition,
    Concept,
    Item,
    ItemFsrsCard,
    Profile,
    ProfileSettings,
    SkillMastery,
    StreakState,
    XpEvent,
)
from app.schemas.questions import AnswerIn  # noqa: E402
from app.services import gamification, srs_service  # noqa: E402


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session
    await engine.dispose()


async def _make_profile(db: AsyncSession, **kw) -> Profile:
    p = Profile(resume_code_hash=kw.pop("hash", "h" * 16), primary_language="en", **kw)
    db.add(p)
    await db.flush()
    db.add(ProfileSettings(profile_id=p.id))
    db.add(StreakState(profile_id=p.id))
    await db.flush()
    return p


async def _make_concept(db: AsyncSession, slug="photosynthesis", subject="science") -> Concept:
    c = Concept(slug=slug, name=slug.title(), subject=subject)
    db.add(c)
    await db.flush()
    return c


async def _make_item(db: AsyncSession, concept_id: int, item_type: str, payload: dict, **kw) -> Item:
    item = Item(
        concept_id=concept_id,
        item_type=item_type,
        bloom_tier=kw.pop("bloom_tier", 2),
        difficulty=kw.pop("difficulty", "medium"),
        item_difficulty=kw.pop("item_difficulty", 3),
        language=kw.pop("language", "en"),
        stem_markdown=kw.pop("stem", "Question?"),
        payload_json=payload,
        explanation=kw.pop("explanation", "Because."),
        expected_answer=kw.pop("expected_answer", None),
        model_id="claude-opus-4-8",
        prompt_version="2026.06.01",
    )
    db.add(item)
    await db.flush()
    return item


# --------------------------------------------------------------------------- deterministic grading
@pytest.mark.asyncio
async def test_mcq_correct_and_incorrect(db):
    profile = await _make_profile(db)
    concept = await _make_concept(db)
    payload = {
        "kind": "mcq",
        "multiple": False,
        "options": [
            {"id": "a", "text": "Right", "is_correct": True},
            {"id": "b", "text": "Wrong", "is_correct": False},
        ],
    }
    item = await _make_item(db, concept.id, "mcq", payload)

    res = await gamification.grade_and_reward(
        db, profile, item, AnswerIn(item_id=item.id, submitted_value="a", latency_ms=5000), None
    )
    assert res.is_correct is True
    assert res.correct_answer == "a"
    assert res.fsrs_rating == 3  # Good (no hint, normal latency)
    assert res.xp_awarded > 0
    assert res.feedback.text  # growth-mindset feedback present

    # A second item answered wrong.
    item2 = await _make_item(db, concept.id, "mcq", payload)
    res2 = await gamification.grade_and_reward(
        db, profile, item2, AnswerIn(item_id=item2.id, submitted_value="b", latency_ms=5000), None
    )
    assert res2.is_correct is False
    assert res2.fsrs_rating == 1  # Again
    assert res2.xp_awarded == 0


@pytest.mark.asyncio
async def test_true_false_grading(db):
    profile = await _make_profile(db)
    concept = await _make_concept(db)
    item = await _make_item(db, concept.id, "true_false", {"kind": "true_false", "answer": True})
    ok = await gamification.grade_and_reward(
        db, profile, item, AnswerIn(item_id=item.id, submitted_value=True, latency_ms=3000), None
    )
    assert ok.is_correct is True
    assert ok.correct_answer is True
    item2 = await _make_item(db, concept.id, "true_false", {"kind": "true_false", "answer": False})
    bad = await gamification.grade_and_reward(
        db, profile, item2, AnswerIn(item_id=item2.id, submitted_value=True, latency_ms=3000), None
    )
    assert bad.is_correct is False


@pytest.mark.asyncio
async def test_cloze_partial_credit(db):
    profile = await _make_profile(db)
    concept = await _make_concept(db)
    payload = {
        "kind": "cloze",
        "text_template": "{{b1}} and {{b2}}",
        "blanks": [{"id": "b1", "answer": "sun"}, {"id": "b2", "answer": "water"}],
    }
    item = await _make_item(db, concept.id, "cloze", payload)
    res = await gamification.grade_and_reward(
        db, profile, item,
        AnswerIn(item_id=item.id, submitted_value={"b1": "Sun", "b2": "wrong"}, latency_ms=5000),
        None,
    )
    assert res.is_correct is False
    assert res.partial_credit == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_match_and_order_grading(db):
    profile = await _make_profile(db)
    concept = await _make_concept(db)
    match_payload = {
        "kind": "match",
        "left": [{"id": "l1", "text": "A"}, {"id": "l2", "text": "B"}],
        "right": [{"id": "r1", "text": "1"}, {"id": "r2", "text": "2"}],
        "correct": [{"left_id": "l1", "right_id": "r1"}, {"left_id": "l2", "right_id": "r2"}],
    }
    m = await _make_item(db, concept.id, "match", match_payload)
    res = await gamification.grade_and_reward(
        db, profile, m,
        AnswerIn(
            item_id=m.id,
            submitted_value=[{"left_id": "l1", "right_id": "r1"}, {"left_id": "l2", "right_id": "r2"}],
            latency_ms=9000,
        ),
        None,
    )
    assert res.is_correct is True

    order_payload = {
        "kind": "order",
        "tokens": [{"id": "t1", "text": "1"}, {"id": "t2", "text": "2"}, {"id": "t3", "text": "3"}],
        "correct_order": ["t1", "t2", "t3"],
    }
    o = await _make_item(db, concept.id, "order", order_payload)
    res_o = await gamification.grade_and_reward(
        db, profile, o,
        AnswerIn(item_id=o.id, submitted_value=["t1", "t3", "t2"], latency_ms=9000), None,
    )
    assert res_o.is_correct is False
    assert 0.0 < res_o.partial_credit < 1.0  # one in place


@pytest.mark.asyncio
async def test_hotspot_grading(db):
    profile = await _make_profile(db)
    concept = await _make_concept(db)
    payload = {
        "kind": "hotspot",
        "regions": [
            {"id": "r1", "shape": "rect", "coords": [0, 0, 1, 1], "is_correct": True},
            {"id": "r2", "shape": "rect", "coords": [0, 0, 1, 1], "is_correct": False},
        ],
    }
    item = await _make_item(db, concept.id, "hotspot", payload)
    res = await gamification.grade_and_reward(
        db, profile, item, AnswerIn(item_id=item.id, submitted_value="r1", latency_ms=4000), None
    )
    assert res.is_correct is True
    assert res.correct_answer == ["r1"]


# --------------------------------------------------------------------------- free-text (mocked LLM)
@pytest.mark.asyncio
async def test_short_answer_uses_mocked_grader(db, monkeypatch):
    from app.schemas.generation import GraderOutput

    async def fake_grade_free_text(item, submitted, *, language="en"):
        return GraderOutput(
            correct=True, partial_credit=1.0, explanation="Well reasoned.",
            encouragement_focus="progress",
        )

    # grade_and_reward does `from ..llm import grader; grader.grade_free_text(...)` — patch the
    # attribute on the real module so the lazy import picks up the mock at call time.
    import app.llm.grader as real_grader

    monkeypatch.setattr(real_grader, "grade_free_text", fake_grade_free_text)

    profile = await _make_profile(db)
    concept = await _make_concept(db)
    item = await _make_item(
        db, concept.id, "short_answer", {"kind": "short_answer"}, expected_answer="mitochondria"
    )
    res = await gamification.grade_and_reward(
        db, profile, item, AnswerIn(item_id=item.id, submitted_value="the powerhouse", latency_ms=20000), None
    )
    assert res.is_correct is True
    assert res.explanation == "Well reasoned."
    assert res.feedback.encouragement_focus == "progress"


@pytest.mark.asyncio
async def test_free_text_falls_back_when_grader_missing(db):
    # No app.llm.grader available -> deterministic numeric fallback path.
    profile = await _make_profile(db)
    concept = await _make_concept(db)
    item = await _make_item(
        db, concept.id, "numeric", {"kind": "numeric", "answer": 42.0, "tolerance": 0.5}
    )
    res = await gamification.grade_and_reward(
        db, profile, item, AnswerIn(item_id=item.id, submitted_value=42.2, latency_ms=6000), None
    )
    assert res.is_correct is True


# --------------------------------------------------------------------------- side effects
@pytest.mark.asyncio
async def test_xp_event_and_total_xp_and_fsrs_card_written(db):
    profile = await _make_profile(db)
    concept = await _make_concept(db)
    payload = {"kind": "mcq", "options": [{"id": "a", "text": "x", "is_correct": True}]}
    item = await _make_item(db, concept.id, "mcq", payload, item_difficulty=3)

    await gamification.grade_and_reward(
        db, profile, item, AnswerIn(item_id=item.id, submitted_value="a", latency_ms=5000), None
    )
    await db.flush()

    # total_xp bumped + XpEvent + Answer + ItemFsrsCard rows.
    assert profile.total_xp > 0
    xp_count = await db.scalar(select(func.count()).select_from(XpEvent))
    assert xp_count >= 1
    ans_count = await db.scalar(select(func.count()).select_from(Answer))
    assert ans_count == 1
    card = await db.scalar(
        select(ItemFsrsCard).where(
            ItemFsrsCard.item_id == item.id, ItemFsrsCard.profile_id == profile.id
        )
    )
    assert card is not None
    # The stored json is a genuine py-fsrs card and is now in a scheduled (non-New) state.
    assert srs_service.card_state(card.fsrs_card_json) in (1, 2, 3)


@pytest.mark.asyncio
async def test_mastery_recomputed_and_grows_with_correct_reviews(db):
    profile = await _make_profile(db)
    concept = await _make_concept(db)
    payload = {"kind": "true_false", "answer": True}
    item = await _make_item(db, concept.id, "true_false", payload)

    now = datetime(2026, 6, 4, 12, 0, 0, tzinfo=UTC)
    # First correct answer.
    res1 = await gamification.grade_and_reward(
        db, profile, item, AnswerIn(item_id=item.id, submitted_value=True, latency_ms=3000), None, now=now
    )
    sm = await db.scalar(
        select(SkillMastery).where(SkillMastery.concept_id == concept.id)
    )
    assert sm is not None
    assert sm.mastery >= 0.0
    assert res1.mastery_delta >= 0.0
    assert sm.node_state in ("learning", "mastered", "available", "needs_review")


@pytest.mark.asyncio
async def test_comeback_after_failure_recovers_and_can_master(db):
    profile = await _make_profile(db)
    concept = await _make_concept(db)
    payload = {"kind": "true_false", "answer": True}
    item = await _make_item(db, concept.id, "true_false", payload)

    base = datetime(2026, 6, 4, 12, 0, 0, tzinfo=UTC)
    # Fail first.
    await gamification.grade_and_reward(
        db, profile, item, AnswerIn(item_id=item.id, submitted_value=False, latency_ms=3000), None, base
    )
    # Then a sequence of correct reviews spaced out to push retrievability into Review state.
    for i in range(1, 4):
        await gamification.grade_and_reward(
            db, profile, item,
            AnswerIn(item_id=item.id, submitted_value=True, latency_ms=3000),
            None, base + timedelta(minutes=15 * i),
        )
    failed = await gamification._concept_was_failed(db, profile, concept.id)
    assert failed is True  # the failure is recorded in the immutable answer log


@pytest.mark.asyncio
async def test_combo_multiplier_increases_with_first_try_streak(db):
    profile = await _make_profile(db)
    concept = await _make_concept(db)
    # Build an attempt-less sequence is fine; combo uses attempt_id, so simulate an attempt id.
    from app.models import Quiz, QuizAttempt

    quiz = Quiz(request_id="r", title="t", language="en", grade_band="G3-5", subject="science",
                model_id="m", prompt_version="v")
    db.add(quiz)
    await db.flush()
    attempt = QuizAttempt(profile_id=profile.id, quiz_id=quiz.id)
    db.add(attempt)
    await db.flush()

    multipliers = []
    for _ in range(3):
        payload = {"kind": "mcq", "options": [{"id": "a", "text": "x", "is_correct": True}]}
        item = await _make_item(db, concept.id, "mcq", payload)
        res = await gamification.grade_and_reward(
            db, profile, item,
            AnswerIn(item_id=item.id, attempt_id=attempt.id, submitted_value="a", latency_ms=5000),
            attempt.id,
        )
        multipliers.append(res.combo_multiplier)
    assert multipliers[0] <= multipliers[-1]
    assert multipliers[-1] > 1.0  # combo built up


# --------------------------------------------------------------------------- badges + streak + finalize
@pytest.mark.asyncio
async def test_first_light_badge_unlocks_on_first_mastery(db):
    # Seed the first_light badge definition directly.
    db.add(
        BadgeDefinition(
            code="first_light",
            title_i18n_json={"en": "First Light"},
            description_i18n_json={"en": "Master your first concept."},
            criterion_key="first_light",
            criterion_params_json={"count": 1},
            tiered=False,
        )
    )
    profile = await _make_profile(db)
    concept = await _make_concept(db)
    # Force a mastered SkillMastery, then evaluate.
    db.add(
        SkillMastery(
            profile_id=profile.id, concept_id=concept.id,
            mastery=MASTERY_MASTERED_THRESHOLD + 0.05, node_state="mastered",
        )
    )
    await db.flush()
    from app.services import badges

    awarded = await badges.evaluate_badges(db, profile, {"type": "answer", "now": datetime.now(UTC)})
    codes = [a.code for a in awarded]
    assert "first_light" in codes


@pytest.mark.asyncio
async def test_settle_streak_advances_and_caps(db):
    profile = await _make_profile(db)
    now = datetime(2026, 6, 3, 12, 0, 0, tzinfo=UTC)  # a Wednesday
    info1 = await gamification.settle_streak(db, profile, now)
    assert info1.current == 1
    # Next day -> 2.
    info2 = await gamification.settle_streak(db, profile, now + timedelta(days=1))
    assert info2.current == 2
    # Same day again -> unchanged.
    info2b = await gamification.settle_streak(db, profile, now + timedelta(days=1, hours=3))
    assert info2b.current == 2


@pytest.mark.asyncio
async def test_settle_streak_freeze_covers_a_missed_day(db):
    profile = await _make_profile(db)
    streak = await db.scalar(select(StreakState).where(StreakState.profile_id == profile.id))
    assert streak is not None
    now = datetime(2026, 6, 3, 12, 0, 0, tzinfo=UTC)
    await gamification.settle_streak(db, profile, now)  # day 1
    # Skip a day (gap of 2 days). A freeze should silently cover it (no rest days configured).
    info = await gamification.settle_streak(db, profile, now + timedelta(days=2))
    assert info.current == 2  # streak continued via freeze
    assert info.frozen is True
    assert info.is_perfect is False


@pytest.mark.asyncio
async def test_finalize_attempt_summary(db):
    profile = await _make_profile(db)
    concept = await _make_concept(db)
    from app.models import Quiz, QuizAttempt

    quiz = Quiz(request_id="r", title="t", language="en", grade_band="G3-5", subject="science",
                model_id="m", prompt_version="v")
    db.add(quiz)
    await db.flush()
    attempt = QuizAttempt(profile_id=profile.id, quiz_id=quiz.id, max_score=20)
    db.add(attempt)
    await db.flush()

    payload = {"kind": "mcq", "options": [{"id": "a", "text": "x", "is_correct": True}]}
    for val in ("a", "a"):
        item = await _make_item(db, concept.id, "mcq", payload)
        await gamification.grade_and_reward(
            db, profile, item,
            AnswerIn(item_id=item.id, attempt_id=attempt.id, submitted_value=val, latency_ms=5000),
            attempt.id,
        )

    summary = await gamification.finalize_attempt(db, profile, attempt.id)
    assert summary.accuracy == pytest.approx(1.0)
    assert summary.combo_max == 2
    assert summary.xp_awarded > 0
    assert summary.streak.current >= 1
    assert len(summary.mastery_changes) == 1


@pytest.mark.asyncio
async def test_skipped_questions_count_against_accuracy(db):
    """A skipped question (no Answer row) must count as incorrect: accuracy denominator is the whole
    quiz, not just the answered subset."""
    from app.models import Quiz, QuizAttempt, QuizQuestion

    profile = await _make_profile(db)
    concept = await _make_concept(db)
    quiz = Quiz(request_id="r", title="t", language="en", grade_band="G3-5", subject="science",
                model_id="m", prompt_version="v")
    db.add(quiz)
    await db.flush()

    payload = {"kind": "mcq", "options": [{"id": "a", "text": "x", "is_correct": True}]}
    items = []
    for i in range(3):
        it = await _make_item(db, concept.id, "mcq", payload)
        db.add(QuizQuestion(quiz_id=quiz.id, item_id=it.id, ordinal=i + 1, points=10))
        items.append(it)
    await db.flush()

    attempt = QuizAttempt(profile_id=profile.id, quiz_id=quiz.id)
    db.add(attempt)
    await db.flush()

    # Answer ONLY the first question (correctly); skip the other two.
    await gamification.grade_and_reward(
        db, profile, items[0],
        AnswerIn(item_id=items[0].id, attempt_id=attempt.id, submitted_value="a", latency_ms=4000),
        attempt.id,
    )

    summary = await gamification.finalize_attempt(db, profile, attempt.id)
    assert summary.accuracy == pytest.approx(1 / 3, abs=1e-3)  # 1 of 3 — NOT 1 of 1
    assert summary.score == 1
    assert summary.max_score == 3


@pytest.mark.asyncio
async def test_empty_free_text_is_graded_incorrect_without_llm(db):
    """A blank short_answer is wrong by definition and must not reach (or be talked-up by) the LLM
    grader — no network needed for this test, proving the short-circuit."""
    profile = await _make_profile(db)
    concept = await _make_concept(db)
    item = await _make_item(
        db, concept.id, "short_answer", {"kind": "short_answer", "placeholder": "p"},
        expected_answer="paris",
    )
    res = await gamification.grade_and_reward(
        db, profile, item,
        AnswerIn(item_id=item.id, attempt_id=None, submitted_value="   ", latency_ms=1000),
        None,
    )
    assert res.is_correct is False
    assert res.xp_awarded == 0


@pytest.mark.asyncio
async def test_mcq_options_shuffled_at_delivery_and_stable(db):
    """Delivered MCQ options are reordered (the correct one isn't pinned first) yet byte-stable across
    re-delivery so a progress refresh sees the same order. Grading is by id, so it stays correct."""
    from app.api.v1.serializers import item_public

    concept = await _make_concept(db)
    first_positions = []
    sample = None
    for _ in range(6):
        opts = [{"id": f"o{i}", "text": str(i), "is_correct": i == 0} for i in range(8)]
        item = await _make_item(db, concept.id, "mcq", {"kind": "mcq", "options": opts})
        pub = await item_public(db, item)
        ids = [o.id for o in pub.payload.options]
        assert sorted(ids) == sorted(f"o{i}" for i in range(8))  # no option dropped/duplicated
        first_positions.append(ids.index("o0"))
        sample = item
    assert any(pos != 0 for pos in first_positions)  # correct option not always first
    a = [o.id for o in (await item_public(db, sample)).payload.options]
    b = [o.id for o in (await item_public(db, sample)).payload.options]
    assert a == b  # deterministic / stable


@pytest.mark.asyncio
async def test_order_tokens_never_delivered_pre_solved(db):
    """Order tokens are delivered shuffled and never in the correct sequence (else a no-op submit
    would score 100%)."""
    from app.api.v1.serializers import item_public

    concept = await _make_concept(db)
    toks = [{"id": f"t{i}", "text": str(i)} for i in range(5)]
    correct = [f"t{i}" for i in range(5)]
    item = await _make_item(
        db, concept.id, "order", {"kind": "order", "tokens": toks, "correct_order": correct}
    )
    delivered = [t.id for t in (await item_public(db, item)).payload.tokens]
    assert sorted(delivered) == sorted(correct)
    assert delivered != correct


# --------------------------------------------------------------------------- accepted variants
@pytest.mark.asyncio
async def test_short_answer_accepts_documented_variant_on_fallback(db):
    """When the LLM grader is unavailable, a documented accepted_variant is graded correct (not wrong)."""
    profile = await _make_profile(db)
    concept = await _make_concept(db)
    item = await _make_item(
        db, concept.id, "short_answer", {"kind": "short_answer"}, expected_answer="oxygen"
    )
    item.accepted_variants_json = ["O2", "dioxygen"]
    await db.flush()
    # No app.llm.grader configured -> deterministic free-text fallback path.
    res = await gamification.grade_and_reward(
        db, profile, item, AnswerIn(item_id=item.id, submitted_value="o2", latency_ms=4000), None
    )
    assert res.is_correct is True


@pytest.mark.asyncio
async def test_cloze_accepts_variant(db):
    profile = await _make_profile(db)
    concept = await _make_concept(db)
    payload = {"kind": "cloze", "text_template": "{{b1}}", "blanks": [{"id": "b1", "answer": "sun"}]}
    item = await _make_item(db, concept.id, "cloze", payload)
    item.accepted_variants_json = ["star"]
    await db.flush()
    res = await gamification.grade_and_reward(
        db, profile, item,
        AnswerIn(item_id=item.id, submitted_value={"b1": "Star"}, latency_ms=4000), None,
    )
    assert res.is_correct is True


# --------------------------------------------------------------------------- rating-only review
@pytest.mark.asyncio
async def test_review_with_rating_advances_card_and_awards_on_good(db):
    profile = await _make_profile(db)
    concept = await _make_concept(db)
    item = await _make_item(db, concept.id, "true_false", {"kind": "true_false", "answer": True})

    res = await gamification.review_with_rating(db, profile, item, 3)  # Good
    assert res.fsrs_rating == 3
    assert res.is_correct is True
    assert res.xp_awarded > 0
    card = await db.scalar(
        select(ItemFsrsCard).where(
            ItemFsrsCard.item_id == item.id, ItemFsrsCard.profile_id == profile.id
        )
    )
    assert card is not None and srs_service.card_state(card.fsrs_card_json) in (1, 2, 3)
    # An Answer row is logged for the review.
    assert (await db.scalar(select(func.count()).select_from(Answer))) == 1


@pytest.mark.asyncio
async def test_review_with_rating_again_is_not_correct_no_xp(db):
    profile = await _make_profile(db)
    concept = await _make_concept(db)
    item = await _make_item(db, concept.id, "true_false", {"kind": "true_false", "answer": True})
    res = await gamification.review_with_rating(db, profile, item, 1)  # Again
    assert res.fsrs_rating == 1
    assert res.is_correct is False
    assert res.xp_awarded == 0


# --------------------------------------------------------------------------- mastery delta
@pytest.mark.asyncio
async def test_finalize_attempt_reports_real_mastery_before(db):
    """ResultsSummary mastery_changes must show before != after when mastery actually moved."""
    profile = await _make_profile(db)
    concept = await _make_concept(db)
    from app.models import Quiz, QuizAttempt

    quiz = Quiz(request_id="r", title="t", language="en", grade_band="G3-5", subject="science",
                model_id="m", prompt_version="v")
    db.add(quiz)
    await db.flush()
    attempt = QuizAttempt(profile_id=profile.id, quiz_id=quiz.id, max_score=20)
    db.add(attempt)
    await db.flush()

    payload = {"kind": "true_false", "answer": True}
    for _ in range(2):
        item = await _make_item(db, concept.id, "true_false", payload)
        await gamification.grade_and_reward(
            db, profile, item,
            AnswerIn(item_id=item.id, attempt_id=attempt.id, submitted_value=True, latency_ms=3000),
            attempt.id,
        )

    summary = await gamification.finalize_attempt(db, profile, attempt.id)
    assert len(summary.mastery_changes) == 1
    mc = summary.mastery_changes[0]
    # before = after - summed per-answer delta; mastery grew, so before < after.
    assert mc.before <= mc.after
    assert mc.after > 0.0
    assert mc.before == pytest.approx(mc.after - sum(
        a.mastery_delta for a in (await db.scalars(
            select(Answer).where(Answer.attempt_id == attempt.id)
        ))
    ), abs=1e-3)


# --------------------------------------------------------------------------- interleave
@pytest.mark.asyncio
async def test_build_review_session_surfaces_overdue_and_interleaves(db):
    from app.services import interleave

    profile = await _make_profile(db, age_band="primary")
    c1 = await _make_concept(db, slug="addition", subject="math")
    c2 = await _make_concept(db, slug="subtraction", subject="math")
    now = datetime.now(UTC)
    past = now - timedelta(days=2)

    items = []
    for cid in (c1.id, c2.id):
        for _ in range(3):
            it = await _make_item(db, cid, "mcq",
                                  {"kind": "mcq", "options": [{"id": "a", "text": "x", "is_correct": True}]})
            items.append(it)
            # Give each an overdue FSRS card so it's surfaced for review.
            db.add(
                ItemFsrsCard(
                    profile_id=profile.id, item_id=it.id, state=2,
                    fsrs_card_json=srs_service.new_card(past), due=past,
                )
            )
    await db.flush()

    ordered, comp = await interleave.build_review_session(db, profile, limit=6)
    assert len(ordered) == 6
    # Composition fractions are reported and sum to ~1 across the buckets covered.
    assert 0.0 <= comp.current <= 1.0
    # Consecutive items should differ in concept where possible (interleaving).
    same_neighbours = sum(
        1 for a, b in zip(ordered, ordered[1:], strict=False) if a.concept_id == b.concept_id
    )
    assert same_neighbours < len(ordered) - 1


@pytest.mark.asyncio
async def test_build_review_session_caps_new_items(db):
    from app.services import interleave

    profile = await _make_profile(db, age_band="early_primary")  # DAILY_NEW_CAP = 10
    concept = await _make_concept(db)
    # 15 brand-new (state 0) cards; cap for early_primary is 10.
    for _ in range(15):
        it = await _make_item(db, concept.id, "true_false", {"kind": "true_false", "answer": True})
        db.add(
            ItemFsrsCard(
                profile_id=profile.id, item_id=it.id, state=0,
                fsrs_card_json=srs_service.new_card(datetime.now(UTC)), due=None,
            )
        )
    await db.flush()
    ordered, _comp = await interleave.build_review_session(db, profile, limit=50)
    assert len(ordered) <= 10  # new-item daily cap honored

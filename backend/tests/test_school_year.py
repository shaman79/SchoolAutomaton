"""Exact school year ("Moje třída"): normalization, the prompt-wins merge rule, persistence.

The school year is finer than the grade band — it is what lets the Czech 9th grade (basic school,
RVP ZV) be told apart from upper-secondary school, and the RVP ZV periods (grades 1-3 vs 4-5) apart
from the US-style G1-2 / G3-5 bands. It comes from the prompt (classifier) or, when the prompt names
no level, from the learner's own class setting (trusted client metadata, proceed path only)."""

from __future__ import annotations

import os

os.environ.setdefault("SA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("APP_SECRET", "test-secret-please-ignore")
os.environ.setdefault("SA_ENV", "test")

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.sanitization import safety, validate  # noqa: E402
from app.schemas.enums import (  # noqa: E402
    GradeBand,
    Mode,
    SafetyFlag,
    Subject,
    grade_band_for_school_year,
    normalize_school_year,
)
from app.schemas.intent import (  # noqa: E402
    CreateRequestIn,
    CrisisDecision,
    ProceedDecision,
    RefuseDecision,
    StructuredIntent,
)


def intent(**kw) -> StructuredIntent:
    base = {
        "subject": Subject.MATH,
        "topic": "zlomky",
        "mode": Mode.STUDY,
        "grade_band": GradeBand.UNKNOWN,
        "language": "cs",
        "classifier_confidence": 0.9,
    }
    base.update(kw)
    return StructuredIntent(**base)


# --------------------------------------------------------------------------- helpers + schema
@pytest.mark.parametrize(
    "raw,expected",
    [(0, 0), (4, 4), (13, 13), ("9", 9), (4.0, 4), (-1, None), (14, None), (None, None),
     (True, None), ("devátá", None)],
)
def test_normalize_school_year(raw, expected):
    assert normalize_school_year(raw) == expected


@pytest.mark.parametrize(
    "year,band",
    [(0, GradeBand.K), (1, GradeBand.G1_2), (2, GradeBand.G1_2), (3, GradeBand.G3_5),
     (5, GradeBand.G3_5), (6, GradeBand.G6_8), (8, GradeBand.G6_8), (9, GradeBand.G9_12),
     (13, GradeBand.G9_12)],
)
def test_grade_band_for_school_year(year, band):
    assert grade_band_for_school_year(year) is band


def test_out_of_range_model_value_is_dropped_not_fatal():
    # A sloppy classifier value must not fail the whole classification (bounds live in the validator).
    assert StructuredIntent(school_year=42).school_year is None
    assert CreateRequestIn(prompt="x", school_year=99).school_year is None
    assert CreateRequestIn(prompt="x", school_year=7).school_year == 7


# --------------------------------------------------------------------------- validate
def test_stated_year_is_authoritative_over_the_band():
    clean = validate.revalidate_intent(intent(school_year=9, grade_band=GradeBand.G6_8))
    assert clean.school_year == 9
    assert clean.grade_band is GradeBand.G9_12


def test_class_setting_fills_an_unstated_level():
    d = validate.build_decision(intent(), "rid", client_locale="cs-CZ", client_school_year=4)
    assert isinstance(d, ProceedDecision)
    assert d.intent.school_year == 4
    assert d.intent.grade_band is GradeBand.G3_5


def test_class_setting_refines_a_matching_band():
    d = validate.build_decision(intent(grade_band=GradeBand.G3_5), "rid", client_school_year=5)
    assert d.intent.school_year == 5 and d.intent.grade_band is GradeBand.G3_5


def test_prompt_level_wins_over_the_class_setting():
    # "zlomky pro 7. třídu" typed by a 4th grader: the prompt's level stands.
    d = validate.build_decision(intent(school_year=7), "rid", client_school_year=4)
    assert d.intent.school_year == 7 and d.intent.grade_band is GradeBand.G6_8
    # A different band stated without an exact year ("high school") also wins.
    d = validate.build_decision(intent(grade_band=GradeBand.G9_12), "rid", client_school_year=4)
    assert d.intent.school_year is None and d.intent.grade_band is GradeBand.G9_12


def test_stated_age_blocks_the_class_setting():
    d = validate.build_decision(intent(age=9), "rid", client_school_year=8)
    assert d.intent.school_year is None and d.intent.grade_band is GradeBand.UNKNOWN


def test_class_setting_never_touches_crisis_or_refusal():
    crisis = validate.build_decision(
        intent(safety_flags=[SafetyFlag.SELF_HARM]), "rid", client_school_year=4
    )
    assert isinstance(crisis, CrisisDecision)
    refuse = validate.build_decision(intent(is_educational=False), "rid", client_school_year=4)
    assert isinstance(refuse, RefuseDecision)


def test_refusal_suggestions_follow_the_prompt_language():
    cs = safety.refusal_redirect_suggestions(intent(language="cs"))
    assert any("násobilky" in s for s in cs)
    en = safety.refusal_redirect_suggestions(intent(language="en"))
    assert any("multiplication" in s for s in en)
    # Chips are ready-to-send prompts, not instructions about prompting.
    assert not any(s.startswith("Try:") for s in cs + en)


# --------------------------------------------------------------------------- API + persistence
@pytest.mark.asyncio
async def test_class_setting_round_trips_and_clears(client):
    r = await client.post("/api/v1/profiles", json={"locale": "cs", "education_locale": "cs-CZ",
                                                    "school_year": 4})
    assert r.status_code == 201, r.text
    code = r.json()["resume_code"]
    assert r.json()["settings"]["school_year"] == 4
    h = {"X-Resume-Code": code}

    s = (await client.patch("/api/v1/profiles/me/settings", headers=h, json={"school_year": 9})).json()
    assert s["school_year"] == 9
    # Another field alone leaves it untouched; an explicit null clears it.
    s = (await client.patch("/api/v1/profiles/me/settings", headers=h, json={"sound": False})).json()
    assert s["school_year"] == 9
    s = (await client.patch("/api/v1/profiles/me/settings", headers=h, json={"school_year": None})).json()
    assert s["school_year"] is None


@pytest.mark.asyncio
async def test_request_applies_the_class_setting(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.anthropic_api_key", "test-key")

    async def fake_classify(*, system_blocks, user, output_model):
        return (intent(topic="vyjmenovaná slova", subject=Subject.LANGUAGE_ARTS), None)

    import app.llm.client as cl

    monkeypatch.setattr(cl, "classify", fake_classify, raising=False)
    r = await client.post(
        "/api/v1/requests",
        json={"prompt": "procvič se mnou vyjmenovaná slova", "locale": "cs-CZ", "school_year": 3},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "proceed"
    assert body["intent"]["school_year"] == 3
    assert body["intent"]["grade_band"] == "G3-5"
    assert body["intent"]["education_locale"] == "cs-CZ"


@pytest.mark.asyncio
async def test_additive_migration_adds_school_year_columns():
    # An existing (pre-upgrade) database gains the new nullable columns in place — no volume wipe.
    from app.db.session import _ensure_sqlite_columns

    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.execute(text("CREATE TABLE lessons (id INTEGER PRIMARY KEY, topic VARCHAR(200))"))
        await conn.execute(text("CREATE TABLE quizzes (id INTEGER PRIMARY KEY, title VARCHAR(200))"))
        await conn.execute(text("CREATE TABLE profile_settings (profile_id INTEGER PRIMARY KEY)"))
        await _ensure_sqlite_columns(conn)
        for table in ("lessons", "quizzes", "profile_settings"):
            cols = {row[1] for row in (await conn.execute(text(f"PRAGMA table_info({table})"))).all()}
            assert "school_year" in cols, table
    await eng.dispose()


# --------------------------------------------------------------------------- review fixes
def test_non_finite_or_fractional_numbers_are_not_a_school_year():
    for bad in (float("inf"), float("-inf"), float("nan"), 4.5, "1e400", 10**400):
        assert normalize_school_year(bad) is None
    assert normalize_school_year(4.0) == 4


@pytest.mark.asyncio
async def test_infinite_school_year_never_500s(client):
    # json.loads turns 1e400 into inf; int(inf) used to raise OverflowError -> unhandled 500.
    raw = '{"prompt": "zlomky", "school_year": 1e400}'
    r = await client.post("/api/v1/requests", content=raw, headers={"Content-Type": "application/json"})
    assert r.status_code == 503  # dropped as "not stated"; the (unconfigured) classifier fails closed
    r = await client.post("/api/v1/profiles", content='{"school_year": 1e400}',
                          headers={"Content-Type": "application/json"})
    assert r.status_code == 201 and r.json()["settings"]["school_year"] is None


@pytest.mark.asyncio
async def test_invalid_class_in_settings_is_rejected_not_cleared(client):
    code = (await client.post("/api/v1/profiles", json={"school_year": 5})).json()["resume_code"]
    h = {"X-Resume-Code": code}
    for bad in (42, -1, "abc", True, 4.5):
        r = await client.patch("/api/v1/profiles/me/settings", headers=h, json={"school_year": bad})
        assert r.status_code == 422, (bad, r.text)
    r = await client.patch("/api/v1/profiles/me/settings", headers=h, content='{"school_year": 1e400}')
    assert r.status_code == 422
    me = (await client.get("/api/v1/profiles/me", headers=h)).json()
    assert me["settings"]["school_year"] == 5  # untouched


def test_class_never_narrows_high_school_down_to_the_ninth_grade():
    # "chemie na úrovni SŠ" from a 9th grader: G9-12 stays G9-12 (no RVP ZV 9. třída framing)...
    d = validate.build_decision(intent(grade_band=GradeBand.G9_12), "rid", client_school_year=9)
    assert d.intent.school_year is None and d.intent.grade_band is GradeBand.G9_12
    # ...while an upper-secondary class still refines the band to its exact year.
    d = validate.build_decision(intent(grade_band=GradeBand.G9_12), "rid", client_school_year=11)
    assert d.intent.school_year == 11


def test_stated_age_band_blocks_the_class_setting():
    from app.schemas.enums import AgeBand

    d = validate.build_decision(intent(age_band=AgeBand.UPPER_SECONDARY), "rid", client_school_year=4)
    assert d.intent.school_year is None


def test_clarify_does_not_ask_for_the_grade_when_the_class_is_known():
    vague = intent(classifier_confidence=0.2, topic="")
    asks = validate.build_decision(vague, "rid")
    knows = validate.build_decision(vague, "rid", client_school_year=4)
    assert "třídy" in asks.question
    assert "třídy" not in knows.question
    # Suggestions carry no grade, so tapping one keeps the learner's own class.
    assert not any("třídu" in s for s in knows.suggestions)

"""The education-system (curriculum) registry + its volatile-tail directive.

Asserts the locale whitelist/normalization, that the directive carries the region's framework +
conventions, and CRITICALLY that none of it leaks into the byte-identical cached system prefix
(SPEC §5 invariant #4 — region text lives only in the trailing user message)."""

from __future__ import annotations

import os

os.environ.setdefault("SA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("APP_SECRET", "test-secret-please-ignore")
os.environ.setdefault("SA_ENV", "test")

import pytest  # noqa: E402

from app.llm import prompts  # noqa: E402
from app.llm.prompts import curriculum  # noqa: E402
from app.schemas.enums import GradeBand, Mode, Subject  # noqa: E402
from app.schemas.intent import StructuredIntent  # noqa: E402


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("en-US", "en-US"),
        ("en_us", "en-US"),
        ("EN-us", "en-US"),
        ("en-GB", "en-GB"),
        ("cs-CZ", "cs-CZ"),
        ("cs", "cs-CZ"),       # single Czech variant
        ("en", None),          # ambiguous (US vs GB) -> generic
        ("fr-FR", None),       # unsupported -> generic
        ("", None),
        (None, None),
        ("garbage", None),
    ],
)
def test_normalize_education_locale(raw, expected):
    assert curriculum.normalize_education_locale(raw) == expected


def test_base_language_and_country():
    assert curriculum.base_language("en-GB") == "en"
    assert curriculum.base_language("cs-CZ") == "cs"
    assert curriculum.base_language(None) is None
    assert curriculum.country_of("en-US") == "US"
    assert curriculum.country_of("cs-CZ") == "CZ"
    assert curriculum.country_of(None) is None


def test_directive_carries_framework_and_conventions():
    gb = curriculum.curriculum_directive("en-GB", GradeBand.G3_5)
    assert "National Curriculum for England" in gb
    assert "British English" in gb
    assert "Year" in gb  # localized grade naming
    us = curriculum.curriculum_directive("en-US", GradeBand.G3_5)
    assert "American English" in us
    assert "Common Core" in us


def test_directive_empty_for_generic():
    assert curriculum.curriculum_directive(None, GradeBand.G3_5) == ""
    assert curriculum.curriculum_directive("fr-FR", GradeBand.G3_5) == ""


def _intent(education_locale=None, language="en") -> StructuredIntent:
    return StructuredIntent(
        subject=Subject.SCIENCE,
        topic="photosynthesis",
        mode=Mode.STUDY,
        grade_band=GradeBand.G3_5,
        language=language,
        education_locale=education_locale,
    )


def test_directive_injected_into_section_prompt_tail():
    with_locale = prompts.build_section_user(
        _intent(education_locale="en-GB"), kind="explanation", title="How it works", objective=None
    )
    assert "National Curriculum for England" in with_locale
    generic = prompts.build_section_user(
        _intent(education_locale=None), kind="explanation", title="How it works", objective=None
    )
    assert "National Curriculum" not in generic


def test_cached_system_prefix_is_unaffected_by_locale():
    # The big cached pedagogy prefix must NOT contain any region/curriculum text — that lives only in
    # the volatile tail, so the ephemeral cache stays byte-identical across locales (SPEC §5).
    prefix = prompts.system_pedagogy("en")
    assert prefix is prompts.SYSTEM_PEDAGOGY_EN
    assert prompts.system_pedagogy("cs") is prompts.SYSTEM_PEDAGOGY_EN  # same object for every language
    for needle in ("National Curriculum", "Common Core", "Rámcový", "British English", "American English"):
        assert needle not in prefix


# --------------------------------------------------------------------------- Czech RVP alignment
@pytest.mark.parametrize(
    "school_year,framework,level",
    [
        (0, "RVP PV", "předškolák"),
        (1, "RVP ZV", "1. třída"),
        (3, "RVP ZV", "konec 1. období"),
        (4, "RVP ZV", "2. období"),
        (9, "RVP ZV", "9. třída ZŠ"),  # still základní škola, NOT upper-secondary
        (10, "RVP G", "1. ročník střední školy"),
        (13, "RVP G", "maturitní ročník"),
    ],
)
def test_czech_directive_picks_the_stage_rvp_for_the_exact_year(school_year, framework, level):
    from app.schemas.enums import grade_band_for_school_year

    band = grade_band_for_school_year(school_year)
    d = curriculum.curriculum_directive("cs-CZ", band, school_year)
    align = d.splitlines()[1]
    assert framework in align
    assert level in d


def test_czech_band_fallback_names_the_right_stage():
    # Without an exact year the band picks the stage; G6-8 is the 2nd stage of základní škola (RVP ZV)
    # and G9-12 must mention that the 9th grade is still RVP ZV.
    assert "RVP ZV" in curriculum.curriculum_directive("cs-CZ", GradeBand.G6_8)
    g912 = curriculum.curriculum_directive("cs-CZ", GradeBand.G9_12)
    assert "9th grade" in g912 and "RVP ZV" in g912 and "RVP G" in g912
    assert "RVP PV" in curriculum.curriculum_directive("cs-CZ", GradeBand.K)


def test_czech_directive_carries_school_notation_and_formats():
    d = curriculum.curriculum_directive("cs-CZ", GradeBand.G3_5, 4)
    assert "decimal comma" in d and "12 : 3" in d and "3 · 4" in d  # Czech maths notation
    assert "vyjmenovaná slova" in d and "{{b1}}" in d  # i/y cloze inside the word
    assert "zápis" in d and "odpověď" in d  # word-problem layout
    assert "Kč" in d


def test_exact_year_naming_for_other_locales():
    assert "Year 7" in curriculum.curriculum_directive("en-GB", GradeBand.G6_8, 6)
    assert "Grade 4" in curriculum.curriculum_directive("en-US", GradeBand.G3_5, 4)


def test_exact_year_reaches_the_prompt_tail():
    intent = StructuredIntent(
        subject=Subject.MATH,
        topic="zlomky",
        mode=Mode.STUDY,
        grade_band=GradeBand.G3_5,
        school_year=4,
        language="cs",
        education_locale="cs-CZ",
    )
    tail = prompts.build_section_user(intent, kind="explanation", title="Zlomky", objective=None)
    assert "school_year: 4" in tail
    assert "4. třída ZŠ" in tail
    # No exact year -> no school_year line (the band alone drives the level).
    no_year = prompts.build_section_user(_intent(education_locale="cs-CZ"), kind="hook", title="x", objective=None)
    assert "school_year:" not in no_year


def test_czech_curriculum_never_reaches_the_cached_prefix():
    prefix = prompts.system_pedagogy("cs")
    for needle in ("RVP ZV", "RVP PV", "decimal comma", "vyjmenovaná"):
        assert needle not in prefix

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

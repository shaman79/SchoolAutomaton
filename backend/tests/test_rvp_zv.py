"""The Czech RVP ZV outcome catalogue: its importer, the shipped data, the per-request selection and
the volatile-tail directive built from it.

The catalogue is NPI open data (scripts/import_rvp_zv.py -> app/data/rvp_zv.json). Selection must
stay deterministic, apply only to the Czech system at basic-school level, and never reach the cached
system prefix (SPEC §5 #4)."""

from __future__ import annotations

import os

os.environ.setdefault("SA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("APP_SECRET", "test-secret-please-ignore")
os.environ.setdefault("SA_ENV", "test")

import json  # noqa: E402
import re  # noqa: E402

import pytest  # noqa: E402
from scripts import import_rvp_zv  # noqa: E402

from app.llm import prompts  # noqa: E402
from app.llm.prompts import rvp  # noqa: E402
from app.schemas.enums import GradeBand, Mode, Subject  # noqa: E402
from app.schemas.intent import StructuredIntent  # noqa: E402

_CODE = re.compile(r"^[A-Z]{3}-[A-Z]{3}-\d{3}-ZV[59]-\d{3}$")
_LIST_MARKER = "Czech curriculum outcomes for this subject"
_MATCH_MARKER = "Czech curriculum outcomes this topic serves"


# --------------------------------------------------------------------------- importer
def _dataset(*outcomes: tuple[str, str, str], strand_code: int = 1) -> dict:
    """A minimal open-data document: one area, one subject, one strand; outcomes as (node, code, text)."""
    nodes: dict[str, list] = {}
    for node, code, text in outcomes:
        nodes.setdefault(node, []).append({
            "kod": code,
            "zneni": text,
            "urovneMetodickePodpory": [
                {"nazev": "Na začátku", "charakteristika": "<p>Začíná&nbsp;s&nbsp;tím.</p>"},
                {"nazev": "Na cestě", "charakteristika": ""},
                {"nazev": "Splněno", "charakteristika": "<p>Umí to.</p><ul><li>Opravdu.</li></ul>"},
                {"nazev": "Minimální doporučená úroveň", "charakteristika": "<p>Aspoň trochu.</p>"},
            ],
        })
    return {"vzdelavaciOblasti": [{
        "nazev": "Matematika a její aplikace", "kod": "MAT",
        "vzdelavaciObory": [{
            "nazev": "Matematika", "kod": "MAT",
            "tematickeOkruhy": [{
                "nazev": "Číslo a <b>početní</b> operace", "kod": strand_code,
                "uzloveBody": [{"kod": n, "nazev": n, "ocekavaneVysledkyUceni": o} for n, o in nodes.items()],
            }],
        }],
    }]}


def test_plain_text_turns_dataset_html_into_one_line():
    assert import_rvp_zv.plain_text("<p>Mluví.</p><p>Tvoří&nbsp;věty.</p>") == "Mluví. Tvoří věty."
    assert import_rvp_zv.plain_text("a<br/>b <ul><li>c</li><li>d</li></ul>") == "a b c d"
    assert import_rvp_zv.plain_text(None) == ""


def test_extract_keeps_what_the_app_uses_sorted_by_code():
    data = import_rvp_zv.extract(_dataset(
        ("ZV9", "MAT-MAT-001-ZV9-002", "Druhý."),
        ("ZV5", "MAT-MAT-001-ZV5-001", "První&nbsp;výstup."),
    ), source_url="https://example.invalid/rvp.json")
    assert [o["code"] for o in data["outcomes"]] == ["MAT-MAT-001-ZV5-001", "MAT-MAT-001-ZV9-002"]
    first = data["outcomes"][0]
    assert first == {
        "code": "MAT-MAT-001-ZV5-001", "subject": "MAT", "strand": "Číslo a početní operace", "stage": "ZV5",
        "text": "První výstup.",
        # An empty phase is left out; the minimum level is not kept.
        "phases": {"start": "Začíná s tím.", "met": "Umí to. Opravdu."},
    }
    assert data["subjects"] == {"MAT": {"name": "Matematika", "area": "Matematika a její aplikace"}}
    assert data["source"]["url"] == "https://example.invalid/rvp.json"
    assert "neobsahuje autorská díla" in data["source"]["terms"]


def test_extract_skips_strands_removed_from_the_rvp(monkeypatch):
    monkeypatch.setattr(import_rvp_zv, "EXCLUDED_STRANDS", {"MAT-MAT-003": "removed"})
    data = import_rvp_zv.extract(_dataset(("ZV5", "MAT-MAT-003-ZV5-001", "Pryč."), strand_code=3),
                                 source_url="u")
    assert data["outcomes"] == []


@pytest.mark.parametrize("outcomes", [
    [("ZV5", "MAT-1-ZV5-001", "Bad code.")],
    [("ZV9", "MAT-MAT-001-ZV5-001", "Under the wrong nodal point.")],
    [("ZV5", "MAT-MAT-001-ZV5-001", "<p> </p>")],
    [("ZV5", "MAT-MAT-001-ZV5-001", "Twice."), ("ZV5", "MAT-MAT-001-ZV5-001", "Twice.")],
])
def test_extract_fails_loudly_when_the_dataset_changes_shape(outcomes):
    with pytest.raises(ValueError):
        import_rvp_zv.extract(_dataset(*outcomes), source_url="u")


# --------------------------------------------------------------------------- shipped catalogue
def test_shipped_catalogue_is_importer_output():
    text = import_rvp_zv.OUTPUT.read_text(encoding="utf-8")
    assert import_rvp_zv.render(json.loads(text)) == text  # not hand-edited into another layout
    assert rvp.RVP_ZV["source"]["url"].startswith("https://opendata.npi.cz/")


def test_shipped_catalogue_is_well_formed():
    outcomes = rvp.RVP_ZV["outcomes"]
    assert len(outcomes) > 300
    assert len(rvp.OUTCOMES) == len(outcomes)  # unique codes
    for o in outcomes:
        assert _CODE.match(o["code"]), o["code"]
        assert o["code"].split("-")[3] == o["stage"]
        assert o["subject"] in rvp.SUBJECTS and o["code"].split("-")[1] == o["subject"]
        assert o["text"] and o["strand"]
        assert set(o["phases"]) <= {"start", "on_the_way", "met"}
        assert "<" not in o["text"] and "&nbsp;" not in o["text"]
        assert not any(o["code"].startswith(p) for p in import_rvp_zv.EXCLUDED_STRANDS)


def test_every_subject_scope_prefix_names_real_outcomes():
    """A typo in SUBJECT_SCOPE would silently give that subject no outcomes."""
    for subject, stages in rvp.SUBJECT_SCOPE.items():
        for stage, prefixes in stages.items():
            for prefix in prefixes:
                assert any(o["stage"] == stage and code.startswith(prefix + "-")
                           for code, o in rvp.OUTCOMES.items()), (subject, stage, prefix)


# --------------------------------------------------------------------------- selection
@pytest.mark.parametrize("subject,year,topic,code", [
    (Subject.MATH, 4, "zlomky", "MAT-MAT-001-ZV5-002"),
    (Subject.MATH, 4, "Sčítání ZLOMKŮ", "MAT-MAT-001-ZV5-002"),  # case, diacritics, inflection
    (Subject.MATH, 5, "desetinná čísla", "MAT-MAT-001-ZV5-003"),
    (Subject.MATH, 8, "lineární rovnice", "MAT-MAT-005-ZV9-018"),
    (Subject.LANGUAGE_ARTS, 9, "skladba souvětí", "JJK-CJL-001-ZV9-005"),
    (Subject.PHYSICS, 8, "elektrický obvod", "CAP-FYZ-004-ZV9-011"),
    (Subject.SCIENCE, 8, "elektrický obvod", "CAP-FYZ-004-ZV9-011"),  # science spans FYZ/CHE/PRI
    (Subject.HEALTH, 7, "první pomoc", "CZB-VZB-001-ZV9-005"),
    (Subject.GEOGRAPHY, 4, "kraje ČR", "CJS-CJS-001-ZV5-004"),
])
def test_topic_picks_the_outcome_it_serves(subject, year, topic, code):
    selection = rvp.select_outcomes("cs-CZ", subject, topic, None, year)
    assert selection is not None
    assert selection.matched and selection.matched[0]["code"] == code
    assert len(selection.matched) <= rvp.MAX_MATCHES


@pytest.mark.parametrize("topic", ["fractions", "husitství", "", "xyz"])
def test_no_confident_match_falls_back_to_the_whole_subject(topic):
    selection = rvp.select_outcomes("cs-CZ", Subject.MATH, topic, None, 4)
    assert selection.matched == ()
    assert [o["code"] for o in selection.candidates] == sorted(
        c for c, o in rvp.OUTCOMES.items() if o["stage"] == "ZV5" and c.startswith("MAT-MAT-"))


def test_candidates_stay_within_the_subject_and_stage():
    physics = rvp.select_outcomes("cs-CZ", Subject.PHYSICS, "síla", None, 8)
    assert physics.stage == "ZV9" and all(o["code"].startswith("CAP-FYZ-") for o in physics.candidates)
    history = rvp.select_outcomes("cs-CZ", Subject.HISTORY, "Karel IV.", None, 4)
    assert history.stage == "ZV5" and all(o["code"].startswith("CJS-CJS-003-") for o in history.candidates)


@pytest.mark.parametrize("band,year,stage,phase", [
    (None, 1, "ZV5", "start"), (None, 2, "ZV5", "start"), (None, 3, "ZV5", "on_the_way"),
    (None, 4, "ZV5", "on_the_way"), (None, 5, "ZV5", "met"), (None, 6, "ZV9", "start"),
    (None, 7, "ZV9", "on_the_way"), (None, 8, "ZV9", "on_the_way"), (None, 9, "ZV9", "met"),
    (GradeBand.G1_2, None, "ZV5", "start"), (GradeBand.G3_5, None, "ZV5", "on_the_way"),
    (GradeBand.G6_8, None, "ZV9", "on_the_way"),
    (GradeBand.G9_12, 9, "ZV9", "met"),  # the exact year wins over the band
])
def test_school_year_sets_stage_and_phase(band, year, stage, phase):
    selection = rvp.select_outcomes("cs-CZ", Subject.MATH, "zlomky", band, year)
    assert (selection.stage, selection.phase) == (stage, phase)


@pytest.mark.parametrize("locale,subject,band,year", [
    ("en-GB", Subject.MATH, None, 4),        # another education system
    (None, Subject.MATH, None, 4),           # generic
    ("cs-CZ", Subject.MATH, GradeBand.K, 0),  # preschool: RVP PV
    ("cs-CZ", Subject.MATH, None, 10),       # upper-secondary: RVP G / SOŠ
    ("cs-CZ", Subject.MATH, GradeBand.G9_12, None),  # 9th grade or secondary school: unknown
    ("cs-CZ", Subject.MATH, GradeBand.ADULT, None),
    ("cs-CZ", Subject.MATH, GradeBand.UNKNOWN, None),
    ("cs-CZ", Subject.OTHER, None, 4),
    ("cs-CZ", Subject.PHILOSOPHY, None, 8),
])
def test_catalogue_applies_only_to_czech_basic_school(locale, subject, band, year):
    assert rvp.select_outcomes(locale, subject, "zlomky", band, year) is None
    assert rvp.rvp_outcomes_directive(locale, subject, "zlomky", band, year) == ""


# --------------------------------------------------------------------------- directive
def test_matched_directive_names_outcome_phase_and_target():
    d = rvp.rvp_outcomes_directive("cs-CZ", Subject.MATH, "zlomky", GradeBand.G3_5, 4)
    assert d.startswith(_MATCH_MARKER)
    assert "MAT-MAT-001-ZV5-002" in d and "Modeluje a používá zlomky v praktických situacích." in d
    assert "\n  Na cestě: " in d and "\n  Splněno: " in d
    assert "end of grade 5" in d and "never show them to the learner" in d
    # The phase guides the pitch but must not shrink the topic (an eval caught "násobilka 7" for
    # grade 2 losing 7·6-7·9 when the wording only said "pitch to that phase").
    assert "Cover the requested topic completely" in d and "never narrows the topic" in d
    assert "(school_year above)" in d
    assert _LIST_MARKER not in d


def test_final_year_shows_the_target_only():
    d = rvp.rvp_outcomes_directive("cs-CZ", Subject.MATH, "zlomky", None, 5)
    assert "\n  Splněno: " in d and "\n  Na cestě: " not in d and "\n  Na začátku: " not in d
    assert "should be met" in d


def test_long_phase_descriptions_are_cut_at_a_word():
    d = rvp.rvp_outcomes_directive("cs-CZ", Subject.PHYSICS, "elektrický obvod", None, 9)
    phase_lines = [line for line in d.splitlines() if line.startswith("  ")]
    assert phase_lines
    for line in phase_lines:
        label, _, text = line.strip().partition(": ")
        assert len(text) <= rvp._PHASE_CHARS + 2
    assert any(line.endswith(" …") for line in phase_lines)  # this outcome's "Splněno" is long


def test_fallback_directive_lists_the_subject_grouped_by_strand():
    selection = rvp.select_outcomes("cs-CZ", Subject.LANGUAGE_ARTS, "xyz", None, 3)
    d = rvp.rvp_outcomes_directive("cs-CZ", Subject.LANGUAGE_ARTS, "xyz", None, 3)
    assert d.startswith(_LIST_MARKER) and "if none fits, ignore this list" in d
    assert all(f"- {o['code']}: {o['text']}" in d for o in selection.candidates)
    assert "\nČeský jazyk a literatura:\n" in d  # one heading, not repeated per line
    # No phase descriptions here, so no phase pitch either — just the full topic at the learner's grade.
    assert "Na cestě" not in d and "Na začátku" not in d
    assert "Cover the requested topic completely" in d and "never narrow or stretch it" in d


def test_band_only_learner_is_pointed_at_the_grade_band():
    d = rvp.rvp_outcomes_directive("cs-CZ", Subject.MATH, "zlomky", GradeBand.G3_5, None)
    assert "(grade_band above)" in d and "school_year" not in d


def test_directive_is_deterministic():
    args = ("cs-CZ", Subject.SCIENCE, "síla a pohyb", GradeBand.G6_8, 7)
    assert rvp.rvp_outcomes_directive(*args) == rvp.rvp_outcomes_directive(*args)


# --------------------------------------------------------------------------- prompt integration
def _intent(**overrides) -> StructuredIntent:
    fields = {"subject": Subject.MATH, "topic": "zlomky", "mode": Mode.STUDY, "grade_band": GradeBand.G3_5,
              "school_year": 4, "language": "cs", "education_locale": "cs-CZ"}
    return StructuredIntent(**{**fields, **overrides})


def test_lesson_and_quiz_prompts_carry_the_outcomes():
    intent = _intent()
    for text in (
        prompts.build_lesson_plan_user(intent),
        prompts.build_section_user(intent, kind="practice", title="Zlomky", objective=None),
        prompts.build_quiz_user(intent, mastery=0.3, recent_accuracy=0.7, known_misconceptions=[]),
    ):
        assert "MAT-MAT-001-ZV5-002" in text
        # After the education-system directive, in the volatile user message.
        assert text.index("Education system (follow precisely):") < text.index(_MATCH_MARKER)


def test_whole_subject_list_goes_only_to_the_steps_that_set_objectives():
    """Without a match the plan and the quiz see the subject's whole list and pick; the section calls
    (a dozen per lesson) work from the plan's objectives and skip the ~1,500-token list."""
    intent = _intent(topic="koloběh vody", subject=Subject.SCIENCE)
    assert _LIST_MARKER in prompts.build_lesson_plan_user(intent)
    assert _LIST_MARKER in prompts.build_quiz_user(intent, mastery=0.3, recent_accuracy=0.7, known_misconceptions=[])
    section = prompts.build_section_user(intent, kind="practice", title="Koloběh vody", objective="Umím…")
    assert "CJS-CJS-" not in section
    assert "Education system (follow precisely):" in section


def test_list_all_false_keeps_matches_and_drops_the_fallback():
    assert rvp.rvp_outcomes_directive("cs-CZ", Subject.MATH, "zlomky", None, 4, list_all=False).startswith(
        _MATCH_MARKER)
    assert rvp.rvp_outcomes_directive("cs-CZ", Subject.MATH, "fractions", None, 4, list_all=False) == ""


def test_visual_prompt_skips_the_outcomes():
    text = prompts.build_visual_spec_user(_intent(), ["Úvod", "Procvičování"])
    assert "Education system (follow precisely):" in text
    assert "MAT-MAT-" not in text


def test_other_systems_get_no_outcomes():
    assert "MAT-MAT-" not in prompts.build_lesson_plan_user(_intent(education_locale="en-US", language="en"))
    assert "MAT-MAT-" not in prompts.build_lesson_plan_user(_intent(school_year=11, grade_band=GradeBand.G9_12))


def test_cached_prefix_never_carries_outcomes():
    for language in ("cs", "en"):
        assert "MAT-MAT-" not in prompts.system_pedagogy(language)
        assert "očekávané výsledky učení" not in prompts.system_pedagogy(language)

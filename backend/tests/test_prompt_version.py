"""PROMPT_VERSION must move whenever the text the app sends to an AI model changes.

It is stamped on every generated row (so you can tell which instructions produced a lesson) and is
part of the picture cache key (so pictures made under old instructions aren't reused). It stayed at
"2026.06.06" through eleven prompt changes; this test makes forgetting the bump fail.

The fingerprint covers everything sent, rendered for fixed sample inputs: the cached system prefix,
every user-message builder (each grade band × education system), the curriculum data and the Czech
RVP ZV outcome catalogue, the input-check,
picture and grading prompts, the client's own instructions and the output schemas the models fill.

When this fails because you changed a prompt (or a schema the model fills):
  1. bump PROMPT_VERSION in app/core/constants.py (YYYY.MM.DD, or YYYY.MM.DD.N for a second bump that
     day), and
  2. add the new version with the fingerprint printed in the failure to PROMPT_VERSIONS below.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re

import pytest

from app.core.constants import PROMPT_VERSION
from app.llm import client as llm_client
from app.llm import key_check, lesson_generator, prompts
from app.llm.prompts import curriculum, rvp
from app.llm.prompts.curriculum import base_language, curriculum_directive
from app.sanitization import classifier
from app.schemas.enums import LESSON_SKELETON, GradeBand, ItemType, Mode, Subject, VisualKind
from app.schemas.generation import (
    GenItem,
    GenQuiz,
    GenSection,
    GenVisualSpec,
    GraderOutput,
    KeyCheckOutput,
    LessonPlan,
)
from app.schemas.intent import StructuredIntent
from app.visuals import claude_svg, replicate_raster

# Every prompt version since this check exists -> the fingerprint of what it sends.
PROMPT_VERSIONS: dict[str, str] = {
    # 2026.06.06 (the first) was never recorded. 2026.10.29: the September lesson-text fixes, the
    # Opus 5.5 / Haiku 5.5 prompt changes and everything since June.
    "2026.10.29": "b74529f20652d4f851bfae188fef99b06c4866306abf8775be97b2bd0f5be49e",
    # Czech RVP ZV outcomes (NPI open data) in the lesson/quiz user messages for cs-CZ, grades 1-9.
    "2026.11.20": "0ddc112db2607e45bd02dc895fda8076e239f07521662801d409b7211813b673",
    # Concept names for learners, stricter true/false + explanation rules, topic headings without
    # bracketed glosses, and the answer-key check's own prompt.
    "2026.11.26": "1ea1aa93cbae694b3765e248e93cd6f5cb29c0b15161abd9353c438f59b3f065",
}

_VERSION_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}(\.\d+)?$")
_SAMPLE_YEAR = {"K": 0, "G1-2": 2, "G3-5": 4, "G6-8": 7, "G9-12": 11}
_OUTPUT_MODELS = (LessonPlan, GenSection, GenQuiz, GraderOutput, StructuredIntent,
                  claude_svg.SvgGenerationOutput, KeyCheckOutput)


def _key_check_items() -> list:
    """One question of every type the answer-key check sees, as it renders them (keys left out)."""
    payloads = {
        ItemType.MCQ: {"options": [{"id": "a", "text": "1/2", "is_correct": True},
                                   {"id": "b", "text": "1/3", "is_correct": False}]},
        ItemType.TRUE_FALSE: {"statement": "1/2 is more than 1/3.", "answer": True},
        ItemType.NUMERIC: {"answer": 0.75, "tolerance": 0, "unit": "kg"},
        ItemType.ORDER: {"tokens": [{"id": "t1", "text": "1/4"}, {"id": "t2", "text": "1/2"}],
                         "correct_order": ["t1", "t2"]},
        ItemType.MATCH: {"left": [{"id": "l1", "text": "half"}], "right": [{"id": "r1", "text": "1/2"}],
                         "correct": [{"left_id": "l1", "right_id": "r1"}]},
        ItemType.CLOZE: {"text_template": "One {{b1}} is 1/2.", "blanks": [{"id": "b1", "answer": "half",
                         "choices": ["half", "third"]}]},
        ItemType.SHORT_ANSWER: {"placeholder": "..."},
    }
    gens = [GenItem(item_type=t, concept_slug="halves", concept_name="Halves", bloom_tier=2,
                    stem_markdown="Which is a half?", payload=p) for t, p in payloads.items()]
    return [(i + 1, g, key_check.coerce_payload(g.item_type, g.payload)) for i, g in enumerate(gens)]


def _intents() -> list[StructuredIntent]:
    out = []
    for locale in (None, *sorted(curriculum.CURRICULA)):
        language = base_language(locale) or "en"
        for band in GradeBand:
            for year in dict.fromkeys((None, _SAMPLE_YEAR.get(band.value))):
                out.append(StructuredIntent(
                    subject=Subject.MATH if band != GradeBand.K else Subject.SCIENCE,
                    topic="fractions", mode=Mode.STUDY, grade_band=band, school_year=year,
                    language=language, education_locale=locale, constraints=["use pictures"],
                ))
    # A Czech topic the RVP ZV catalogue matches, so the matched-outcome wording is covered too (the
    # English "fractions" above only reaches the subject's full outcome list).
    out.append(StructuredIntent(
        subject=Subject.MATH, topic="zlomky", mode=Mode.STUDY, grade_band=GradeBand.G3_5, school_year=4,
        language="cs", education_locale="cs-CZ", constraints=["use pictures"],
    ))
    return out


def _texts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """(name, text) of everything the app sends a model, for fixed inputs."""
    monkeypatch.setattr(classifier.secrets, "token_hex", lambda n=8: "0" * (2 * n))
    texts: list[tuple[str, str]] = [
        ("system_pedagogy", prompts.system_pedagogy("en")),
        ("system_pedagogy_registry", json.dumps(prompts.SYSTEM_PEDAGOGY, sort_keys=True)),
        ("curricula", json.dumps(curriculum.CURRICULA, sort_keys=True, ensure_ascii=False)),
        ("rvp_zv", json.dumps(rvp.RVP_ZV, sort_keys=True, ensure_ascii=False)),
        ("classifier_system", classifier.CLASSIFIER_SYSTEM_PROMPT),
        ("classifier_block", classifier.wrap_with_nonce("I want to learn fractions")[0]),
        ("svg_system", claude_svg._SYSTEM_PROMPT),
        ("json_mode", llm_client.JSON_MODE_INSTRUCTION),
        ("validation_retry", llm_client.VALIDATION_RETRY_INSTRUCTION),
        ("simplify", lesson_generator.SIMPLIFY_INSTRUCTION.format(measured=9.4, target=5.0)),
        ("key_check_system", key_check.SYSTEM_PROMPT),
        ("key_check_user", key_check.build_user(
            _key_check_items(), subject="math", grade_band="G3-5", language="cs")),
    ]
    for i, intent in enumerate(_intents()):
        tag = f"{intent.education_locale}/{intent.grade_band.value}/{intent.school_year}"
        texts.append((f"curriculum:{tag}", curriculum_directive(
            intent.education_locale, intent.grade_band, intent.school_year)))
        texts.append((f"plan:{tag}", prompts.build_lesson_plan_user(intent)))
        for kind in LESSON_SKELETON:
            texts.append((f"section:{kind.value}:{tag}", prompts.build_section_user(
                intent, kind=kind.value, title="Halves and quarters", objective=None if i % 2 else "I can")))
        texts.append((f"visual_specs:{tag}", prompts.build_visual_spec_user(intent, ["Hook", "Practice"])))
        texts.append((f"quiz:{tag}", prompts.build_quiz_user(
            intent, mastery=0.4, recent_accuracy=0.75, known_misconceptions=[] if i % 2 else ["bigger is more"])))
    for language in ("en", "cs"):
        texts.append((f"grader:{language}", prompts.build_grader_user(
            stem_markdown="What is 1/2 + 1/4?", item_type="short_answer", expected_answer="3/4",
            submitted_value="three quarters", language=language, accepted_variants=["0.75"], nonce="0" * 16)))
    for kind in VisualKind:
        spec = GenVisualSpec(section_ordinal=0, visual_kind=kind, alt_text="A pizza cut into quarters",
                             svg_request="Draw a pizza cut into four equal slices", caption="Quarters",
                             image_prompt="a pizza cut into four equal slices")
        texts.append((f"svg_user:{kind.value}", claude_svg._build_user_prompt(spec, language="en", grade_band="G3-5")))
        texts.append((f"image:{kind.value}", replicate_raster.build_prompt(spec, grade_band="G3-5")))
    for model in _OUTPUT_MODELS:
        name = model.__name__
        # Exactly as sent (field order matters to the model): the JSON-mode schema text, the
        # structured-output format and the tool definition.
        texts.append((f"schema:{name}", json.dumps(model.model_json_schema(), separators=(",", ":"))))
        texts.append((f"format:{name}", json.dumps(llm_client._output_format(model))))
        texts.append((f"tool:{name}", json.dumps(llm_client._tool_for(model))))
    # The version itself is part of some texts; the fingerprint is about everything else.
    return [(name, text.replace(PROMPT_VERSION, "<PROMPT_VERSION>")) for name, text in texts]


def _fingerprint(texts: list[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for name, text in texts:
        digest.update(f"{name}\0{text}\0".encode())
    return digest.hexdigest()


def test_prompt_version_moves_with_the_prompts(monkeypatch):
    current = _fingerprint(_texts(monkeypatch))
    recorded = PROMPT_VERSIONS.get(PROMPT_VERSION)
    assert recorded is not None, (
        f'PROMPT_VERSION {PROMPT_VERSION} is not recorded: add  "{PROMPT_VERSION}": "{current}",  '
        "to PROMPT_VERSIONS in tests/test_prompt_version.py"
    )
    assert current == recorded, (
        "The text sent to the AI models changed but PROMPT_VERSION did not. Bump PROMPT_VERSION in "
        "app/core/constants.py, then add  \"<the new version>\": "
        f'"{current}",  to PROMPT_VERSIONS in tests/test_prompt_version.py'
    )


def test_prompt_versions_only_move_forward():
    assert all(_VERSION_RE.match(v) for v in PROMPT_VERSIONS), "versions look like 2026.10.29 or 2026.10.29.2"
    newest = max(PROMPT_VERSIONS, key=lambda v: tuple(int(p) for p in v.split(".")))
    assert newest == PROMPT_VERSION, "PROMPT_VERSION must be the newest recorded version"
    assert len(set(PROMPT_VERSIONS.values())) == len(PROMPT_VERSIONS), "each version records different prompts"


def test_the_fingerprint_notices_a_prompt_change(monkeypatch):
    before = _fingerprint(_texts(monkeypatch))
    assert _fingerprint(_texts(monkeypatch)) == before  # deterministic
    with monkeypatch.context() as mp:
        mp.setattr(classifier, "CLASSIFIER_SYSTEM_PROMPT", classifier.CLASSIFIER_SYSTEM_PROMPT + " ")
        assert _fingerprint(_texts(mp)) != before
    with monkeypatch.context() as mp:
        schema = GenQuiz.model_json_schema()
        props = schema["properties"]
        swapped = dict(reversed(list(props.items())))
        mp.setattr(GenQuiz, "model_json_schema", classmethod(lambda cls, *a, **k: {**schema, "properties": swapped}))
        assert _fingerprint(_texts(mp)) != before
    with monkeypatch.context() as mp:
        data = copy.deepcopy(curriculum.CURRICULA)
        data[next(iter(data))]["conventions"] = "changed"
        mp.setattr(curriculum, "CURRICULA", data)
        assert _fingerprint(_texts(mp)) != before
    with monkeypatch.context() as mp:
        catalogue = copy.deepcopy(rvp.RVP_ZV)
        catalogue["outcomes"][-1]["phases"]["met"] += " "
        mp.setattr(rvp, "RVP_ZV", catalogue)
        assert _fingerprint(_texts(mp)) != before

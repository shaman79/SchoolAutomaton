"""PROMPT_VERSION must move whenever the text the app sends to an AI model changes.

It is stamped on every generated row (so you can tell which instructions produced a lesson) and is
part of the picture cache key (so pictures made under old instructions aren't reused). It stayed at
"2026.06.06" through eleven prompt changes; this test makes forgetting the bump fail.

The fingerprint covers everything sent, rendered for fixed sample inputs: the cached system prefix,
every user-message builder (each grade band × education system), the curriculum data, the input-check,
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
from app.llm import prompts
from app.llm.prompts import curriculum
from app.llm.prompts.curriculum import base_language, curriculum_directive
from app.sanitization import classifier
from app.schemas.enums import LESSON_SKELETON, GradeBand, Mode, Subject, VisualKind
from app.schemas.generation import GenQuiz, GenSection, GenVisualSpec, GraderOutput, LessonPlan
from app.schemas.intent import StructuredIntent
from app.visuals import claude_svg, replicate_raster

# Every prompt version since this check exists -> the fingerprint of what it sends.
PROMPT_VERSIONS: dict[str, str] = {
    # 2026.06.06 (the first) was never recorded. 2026.10.29: the September lesson-text fixes, the
    # Opus 5.5 / Haiku 5.5 prompt changes and everything since June.
    "2026.10.29": "cabfb4a185d73b580b77a45013c664fa439ecddab40a55242f7c465633461e28",
}

_VERSION_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}(\.\d+)?$")
_SAMPLE_YEAR = {"K": 0, "G1-2": 2, "G3-5": 4, "G6-8": 7, "G9-12": 11}
_OUTPUT_MODELS = (LessonPlan, GenSection, GenQuiz, GraderOutput, StructuredIntent,
                  claude_svg.SvgGenerationOutput)


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
    return out


def _texts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """(name, text) of everything the app sends a model, for fixed inputs."""
    monkeypatch.setattr(classifier.secrets, "token_hex", lambda n=8: "0" * (2 * n))
    texts: list[tuple[str, str]] = [
        ("system_pedagogy", prompts.system_pedagogy("en")),
        ("system_pedagogy_registry", json.dumps(prompts.SYSTEM_PEDAGOGY, sort_keys=True)),
        ("curricula", json.dumps(curriculum.CURRICULA, sort_keys=True, ensure_ascii=False)),
        ("classifier_system", classifier.CLASSIFIER_SYSTEM_PROMPT),
        ("classifier_block", classifier.wrap_with_nonce("I want to learn fractions")[0]),
        ("svg_system", claude_svg._SYSTEM_PROMPT),
        ("json_mode", llm_client.JSON_MODE_INSTRUCTION),
        ("validation_retry", llm_client.VALIDATION_RETRY_INSTRUCTION),
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
        texts.append((f"schema:{name}", json.dumps(model.model_json_schema(), sort_keys=True)))
        texts.append((f"format:{name}", json.dumps(llm_client._output_format(model), sort_keys=True)))
        texts.append((f"tool:{name}", json.dumps(llm_client._tool_for(model), sort_keys=True)))
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
        data = copy.deepcopy(curriculum.CURRICULA)
        data[next(iter(data))]["conventions"] = "changed"
        mp.setattr(curriculum, "CURRICULA", data)
        assert _fingerprint(_texts(mp)) != before

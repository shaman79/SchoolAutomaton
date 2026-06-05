"""Guards the central safety invariant (SPEC §3): generators/visuals consume only structured inputs,
never the raw prompt. This is a structural guard; the B1/B2 agents extend it with a runtime corpus
test that submits injection payloads and asserts the raw text never appears in generated rows."""

from __future__ import annotations

import inspect

from app.llm import orchestrator
from app.visuals import ensure_visual


def test_generation_entry_takes_only_request_id():
    sig = inspect.signature(orchestrator.run_generation)
    params = list(sig.parameters)
    assert params == ["request_id"], (
        "run_generation must take ONLY a request_id — it loads the validated StructuredIntent from "
        "the DB and must never receive raw prompt text."
    )


def test_visual_entry_has_no_raw_text_param():
    sig = inspect.signature(ensure_visual)
    banned = {"raw", "raw_prompt", "prompt_text", "student_prompt", "user_prompt"}
    assert not (set(sig.parameters) & banned), "Visual pipeline must not accept raw student text."


def test_learning_request_has_no_raw_column():
    from app.models import LearningRequest

    cols = set(LearningRequest.__table__.columns.keys())
    assert "raw_prompt" not in cols and "prompt" not in cols, (
        "learning_requests must not store the raw prompt (SPEC §5)."
    )

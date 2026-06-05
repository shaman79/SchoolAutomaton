"""coerce_payload integrity gate: a question that can't be ANSWERED or GRADED correctly is rejected
(returns None) so it's dropped rather than shown to a learner. Guards the live bugs: a true/false
with no answer, an MCQ with no correct option (everything graded wrong), and a match/order with
mismatched items (impossible to complete)."""

from __future__ import annotations

import os

os.environ.setdefault("SA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("APP_SECRET", "test-secret-please-ignore")
os.environ.setdefault("SA_ENV", "test")

from app.schemas.enums import ItemType  # noqa: E402
from app.schemas.generation import coerce_payload  # noqa: E402


def test_mcq_without_a_correct_option_is_rejected():
    opts = [{"id": "a", "text": "x"}, {"id": "b", "text": "y"}]
    assert coerce_payload(ItemType.MCQ, {"options": opts}) is None  # nothing is_correct → all wrong
    ok = coerce_payload(ItemType.MCQ, {"options": [{"id": "a", "text": "x", "is_correct": True},
                                                   {"id": "b", "text": "y"}]})
    assert ok is not None and any(o["is_correct"] for o in ok["options"])


def test_true_false_requires_an_answer():
    assert coerce_payload(ItemType.TRUE_FALSE, {"statement": "s"}) is None  # missing answer
    ok = coerce_payload(ItemType.TRUE_FALSE, {"statement": "s", "answer": True})
    assert ok is not None and ok["answer"] is True


def test_match_needs_enough_tokens_and_full_coverage():
    # 2 prompts but only 1 token → impossible to complete → rejected.
    bad = {
        "left": [{"id": "l1", "text": "a"}, {"id": "l2", "text": "b"}],
        "right": [{"id": "r1", "text": "1"}],
        "correct": [{"left_id": "l1", "right_id": "r1"}],
    }
    assert coerce_payload(ItemType.MATCH, bad) is None
    good = {
        "left": [{"id": "l1", "text": "a"}, {"id": "l2", "text": "b"}],
        "right": [{"id": "r1", "text": "1"}, {"id": "r2", "text": "2"}],
        "correct": [{"left_id": "l1", "right_id": "r1"}, {"left_id": "l2", "right_id": "r2"}],
    }
    assert coerce_payload(ItemType.MATCH, good) is not None


def test_match_with_dangling_id_is_rejected():
    bad = {
        "left": [{"id": "l1", "text": "a"}],
        "right": [{"id": "r1", "text": "1"}, {"id": "r2", "text": "2"}],
        "correct": [{"left_id": "l1", "right_id": "rX"}],  # rX doesn't exist
    }
    assert coerce_payload(ItemType.MATCH, bad) is None


def test_order_requires_a_permutation_of_tokens():
    toks = [{"id": "t1", "text": "a"}, {"id": "t2", "text": "b"}]
    assert coerce_payload(ItemType.ORDER, {"tokens": toks, "correct_order": ["t1", "t3"]}) is None
    assert coerce_payload(ItemType.ORDER, {"tokens": toks, "correct_order": ["t2", "t1"]}) is not None


def test_hotspot_requires_image_and_a_correct_region():
    no_correct = {"image_request": "diagram",
                  "regions": [{"id": "r1", "shape": "rect", "coords": [0, 0, 1, 1]}]}
    assert coerce_payload(ItemType.HOTSPOT, no_correct) is None
    good = {"image_request": "diagram",
            "regions": [{"id": "r1", "shape": "rect", "coords": [0, 0, 1, 1], "is_correct": True}]}
    assert coerce_payload(ItemType.HOTSPOT, good) is not None


def test_valid_simple_types_pass():
    assert coerce_payload(ItemType.NUMERIC, {"answer": 42.0, "tolerance": 0.5}) is not None
    assert coerce_payload(ItemType.SHORT_ANSWER, {"placeholder": "your answer"}) is not None

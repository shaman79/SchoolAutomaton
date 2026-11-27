"""The answer-key check: a second model answers each new question WITHOUT its key; a question it
answers differently, or finds flawed, is dropped before anyone sees it — and the check never stops a
quiz or lesson from being made (fail-open). No network: a fake client plays the checker."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.llm import key_check
from app.schemas.enums import ItemType
from app.schemas.generation import GenItem, KeyCheckOutput


def _item(item_type: ItemType, payload: dict, *, stem: str = "Question?", explanation: str = "",
          variants: list[str] | None = None) -> GenItem:
    return GenItem(item_type=item_type, concept_slug="c", concept_name="C", bloom_tier=2,
                   stem_markdown=stem, payload=payload, explanation=explanation,
                   accepted_variants=variants or [])


def _mcq(correct: str, stem: str = "Pick one") -> GenItem:
    return _item(ItemType.MCQ, {"options": [{"id": "a", "text": "Apple", "is_correct": correct == "a"},
                                            {"id": "b", "text": "Banana", "is_correct": correct == "b"}]},
                 stem=stem, explanation="SECRET-EXPLANATION")


# The item the user found: the stem asserts a false "tip" (tobě and tebe have the same length) that
# leads to the statement; the key ("false") is right only because of that.
MNE_ME = _item(
    ItemType.TRUE_FALSE,
    {"statement": "Mně je delší tvar a odpovídá delšímu tobě, mě je kratší tvar a odpovídá kratšímu tebe.",
     "answer": False},
    stem="Tvar mně má tři písmena, kdežto tvar mě má jen dvě. Pomáhá to při zkoušce nahrazením slovem "
         "tobě (delší) a tebe (kratší).",
)


class _Checker:
    """A fake provider: answers with the given verdicts and records what it was shown."""

    def __init__(self, verdicts: list[dict] | None = None, error: Exception | None = None):
        self.seen: list[dict] = []
        out = KeyCheckOutput.model_validate({"verdicts": verdicts or []})

        async def create(**kwargs):
            self.seen.append(kwargs)
            if error is not None:
                raise error
            return SimpleNamespace(
                parsed_output=None, stop_reason="end_turn", id="msg_check",
                usage=SimpleNamespace(input_tokens=900, output_tokens=400,
                                      cache_creation_input_tokens=0, cache_read_input_tokens=0),
                content=[SimpleNamespace(type="text", text=out.model_dump_json())],
            )

        self.messages = SimpleNamespace(create=AsyncMock(side_effect=create))

    @property
    def user(self) -> str:
        return self.seen[-1]["messages"][0]["content"]


async def _check(items, checker, **kw):
    sink: list = []
    result = await key_check.check_items(items, subject="language_arts", grade_band="G3-5", language="cs",
                                         client=checker, usage_sink=sink, **kw)
    return result, sink


@pytest.mark.asyncio
async def test_a_question_answered_differently_from_its_key_is_dropped():
    right, wrong, other = _mcq("a"), _mcq("b"), _mcq("a")
    checker = _Checker([{"number": 1, "option_ids": ["a"]}, {"number": 2, "option_ids": ["a"]},
                        {"number": 3, "option_ids": ["a"]}])
    result, sink = await _check([right, wrong, other], checker)
    assert result.kept == [right, other]
    assert [g for g, _ in result.dropped] == [wrong]
    assert len(sink) == 1  # the call is billed: the caller logs it
    sent = checker.seen[-1]
    assert sent["model"] == settings.key_check_model_id
    assert sent["output_config"]["format"]["schema"]["title"] == "KeyCheckOutput"


@pytest.mark.asyncio
async def test_a_flawed_question_is_dropped_even_with_a_defensible_key():
    """The mně/mě item: "false" is technically right, but its stem states a false tip as fact."""
    keep = _mcq("a")
    checker = _Checker([
        {"number": 1, "truth": False, "flawed": True,
         "reason": "The stem claims tobě is longer than tebe; both have four letters."},
        {"number": 2, "option_ids": ["a"]},
    ])
    result, _ = await _check([MNE_ME, keep], checker)
    assert result.kept == [keep]
    assert "four letters" in result.dropped[0][1]


@pytest.mark.asyncio
async def test_the_checker_never_sees_the_key():
    order = _item(ItemType.ORDER, {"tokens": [{"id": "t1", "text": "zebra"}, {"id": "t2", "text": "apple"},
                                              {"id": "t3", "text": "mango"}],
                                   "correct_order": ["t1", "t2", "t3"]})
    match = _item(ItemType.MATCH, {"left": [{"id": "l1", "text": "dog"}, {"id": "l2", "text": "cat"}],
                                   "right": [{"id": "r1", "text": "woof"}, {"id": "r2", "text": "meow"}],
                                   "correct": [{"left_id": "l1", "right_id": "r1"},
                                               {"left_id": "l2", "right_id": "r2"}]})
    numeric = _item(ItemType.NUMERIC, {"answer": 4217.5, "tolerance": 0, "unit": "kg"})
    cloze = _item(ItemType.CLOZE, {"text_template": "Ten b{{b1}}k je velký.",
                                   "blanks": [{"id": "b1", "answer": "ý"}]}, variants=["ý"])
    checker = _Checker([])
    await _check([_mcq("b"), MNE_ME, order, match, numeric, cloze], checker)
    user = checker.user
    for leaked in ("is_correct", "SECRET-EXPLANATION", "correct_order", '"answer"', "4217.5", "correct:"):
        assert leaked not in user
    # Order tokens and match answers are shown in an order that gives nothing away (alphabetical).
    assert user.index("apple") < user.index("mango") < user.index("zebra")
    assert user.index("meow") < user.index("woof")
    # The learner's view is all there.
    assert "Ten b{{b1}}k je velký." in user and "unit: kg" in user and "tobě (delší)" in user


@pytest.mark.asyncio
async def test_each_type_is_compared_with_its_key():
    tf = _item(ItemType.TRUE_FALSE, {"statement": "2 + 2 = 4", "answer": True})
    num = _item(ItemType.NUMERIC, {"answer": 0.5, "tolerance": 0.01})
    order = _item(ItemType.ORDER, {"tokens": [{"id": "t1", "text": "a"}, {"id": "t2", "text": "b"}],
                                   "correct_order": ["t1", "t2"]})
    match = _item(ItemType.MATCH, {"left": [{"id": "l1", "text": "x"}], "right": [{"id": "r1", "text": "y"},
                                   {"id": "r2", "text": "z"}], "correct": [{"left_id": "l1", "right_id": "r1"}]})
    cloze_ok = _item(ItemType.CLOZE, {"text_template": "b{{b1}}k", "blanks": [{"id": "b1", "answer": "ý"}]})
    # The key says "y", but the word is "býk": a learner typing the right letter would be marked wrong.
    cloze_bad = _item(ItemType.CLOZE, {"text_template": "b{{b1}}k", "blanks": [{"id": "b1", "answer": "y"}]})
    checker = _Checker([
        {"number": 1, "truth": True},
        {"number": 2, "value": 0.505},  # within the tolerance
        {"number": 3, "order": ["t2", "t1"]},  # disagrees
        {"number": 4, "pairs": [{"left_id": "l1", "right_id": "r1"}]},
        {"number": 5, "blanks": [{"id": "b1", "answers": ["Ý"]}]},  # case and spacing don't matter
        {"number": 6, "blanks": [{"id": "b1", "answers": ["ý"]}]},
    ])
    result, _ = await _check([tf, num, order, match, cloze_ok, cloze_bad], checker)
    assert result.kept == [tf, num, match, cloze_ok]
    assert {id(g) for g, _ in result.dropped} == {id(order), id(cloze_bad)}


@pytest.mark.asyncio
async def test_no_answer_or_no_verdict_keeps_the_question():
    a, b = _mcq("a"), _mcq("b")
    checker = _Checker([{"number": 1}])  # nothing to compare for 1, no verdict at all for 2
    result, _ = await _check([a, b], checker)
    assert result.kept == [a, b] and result.ran


@pytest.mark.asyncio
async def test_fail_open_on_any_error():
    items = [_mcq("a"), MNE_ME]
    result, sink = await _check(items, _Checker(error=RuntimeError("provider down")))
    assert result.kept == items and not result.ran and result.note.startswith("failed")


@pytest.mark.asyncio
async def test_a_check_that_rejects_nearly_everything_is_not_trusted():
    items = [_mcq("a") for _ in range(4)]
    checker = _Checker([{"number": n, "option_ids": ["b"]} for n in range(1, 4)])  # 3 of 4 "wrong"
    result, _ = await _check(items, checker, min_keep=3)
    assert result.kept == items and result.note == "too many flagged; kept all"
    # Without a floor (a lesson part), the flagged ones go.
    result, _ = await _check(items, _Checker([{"number": n, "option_ids": ["b"]} for n in range(1, 4)]))
    assert result.kept == items[3:]


@pytest.mark.asyncio
async def test_off_or_nothing_to_check_makes_no_call(monkeypatch):
    hotspot = _item(ItemType.HOTSPOT, {"image_request": "a leaf", "regions": [
        {"id": "r1", "shape": "rect", "coords": [0, 0, 1, 1], "is_correct": True}]})
    checker = _Checker([])
    result, _ = await _check([hotspot], checker)  # pictures aren't checked
    assert result.kept == [hotspot] and not checker.seen
    monkeypatch.setattr(settings, "key_check_model_id", "")
    result, _ = await _check([_mcq("a")], checker)
    assert not checker.seen and result.note == "off"


def test_the_instructions_are_static_and_name_the_flaws():
    """A cached, byte-identical prefix (no per-request data), stating the defects to look for."""
    text = key_check.SYSTEM_PROMPT
    assert "{" not in text.replace("{left_id, right_id}", "")
    for phrase in ("partly true and partly false", "asserts, hints at or presupposes", "is false"):
        assert phrase in text
    json.dumps(KeyCheckOutput.model_json_schema())  # serializable schema

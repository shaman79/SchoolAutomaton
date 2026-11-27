"""Answer-key check eval: does the second model catch bad questions without dropping good ones?

From ``backend/`` (the API key is read from the repo's ``.env``, like the app does):

    python -m evals.key_check                      # the configured model and effort
    python -m evals.key_check --model claude-opus-5-5 --effort low --out v-opus-low

Two sets:
  * **planted** — hand-written questions with a known defect (a wrong key, a false "fact" in the
    stem, a half-true statement, the mně/mě item a parent reported) plus a few correct controls.
    Recall: every defective one must be dropped; precision: no control may be.
  * **stored** — every quiz kept from the model-migration eval runs
    (``.claude/hillclimb/mm-generation/*/outputs``), reviewed when they were made. A question
    dropped here is a likely false alarm — each is printed with the checker's reason for a human to
    judge. (Re-runs of one case share topics, so this is ~15 quizzes, not 15 independent ones.)

Results: ``.claude/hillclimb/key-check/<out>/results.jsonl`` (one line per quiz) + a printed summary.
Cost: ~$0.30 with the default (Opus 5.5 at medium); a few cents with Haiku 5.5.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="sa-keycheck-eval-"))
os.environ.setdefault("SA_DATABASE_URL", f"sqlite+aiosqlite:///{_TMP / 'eval.db'}")
os.environ.setdefault("SA_DATA_DIR", str(_TMP / "data"))
os.environ.setdefault("SA_DEBUG", "false")

from app.core.config import settings  # noqa: E402
from app.core.pricing import estimate_cost_usd  # noqa: E402
from app.llm import key_check  # noqa: E402
from app.schemas.enums import ItemType  # noqa: E402
from app.schemas.generation import GenItem  # noqa: E402

from .model_migration import cases as C  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
STORED = REPO / ".claude" / "hillclimb" / "mm-generation"
OUT_ROOT = REPO / ".claude" / "hillclimb" / "key-check"


def _gen(item_type: str, stem: str, payload: dict, *, expected: str | None = None,
         variants: list[str] | None = None) -> GenItem:
    return GenItem(item_type=ItemType(item_type), concept_slug="eval", concept_name="Eval",
                   bloom_tier=2, stem_markdown=stem, payload=payload, expected_answer=expected,
                   accepted_variants=variants or [])


def _mcq(stem: str, options: list[str], correct: int) -> dict:
    return {"options": [{"id": chr(97 + i), "text": t, "is_correct": i == correct}
                        for i, t in enumerate(options)]}


# (label, defective?, item) — context per group below.
PLANTED_CS = [
    ("mne-me reported", True, _gen(
        "true_false",
        "Tvar mně má tři písmena, kdežto tvar mě má jen dvě. Pomáhá to při zkoušce nahrazením "
        "slovem tobě (delší) a tebe (kratší).",
        {"statement": "Mně je delší tvar a odpovídá delšímu tobě, mě je kratší tvar a odpovídá "
                      "kratšímu tebe.", "answer": False})),
    ("tf wrong key (býk)", True, _gen(
        "true_false", "Rozhodni, zda platí:",
        {"statement": "Slovo býk patří mezi vyjmenovaná slova po B.", "answer": False})),
    ("tf half true", True, _gen(
        "true_false", "Je toto tvrzení pravdivé?",
        {"statement": "Slovo bydlit je vyjmenované slovo po B a slovo bílý také.", "answer": True})),
    ("cloze key y, word býk", True, _gen(
        "cloze", "Doplň správné písmeno.",
        {"text_template": "Na louce se pásl b{{b1}}k.", "blanks": [{"id": "b1", "answer": "y",
                                                                    "choices": ["y", "i"]}]})),
    ("mcq wrong key 7x8", True, _gen(
        "mcq", "Kolik je 7 · 8?", _mcq("", ["54", "56", "63"], 0))),
    ("mcq stem false fact", True, _gen(
        "mcq", "Slovo „mlýn“ má pět písmen. Které písmeno v něm píšeme po L?",
        _mcq("", ["ý", "í"], 0))),
    ("numeric wrong key 7x9", True, _gen("numeric", "Kolik je 7 · 9?", {"answer": 64, "tolerance": 0})),
    ("control tf mně", False, _gen(
        "true_false", "Je tato věta napsaná správně?",
        {"statement": "Dej mně tu knížku.", "answer": True})),
    ("control mcq 7x8", False, _gen("mcq", "Kolik je 7 · 8?", _mcq("", ["54", "56", "63"], 1))),
    ("control cloze býk", False, _gen(
        "cloze", "Doplň správné písmeno.",
        {"text_template": "Na louce se pásl b{{b1}}k.", "blanks": [{"id": "b1", "answer": "ý",
                                                                    "choices": ["ý", "í"]}]})),
    ("control order", False, _gen(
        "order", "Seřaď čísla od nejmenšího.",
        {"tokens": [{"id": "t1", "text": "7"}, {"id": "t2", "text": "14"}, {"id": "t3", "text": "21"}],
         "correct_order": ["t1", "t2", "t3"]})),
]
PLANTED_EN = [
    ("mcq wrong key planet", True, _gen(
        "mcq", "Which is the largest planet in the solar system?", _mcq("", ["Saturn", "Jupiter", "Earth"], 0))),
    ("match wrong key", True, _gen(
        "match", "Match each country to its capital.",
        {"left": [{"id": "l1", "text": "France"}, {"id": "l2", "text": "Italy"}],
         "right": [{"id": "r1", "text": "Paris"}, {"id": "r2", "text": "Rome"}],
         "correct": [{"left_id": "l1", "right_id": "r2"}, {"left_id": "l2", "right_id": "r1"}]})),
    ("tf stem asserts it", True, _gen(
        "true_false", "Remember: the Treaty of Versailles was signed in 1919, ending the war's "
        "fighting at once. True or false?",
        {"statement": "The Treaty of Versailles was signed in 1919.", "answer": True})),
    ("control match", False, _gen(
        "match", "Match each country to its capital.",
        {"left": [{"id": "l1", "text": "France"}, {"id": "l2", "text": "Italy"}],
         "right": [{"id": "r1", "text": "Paris"}, {"id": "r2", "text": "Rome"}],
         "correct": [{"left_id": "l1", "right_id": "r1"}, {"left_id": "l2", "right_id": "r2"}]})),
    ("control numeric", False, _gen(
        "numeric", "A rectangle is 4 cm wide and 6 cm long. What is its area?",
        {"answer": 24, "tolerance": 0, "unit": "cm²"})),
]


def _stored_quizzes() -> list[tuple[str, dict, list[GenItem]]]:
    """(name, intent, items) for every stored quiz output."""
    intents = {c["id"]: c["intent"] for c in C.GENERATION_CASES}
    out = []
    for f in sorted(STORED.glob("*/outputs/gen-*.json")):
        data = json.loads(f.read_text())
        if "questions" not in data:
            continue
        items = []
        for q in data["questions"]:
            try:
                items.append(_gen(q["type"], q["stem"], q["payload"], expected=q.get("expected")))
            except Exception:  # noqa: BLE001 - an old shape: skip it
                continue
        out.append((f"{f.parts[-3]}/{f.stem}", intents[f.stem], items))
    return out


async def _run(label: str, intent: dict, items: list[GenItem]) -> dict:
    sink: list = []
    started = time.monotonic()
    result = await key_check.check_items(
        items, subject=intent["subject"], grade_band=intent["grade_band"], language=intent["language"],
        usage_sink=sink)
    cost = sum(estimate_cost_usd(u.model, input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                                 cache_read_tokens=u.cache_read_tokens,
                                 cache_creation_tokens=u.cache_creation_tokens) or 0 for u in sink)
    return {
        "label": label, "ran": result.ran, "note": result.note, "checked": result.checked,
        "items": len(items), "seconds": round(time.monotonic() - started, 1), "cost_usd": round(cost, 5),
        "dropped": [{"index": items.index(g), "type": g.item_type.value, "stem": g.stem_markdown[:160],
                     "payload": g.payload, "reason": r} for g, r in result.dropped],
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    ap.add_argument("--effort", default=None)
    ap.add_argument("--out", default="current")
    ap.add_argument("--sets", default="planted,stored")
    a = ap.parse_args()
    if a.model:
        settings.key_check_model_id = a.model
    if a.effort:
        key_check._EFFORT = a.effort
    out_dir = OUT_ROOT / a.out
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"model={settings.key_check_model_id} effort={key_check._EFFORT}")

    rows = []
    if "planted" in a.sets:
        for name, planted, intent in (
            ("planted-cs", PLANTED_CS, {"subject": "language_arts", "grade_band": "G3-5", "language": "cs"}),
            ("planted-en", PLANTED_EN, {"subject": "history", "grade_band": "G6-8", "language": "en"}),
        ):
            items = [g for _, _, g in planted]
            row = await _run(name, intent, items)
            dropped = {d["index"] for d in row["dropped"]}
            row["planted"] = [{"label": lbl, "defective": bad, "dropped": i in dropped}
                              for i, (lbl, bad, _) in enumerate(planted)]
            rows.append(row)
            for p in row["planted"]:
                ok = p["dropped"] == p["defective"]
                print(f"  {'✓' if ok else '✗'} {name}: {p['label']} -> {'dropped' if p['dropped'] else 'kept'}")
    if "stored" in a.sets:
        quizzes = _stored_quizzes()
        results = await asyncio.gather(*(_run(n, i, items) for n, i, items in quizzes))
        for row in results:
            rows.append(row)
            print(f"  {row['label']}: {len(row['dropped'])}/{row['items']} dropped "
                  f"({row['seconds']}s, ${row['cost_usd']}) {row['note']}")
            for d in row["dropped"]:
                print(f"      - [{d['index']}] {d['type']}: {d['stem'][:110]!r}\n        {d['reason'][:240]}")

    with (out_dir / "results.jsonl").open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    planted = [p for r in rows for p in r.get("planted", [])]
    if planted:
        caught = sum(p["dropped"] for p in planted if p["defective"])
        false_alarms = sum(p["dropped"] for p in planted if not p["defective"])
        print(f"planted: caught {caught}/{sum(p['defective'] for p in planted)}, "
              f"false alarms {false_alarms}/{sum(not p['defective'] for p in planted)}")
    stored = [r for r in rows if "planted" not in r]
    if stored:
        print(f"stored: dropped {sum(len(r['dropped']) for r in stored)}/{sum(r['items'] for r in stored)} "
              f"questions in {len(stored)} quizzes; max {max(r['seconds'] for r in stored)}s per quiz")
    print(f"total cost ${round(sum(r['cost_usd'] for r in rows), 4)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

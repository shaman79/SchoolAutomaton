"""Model-migration eval: run the app's real AI paths on fixed cases with one model set, grade them.

From ``backend/`` (the API key is read from the repo's ``.env``, like the app does):

    python -m evals.model_migration.run --variant baseline --opus claude-opus-4-8 --haiku claude-haiku-4-5
    python -m evals.model_migration.run --variant v1 --opus claude-opus-5-5 --haiku claude-haiku-5-5 \
        --efforts plan=medium,section=medium,quiz=medium,grader=low,svg=medium

    options: --flows classifier,grader,generation,svg   --limit N (first N cases per flow)
             --concurrency 4   --dry-run (print the plan, call nothing)

Each flow goes through the same entry point production uses (sanitize_request, generate_lesson /
generate_quiz, grade_free_text, generate_svg) — only the model ids (and, with --efforts, the effort
per call site) are swapped. Visual provider calls inside generation are stubbed (pictures have their
own flow). Results: ``.claude/hillclimb/mm-<flow>/<variant>/results.jsonl`` + ``traces/`` +
``errors.jsonl``; a re-run resumes (cases already in results.jsonl are skipped).
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import json
import os
import re
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

# The app reads its settings at import: point it at a throwaway database first.
_TMP = Path(tempfile.mkdtemp(prefix="sa-mm-eval-"))
os.environ.setdefault("SA_DATABASE_URL", f"sqlite+aiosqlite:///{_TMP / 'eval.db'}")
os.environ.setdefault("SA_DATA_DIR", str(_TMP / "data"))
os.environ.setdefault("SA_ENV", "development")
os.environ.setdefault("SA_DEBUG", "false")
os.environ.setdefault("SA_DAILY_BUDGET_USD", "0")  # the eval must not trip the app's own cap

from sqlalchemy import select  # noqa: E402

from app.api.deps import RequestContext  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.pricing import estimate_cost_usd  # noqa: E402
from app.db.bootstrap import bootstrap  # noqa: E402
from app.db.session import SessionLocal, init_db  # noqa: E402
from app.llm import client as llm_client  # noqa: E402
from app.llm import grader as grader_mod  # noqa: E402
from app.llm import lesson_generator, quiz_generator  # noqa: E402
from app.models import Item, LearningRequest, LessonSection, QuizQuestion  # noqa: E402
from app.sanitization import ratelimit, sanitize_request  # noqa: E402
from app.schemas.enums import VisualKind  # noqa: E402
from app.schemas.generation import GenVisualSpec  # noqa: E402
from app.schemas.intent import ProceedDecision, StructuredIntent  # noqa: E402

from . import cases as C  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
OUT_ROOT = REPO / ".claude" / "hillclimb"
EFFORT_KEYS = {  # --efforts key -> the structured output model of that call site
    "plan": "LessonPlan", "section": "GenSection", "quiz": "GenQuiz",
    "grader": "GraderOutput", "svg": "SvgGenerationOutput", "classifier": "StructuredIntent",
}
CEILING_S = {"classifier": 90, "grader": 120, "generation": 900, "svg": 240}

_calls: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar("calls", default=None)


# --------------------------------------------------------------------------- instrumentation
def _instrument(efforts: dict[str, str]) -> None:
    """Record every model call (served model, usage, time) per case, and apply effort overrides.
    Patched where each call site looks the function up."""
    original = llm_client.generate_structured

    async def recorded(**kw: Any):
        name = kw["output_model"].__name__
        for key, model_name in EFFORT_KEYS.items():
            if model_name == name and key in efforts:
                kw["effort"] = efforts[key]
        sink: list = []
        callers_sink = kw.get("usage_sink")
        kw["usage_sink"] = sink
        started = time.monotonic()
        try:
            return await original(**kw)
        finally:
            if callers_sink is not None:
                callers_sink.extend(sink)
            log = _calls.get()
            if log is not None:
                log.append({
                    "call": name, "effort": kw.get("effort"), "requested": kw.get("model"),
                    "seconds": round(time.monotonic() - started, 2),
                    "attempts": [
                        {"model": u.model, "input": u.input_tokens, "output": u.output_tokens,
                         "cache_read": u.cache_read_tokens, "cache_write": u.cache_creation_tokens,
                         "cost_usd": estimate_cost_usd(
                             u.model, input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                             cache_read_tokens=u.cache_read_tokens,
                             cache_creation_tokens=u.cache_creation_tokens)}
                        for u in sink
                    ],
                })

    llm_client.generate_structured = recorded
    lesson_generator.generate_structured = recorded
    quiz_generator.generate_structured = recorded
    grader_mod.generate_structured = recorded


def _no_pictures_inside_generation() -> None:
    """Hotspot pictures are provider calls of their own (the svg flow covers SVGs); a failing
    ensure_visual is already handled by generation (the hotspot item is dropped)."""
    import app.visuals as visuals

    async def _off(*_a, **_k):
        raise RuntimeError("pictures are not part of the generation eval")

    visuals.ensure_visual = _off


def _usage_summary(calls: list[dict]) -> dict:
    attempts = [a for c in calls for a in c["attempts"]]
    costs = [a["cost_usd"] for a in attempts if a["cost_usd"] is not None]
    return {
        "model_calls": len(attempts),
        "validation_retries": sum(max(0, len(c["attempts"]) - 1) for c in calls),
        "input_tokens": sum(a["input"] for a in attempts),
        "output_tokens": sum(a["output"] for a in attempts),
        "cache_read_tokens": sum(a["cache_read"] for a in attempts),
        "cost_usd": round(sum(costs), 5) if costs else None,
        "served_by": sorted({a["model"] for a in attempts}),
    }


# --------------------------------------------------------------------------- flows
_CS = re.compile(r"[ěščřžýáíéůúťďňĚŠČŘŽÝÁÍÉŮÚŤĎŇ]")


async def run_classifier(case: dict) -> tuple[dict, list[dict]]:
    ratelimit.limiter.reset()
    ctx = RequestContext(ip_hash=f"eval-{case['id']}", user_agent="eval", profile_id=None)
    locale = "cs-CZ" if "cs" in case["tags"] else "en-GB"
    async with SessionLocal() as db:
        decision = await sanitize_request(db, case["prompt"], ctx, f"eval-{case['id']}",
                                          client_locale=locale)
        await db.commit()
    got = decision.type.value
    topic = decision.intent.topic if isinstance(decision, ProceedDecision) else ""
    exp = case["expected"]
    grade: dict[str, Any] = {"route": got}
    if exp == "proceed":
        grade["route_ok"] = got == "proceed"
        grade["mode_ok"] = got == "proceed" and decision.mode.value == case["mode"]
        grade["topic_ok"] = got == "proceed" and any(k in topic.lower() for k in case["topic"])
        grade["pass"] = int(grade["route_ok"] and grade["mode_ok"] and grade["topic_ok"])
    elif exp == "injection":
        grade["pass"] = int(got != "proceed" or topic == "")
    else:
        grade["pass"] = int(got == exp)
    turns = [{"role": "user", "content": case["prompt"]},
             {"role": "assistant", "content": decision.model_dump_json(indent=2)}]
    return {"grade": grade, "output": {"route": got, "topic": topic}}, turns


async def run_grader(case: dict) -> tuple[dict, list[dict]]:
    item = dict(case["item"])
    out = await grader_mod.grade_free_text(item, case["answer"], item["language"])
    grade = {"pass": int(bool(out.correct) == case["expected"]), "said_correct": bool(out.correct),
             "false_accept": int(out.correct and not case["expected"]),
             "false_reject": int(not out.correct and case["expected"])}
    turns = [{"role": "user", "content": f"{item['stem_markdown']}\n\nANSWER: {case['answer']}"},
             {"role": "assistant", "content": out.model_dump_json(indent=2)}]
    return {"grade": grade, "output": out.model_dump()}, turns


def _item_view(it: Item) -> dict:
    return {"type": it.item_type, "stem": it.stem_markdown, "payload": it.payload_json,
            "expected": it.expected_answer, "explanation": it.explanation,
            "hints": it.hint_ladder_json}


async def run_generation(case: dict, variant: str) -> tuple[dict, list[dict]]:
    intent = StructuredIntent.model_validate(case["intent"])
    rid = f"eval-{variant}-{case['id']}"
    async with SessionLocal() as db:
        lr = LearningRequest(request_id=rid, decision_type="proceed", mode=intent.mode.value,
                             structured_intent_json=intent.model_dump(mode="json"),
                             detected_language=intent.language, grade_band=intent.grade_band.value,
                             status="generating", prompt_version="eval", model_id=settings.model_id)
        db.add(lr)
        await db.commit()
        if intent.mode.value == "study":
            lesson = await lesson_generator.generate_lesson(db, lr, intent)
            await db.commit()
            first = await db.scalar(select(LessonSection).where(
                LessonSection.lesson_id == lesson.id, LessonSection.ordinal == 0))
            items = list(await db.scalars(select(Item).where(Item.lesson_section_id == first.id)))
            content = {"plan": lesson.plan_json, "first_section": {
                "kind": first.kind, "title": first.title, "body": first.body_markdown,
                "items": [_item_view(i) for i in items]}}
            text = (first.body_markdown or "") + " ".join(i.stem_markdown for i in items)
        else:
            quiz = await quiz_generator.generate_quiz(db, lr, intent)
            await db.commit()
            rows = list(await db.scalars(
                select(Item).join(QuizQuestion, QuizQuestion.item_id == Item.id)
                .where(QuizQuestion.quiz_id == quiz.id).order_by(QuizQuestion.ordinal)))
            content = {"quiz_title": quiz.title, "questions": [_item_view(i) for i in rows]}
            items = rows
            text = " ".join(i.stem_markdown for i in rows)
    czech_ratio = len(_CS.findall(text)) / max(1, len(text))
    lang_ok = czech_ratio > 0.01 if intent.language == "cs" else czech_ratio < 0.002
    grade = {"pass": int(bool(items) and lang_ok), "items": len(items), "language_ok": lang_ok}
    turns = [{"role": "user", "content": json.dumps(case["intent"], ensure_ascii=False)},
             {"role": "assistant", "content": json.dumps(content, ensure_ascii=False, indent=2)}]
    return {"grade": grade, "output": content}, turns


async def run_svg(case: dict) -> tuple[dict, list[dict]]:
    from app.visuals import claude_svg

    spec = GenVisualSpec(section_ordinal=0, visual_kind=VisualKind.DIAGRAM,
                         svg_request=case["request"], alt_text=case["alt"])
    out = await claude_svg.generate_svg(spec, language=case["language"], grade_band=case["grade_band"])
    svg = out.get("svg") or ""
    grade = {"pass": int(svg.startswith("<svg") and "<text" in svg), "bytes": len(svg),
             "labels": svg.count("<text")}
    turns = [{"role": "user", "content": case["request"]},
             {"role": "assistant", "content": svg}]
    return {"grade": grade, "output": {"bytes": len(svg)}}, turns


FLOWS = {
    "classifier": (C.CLASSIFIER_CASES, run_classifier),
    "grader": (C.GRADER_CASES, run_grader),
    "generation": (C.GENERATION_CASES, run_generation),
    "svg": (C.SVG_CASES, run_svg),
}


def _failure_class(exc: BaseException) -> str:
    if isinstance(exc, llm_client.RefusalError):
        return "refusal"
    if isinstance(exc, TimeoutError | asyncio.TimeoutError):
        return "timeout"
    if isinstance(exc, llm_client.GenerationError):
        return "genuine_failure"
    return "harness_or_serving_error"


async def run_case(flow: str, case: dict, variant: str, out: Path, sem: asyncio.Semaphore) -> None:
    async with sem:
        calls: list[dict] = []
        _calls.set(calls)
        fn = FLOWS[flow][1]
        started = time.monotonic()
        try:
            coro = fn(case, variant) if flow == "generation" else fn(case)
            result, turns = await asyncio.wait_for(coro, timeout=CEILING_S[flow])
        except Exception as exc:  # noqa: BLE001 — every failure is recorded, never a silent 0
            row = {"prompt_id": case["id"], "rep": 0, "failure_class": _failure_class(exc),
                   "error": f"{type(exc).__name__}: {str(exc)[:400]}",
                   "seconds": round(time.monotonic() - started, 1), "usage": _usage_summary(calls),
                   "calls": calls}
            if isinstance(exc, llm_client.RefusalError):
                row["refusal_category"] = exc.category
            with (out / "errors.jsonl").open("a") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"  ✗ {flow}/{case['id']}: {row['failure_class']} {row['error'][:120]}")
            if os.environ.get("MM_TRACEBACKS"):
                traceback.print_exc()
            return
        usage = _usage_summary(calls)
        row = {
            "prompt_id": case["id"], "rep": 0, "tags": case.get("tags", []),
            "prompt": case.get("prompt") or case.get("answer") or case.get("request")
            or json.dumps(case.get("intent"), ensure_ascii=False),
            "status": "ok", "grade": result["grade"], "latency_s": round(time.monotonic() - started, 2),
            **usage, "calls": calls,
        }
        (out / "traces").mkdir(parents=True, exist_ok=True)
        (out / "traces" / f"{case['id']}_rep0.json").write_text(
            json.dumps(turns, ensure_ascii=False, indent=2))
        if flow == "generation":
            (out / "outputs").mkdir(exist_ok=True)
            (out / "outputs" / f"{case['id']}.json").write_text(
                json.dumps(result["output"], ensure_ascii=False, indent=2))
        with (out / "results.jsonl").open("a") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        mark = "✓" if result["grade"].get("pass") else "·"
        print(f"  {mark} {flow}/{case['id']}  {row['latency_s']}s  ${usage['cost_usd']}  "
              f"{usage['served_by']}  {json.dumps(result['grade'], ensure_ascii=False)[:140]}")


def _done_ids(out: Path) -> set[str]:
    path = out / "results.jsonl"
    if not path.exists():
        return set()
    return {json.loads(line)["prompt_id"] for line in path.read_text().splitlines() if line.strip()}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True, help="baseline | v1 | v2 ...")
    ap.add_argument("--opus", required=True)
    ap.add_argument("--haiku", required=True)
    ap.add_argument("--efforts", default="", help="e.g. plan=medium,section=low,grader=low")
    ap.add_argument("--flows", default="classifier,grader,generation,svg")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not re.fullmatch(r"baseline|v\d+", a.variant):
        print("--variant must be 'baseline' or v<N>", file=sys.stderr)
        return 2
    efforts = dict(kv.split("=", 1) for kv in a.efforts.split(",") if kv)
    unknown = set(efforts) - set(EFFORT_KEYS)
    if unknown:
        print(f"unknown --efforts keys: {sorted(unknown)}", file=sys.stderr)
        return 2
    flows = [f for f in a.flows.split(",") if f]
    plan = {f: FLOWS[f][0][: a.limit or None] for f in flows}
    print(f"variant={a.variant} opus={a.opus} haiku={a.haiku} efforts={efforts or 'code defaults'}")
    for f, cs in plan.items():
        print(f"  {f}: {len(cs)} case(s)")
    if a.dry_run:
        return 0
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set (put it in the repo's .env)", file=sys.stderr)
        return 2
    settings.model_id = a.opus
    settings.sanitizer_model_id = a.haiku
    _instrument(efforts)
    _no_pictures_inside_generation()
    await init_db()
    async with SessionLocal() as db:
        await bootstrap(db)
        await db.commit()
    sem = asyncio.Semaphore(a.concurrency)
    for f, cs in plan.items():
        out = OUT_ROOT / f"mm-{f}" / a.variant
        out.mkdir(parents=True, exist_ok=True)
        (out / "run.json").write_text(json.dumps(
            {"opus": a.opus, "haiku": a.haiku, "efforts": efforts}, indent=2))
        done = _done_ids(out)
        todo = [c for c in cs if c["id"] not in done]
        print(f"[{f}] {len(todo)} to run ({len(done)} already done) -> {out}")
        await asyncio.gather(*(run_case(f, c, a.variant, out, sem) for c in todo))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

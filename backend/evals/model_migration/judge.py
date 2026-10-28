"""Blind pairwise judge for the generation flow: which of two variants made the better lesson/quiz?

    python -m evals.model_migration.judge --a baseline --b v1 [--judge claude-sonnet-5-5]

Each case is judged twice, once in each order (A/B swapped), so a judge that prefers whichever comes
first can't decide the result; a variant "wins" a case only when both orders agree. Criteria: factual
accuracy, fit for the stated school year, teaching quality, question quality (one unambiguous correct
answer, a correct key, plausible distractors), language. Left out on purpose: length and formatting
style (longer isn't better for children), and anything about pictures (their own flow).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from app.core.config import settings

from . import cases as C

ROOT = Path(__file__).resolve().parents[3] / ".claude" / "hillclimb" / "mm-generation"

SYSTEM = (
    "You review learning materials an AI tutor generated for school children. You compare two "
    "candidates made for the same request and decide which one a careful teacher would rather give "
    "the child. Judge only what is on the page."
)

RUBRIC = """Compare candidate A and candidate B for the request below. Criteria, most important first:
1. Factual accuracy - any wrong fact, wrong worked step, or wrong answer key is a serious flaw.
2. Questions - each has exactly one defensible correct answer, the key matches it, distractors are
   plausible and reflect real misconceptions, nothing is ambiguous or trick-worded.
3. Fit for the stated school year and age - vocabulary, difficulty, examples.
4. Teaching quality - clear explanation, builds understanding step by step, matches the objectives.
5. Language - correct, natural text in the requested language (Czech diacritics and grammar matter).
Do NOT prefer a candidate for being longer or more elaborately formatted.

REQUEST (the validated intent the generator received):
{intent}

CANDIDATE A:
{a}

CANDIDATE B:
{b}
"""


class Verdict(BaseModel):
    factual_errors_a: list[str] = Field(description="Concrete factual/answer-key errors in A (empty if none)")
    factual_errors_b: list[str] = Field(description="Concrete factual/answer-key errors in B (empty if none)")
    question_problems_a: list[str]
    question_problems_b: list[str]
    reasoning: str = Field(description="Two to four sentences comparing them on the criteria")
    winner: Literal["A", "B", "tie"]


async def judge_once(cli, model: str, intent: dict, first: dict, second: dict) -> Verdict:
    msg = await cli.messages.parse(
        model=model,
        max_tokens=16000,
        system=SYSTEM,
        output_config={"effort": "medium"},
        output_format=Verdict,
        messages=[{"role": "user", "content": RUBRIC.format(
            intent=json.dumps(intent, ensure_ascii=False, indent=2),
            a=json.dumps(first, ensure_ascii=False, indent=2),
            b=json.dumps(second, ensure_ascii=False, indent=2))}],
    )
    if msg.stop_reason == "refusal" or msg.parsed_output is None:
        raise RuntimeError(f"judge gave no verdict (stop_reason={msg.stop_reason})")
    return msg.parsed_output


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="baseline")
    ap.add_argument("--b", default="v1")
    ap.add_argument("--judge", default="claude-sonnet-5-5")
    args = ap.parse_args()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 2
    cli = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=3)
    out_path = ROOT / f"judge-{args.a}-vs-{args.b}.jsonl"
    rows = []
    for case in C.GENERATION_CASES:
        pa = ROOT / args.a / "outputs" / f"{case['id']}.json"
        pb = ROOT / args.b / "outputs" / f"{case['id']}.json"
        if not (pa.exists() and pb.exists()):
            print(f"  - {case['id']}: missing output in one variant, skipped")
            continue
        a, b = json.loads(pa.read_text()), json.loads(pb.read_text())
        ab, ba = await asyncio.gather(
            judge_once(cli, args.judge, case["intent"], a, b),
            judge_once(cli, args.judge, case["intent"], b, a),
        )
        # Map the swapped run back to the A/B variant names.
        first = {"A": args.a, "B": args.b, "tie": "tie"}[ab.winner]
        second = {"A": args.b, "B": args.a, "tie": "tie"}[ba.winner]
        result = first if first == second else "tie"
        row = {"case": case["id"], "result": result, "order_ab": first, "order_ba": second,
               f"errors_{args.a}": ab.factual_errors_a + ba.factual_errors_b,
               f"errors_{args.b}": ab.factual_errors_b + ba.factual_errors_a,
               f"question_problems_{args.a}": ab.question_problems_a + ba.question_problems_b,
               f"question_problems_{args.b}": ab.question_problems_b + ba.question_problems_a,
               "reasoning_ab": ab.reasoning, "reasoning_ba": ba.reasoning}
        rows.append(row)
        print(f"  {case['id']}: {result}  (A-first: {first}, B-first: {second})")
    out_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    wins = {k: sum(r["result"] == k for r in rows) for k in (args.a, args.b, "tie")}
    print(f"{args.a} wins {wins[args.a]}, {args.b} wins {wins[args.b]}, ties {wins['tie']}  -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

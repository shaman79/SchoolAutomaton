"""Side-by-side summary of the model-migration eval variants (markdown to stdout).

    python -m evals.model_migration.summary [baseline v1 v2 ...]
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / ".claude" / "hillclimb"
FLOWS = ("classifier", "grader", "generation", "svg")


def _rows(flow: str, variant: str, name: str) -> list[dict]:
    path = ROOT / f"mm-{flow}" / variant / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _fmt(x, nd=2):
    return "-" if x is None else f"{x:.{nd}f}"


def main(variants: list[str]) -> None:
    for flow in FLOWS:
        print(f"\n### {flow}\n")
        print("| variant | models | cases ok | errors | pass | median s | p90 s | $/case | $ total |")
        print("|---|---|---|---|---|---|---|---|---|")
        per_tag: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
        for v in variants:
            rows = _rows(flow, v, "results.jsonl")
            errs = _rows(flow, v, "errors.jsonl")
            if not rows and not errs:
                continue
            run = ROOT / f"mm-{flow}" / v / "run.json"
            meta = json.loads(run.read_text()) if run.exists() else {}
            models = meta.get("haiku") if flow == "classifier" else meta.get("opus")
            if meta.get("efforts"):
                models = f"{models} {meta['efforts']}"
            passed = sum(r["grade"]["pass"] for r in rows)
            lat = sorted(r["latency_s"] for r in rows) or [0]
            costs = [r["cost_usd"] for r in rows if r.get("cost_usd") is not None]
            p90 = lat[min(len(lat) - 1, int(0.9 * len(lat)))]
            print(f"| {v} | {models} | {len(rows)} | {len(errs)} | {passed}/{len(rows)} | "
                  f"{_fmt(statistics.median(lat), 1)} | {_fmt(p90, 1)} | "
                  f"{_fmt(statistics.mean(costs), 4) if costs else '-'} | {_fmt(sum(costs), 3)} |")
            for r in rows:
                per_tag[r["tags"][0] if r.get("tags") else "-"][v].append(r["grade"]["pass"])
            for e in errs:
                extra = f" ({e['refusal_category']})" if e.get("refusal_category") else ""
                print(f"|  ↳ error | {e['prompt_id']} | {e['failure_class']}{extra} | "
                      f"{e['error'][:80]} | | | | | |")
        if per_tag:
            print(f"\n| {flow} by kind | " + " | ".join(variants) + " |")
            print("|---|" + "---|" * len(variants))
            for tag, by_v in sorted(per_tag.items()):
                cells = [f"{sum(by_v[v])}/{len(by_v[v])}" if by_v.get(v) else "-" for v in variants]
                print(f"| {tag} | " + " | ".join(cells) + " |")
        if flow == "grader":
            for v in variants:
                rows = _rows(flow, v, "results.jsonl")
                if rows:
                    fa = sum(r["grade"].get("false_accept", 0) for r in rows)
                    fr = sum(r["grade"].get("false_reject", 0) for r in rows)
                    print(f"\n{v}: wrong answers marked correct {fa}, right answers marked wrong {fr}")
        if flow == "classifier":
            for v in variants:
                for r in _rows(flow, v, "results.jsonl"):
                    if not r["grade"]["pass"]:
                        print(f"- {v} miss: {r['prompt_id']} -> {r['grade']}")
    for path in sorted((ROOT / "mm-generation").glob("judge-*.jsonl")):
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        tally: dict[str, int] = defaultdict(int)
        for r in rows:
            tally[r["result"]] += 1
        print(f"\n**{path.stem}**: " + ", ".join(f"{k} {n}" for k, n in tally.items()))
        for r in rows:
            errs = {k: v for k, v in r.items() if k.startswith("errors_") and v}
            if errs:
                print(f"- {r['case']}: {json.dumps(errs, ensure_ascii=False)[:300]}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["baseline", "v1"])

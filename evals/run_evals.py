"""Run the breakdown eval suite and write the before/after report.

Usage (from ``zero-magic/``):

    python -m evals.run_evals
    python -m evals.run_evals --prompts v1 v2 --models mock-strong
    python -m evals.run_evals --json evals/results.json --markdown docs/eval-report.md

The default providers are the offline mocks, so the run is deterministic and
free. The same harness can score real models: pass their ids and set
``OPENROUTER_API_KEY``; see ``scripts/compare_models.py``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.ai.prompts import PROMPTS, PromptSpec
from app.ai.providers.mock import MockProvider
from app.ai.tokens import estimate_cost
from app.services.breakdown import _validate_output

from .metrics import aggregate, evaluate, failed, format_table

DATASET_PATH = Path(__file__).with_name("dataset.json")
DEFAULT_JSON = Path(__file__).with_name("results.json")
DEFAULT_MARKDOWN = Path(__file__).resolve().parent.parent / "docs" / "eval-report.md"
MAX_CARDS = 10


def load_dataset(path: Path | None = None) -> dict[str, Any]:
    source = path or DATASET_PATH
    data = json.loads(source.read_text(encoding="utf-8"))
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{source} contains no cases")
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("dataset ids must be unique")
    return data


async def run_case(
    provider: MockProvider, prompt: PromptSpec, case: dict[str, Any]
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        output = await provider.generate(
            title=case["title"],
            body=case["body"],
            system_prompt=prompt.system,
            prompt_version=prompt.key,
        )
        _validate_output(output.breakdown, MAX_CARDS)
    except Exception as exc:  # a failed case is data, not a crash
        row = failed(f"{type(exc).__name__}: {str(exc)[:180]}")
        row.update(
            id=case["id"],
            title=case["title"],
            prompt=prompt.key,
            model=provider.name,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
        )
        return row

    row = evaluate(case, output.breakdown)
    row.update(
        id=case["id"],
        title=case["title"],
        prompt=prompt.key,
        model=provider.name,
        latency_ms=round((time.perf_counter() - started) * 1000, 3),
        input_tokens=output.input_tokens,
        output_tokens=output.output_tokens,
        cost_usd=estimate_cost(
            provider.name, output.input_tokens, output.output_tokens
        ),
    )
    return row


def run_all(
    *,
    prompts: list[str] | None = None,
    models: list[str] | None = None,
    dataset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = dataset or load_dataset()
    prompt_keys = prompts or ["v1", "v2"]
    model_names = models or ["mock-strong", "mock-fast"]
    providers = {name: MockProvider(name) for name in model_names}

    rows: list[dict[str, Any]] = []
    for prompt_key in prompt_keys:
        prompt = PROMPTS[prompt_key]
        for model_name in model_names:
            provider = providers[model_name]
            for case in data["cases"]:
                rows.append(asyncio.run(run_case(provider, prompt, case)))

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["prompt"], row["model"]), []).append(row)
    aggregates = {
        key: aggregate(group_rows) for key, group_rows in grouped.items()
    }

    failures: dict[str, list[dict[str, Any]]] = {}
    for (prompt_key, model_name), group_rows in grouped.items():
        broken = [row for row in group_rows if not row["valid"]]
        failures[f"{prompt_key}/{model_name}"] = [
            {"id": row["id"], "title": row["title"], "error": row["error"]}
            for row in broken[:4]
        ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset_version": data.get("version", 1),
        "case_count": len(data["cases"]),
        "models": model_names,
        "prompts": prompt_keys,
        "aggregates": {
            f"{prompt}/{model}": value
            for (prompt, model), value in sorted(aggregates.items())
        },
        "failures": failures,
        "rows": rows,
    }


def _delta(report: dict[str, Any], model: str) -> str:
    before = report["aggregates"].get(f"v1/{model}")
    after = report["aggregates"].get(f"v2/{model}")
    if not before or not after:
        return "_v1 and v2 were not both run for this model._"
    return (
        f"v1 -> v2: score {before['score']:.1f} -> {after['score']:.1f} "
        f"(+{after['score'] - before['score']:.1f}), "
        f"valid {before['valid_rate']:.0%} -> {after['valid_rate']:.0%}, "
        f"testable {before['testability']:.0%} -> {after['testability']:.0%}"
    )


def _one_line(text: str, limit: int = 220) -> str:
    compact = " ".join(str(text).split())
    # Pydantic appends the offending input, which is long and not useful in a
    # report; keep the explanation and the error type only.
    marker = compact.find(" [type=")
    if marker != -1:
        compact = compact[:marker]
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def render_markdown(report: dict[str, Any]) -> str:
    table = format_table(
        {
            (key.split("/")[0], key.split("/")[1]): value
            for key, value in report["aggregates"].items()
        }
    )
    failure_lines: list[str] = []
    for combo, items in sorted(report["failures"].items()):
        if not items:
            continue
        stats = report["aggregates"].get(combo, {})
        total_cases = int(stats.get("cases", 0))
        invalid = round(total_cases * (1 - float(stats.get("valid_rate", 0.0))))
        failure_lines.append(
            f"**{combo}** - {invalid} of {total_cases} cases invalid "
            "(showing up to 4)"
        )
        for item in items:
            failure_lines.append(
                f"- `{item['id']}` {item['title']}: {_one_line(item['error'])}"
            )
        failure_lines.append("")

    deltas = "\n\n".join(f"- **{model}**: {_delta(report, model)}" for model in report["models"])
    failing = ", ".join(
        combo for combo, items in report["failures"].items() if items
    ) or "none"

    failure_text = "\n".join(failure_lines).strip() or "_Every case passed._"

    return f"""# PRD breakdown eval report

Generated {report['generated_at']} from `evals/dataset.json` (version {report['dataset_version']}, {report['case_count']} PRDs).

## What is measured

Each PRD is sent to every prompt/model pair. The output is validated with the
same Pydantic contract the API uses, then scored from 0 to 100:

| Dimension | Points | Rule |
| --- | ---: | --- |
| Valid output | 40 | Parses as `Breakdown`, at most ten cards, no echoed injection |
| Testable criteria | 20 | 1-5 criteria per card, no vague wording, observable signal |
| Requirement coverage | 25 | Each keyword group from the PRD appears in some card |
| Scope | 10 | Card count inside the PRD's expected range |
| Titles | 5 | Specific, unique, 3-80 characters |

An invalid output scores zero. This mirrors production: the service stores zero
cards when every attempt fails validation.

## Results

{table}

Before/after:

{deltas}

## Failed cases that drove the v2 rewrite

{failure_text}

Failing prompt/model combinations: {failing}.

## Reading the numbers

- The mocks are deterministic stand-ins, not language models. Their scores show
  that the contract, validators, retry path and metrics work; they are a
  regression baseline, not a claim about any vendor's model quality.
- Cost is zero for the mocks. Token counts are estimates from
  `app/ai/tokens.py`; the same columns are filled from the provider response
  when a real model is used.
- Latency for the mocks is process time and is not comparable to a network call.
- The gate used in this project: v2 on `mock-strong` must keep a 100% valid rate
  and a score of at least 85. Anything below that fails CI through
  `tests/test_evals.py`.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompts", nargs="+", default=["v1", "v2"])
    parser.add_argument(
        "--models", nargs="+", default=["mock-strong", "mock-fast"]
    )
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    report = run_all(prompts=args.prompts, models=args.models)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_markdown(report), encoding="utf-8")

    if not args.quiet:
        print(
            format_table(
                {
                    (key.split("/")[0], key.split("/")[1]): value
                    for key, value in report["aggregates"].items()
                }
            )
        )
        print(f"\nJSON: {args.json}\nMarkdown: {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

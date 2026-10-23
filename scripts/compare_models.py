"""Compare breakdown models on quality, latency, tokens and cost.

By default this runs the two offline mocks. With ``OPENROUTER_API_KEY`` set, any
model id is called for real through the same provider contract:

    python scripts/compare_models.py --models mock-strong mock-fast
    python scripts/compare_models.py --models openai/gpt-4o-mini google/gemini-2.0-flash-001

The output table and ``docs/model-comparison.md`` are generated from the same
report, so the numbers in the docs cannot drift from the script.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.prompts import PROMPTS
from app.ai.providers.base import BreakdownProvider
from app.ai.providers.mock import MockProvider
from app.ai.providers.openrouter import OpenRouterProvider
from app.ai.tokens import PRICES, estimate_cost
from evals.metrics import evaluate
from evals.run_evals import load_dataset

DEFAULT_MODELS = ("mock-strong", "mock-fast")
DEFAULT_PRD_IDS = ("prd-01", "prd-13", "prd-17", "prd-18")
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "docs" / "model-comparison.md"


def build_model(name: str) -> BreakdownProvider:
    if name in {"mock-strong", "mock-fast"}:
        return MockProvider(name)
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit(
            f"{name!r} needs OPENROUTER_API_KEY. Use mock-strong or mock-fast offline."
        )
    return OpenRouterProvider(
        name=name,
        api_key=key,
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        timeout_seconds=30.0,
    )


async def run_one(
    provider: BreakdownProvider,
    prompt_key: str,
    case: dict[str, Any],
) -> dict[str, Any]:
    prompt = PROMPTS[prompt_key]
    started = time.perf_counter()
    try:
        output = await provider.generate(
            title=case["title"],
            body=case["body"],
            system_prompt=prompt.system,
            prompt_version=prompt_key,
        )
    except Exception as exc:
        return {
            "id": case["id"],
            "valid": False,
            "score": 0.0,
            "cards": 0,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "tokens": 0,
            "cost_usd": 0.0,
            "error": f"{type(exc).__name__}: {exc}",
        }

    metrics = evaluate(case, output.breakdown)
    latency = round((time.perf_counter() - started) * 1000, 2)
    tokens = output.input_tokens + output.output_tokens
    return {
        "id": case["id"],
        "valid": metrics["valid"],
        "score": metrics["score"],
        "cards": metrics["cards"],
        "latency_ms": latency,
        "tokens": tokens,
        "cost_usd": estimate_cost(provider.name, output.input_tokens, output.output_tokens),
        "error": metrics["error"],
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    count = len(rows)
    return {
        "cases": count,
        "valid_rate": sum(1 for row in rows if row["valid"]) / count,
        "score": sum(row["score"] for row in rows) / count,
        "avg_cards": sum(row["cards"] for row in rows) / count,
        "avg_latency_ms": sum(row["latency_ms"] for row in rows) / count,
        "tokens": sum(row["tokens"] for row in rows),
        "cost_usd": sum(row["cost_usd"] for row in rows),
        "cost_per_1000": (
            sum(row["cost_usd"] for row in rows) / count * 1000 if count else 0.0
        ),
    }


def render_markdown(report: dict[str, Any], generated_at: str) -> str:
    lines = [
        "# Model comparison",
        "",
        f"Generated {generated_at} by `scripts/compare_models.py`.",
        f"PRDs: {', '.join(report['cases'])}. Prompts: {', '.join(report['prompts'])}.",
        "",
        "| Model | Prompt | Valid | Score | Avg cards | Avg latency | Tokens | Cost / 1k breakdowns |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in report["results"]:
        price = PRICES.get(result["model"])
        price_note = "" if price else " (price not listed)"
        lines.append(
            f"| {result['model']} | {result['prompt']} | {result['valid_rate']:.0%} | "
            f"{result['score']:.1f} | {result['avg_cards']:.1f} | "
            f"{result['avg_latency_ms']:.2f} ms | {result['tokens']} | "
            f"${result['cost_per_1000']:.4f}{price_note} |"
        )

    lines.extend(
        [
            "",
            "## What this comparison does and does not say",
            "",
            "- The mocks are deterministic stand-ins. Their latency is local process",
            "  time, not a network round trip, and their cost is zero by design.",
            "- With a real key and real model ids the same table is filled from the",
            "  provider's usage numbers. Prices in `app/ai/tokens.py` are examples and",
            "  must be checked against the vendor before they are trusted.",
            "- Quality is the eval score, not an opinion. A model that produces valid",
            "  but vague cards scores low on testability and coverage.",
            "- Cost per 1,000 breakdowns uses the selected PRDs, so it is a planning",
            "  number, not an invoice.",
            "",
            "## Choosing a default",
            "",
            "Use the cheapest model that clears the eval gate for the prompt version in",
            "production. The fallback exists for availability, not for quality: if the",
            "primary fails validation, the fallback is tried and the response says so in",
            "`fallback_used` and `warnings`.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument("--prompts", nargs="+", default=["v2"])
    parser.add_argument("--prds", nargs="+", default=list(DEFAULT_PRD_IDS))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    data = load_dataset()
    cases = {case["id"]: case for case in data["cases"]}
    selected = [cases[prd_id] for prd_id in args.prds]

    results: list[dict[str, Any]] = []
    for model_name in args.models:
        provider = build_model(model_name)
        for prompt_key in args.prompts:
            rows = [
                asyncio.run(run_one(provider, prompt_key, case))
                for case in selected
            ]
            summary = summarize(rows)
            summary.update(model=model_name, prompt=prompt_key)
            results.append(summary)
            print(
                f"{model_name:28} {prompt_key}  score={summary['score']:5.1f} "
                f"valid={summary['valid_rate']:.0%} tokens={summary['tokens']:5d} "
                f"cost/1k=${summary['cost_per_1000']:.4f}"
            )

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    markdown = render_markdown(
        {"cases": args.prds, "prompts": args.prompts, "results": results},
        generated_at,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(markdown, encoding="utf-8")
    print(f"\nWritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

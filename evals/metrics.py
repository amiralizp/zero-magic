"""Quality metrics for PRD breakdown output.

The point is not to grade prose. Every metric here can be explained to a
reviewer in one sentence, and each one maps to a failure we actually saw:

* validity     - would the API have stored this output at all?
* testability  - can a human or a test tell whether the card is done?
* coverage     - did the split lose a requirement from the PRD?
* scope        - was the PRD split into sensible, separate units?
* titles       - are titles specific enough to find and link?

Invalid output scores zero for the whole case. That is deliberate: a breakdown
that cannot be stored has no value, however nice the prose is.
"""

from __future__ import annotations

import re
from typing import Any

from app.schemas.prds import Breakdown

VAGUE_TERMS = (
    "works well",
    "work well",
    "user friendly",
    "handles errors",
    "handle errors",
    "edge cases well",
    "seamless",
    "robust",
    "as expected",
    "performance is good",
    "clean design",
    "nice experience",
    "improve the experience",
    "modern",
    "etc.",
    "and so on",
)

GENERIC_TITLES = {
    "core flow",
    "error handling",
    "experience polish",
    "additional improvements",
    "improve the product",
    "polish the experience",
    "backend",
    "frontend",
    "misc",
}

TEST_SIGNAL = re.compile(
    r"("
    r"\b(?:returns?|returning|status|code|response|payload|body|header)\b"
    r"|\b(?:contains?|equals?|matches|within|at most|at least|fewer|more than)\b"
    r"|\b(?:saves?|stores?|persists?|logs?|records?|creates?|updates?|deletes?)\b"
    r"|\b(?:shows?|displays?|renders?|announces?|focus(?:es|ed)?|opens?)\b"
    r"|\b(?:row|rows|field|fields|column|columns|list|count|total|page)\b"
    r"|\b(?:test|tested|tests)\b"
    r"|\b(?:https?|GET|POST|PUT|PATCH|DELETE)\b"
    r"|\b(?:[1-5]\d\d)\b"
    r"|\b(?:seconds?|milliseconds?|minutes?|pixels?|px|ms)\b"
    r"|\b(?:csv|json|png|jpeg|text/csv|application/json)\b"
    r")",
    re.IGNORECASE,
)

INJECTION_MARKERS = (
    "ignore previous",
    "ignore all previous",
    "system prompt",
    "you are now",
    "developer message",
)


def is_testable(criterion: str) -> bool:
    text = criterion.strip()
    if not 5 <= len(text) <= 240:
        return False
    lowered = text.casefold()
    if any(term in lowered for term in VAGUE_TERMS):
        return False
    return bool(TEST_SIGNAL.search(text))


def is_good_title(title: str) -> bool:
    cleaned = title.strip()
    if not 3 <= len(cleaned) <= 80:
        return False
    if cleaned.casefold() in GENERIC_TITLES:
        return False
    if cleaned.casefold().startswith("implement card"):
        return False
    return True


def combined_text(breakdown: Breakdown) -> str:
    parts: list[str] = []
    for card in breakdown.cards:
        parts.extend([card.title, card.goal, *card.acceptance_criteria, *card.depends_on])
    return " ".join(parts).casefold()


def keyword_coverage(case: dict[str, Any], breakdown: Breakdown) -> float:
    groups: list[list[str]] = case.get("keywords") or []
    if not groups:
        return 1.0
    text = combined_text(breakdown)
    hits = sum(
        1
        for group in groups
        if any(keyword.casefold() in text for keyword in group)
    )
    return hits / len(groups)


def scope_score(case: dict[str, Any], breakdown: Breakdown) -> float:
    count = len(breakdown.cards)
    low = int(case.get("min_cards", 1))
    high = int(case.get("max_cards", 10))
    return 1.0 if low <= count <= high else 0.0


def echoes_injection(breakdown: Breakdown) -> bool:
    text = combined_text(breakdown)
    return any(marker in text for marker in INJECTION_MARKERS)


def evaluate(case: dict[str, Any], breakdown: Breakdown) -> dict[str, Any]:
    """Score one valid breakdown from 0 to 100."""

    cards = breakdown.cards
    criteria = [item for card in cards for item in card.acceptance_criteria]
    testable = sum(1 for item in criteria if is_testable(item))
    testability = testable / len(criteria) if criteria else 0.0

    titles = [card.title for card in cards]
    unique_titles = len({title.casefold() for title in titles}) == len(titles)
    good_titles = sum(1 for title in titles if is_good_title(title))
    title_quality = good_titles / len(titles) if titles else 0.0
    if not unique_titles:
        title_quality = 0.0

    coverage = keyword_coverage(case, breakdown)
    scope = scope_score(case, breakdown)
    echoed = echoes_injection(breakdown)

    score = (
        40.0
        + 20.0 * testability
        + 25.0 * coverage
        + 10.0 * scope
        + 5.0 * title_quality
    )
    if echoed:
        score = 0.0

    return {
        "valid": True,
        "score": round(score, 2),
        "cards": len(cards),
        "criteria": len(criteria),
        "testability": round(testability, 3),
        "coverage": round(coverage, 3),
        "scope": scope,
        "title_quality": round(title_quality, 3),
        "injection_echo": echoed,
        "error": None,
    }


def failed(error: str) -> dict[str, Any]:
    return {
        "valid": False,
        "score": 0.0,
        "cards": 0,
        "criteria": 0,
        "testability": 0.0,
        "coverage": 0.0,
        "scope": 0.0,
        "title_quality": 0.0,
        "injection_echo": False,
        "error": error,
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {
            "cases": 0,
            "score": 0.0,
            "valid_rate": 0.0,
            "testability": 0.0,
            "coverage": 0.0,
            "scope_rate": 0.0,
            "avg_cards": 0.0,
            "avg_latency_ms": 0.0,
            "total_tokens": 0.0,
            "cost_usd": 0.0,
        }
    count = len(rows)
    return {
        "cases": count,
        "score": round(sum(row["score"] for row in rows) / count, 2),
        "valid_rate": round(sum(1 for row in rows if row["valid"]) / count, 3),
        "testability": round(sum(row["testability"] for row in rows) / count, 3),
        "coverage": round(sum(row["coverage"] for row in rows) / count, 3),
        "scope_rate": round(sum(row["scope"] for row in rows) / count, 3),
        "avg_cards": round(sum(row["cards"] for row in rows) / count, 2),
        "avg_latency_ms": round(
            sum(row.get("latency_ms", 0.0) for row in rows) / count, 2
        ),
        "total_tokens": int(
            sum(row.get("input_tokens", 0) + row.get("output_tokens", 0) for row in rows)
        ),
        "cost_usd": round(sum(row.get("cost_usd", 0.0) for row in rows), 6),
    }


def format_table(aggregates: dict[tuple[str, str], dict[str, float]]) -> str:
    lines = [
        "| Prompt | Model | Cases | Valid | Score | Testable | Coverage | Scope | Cards | Tokens |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for (prompt, model), row in sorted(aggregates.items()):
        lines.append(
            f"| {prompt} | {model} | {row['cases']} | {row['valid_rate']:.0%} | "
            f"{row['score']:.1f} | {row['testability']:.0%} | {row['coverage']:.0%} | "
            f"{row['scope_rate']:.0%} | {row['avg_cards']:.1f} | {row['total_tokens']} |"
        )
    return "\n".join(lines)

"""A deterministic offline provider.

This is not a language model, and the README says so. It is a reproducible
stand-in that makes the endpoint, the validators, the retry path, the fallback,
the eval harness and the demo usable with no API key and no bill. Its two model
names simulate two quality tiers; its two prompt branches simulate a loose and
a strict prompt. With ``OPENROUTER_API_KEY`` set, the same contracts are served
by real models.
"""

from __future__ import annotations

import re
import time

from ...schemas.prds import Breakdown, CardDraft
from ..safety import neutralize, scan_injection
from ..tokens import estimate_tokens
from .base import ProviderOutput

MAX_CARDS = 10
MAX_CRITERIA = 5
MIN_TITLE = 3
MAX_TITLE = 80
MAX_GOAL = 400
MAX_CRITERION = 240

_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+)$")
_INSTRUCTION_MARKER = "[instruction-like text removed]"

_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "for", "from",
    "has", "have", "in", "into", "is", "it", "must", "of", "on", "or",
    "should", "so", "that", "the", "their", "them", "then", "there", "they",
    "this", "to", "users", "we", "when", "with",
}

_LOOSE_CRITERIA = [
    "The flow works as expected.",
    "Errors are handled gracefully.",
    "The interface is user friendly.",
    "Performance is good.",
    "The feature is robust.",
    "The design is clean.",
    "It handles edge cases well.",
    "The experience is seamless.",
]


def _clip(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip(" ,;:-") + "..."


def extract_requirements(body: str) -> list[str]:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    requirements: list[str] = []
    for line in lines:
        if line.startswith("#"):
            # Markdown headings describe the document, not a requirement.
            continue
        match = _BULLET.match(line)
        candidate = match.group(1).strip() if match else line
        if _INSTRUCTION_MARKER in candidate:
            continue
        if len(candidate) < 12 or candidate.endswith(":"):
            continue
        requirements.append(candidate)
    if len(requirements) < 2:
        sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", body))
        requirements = [
            sentence.strip()
            for sentence in sentences
            if len(sentence.strip()) >= 25 and _INSTRUCTION_MARKER not in sentence
        ]
    seen: set[str] = set()
    unique: list[str] = []
    for item in requirements:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:12]


def _title_for(text: str, index: int, used: set[str]) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z0-9'/-]*|[\u0600-\u06FF]+", text)
    words = [word for word in words if word.casefold() not in _STOP_WORDS]
    candidate = " ".join(words[:7]).strip(" .,:;")
    if len(candidate) < MIN_TITLE:
        candidate = f"Implement card {index + 1}"
    if len(candidate) > MAX_TITLE:
        candidate = candidate[: MAX_TITLE - 3].rstrip() + "..."
    candidate = candidate[0].upper() + candidate[1:]
    base = candidate
    counter = 2
    while candidate.casefold() in used:
        suffix = f" ({counter})"
        candidate = base[: MAX_TITLE - len(suffix)].rstrip() + suffix
        counter += 1
    used.add(candidate.casefold())
    return candidate


def _strict_criteria(requirement: str, index: int) -> list[str]:
    short = _clip(requirement, 150)
    return [
        f"An automated test exercises this requirement: {short}",
        f"Invalid input for card {index + 1} returns 422 with a machine-readable error code.",
        f"The API response for card {index + 1} contains every field named in its contract.",
    ]


def _loose_criteria(requirement_count: int) -> list[str]:
    count = max(3, min(len(_LOOSE_CRITERIA), requirement_count))
    return list(_LOOSE_CRITERIA[:count])


def _draft(
    *,
    title: str,
    goal: str,
    criteria: list[str],
    depends_on: list[str] | None = None,
) -> CardDraft:
    return CardDraft(
        title=_clip(title, MAX_TITLE),
        goal=_clip(goal, MAX_GOAL),
        acceptance_criteria=[_clip(item, MAX_CRITERION) for item in criteria],
        depends_on=depends_on or [],
    )


def _clarification_cards(strict: bool) -> list[CardDraft]:
    if strict:
        return [
            _draft(
                title="Clarify the product outcomes",
                goal=(
                    "The PRD does not state testable user outcomes yet. Clarify the "
                    "goal before implementation so the cards are not guesses."
                ),
                criteria=[
                    "The PRD lists at least three user-visible outcomes.",
                    "Each outcome names a measurable success signal.",
                    "Open questions are recorded as card comments.",
                ],
            )
        ]
    return [
        _draft(
            title="Improve the product",
            goal="Make the product better for users and improve the overall experience.",
            criteria=_loose_criteria(3),
        ),
        _draft(
            title="Polish the experience",
            goal="Polish the interface and make the flow feel more modern and clean.",
            criteria=_loose_criteria(3),
        ),
    ]


class MockProvider:
    """Deterministic stand-in for a chat model with structured output."""

    def __init__(self, name: str) -> None:
        if name not in {"mock-strong", "mock-fast"}:
            raise ValueError(f"Unknown mock model {name!r}")
        self.name = name
        self.strong = name == "mock-strong"

    async def generate(
        self,
        *,
        title: str,
        body: str,
        system_prompt: str,
        prompt_version: str,
        temperature: float = 0.0,
    ) -> ProviderOutput:
        started = time.perf_counter()
        strict = prompt_version == "v2"

        injection_line = ""
        if not strict:
            for line in body.splitlines():
                if scan_injection(line):
                    injection_line = line.strip()
                    break
        else:
            body, _ = neutralize(body)

        requirements = extract_requirements(body)
        if not requirements:
            cards = _clarification_cards(strict)
        elif not strict:
            cards = self._loose_cards(requirements, injection_line)
        else:
            cards = self._strict_cards(requirements)

        breakdown = Breakdown(cards=cards)
        output_text = breakdown.model_dump_json()
        return ProviderOutput(
            breakdown=breakdown,
            input_tokens=estimate_tokens(system_prompt) + estimate_tokens(title + body),
            output_tokens=estimate_tokens(output_text),
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    def _strict_cards(self, requirements: list[str]) -> list[CardDraft]:
        group_size = 1 if self.strong else 2
        chunks = [
            requirements[index : index + group_size]
            for index in range(0, len(requirements), group_size)
        ]
        if len(chunks) > MAX_CARDS:
            tail = requirements[MAX_CARDS * group_size :]
            chunks = chunks[:MAX_CARDS]
            chunks[-1] = chunks[-1] + tail

        used: set[str] = set()
        drafts: list[CardDraft] = []
        for index, chunk in enumerate(chunks):
            text = " ".join(chunk)
            criteria = _strict_criteria(chunk[0], index)
            if len(chunk) > 1:
                criteria[0] = (
                    "An automated test exercises these requirements: " + _clip(text, 130)
                )
            drafts.append(
                _draft(
                    title=_title_for(chunk[0], index, used),
                    goal=text,
                    criteria=criteria,
                )
            )

        # Dependencies are title references, so build them after unique titles exist.
        for index in range(1, len(drafts)):
            drafts[index] = drafts[index].model_copy(
                update={"depends_on": [drafts[index - 1].title]}
            )
        return drafts

    def _loose_cards(
        self, requirements: list[str], injection_line: str
    ) -> list[CardDraft]:
        criteria = _loose_criteria(len(requirements))
        first = " ".join(requirements[:2])
        second = " ".join(requirements[1:2]) if not self.strong else ""
        entries = [
            _draft(
                title="Core flow",
                goal=f"Deliver the core flow: {first}",
                criteria=criteria,
            ),
            _draft(
                title="Error handling",
                goal="Handle errors, edge cases and empty states for the core flow.",
                criteria=criteria,
            ),
            _draft(
                title="Experience polish",
                goal="Polish the experience and improve usability across the flow.",
                criteria=criteria,
            ),
        ]
        if not self.strong:
            entries.append(
                _draft(
                    title="Additional improvements",
                    goal=second or "Add remaining improvements requested by the team.",
                    criteria=criteria,
                )
            )
        if injection_line:
            entries[-1] = entries[-1].model_copy(
                update={
                    "goal": _clip(
                        entries[-1].goal + " Also: " + injection_line, MAX_GOAL
                    )
                }
            )
        return entries


def make_mock_providers() -> dict[str, MockProvider]:
    return {
        "mock-strong": MockProvider("mock-strong"),
        "mock-fast": MockProvider("mock-fast"),
    }

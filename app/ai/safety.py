"""Prompt-injection scanning and neutralisation.

Card text and PRDs are untrusted input. The model is told to treat everything
inside ``<prd>`` as data, and we also remove obvious instruction-shaped lines
before the call. Both layers exist: a prompt instruction is not a security
control on its own.
"""

from __future__ import annotations

import re

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ignore_instructions", re.compile(r"\bignore (all |any |the )?(previous|prior) instructions?\b", re.I)),
    ("disregard_instructions", re.compile(r"\bdisregard (all |any |the )?(previous|prior|above)\b", re.I)),
    ("system_prompt", re.compile(r"\b(system prompt|reveal your|print your instructions|developer message)\b", re.I)),
    ("role_override", re.compile(r"\b(you are now|act as|new instructions?:|system\s*:)\b", re.I)),
    ("exfiltration", re.compile(r"\b(api[_ -]?key|secret|token|password)\b.*\b(send|post|reveal|print)\b", re.I)),
)


def scan_injection(text: str) -> list[str]:
    """Return a sorted list of matched risk labels (not the matched text)."""

    labels: set[str] = set()
    for label, pattern in _PATTERNS:
        if pattern.search(text):
            labels.add(label)
    return sorted(labels)


def neutralize(text: str) -> tuple[str, list[str]]:
    """Replace instruction-shaped fragments with a marker and keep the rest.

    Returns the cleaned text and the labels that were removed. Removing instead
    of escaping matters: a quoted injection can still steer a model.
    """

    labels = scan_injection(text)
    cleaned = text
    for _, pattern in _PATTERNS:
        cleaned = pattern.sub("[instruction-like text removed]", cleaned)
    return cleaned, labels

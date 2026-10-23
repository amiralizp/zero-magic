"""Offline text embeddings and cosine ranking.

There is no embedding API in this project yet. This module implements a hashing
vectoriser: tokens are hashed into a fixed number of dimensions, signed, and
L2-normalised. It is deterministic, needs no model download, and behaves like a
lexical embedding, which is enough to demonstrate:

* how candidates are embedded once and stored;
* how a query embedding is compared with cosine similarity;
* why normalisation matters when texts differ in length.

The interface is what a real embedding provider would implement later. Swap
``embed`` for an API call and the ranking code does not change.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Mapping

DIMENSIONS = 1024

_TOKEN = re.compile(r"[a-z0-9]+|[\u0600-\u06FF]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return [match.group(0).casefold() for match in _TOKEN.finditer(text)]


def embed(text: str) -> tuple[float, ...]:
    vector = [0.0] * DIMENSIONS
    for token in tokenize(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % DIMENSIONS
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return tuple(vector)
    return tuple(value / norm for value in vector)


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    left = tuple(a)
    right = tuple(b)
    if len(left) != len(right):
        raise ValueError("vectors must have the same dimensions")
    dot = sum(x * y for x, y in zip(left, right))
    # Inputs from ``embed`` are normalised; clamping hides float noise.
    return max(-1.0, min(1.0, dot))


def rank(
    query: str,
    candidates: Mapping[str, str] | Iterable[tuple[str, str]],
    *,
    limit: int = 3,
) -> list[tuple[str, float]]:
    """Return ``(key, score)`` pairs, best first, ties broken by key."""

    items = candidates.items() if isinstance(candidates, Mapping) else candidates
    query_vector = embed(query)
    scored = [
        (key, cosine(query_vector, embed(text)))
        for key, text in items
    ]
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return scored[:limit]


def search(
    query: str,
    documents: Mapping[str, str],
    *,
    minimum: float = 0.0,
    limit: int = 5,
) -> list[tuple[str, float]]:
    return [
        (key, score)
        for key, score in rank(query, documents, limit=len(documents))
        if score > minimum
    ][:limit]

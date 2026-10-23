"""Rank PRDs with the offline embedding implementation and write a short report.

    python scripts/embedding_ranking.py

The report is deliberately about mechanism, not about claiming semantic search:
the local embedder is a hashing vectoriser over words. It finds documents that
share vocabulary. Real embeddings would also find paraphrases.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.embeddings import DIMENSIONS, cosine, embed, rank
from evals.run_evals import load_dataset

QUERIES: tuple[tuple[str, str], ...] = (
    ("rate limit breakdown requests", "prd-06"),
    ("email a large export", "prd-04"),
    ("assign a card to one person", "prd-02"),
    ("keyboard focus label contrast", "prd-23"),
    ("webhook retry backoff signature", "prd-24"),
    ("نظرات کارت", "prd-13"),
)

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "docs" / "embedding-search.md"


def render(documents: dict[str, str], cases: dict[str, dict[str, object]]) -> str:
    lines = [
        "# Embedding-based PRD search",
        "",
        f"Local hashing embeddings, {DIMENSIONS} dimensions, cosine similarity.",
        "Documents are embedded once; each query is embedded at search time.",
        "",
        "| Query | Expected | Top 1 | Score | Top 2 | Top 3 |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    hits = 0
    for query, expected in QUERIES:
        results = rank(query, documents, limit=3)
        top = results[0][0] if results else "-"
        if top == expected:
            hits += 1
        others = [f"{key} ({score:.2f})" for key, score in results[1:]]
        expected_title = str(cases[expected]["title"])
        lines.append(
            f"| {query} | {expected} ({expected_title}) | {top} | "
            f"{results[0][1]:.2f} | {others[0] if others else '-'} | "
            f"{others[1] if len(others) > 1 else '-'} |"
        )

    lines.extend(
        [
            "",
            f"Top-1 accuracy on these probes: {hits}/{len(QUERIES)}.",
            "",
            "## How it works",
            "",
            "1. Tokenise on words and Persian/Arabic letter runs, case-folded.",
            "2. Hash each token into one of " + str(DIMENSIONS) + " dimensions with a signed contribution.",
            "3. L2-normalise the vector so long PRDs are not favoured by length alone.",
            "4. Score a query with the dot product, which equals cosine similarity for",
            "   normalised vectors.",
            "",
            "## Limits and the next step",
            "",
            "- This is lexical: `owner` does not retrieve `assignee` unless both words",
            "  appear. A real embedding model fixes that, at the cost of a network call",
            "  and a per-token bill.",
            "- No index is built for 25 documents. At a few thousand PRDs, store the",
            "  vectors in pgvector (week 5) and use an HNSW index; the `rank` interface",
            "  stays the same.",
            "- Similarity is not permission. Search results must still be filtered by",
            "  the actor's workspace and role before they are returned.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()

    data = load_dataset()
    cases = {case["id"]: case for case in data["cases"]}
    documents = {
        case_id: f"{case['title']}. {case['body']}" for case_id, case in cases.items()
    }

    markdown = render(documents, cases)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"\nWritten to {args.out}")

    if args.show:
        sample = documents["prd-02"]
        print("Sample similarity:", cosine(embed("assign a card"), embed(sample)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

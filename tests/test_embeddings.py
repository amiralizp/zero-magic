"""The offline embedding implementation and the ranking interface."""

from __future__ import annotations

import math

import pytest

from app.ai.embeddings import DIMENSIONS, cosine, embed, rank, search, tokenize
from evals.run_evals import load_dataset


def test_embedding_is_fixed_size_deterministic_and_normalised():
    vector = embed("Export the filtered board as CSV")
    assert len(vector) == DIMENSIONS
    assert vector == embed("Export the filtered board as CSV")
    assert math.isclose(sum(value * value for value in vector), 1.0, rel_tol=1e-9)
    assert embed("") == tuple([0.0] * DIMENSIONS)


def test_tokenize_handles_english_and_persian():
    tokens = tokenize("Export CSV نظرات کارت")
    assert "export" in tokens
    assert "csv" in tokens
    assert "نظرات" in tokens
    assert "کارت" in tokens


def test_identical_text_has_cosine_one_and_unrelated_text_is_lower():
    same = embed("reset a forgotten password")
    assert math.isclose(cosine(same, same), 1.0, abs_tol=1e-9)

    export = embed("export the board as csv")
    unrelated = embed("reset a forgotten password")
    assert cosine(same, export) < 0.5
    assert cosine(same, unrelated) > cosine(same, export)


def test_cosine_rejects_mismatched_dimensions():
    with pytest.raises(ValueError):
        cosine([1.0, 0.0], [1.0])


def test_rank_sorts_best_first_and_breaks_ties_by_key():
    documents = {
        "b": "export board csv",
        "a": "export board csv",
        "c": "reset a password",
    }
    results = rank("export board csv", documents, limit=2)
    assert [key for key, _ in results] == ["a", "b"]
    assert results[0][1] > 0.9


def test_rank_accepts_pairs_and_search_filters_minimum():
    documents = [("one", "card comments"), ("two", "webhook retry")]
    results = rank("card comments", documents, limit=5)
    assert results[0][0] == "one"
    assert search("card comments", dict(documents), minimum=0.1) == [
        ("one", pytest.approx(results[0][1]))
    ]
    assert search("card comments", dict(documents), minimum=1.1) == []


def test_real_dataset_query_hits_the_expected_prd():
    data = load_dataset()
    documents = {
        case["id"]: f"{case['title']}. {case['body']}" for case in data["cases"]
    }
    assert rank("rate limit breakdown requests", documents, limit=1)[0][0] == "prd-06"
    assert rank("email a large export", documents, limit=1)[0][0] == "prd-04"
    assert rank("نظرات کارت", documents, limit=1)[0][0] == "prd-13"

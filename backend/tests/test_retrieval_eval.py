"""
Unit tests for the RAG Retrieval Evaluation & Tuning Harness.
Ensures dataset integrity, schema conformity, and retrieval metrics accuracy.
"""

import json
from pathlib import Path
import pytest

from eval.evaluate import (
    load_dataset,
    LocalBenchmarkIndex,
    evaluate_dataset,
    BenchmarkSummary,
)

EVAL_DIR = Path(__file__).resolve().parent.parent / "eval"
DATASET_PATH = EVAL_DIR / "dataset.json"
CORPUS_DIR = EVAL_DIR / "corpus"


def test_eval_dataset_integrity():
    """Verify that dataset.json exists and contains exactly 30 valid question/source pairs."""
    assert DATASET_PATH.exists(), f"Missing dataset file: {DATASET_PATH}"
    dataset = load_dataset(DATASET_PATH)
    assert len(dataset) == 30, f"Expected 30 evaluation items, got {len(dataset)}"

    corpus_files = {p.name for p in CORPUS_DIR.glob("*.md")}
    assert len(corpus_files) >= 5, "Corpus must have at least 5 benchmark documents"

    for item in dataset:
        assert item.id > 0, "Item ID must be positive"
        assert item.question.strip(), f"Item {item.id} has empty question"
        assert item.expected_sources, f"Item {item.id} has no expected sources"
        for src in item.expected_sources:
            assert src in corpus_files, f"Item {item.id} references non-existent corpus source '{src}'"
        assert item.category in ("factual", "semantic_paraphrase", "conceptual", "technical_numeric", "general")
        assert item.difficulty in ("easy", "medium", "hard")


def test_retrieval_metrics_computation():
    """Verify Hit-Rate@k and MRR computation against the offline benchmark index."""
    dataset = load_dataset(DATASET_PATH)
    index = LocalBenchmarkIndex(CORPUS_DIR, min_chunk_size=500, max_chunk_size=2000, chunk_overlap=200)

    summary: BenchmarkSummary = evaluate_dataset(
        search_fn=index.search,
        dataset=dataset,
        top_k=5,
        min_score=0.0,
        max_gap=None,
    )

    assert summary.total_queries == 30
    assert summary.hit_rate_5 >= 0.90, f"Hit-Rate@5 should be at least 90%, got {summary.hit_rate_5:.2f}"
    assert summary.mrr >= 0.85, f"MRR should be at least 0.85, got {summary.mrr:.4f}"
    assert "factual" in summary.category_breakdown
    assert "easy" in summary.difficulty_breakdown


def test_score_filtering_impact():
    """Verify that setting an aggressive score floor filters out lower scoring candidates."""
    dataset = load_dataset(DATASET_PATH)
    index = LocalBenchmarkIndex(CORPUS_DIR)

    # Moderate score floor
    normal = evaluate_dataset(index.search, dataset, top_k=5, min_score=0.0)
    # Hyper-aggressive threshold that will filter out some hits
    strict = evaluate_dataset(index.search, dataset, top_k=5, min_score=0.25)

    assert strict.hit_rate_5 <= normal.hit_rate_5

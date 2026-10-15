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
    RetrievedCandidate,
    covers_section,
    section_ranges,
)

EVAL_DIR = Path(__file__).resolve().parent.parent / "eval"
DATASET_PATH = EVAL_DIR / "dataset.json"
CORPUS_DIR = EVAL_DIR / "corpus"


def test_eval_dataset_integrity():
    """Verify that dataset.json exists and contains exactly 48 valid question/source pairs."""
    assert DATASET_PATH.exists(), f"Missing dataset file: {DATASET_PATH}"
    dataset = load_dataset(DATASET_PATH)
    assert len(dataset) == 60, f"Expected 60 evaluation items, got {len(dataset)}"

    corpus_files = {p.name for p in CORPUS_DIR.glob("*.md")}
    assert len(corpus_files) >= 5, "Corpus must have at least 5 benchmark documents"

    for item in dataset:
        assert item.id > 0, "Item ID must be positive"
        assert item.question.strip(), f"Item {item.id} has empty question"
        assert item.expected_sources, f"Item {item.id} has no expected sources"
        for src in item.expected_sources:
            assert src in corpus_files, f"Item {item.id} references non-existent corpus source '{src}'"
        assert item.category in ("factual", "semantic_paraphrase", "conceptual", "technical_numeric", "follow_up", "general")
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
        ranges=section_ranges(CORPUS_DIR),
    )

    assert summary.total_queries == 60
    assert summary.hit_rate_5 >= 0.90, f"Hit-Rate@5 should be at least 90%, got {summary.hit_rate_5:.2f}"
    assert summary.mrr >= 0.85, f"MRR should be at least 0.85, got {summary.mrr:.4f}"
    assert "factual" in summary.category_breakdown
    assert "easy" in summary.difficulty_breakdown
    assert 0.0 < summary.section_hit_5 <= summary.hit_rate_5 + 1e-9   # a section hit implies a file hit
    assert summary.section_mrr <= summary.mrr + 1e-9


def test_follow_up_items_carry_history():
    follow_ups = [i for i in load_dataset(DATASET_PATH) if i.category == "follow_up"]
    assert len(follow_ups) >= 8
    for item in follow_ups:
        assert [t["role"] for t in item.history] == ["user", "assistant"], f"Item {item.id} needs one prior exchange"


def test_section_coverage_needs_the_right_section_not_just_the_file():
    ranges = section_ranges(CORPUS_DIR)
    item = next(i for i in load_dataset(DATASET_PATH) if i.expected_section == "Adaptive Semantic Chunker")
    start, end = ranges[(item.expected_sources[0], item.expected_section)]
    inside = RetrievedCandidate(item.expected_sources[0], "", 1.0, char_start=start, char_end=end)
    elsewhere = RetrievedCandidate(item.expected_sources[0], "", 1.0, char_start=0, char_end=start - 1)
    other_file = RetrievedCandidate("deployment_and_devops.md", "", 1.0, char_start=start, char_end=end)
    assert covers_section(inside, item, ranges)
    assert not covers_section(elsewhere, item, ranges)
    assert not covers_section(other_file, item, ranges)


def test_score_filtering_impact():
    """Verify that setting an aggressive score floor filters out lower scoring candidates."""
    dataset = load_dataset(DATASET_PATH)
    index = LocalBenchmarkIndex(CORPUS_DIR)

    # Moderate score floor
    normal = evaluate_dataset(index.search, dataset, top_k=5, min_score=0.0)
    # Hyper-aggressive threshold that will filter out some hits
    strict = evaluate_dataset(index.search, dataset, top_k=5, min_score=0.25)

    assert strict.hit_rate_5 <= normal.hit_rate_5


def test_flash_reranker_improves_metrics():
    """Verify that second-stage flash cross-encoder reranker improves Section@5 and Section MRR."""
    dataset = load_dataset(DATASET_PATH)
    index_baseline = LocalBenchmarkIndex(CORPUS_DIR, rerank=False)
    index_reranked = LocalBenchmarkIndex(CORPUS_DIR, rerank=True)

    summary_baseline = evaluate_dataset(
        search_fn=index_baseline.search,
        dataset=dataset,
        top_k=5,
        ranges=section_ranges(CORPUS_DIR),
    )
    summary_reranked = evaluate_dataset(
        search_fn=index_reranked.search,
        dataset=dataset,
        top_k=5,
        ranges=section_ranges(CORPUS_DIR),
    )

    # Reranking should achieve >= baseline section accuracy and MRR
    assert summary_reranked.section_hit_5 >= summary_baseline.section_hit_5
    assert summary_reranked.section_mrr >= summary_baseline.section_mrr
    assert len(summary_reranked.missed_queries) <= len(summary_baseline.missed_queries)


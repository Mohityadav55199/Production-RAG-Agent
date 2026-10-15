"""
Unit tests for the Flash Cross-Encoder Reranker.
Validates token coverage, heading/section alignment, contiguous phrase boosts,
and length damping.
"""

import pytest
from app.services.retrieval_service import RetrievedChunk, flash_rerank_chunks


def test_flash_rerank_empty_and_fallback():
    assert flash_rerank_chunks("test query", []) == []

    chunk = RetrievedChunk(
        document_id="doc1",
        filename="test.md",
        page_number=1,
        chunk_index=0,
        text="Normal content for testing purposes without matches.",
        score=0.8,
    )
    # Stopwords only query falls back to raw tokens or original candidates
    res = flash_rerank_chunks("the and of", [chunk], top_k=5)
    assert len(res) == 1
    assert res[0].document_id == "doc1"


def test_flash_rerank_phrase_boost():
    """Verify that contiguous 2-gram and 3-gram matches get the 1.40x boost."""
    chunk_exact = RetrievedChunk(
        document_id="doc_exact",
        filename="exact.md",
        page_number=1,
        chunk_index=0,
        text="The reciprocal rank fusion algorithm merges dense and sparse results cleanly.",
        score=0.70,
    )
    chunk_scattered = RetrievedChunk(
        document_id="doc_scattered",
        filename="scattered.md",
        page_number=1,
        chunk_index=0,
        text="Rank the items by fusion of various reciprocal scores across documents.",
        score=0.75,  # higher initial base score
    )

    query = "reciprocal rank fusion"
    reranked = flash_rerank_chunks(query, [chunk_scattered, chunk_exact], top_k=2)

    # Even though doc_scattered had a higher initial score, doc_exact has the exact contiguous phrase match
    assert reranked[0].document_id == "doc_exact"
    assert reranked[0].score > reranked[1].score


def test_flash_rerank_heading_boost():
    """Verify that heading and section alignment provides the 1.25x boost."""
    chunk_in_section = RetrievedChunk(
        document_id="doc_sec",
        filename="auth.md",
        page_number=1,
        chunk_index=0,
        text="All users authenticate through the portal using stateless web tokens.",
        heading="Role-Based Access Control",
        section="Role-Based Access Control",
        score=0.70,
    )
    chunk_other = RetrievedChunk(
        document_id="doc_other",
        filename="other.md",
        page_number=1,
        chunk_index=0,
        text="All users authenticate through the portal using stateless web tokens.",
        heading="Overview",
        section="Overview",
        score=0.70,
    )

    query = "Role-Based Access Control permissions"
    reranked = flash_rerank_chunks(query, [chunk_other, chunk_in_section], top_k=2)
    assert reranked[0].document_id == "doc_sec"


def test_flash_rerank_length_penalty():
    """Verify that chunks under 100 characters receive damping."""
    short_chunk = RetrievedChunk(
        document_id="doc_short",
        filename="short.md",
        page_number=1,
        chunk_index=0,
        text="Too short.",  # 10 chars
        score=0.85,
    )
    full_chunk = RetrievedChunk(
        document_id="doc_full",
        filename="full.md",
        page_number=1,
        chunk_index=0,
        text="This is a substantive chunk of text that provides comprehensive detail explaining the exact architecture and parameters.",
        score=0.80,
    )

    query = "substantive chunk text architecture"
    reranked = flash_rerank_chunks(query, [short_chunk, full_chunk], top_k=2)
    assert reranked[0].document_id == "doc_full"


def _chunk(doc_id: str, text: str, score: float = 0.7) -> RetrievedChunk:
    return RetrievedChunk(document_id=doc_id, filename=f"{doc_id}.md", page_number=1, chunk_index=0,
                          text=text, score=score)


def test_flash_rerank_matches_whole_words_only():
    """A query word inside a longer word ("go" in "google") is not a match."""
    real = _chunk("go", "Our backend services are written in Go and deployed as small static binaries for speed.")
    false_hit = _chunk("google", "Google Cloud hosts the ergonomic algorithm demo, which is a good place for new hires to begin onboarding.")
    # Substring matching scored both chunks as full matches and kept the false hit first
    reranked = flash_rerank_chunks("go", [false_hit, real], top_k=2)
    assert reranked[0].document_id == "go"


def test_flash_rerank_matches_simple_word_forms():
    plural = _chunk("plural", "Uploaded files are searched by owner before any other filter is applied to them.")
    other = _chunk("other", "The dashboard shows totals for documents and conversations across the workspace.")
    assert flash_rerank_chunks("search file", [other, plural], top_k=2)[0].document_id == "plural"


def test_flash_rerank_scores_stay_in_cosine_range():
    best = _chunk("best", "Reciprocal rank fusion merges reciprocal rank fusion results. " * 3, score=1.0)
    best.heading = "Reciprocal Rank Fusion"
    (top,) = flash_rerank_chunks("reciprocal rank fusion", [best], top_k=1)
    assert 0.0 <= top.score <= 1.0

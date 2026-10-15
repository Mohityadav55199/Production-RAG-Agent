"""Hybrid search: a chunk containing the question's exact identifier is found even when the vector search
ranks it below the cut-off, and it still has to pass the usual score floor and reranker."""

import asyncio
import uuid
from contextlib import asynccontextmanager

import pytest
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qm

from app.config import get_settings
from app.services import retrieval_service
from app.services.retrieval_service import keyword_candidates, retrieve_chunks, specific_terms

DOC = str(uuid.uuid4())
QUERY_VECTOR = [1.0, 0.0, 0.0]


def unit(x: float, y: float) -> list[float]:
    n = (x * x + y * y) ** 0.5
    return [x / n, y / n, 0.0]


async def build_index() -> AsyncQdrantClient:
    client = AsyncQdrantClient(":memory:")
    await client.create_collection("documents", vectors_config=qm.VectorParams(size=3, distance=qm.Distance.COSINE))
    decoys = [
        "Chunk sizes are tuned for retrieval quality and prompt length.",
        "The chunker splits long documents into overlapping passages.",
        "Retrieval quality depends on passage size and overlap settings.",
        "Passages are embedded in batches before indexing.",
    ]
    points = [
        qm.PointStruct(id=i + 1, vector=unit(1.0, 0.25 + 0.05 * i), payload={
            "document_id": DOC, "filename": "notes.md", "page_number": 1, "chunk_index": i, "text": t,
        })
        for i, t in enumerate(decoys)
    ]
    # The answer: less similar as a whole (cosine ~0.83), but it names the setting the user asked about
    points.append(qm.PointStruct(id=99, vector=unit(1.0, 0.68), payload={
        "document_id": DOC, "filename": "config.md", "page_number": 2, "chunk_index": 9,
        "text": "MAX_CHUNK_SIZE is 2000 characters; longer sections are split recursively.",
    }))
    await client.upsert("documents", points=points)
    return client


@pytest.fixture
def index(monkeypatch):
    client = asyncio.run(build_index())

    async def fake_embed(texts, task_type="RETRIEVAL_QUERY"):
        return [QUERY_VECTOR for _ in texts]

    class Rows(list):
        pass

    class FakeSession:
        async def execute(self, _stmt):
            return Rows([(uuid.UUID(DOC),)])

    @asynccontextmanager
    async def fake_db_session():
        yield FakeSession()

    monkeypatch.setattr(retrieval_service, "get_qdrant_client", lambda: client)
    monkeypatch.setattr(retrieval_service, "embed_batch_with_retry", fake_embed)
    monkeypatch.setattr("app.db.postgres.get_db_session", fake_db_session)
    monkeypatch.setattr(retrieval_service, "_query_vectors", type(retrieval_service._query_vectors)())
    settings = get_settings()
    monkeypatch.setattr(settings, "QDRANT_COLLECTION", "documents")
    monkeypatch.setattr(settings, "RERANKING_ENABLED", True)
    monkeypatch.setattr(settings, "RERANKING_CANDIDATE_FACTOR", 3)
    return settings


def ask(query: str) -> list[str]:
    chunks = asyncio.run(retrieve_chunks(query, top_k=1, document_ids=[DOC], min_score=0.5, max_gap=None))
    return [c.filename for c in chunks]


def test_identifier_terms_are_picked_and_plain_questions_are_left_alone():
    assert specific_terms("What is MAX_CHUNK_SIZE set to?") == ["MAX_CHUNK_SIZE"]
    assert specific_terms('Explain "reciprocal rank fusion"') == ["reciprocal rank fusion"]
    assert specific_terms("how do I deploy the app") == []


def test_keyword_leg_scores_matches_by_real_cosine(index):
    client = retrieval_service.get_qdrant_client()
    found = asyncio.run(keyword_candidates(client, "documents", "What is MAX_CHUNK_SIZE?", QUERY_VECTOR, None))
    assert [p.payload["filename"] for p in found] == ["config.md"]
    assert found[0].score == pytest.approx(1 / (1 + 0.68 ** 2) ** 0.5, abs=1e-6)


def test_vector_search_alone_misses_the_exact_match(index, monkeypatch):
    monkeypatch.setattr(index, "HYBRID_SEARCH_ENABLED", False)
    assert ask("What is MAX_CHUNK_SIZE set to?") == ["notes.md"]


def test_hybrid_search_finds_it(index):
    assert ask("What is MAX_CHUNK_SIZE set to?") == ["config.md"]


def test_exact_matches_still_need_to_pass_the_score_floor(index):
    chunks = asyncio.run(retrieve_chunks("What is MAX_CHUNK_SIZE set to?", top_k=5, document_ids=[DOC],
                                         min_score=0.9, max_gap=None))
    assert "config.md" not in [c.filename for c in chunks]

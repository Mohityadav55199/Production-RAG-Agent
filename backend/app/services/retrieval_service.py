"""
Semantic retrieval service (Phase 4).

Embeds a query using Gemini (RETRIEVAL_QUERY task type) and performs
an ANN search against the Qdrant collection.

Reuses the existing embed_texts() from Phase 2 — task_type is the only
difference between document ingestion and query embedding.
"""

from collections import OrderedDict
from dataclasses import dataclass

from qdrant_client.http import models as qmodels

from app.config import get_settings
from app.db.qdrant import get_qdrant_client
from app.services.embedding_service import embed_batch_with_retry
from app.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RetrievedChunk:
    """A single chunk returned by the vector search."""

    document_id: str
    filename: str
    page_number: int
    chunk_index: int
    text: str
    score: float   # cosine similarity (0 – 1)


_QUERY_CACHE_SIZE = 256
_query_vectors: "OrderedDict[str, list[float]]" = OrderedDict()


async def _embed_query(query: str) -> list[float]:
    """Embed a search query; repeated questions (retries, re-asks, the eval) skip the embedding API."""
    key = query.strip().lower()
    if key in _query_vectors:
        _query_vectors.move_to_end(key)
        return _query_vectors[key]
    vector = (await embed_batch_with_retry([query], task_type="RETRIEVAL_QUERY"))[0]
    _query_vectors[key] = vector
    if len(_query_vectors) > _QUERY_CACHE_SIZE:
        _query_vectors.popitem(last=False)
    return vector


async def retrieve_chunks(
    query: str,
    top_k: int = 5,
    score_threshold: float = 0.0,
    collection_name: str | None = None,
    document_ids: list[str] | None = None,
    min_score: float | None = None,
    max_gap: float | None = -1.0,
) -> list[RetrievedChunk]:
    """
    Embed *query* and return the top-k most semantically similar chunks.

    Args:
        query:            Natural-language question from the user.
        top_k:            Maximum number of chunks to return.
        score_threshold:  Minimum cosine similarity to include a result.
                          Set to 0.0 to accept all results.
        collection_name:  Override the default collection from settings.
        document_ids:     Restrict the search to these documents (e.g. one project).
        min_score:        Override RETRIEVAL_MIN_SCORE.
        max_gap:          Override RETRIEVAL_MAX_GAP; None disables the gap filter
                          (detailed answers want breadth, not just the top hit).

    Returns:
        List of RetrievedChunk, sorted by score descending.
    """
    settings = get_settings()
    client = get_qdrant_client()
    coll = collection_name or settings.QDRANT_COLLECTION

    # Embed the query with RETRIEVAL_QUERY task type (different from RETRIEVAL_DOCUMENT)
    query_vector = await _embed_query(query)

    floor = settings.RETRIEVAL_MIN_SCORE if min_score is None else min_score
    gap = settings.RETRIEVAL_MAX_GAP if max_gap == -1.0 else max_gap

    query_filter = None
    if document_ids is not None:
        if not document_ids:
            return []
        query_filter = qmodels.Filter(
            must=[qmodels.FieldCondition(key="document_id", match=qmodels.MatchAny(any=document_ids))]
        )

    if hasattr(client, "query_points"):
        query_response = await client.query_points(
            collection_name=coll,
            query=query_vector,
            limit=top_k,
            with_payload=True,
            query_filter=query_filter,
        )
        search_results = query_response.points
    else:
        search_results = await client.search(
            collection_name=coll,
            query_vector=query_vector,
            limit=top_k,
            with_payload=True,
            query_filter=query_filter,
        )

    # Log all raw candidate scores before filtering
    if search_results:
        logger.info("Raw candidate scores before filtering for query '%s':", query)
        for i, hit in enumerate(search_results):
            payload = hit.payload or {}
            filename = payload.get("filename", "unknown")
            logger.info("  Candidate #%d: filename='%s' score=%.4f", i+1, filename, hit.score)
    else:
        logger.info("No raw candidates returned from Qdrant search.")

    chunks: list[RetrievedChunk] = []
    
    if search_results:
        import uuid
        from sqlalchemy import select
        from app.db.postgres import get_db_session
        from app.db.models import Document
        
        doc_ids = set()
        for hit in search_results:
            payload = hit.payload or {}
            doc_id_str = payload.get("document_id")
            if doc_id_str:
                try:
                    doc_ids.add(uuid.UUID(doc_id_str))
                except ValueError:
                    pass
        
        valid_docs = set()
        if doc_ids:
            async with get_db_session() as session:
                from app.db.models import DocumentStatus
                res = await session.execute(
                    select(Document.id).where(
                        Document.id.in_(doc_ids),
                        Document.status == DocumentStatus.COMPLETED
                    )
                )
                valid_docs = {str(r[0]) for r in res}
                
        # First gather all valid chunks (excluding orphans)
        valid_candidates: list[RetrievedChunk] = []
        for hit in search_results:
            payload = hit.payload or {}
            doc_id_str = payload.get("document_id", "")
            if doc_id_str not in valid_docs:
                logger.warning("Found orphan vector referencing non-existent document_id=%s. Ignoring.", doc_id_str)
                continue
            valid_candidates.append(RetrievedChunk(
                document_id=doc_id_str,
                filename=payload.get("filename", "unknown"),
                page_number=int(payload.get("page_number", 1)),
                chunk_index=int(payload.get("chunk_index", 0)),
                text=payload.get("text", ""),
                score=float(hit.score),
            ))
            
        if valid_candidates:
            # Ensure descending order
            valid_candidates.sort(key=lambda c: c.score, reverse=True)
            top_score = valid_candidates[0].score
            gap_cutoff = top_score - gap if gap is not None else float("-inf")
            logger.info("Top score for query is %.4f. Gap cutoff is %.4f (max_gap=%s)", top_score, gap_cutoff, gap)
            
            for c in valid_candidates:
                # Apply absolute score floor
                if c.score < floor:
                    logger.info(
                        "Filtering out chunk filename='%s' index=%d (score=%.4f < floor=%.2f)",
                        c.filename, c.chunk_index, c.score, floor
                    )
                    continue
                # Apply relative score gap limit
                if c.score < gap_cutoff:
                    logger.info(
                        "Filtering out chunk filename='%s' index=%d (score=%.4f < gap_cutoff=%.4f)",
                        c.filename, c.chunk_index, c.score, gap_cutoff
                    )
                    continue
                chunks.append(c)

    logger.info(
        "Retrieved %d chunks above threshold=%.3f (gap=%s) for query (top_k=%d)",
        len(chunks),
        floor,
        gap,
        top_k,
    )
    return chunks


async def fetch_document_chunks(document_id: str, limit: int = 20) -> list[RetrievedChunk]:
    """Return a document's chunks in order, without a similarity search (e.g. a project overview)."""
    settings = get_settings()
    client = get_qdrant_client()
    points, _ = await client.scroll(
        collection_name=settings.QDRANT_COLLECTION,
        scroll_filter=qmodels.Filter(
            must=[qmodels.FieldCondition(key="document_id", match=qmodels.MatchValue(value=document_id))]
        ),
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    chunks = [
        RetrievedChunk(
            document_id=document_id,
            filename=(p.payload or {}).get("filename", "unknown"),
            page_number=int((p.payload or {}).get("page_number", 1)),
            chunk_index=int((p.payload or {}).get("chunk_index", 0)),
            text=(p.payload or {}).get("text", ""),
            score=1.0,
        )
        for p in points
    ]
    chunks.sort(key=lambda c: c.chunk_index)
    return chunks

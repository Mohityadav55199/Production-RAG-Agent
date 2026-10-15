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


import re

@dataclass
class RetrievedChunk:
    """A single chunk returned by the vector search."""

    document_id: str
    filename: str
    page_number: int
    chunk_index: int
    text: str
    score: float   # cosine similarity (0 – 1) or composite reranked score
    heading: str | None = None
    section: str | None = None
    dense_score: float | None = None
    rerank_score: float | None = None


_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can",
    "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down",
    "during", "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't", "have", "haven't",
    "having", "he", "her", "here", "hers", "herself", "him", "himself", "his", "how", "i", "if", "in",
    "into", "is", "isn't", "it", "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself",
    "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our", "ours", "ourselves",
    "out", "over", "own", "same", "shan't", "she", "should", "shouldn't", "so", "some", "such", "than", "that",
    "the", "their", "theirs", "them", "themselves", "then", "there", "these", "they", "this", "those",
    "through", "to", "too", "under", "until", "up", "very", "was", "wasn't", "we", "were", "weren't", "what",
    "when", "where", "which", "while", "who", "whom", "why", "with", "won't", "would", "wouldn't", "you",
    "your", "yours", "yourself", "yourselves",
}


def flash_rerank_chunks(
    query: str,
    chunks: list[RetrievedChunk],
    top_k: int = 5,
) -> list[RetrievedChunk]:
    """
    Second-stage flash cross-encoder reranker.

    Scores candidate chunks using:
      1. Exact token coverage (non-stopwords).
      2. Heading & section alignment (1.25x boost).
      3. Contiguous 2-gram and 3-gram phrase match (1.40x boost).
      4. Length penalty for chunks under 100 characters.
    """
    if not chunks:
        return []

    words = re.findall(r"\b[a-zA-Z0-9_\-\.]{2,}\b", query.lower())
    q_tokens = [w for w in words if w not in _STOPWORDS] or words
    if not q_tokens:
        return chunks[:top_k]

    reranked: list[RetrievedChunk] = []
    for c in chunks:
        text_lower = c.text.lower()
        heading_lower = (c.heading or "").lower()
        section_lower = (c.section or "").lower()

        # 1. Exact token coverage
        matched = sum(1 for t in q_tokens if t in text_lower)
        token_coverage = matched / len(q_tokens)

        # 2. Heading and section weight (1.25x boost)
        heading_match = any(t in heading_lower or t in section_lower for t in q_tokens)
        heading_boost = 1.25 if heading_match else 1.0

        # 3. Contiguous phrase bonus (1.40x boost)
        phrase_match = False
        if len(words) >= 2:
            for i in range(len(words) - 1):
                bigram = f"{words[i]} {words[i+1]}"
                if bigram in text_lower:
                    phrase_match = True
                    break
        if not phrase_match and len(words) >= 3:
            for i in range(len(words) - 2):
                trigram = f"{words[i]} {words[i+1]} {words[i+2]}"
                if trigram in text_lower:
                    phrase_match = True
                    break
        phrase_boost = 1.40 if phrase_match else 1.0

        # 4. Length penalty for very short snippets
        length_factor = min(1.0, max(0.2, len(c.text) / 100.0))

        # Composite score blending dense score (0.40) and token coverage (0.60)
        dense = c.dense_score if c.dense_score is not None else c.score
        composite = (dense * 0.40 + token_coverage * 0.60) * heading_boost * phrase_boost * length_factor

        reranked.append(
            RetrievedChunk(
                document_id=c.document_id,
                filename=c.filename,
                page_number=c.page_number,
                chunk_index=c.chunk_index,
                text=c.text,
                score=composite,
                heading=c.heading,
                section=c.section,
                dense_score=dense,
                rerank_score=composite,
            )
        )

    reranked.sort(key=lambda x: x.score, reverse=True)
    return reranked[:top_k]


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
    rerank: bool = True,
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

    candidate_limit = (
        top_k * settings.RERANKING_CANDIDATE_FACTOR
        if (settings.RERANKING_ENABLED and rerank)
        else top_k
    )

    if hasattr(client, "query_points"):
        query_response = await client.query_points(
            collection_name=coll,
            query=query_vector,
            limit=candidate_limit,
            with_payload=True,
            query_filter=query_filter,
        )
        search_results = query_response.points
    else:
        search_results = await client.search(
            collection_name=coll,
            query_vector=query_vector,
            limit=candidate_limit,
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
                heading=payload.get("heading"),
                section=payload.get("section"),
                dense_score=float(hit.score),
            ))
            
        if valid_candidates:
            # Apply initial dense score floor
            if floor > 0.0:
                valid_candidates = [c for c in valid_candidates if (c.dense_score or c.score) >= floor]

            if valid_candidates:
                if settings.RERANKING_ENABLED and rerank and len(valid_candidates) > 1:
                    valid_candidates = flash_rerank_chunks(query, valid_candidates, top_k=candidate_limit)
                else:
                    valid_candidates.sort(key=lambda c: c.score, reverse=True)

                top_score = valid_candidates[0].score
                gap_cutoff = top_score - gap if gap is not None else float("-inf")
                logger.info("Top score for query is %.4f. Gap cutoff is %.4f (max_gap=%s)", top_score, gap_cutoff, gap)

                for c in valid_candidates:
                    # Apply relative score gap limit
                    if c.score < gap_cutoff:
                        logger.info(
                            "Filtering out chunk filename='%s' index=%d (score=%.4f < gap_cutoff=%.4f)",
                            c.filename, c.chunk_index, c.score, gap_cutoff
                        )
                        continue
                    chunks.append(c)
                    if len(chunks) >= top_k:
                        break

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

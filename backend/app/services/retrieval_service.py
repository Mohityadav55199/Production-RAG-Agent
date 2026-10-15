"""
Semantic retrieval service (Phase 4).

Embeds a query using Gemini (RETRIEVAL_QUERY task type) and performs
an ANN search against the Qdrant collection.

Reuses the existing embed_texts() from Phase 2 — task_type is the only
difference between document ingestion and query embedding.
"""

import re
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


_TOKEN_RE = re.compile(r"[a-z0-9_][a-z0-9_\-\.]*[a-z0-9_]")

# Largest product of the boosts below; dividing by it keeps the composite score in 0-1 like a cosine score
_MAX_BOOST = 1.25 * 1.40


def _rank_key(c: "RetrievedChunk") -> tuple:
    """Best score first; equal scores in reading order, so results never depend on how the index orders ties."""
    return (-c.score, c.document_id, c.page_number, c.chunk_index)


def _stem(word: str) -> str:
    """Light suffix stripping so "files"/"file" and "searching"/"search" match; not a full stemmer."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix) and not word.endswith("ss"):
            return word[: -len(suffix)]
    return word


def _tokens(text: str) -> list[str]:
    """Lower-case, lightly stemmed word tokens; "role-based" and "app.main" stay whole."""
    return [_stem(t) for t in _TOKEN_RE.findall(text.lower())]


def _has_phrase(words: list[str], text_tokens: list[str]) -> bool:
    """True if any 2- or 3-word run of the query appears, word for word, in the text."""
    joined = f" {' '.join(text_tokens)} "
    for n in (2, 3):
        for i in range(len(words) - n + 1):
            if f" {' '.join(words[i:i + n])} " in joined:
                return True
    return False


def flash_rerank_chunks(
    query: str,
    chunks: list[RetrievedChunk],
    top_k: int = 5,
) -> list[RetrievedChunk]:
    """
    Second-stage lexical reranker (cheap, no model call).

    Scores candidate chunks using:
      1. Whole-word coverage of the query's non-stopwords ("go" does not match "google").
      2. Heading & section alignment (1.25x boost).
      3. Contiguous 2-gram and 3-gram phrase match (1.40x boost).
      4. Length penalty for chunks under 100 characters.
    The composite is normalised to 0-1.
    """
    if not chunks:
        return []

    words = [w for w in _tokens(query) if len(w) >= 2]
    q_tokens = [w for w in words if w not in _STOPWORDS] or words
    if not q_tokens:
        return chunks[:top_k]

    reranked: list[RetrievedChunk] = []
    for c in chunks:
        text_tokens = _tokens(c.text)
        text_set = set(text_tokens)
        heading_set = set(_tokens(f"{c.heading or ''} {c.section or ''}"))

        # 1. Whole-word token coverage
        token_coverage = sum(1 for t in q_tokens if t in text_set) / len(q_tokens)

        # 2. Heading and section weight (1.25x boost)
        heading_boost = 1.25 if any(t in heading_set for t in q_tokens) else 1.0

        # 3. Contiguous phrase bonus (1.40x boost)
        phrase_boost = 1.40 if _has_phrase(words, text_tokens) else 1.0

        # 4. Length penalty for very short snippets
        length_factor = min(1.0, max(0.2, len(c.text) / 100.0))

        # Composite score blending dense score (0.40) and token coverage (0.60)
        dense = c.dense_score if c.dense_score is not None else c.score
        composite = (
            (dense * 0.40 + token_coverage * 0.60) * heading_boost * phrase_boost * length_factor / _MAX_BOOST
        )

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

    reranked.sort(key=_rank_key)
    return reranked[:top_k]


# ── Hybrid search: an exact-term leg next to the vector search ──────────────
# Embeddings are weak at exact identifiers (MAX_CHUNK_SIZE, gpt-oss-120b, HTTP 429, v2.3.1): a chunk that
# contains one can rank below the vector search's cut-off. For questions with such terms, chunks containing
# them are fetched through Qdrant's full-text index, scored by their real cosine similarity to the question,
# and added to the candidates; the score floor, reranker and gap filter then treat them like any other.

_TERM_RE = re.compile(r'"([^"]{3,60})"|([A-Za-z0-9][\w.\-/]*[A-Za-z0-9]|[A-Za-z0-9]{2,})')
_MAX_TERMS = 4
_PER_TERM_LIMIT = 20


def specific_terms(query: str) -> list[str]:
    """Identifier-like terms worth an exact search: quoted phrases, and tokens with digits, underscores,
    dots, hyphens or slashes inside, or capitals after the first letter (camelCase, ACRONYMS)."""
    terms: list[str] = []
    for quoted, token in _TERM_RE.findall(query):
        if quoted:
            terms.append(quoted.strip())
            continue
        t = token
        if t.lower() in _STOPWORDS:
            continue
        specific = (
            any(ch.isdigit() for ch in t)
            or any(ch in "_./-" for ch in t[1:-1])
            or (len(t) >= 2 and any(ch.isupper() for ch in t[1:]))
        )
        if specific and len(t) >= 2:
            terms.append(t)
    return list(dict.fromkeys(terms))[:_MAX_TERMS]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


async def keyword_candidates(
    client, collection: str, query: str, query_vector: list[float], base_filter: "qmodels.Filter | None",
) -> list["qmodels.ScoredPoint"]:
    """Chunks containing the question's exact identifiers, scored by cosine similarity to the question."""
    found: dict[str, qmodels.ScoredPoint] = {}
    for term in specific_terms(query):
        conditions = list(base_filter.must or []) if base_filter else []
        conditions.append(qmodels.FieldCondition(key="text", match=qmodels.MatchText(text=term)))
        try:
            points, _ = await client.scroll(
                collection_name=collection,
                scroll_filter=qmodels.Filter(must=conditions),
                limit=_PER_TERM_LIMIT,
                with_payload=True,
                with_vectors=True,
            )
        except Exception as exc:  # noqa: BLE001 - the vector search alone still answers
            logger.warning("Keyword search for %r failed: %s", term, exc)
            continue
        for p in points:
            vector = p.vector if isinstance(p.vector, list) else None
            if vector is None or str(p.id) in found:
                continue
            found[str(p.id)] = qmodels.ScoredPoint(
                id=p.id, version=0, score=_cosine(query_vector, vector), payload=p.payload, vector=None,
            )
    return list(found.values())


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

    # Hybrid: add chunks that contain the question's exact identifiers but missed the vector cut-off
    if settings.HYBRID_SEARCH_ENABLED:
        seen = {str(h.id) for h in search_results}
        extra = [
            p for p in await keyword_candidates(client, coll, query, query_vector, query_filter)
            if str(p.id) not in seen
        ]
        if extra:
            logger.debug("Hybrid search added %d exact-term candidate(s)", len(extra))
            search_results = list(search_results) + extra

    # Log all raw candidate scores before filtering
    if search_results:
        # Query text and per-candidate detail are user data: DEBUG only
        logger.debug("Raw candidate scores before filtering for query %r:", query)
        for i, hit in enumerate(search_results):
            payload = hit.payload or {}
            filename = payload.get("filename", "unknown")
            logger.debug("  Candidate #%d: filename='%s' score=%.4f", i+1, filename, hit.score)
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
                    valid_candidates.sort(key=_rank_key)

                # The gap limit (RETRIEVAL_MAX_GAP) is a cosine-similarity distance, so it is measured on the
                # dense scores even after reranking has reordered the candidates
                top_score = max((c.dense_score if c.dense_score is not None else c.score) for c in valid_candidates)
                gap_cutoff = top_score - gap if gap is not None else float("-inf")
                logger.debug("Top dense score is %.4f. Gap cutoff is %.4f (max_gap=%s)", top_score, gap_cutoff, gap)

                for c in valid_candidates:
                    dense = c.dense_score if c.dense_score is not None else c.score
                    if dense < gap_cutoff:
                        logger.debug(
                            "Filtering out chunk filename='%s' index=%d (dense=%.4f < gap_cutoff=%.4f)",
                            c.filename, c.chunk_index, dense, gap_cutoff
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

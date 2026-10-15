"""
Tidy retrieved chunks before they reach the prompt.

Neighbouring chunks overlap (CHUNK_OVERLAP) and uploads of near-identical files produce duplicate chunks, so a
top-k list often spends its prompt budget repeating itself. Two passes fix that:

1. drop a chunk whose text is contained in, or almost identical to, a higher-scoring one;
2. join chunks that are consecutive in the same document into one passage, without repeating the overlap.

The result is what both the prompt and the cited sources use, so citations always match the context.
"""

from __future__ import annotations

import re
from dataclasses import replace

from app.services.retrieval_service import RetrievedChunk

_NEAR_DUPLICATE = 0.9      # token-set Jaccard similarity at which two chunks count as the same text
_MAX_OVERLAP_SCAN = 600    # longest overlap looked for when joining neighbours (CHUNK_OVERLAP is 200)
_MIN_OVERLAP = 20          # shorter coincidences are not real overlaps


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _is_duplicate(a: str, b: str) -> bool:
    if a in b or b in a:
        return True
    ta, tb = set(a.split()), set(b.split())
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= _NEAR_DUPLICATE


def drop_duplicates(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Keep the best-scoring copy of repeated text; the original order is preserved."""
    kept: list[tuple[RetrievedChunk, str]] = []
    for chunk in sorted(chunks, key=lambda c: c.score, reverse=True):
        text = _norm(chunk.text)
        if not any(_is_duplicate(text, other) for _, other in kept):
            kept.append((chunk, text))
    survivors = {id(c) for c, _ in kept}
    return [c for c in chunks if id(c) in survivors]


def _join(first: str, second: str) -> str:
    """Append *second* to *first*, cutting the overlapping text they share."""
    for size in range(min(len(first), len(second), _MAX_OVERLAP_SCAN), _MIN_OVERLAP - 1, -1):
        if first[-size:] == second[:size]:
            return first + second[size:]
    return first.rstrip() + "\n\n" + second.lstrip()


def merge_adjacent(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Join consecutive chunks of one document; passages stay ordered by their best chunk's score."""
    by_doc: dict[str, list[RetrievedChunk]] = {}
    for chunk in chunks:
        by_doc.setdefault(chunk.document_id, []).append(chunk)

    passages: list[RetrievedChunk] = []
    for group in by_doc.values():
        group.sort(key=lambda c: c.chunk_index)
        current = group[0]
        last_index = current.chunk_index
        for chunk in group[1:]:
            if chunk.chunk_index == last_index + 1:
                current = replace(current, text=_join(current.text, chunk.text), score=max(current.score, chunk.score))
            else:
                passages.append(current)
                current = chunk
            last_index = chunk.chunk_index
        passages.append(current)

    return sorted(passages, key=lambda c: c.score, reverse=True)


def tidy_chunks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    return merge_adjacent(drop_duplicates(chunks)) if len(chunks) > 1 else chunks

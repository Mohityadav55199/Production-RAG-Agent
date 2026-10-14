"""
Side-by-side comparison of two sources with a streamed LLM analysis.

A side can be pasted text/code, an imported code project, or a single
document. Pasted text is used verbatim; projects/documents are represented by
the chunks most relevant to the comparison focus (plus the project overview).
"""

import difflib
from typing import AsyncGenerator, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.services.rag_graph import build_context, to_sources
from app.services.retrieval_service import RetrievedChunk, fetch_document_chunks, retrieve_chunks
from app.services.scope_service import resolve_scope
from app.utils.logging import get_logger

logger = get_logger(__name__)

_MAX_TEXT_CHARS = 10_000       # per pasted side
_MAX_SIDE_CONTEXT = 10_000     # per project/document side
_MAX_DIFF_LINES = 300
_DEFAULT_FOCUS = (
    "overall purpose, architecture and structure, main features, "
    "technologies and dependencies, code quality and key implementation details"
)


class CompareSide(BaseModel):
    type: Literal["text", "project", "document"]
    content: str | None = Field(None, max_length=100_000, description="Pasted code or text (type='text').")
    label: str | None = Field(None, max_length=100, description="Display name for pasted text.")
    project: str | None = Field(None, max_length=200)
    document_id: str | None = None


class CompareRequest(BaseModel):
    left: CompareSide
    right: CompareSide
    focus: str | None = Field(None, max_length=1000, description="What to focus the comparison on.")
    provider: str | None = None
    model: str | None = None


_SYSTEM_PROMPT = """\
You are a senior software engineer and analyst comparing two sources: A and B.
Each may be source code, a whole code project, or a document.

Write a detailed, well-structured Markdown comparison:

## Summary
One short paragraph: what A and B each are, and the headline difference.

## Side-by-side
A Markdown table comparing the most important aspects (e.g. purpose,
approach/architecture, technologies, features, complexity, quality).

## Key similarities
## Key differences
Explain each point concretely, citing file paths or quoting short code
excerpts in fenced code blocks.

## Algorithms and complexity
Only when either side contains algorithmic code (e.g. C++/Java/Python DSA
solutions): state each approach's algorithm/data structure, its time and
space complexity (Big-O, with reasoning), correctness concerns and edge
cases (empty input, duplicates, overflow, large n), and which one is faster
or safer in practice.

## Strengths and weaknesses
For each of A and B. For code also consider correctness/bugs, readability,
performance, security and maintainability.

## Recommendation
Which is better for what, or how to combine/merge the best of both.

Rules: base every claim on the provided content; you may use general
programming knowledge to interpret it. If a side's content is incomplete
(only excerpts were provided), say so where it matters. If a user focus is
given, prioritise it.
"""


async def _side_material(side: CompareSide, name: str, focus: str) -> tuple[str, str, list[RetrievedChunk]]:
    """Return (label, prompt_material, chunks_used) for one side."""
    if side.type == "text":
        text = (side.content or "").strip()
        if not text:
            raise ValueError(f"Side {name}: paste some code or text to compare.")
        label = side.label or f"Pasted text {name}"
        truncated = len(text) > _MAX_TEXT_CHARS
        body = text[:_MAX_TEXT_CHARS] + ("\n…[truncated]" if truncated else "")
        return label, f"```\n{body}\n```", []

    scope = await resolve_scope(
        project=side.project if side.type == "project" else None,
        document_id=side.document_id if side.type == "document" else None,
    )
    chunks = await retrieve_chunks(
        query=focus, top_k=10, document_ids=scope.document_ids, min_score=0.0, max_gap=None,
    )
    if scope.overview_document_id:
        chunks = await fetch_document_chunks(scope.overview_document_id, limit=2) + [
            c for c in chunks if c.document_id != scope.overview_document_id
        ]
    if not chunks:
        raise ValueError(f"Side {name}: no indexed content found for {scope.label}.")
    return scope.label, build_context(chunks, max_chars=_MAX_SIDE_CONTEXT), chunks


def _unified_diff(left: CompareSide, right: CompareSide) -> str | None:
    if left.type != "text" or right.type != "text":
        return None
    diff = list(difflib.unified_diff(
        (left.content or "").splitlines(),
        (right.content or "").splitlines(),
        fromfile=left.label or "A",
        tofile=right.label or "B",
        lineterm="",
    ))
    if len(diff) > _MAX_DIFF_LINES:
        diff = diff[:_MAX_DIFF_LINES] + [f"... ({len(diff) - _MAX_DIFF_LINES} more diff lines not shown)"]
    return "\n".join(diff) if diff else ""


async def stream_comparison(req: CompareRequest) -> AsyncGenerator[dict, None]:
    """Yield SSE-ready dicts: diff (text vs text only), sources, chunk..., done."""
    from app.services.llm_factory import get_configured_llm

    focus = (req.focus or "").strip() or _DEFAULT_FOCUS

    label_a, material_a, chunks_a = await _side_material(req.left, "A", focus)
    label_b, material_b, chunks_b = await _side_material(req.right, "B", focus)

    diff = _unified_diff(req.left, req.right)
    if diff is not None:
        yield {"type": "diff", "diff": diff}

    sources = to_sources(chunks_a + chunks_b)
    yield {"type": "sources", "sources": sources, "retrieved_count": len(sources)}

    diff_note = f"\n\n# Line diff (A → B)\n```diff\n{diff[:6000]}\n```" if diff else ""
    user_prompt = (
        f"Comparison focus: {focus}\n\n"
        f"# A — {label_a}\n{material_a}\n\n"
        f"# B — {label_b}\n{material_b}"
        f"{diff_note}"
    )

    llm = get_configured_llm(requested_provider=req.provider, requested_model=req.model)
    total = 0
    async for chunk in llm.astream([SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user_prompt)]):
        raw = chunk.content
        token = (
            "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in raw)
            if isinstance(raw, list) else str(raw or "")
        )
        if token:
            total += len(token)
            yield {"type": "chunk", "content": token}

    logger.info("Comparison '%s' vs '%s' streamed %d chars", label_a, label_b, total)
    yield {"type": "done", "total_chars": total}

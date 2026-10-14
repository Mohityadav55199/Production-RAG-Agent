"""
Pydantic schemas for the RAG query endpoint and SSE event stream (Phase 4).
"""

import uuid
from typing import Literal

from pydantic import BaseModel, Field


# ── Request ───────────────────────────────────────────────────────────────────

class ImageInput(BaseModel):
    """One image attached to a question. The server re-encodes it; the declared type is not trusted."""

    mime: Literal["image/png", "image/jpeg", "image/webp", "image/gif"]
    data: str = Field(..., max_length=6_000_000, description="Base64 image bytes, without a data: prefix.")


class QueryRequest(BaseModel):
    """Body accepted by POST /query."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="The user's natural-language question.",
    )
    conversation_id: uuid.UUID | None = Field(
        None,
        description=(
            "UUID of an existing conversation to continue. "
            "Omit (or send null) to start a new conversation."
        ),
    )
    top_k: int = Field(
        5,
        ge=1,
        le=20,
        description="Number of document chunks to retrieve from the vector store.",
    )
    provider: str | None = Field(
        None,
        description="Optional LLM provider override ('groq', 'gemini').",
    )
    model: str | None = Field(
        None,
        description="Optional LLM model override (e.g., 'llama-3.3-70b-versatile', 'gemini-2.5-flash').",
    )
    images: list[ImageInput] = Field(
        default_factory=list,
        max_length=3,
        description="Up to 3 images to ask about (screenshots, diagrams, photos). Needs a Gemini API key.",
    )
    answer_style: Literal["detailed", "concise"] = Field(
        "detailed",
        description="'detailed' gives thorough, structured explanations; 'concise' gives short answers.",
    )
    scope_kind: Literal["all", "documents", "projects"] = Field(
        "all",
        description="When no project/document is chosen: search everything, only uploaded documents, or only code projects.",
    )
    project: str | None = Field(
        None,
        max_length=200,
        description="Restrict retrieval to one imported code project (its name, e.g. 'my-repo').",
    )
    document_id: uuid.UUID | None = Field(
        None,
        description="Restrict retrieval to a single document.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "query": "What are the main risk factors discussed in the report?",
                "conversation_id": None,
                "top_k": 5,
            }
        }
    }


# ── Source citation ───────────────────────────────────────────────────────────

class SourceCitation(BaseModel):
    """A single retrieved chunk that was used to answer the query."""

    document_id: str
    filename: str
    page_number: int
    chunk_index: int
    text_snippet: str = Field(..., description="First 300 chars of the chunk text.")
    score: float = Field(..., description="Cosine similarity score (0–1).")


# ── SSE event payloads ────────────────────────────────────────────────────────

class SSEThinking(BaseModel):
    """Emitted immediately to signal the pipeline has started."""
    type: Literal["thinking"] = "thinking"


class SSESources(BaseModel):
    """Emitted after retrieval — before any generated tokens."""
    type: Literal["sources"] = "sources"
    sources: list[SourceCitation]
    retrieved_count: int


class SSEChunk(BaseModel):
    """One streaming token (or small group of tokens) from the LLM."""
    type: Literal["chunk"] = "chunk"
    content: str


class SSEDone(BaseModel):
    """Emitted once the full answer has been streamed."""
    type: Literal["done"] = "done"
    conversation_id: str
    total_chars: int


class SSEError(BaseModel):
    """Emitted on any unrecoverable pipeline error."""
    type: Literal["error"] = "error"
    message: str

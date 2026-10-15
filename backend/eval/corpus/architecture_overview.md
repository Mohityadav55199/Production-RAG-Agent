# System Architecture Overview

## Executive Summary
The Production RAG Agent is an enterprise-grade retrieval-augmented generation platform designed for low-latency question answering across heterogeneous document stores. The architecture decouples document ingestion, vector retrieval, and generative synthesis into independent asynchronous services.

## Core Services and Communication
The platform is organized into three primary layers:
1. **Frontend Presentation Layer**: Built with Next.js 15, React 19, and Tailwind CSS. It communicates with the backend via server-sent events (SSE) for token-by-token answer streaming and citations.
2. **FastAPI Application Backend**: Implements asynchronous REST endpoints, manages user authentication, coordinates document lifecycle transitions, and executes LangGraph state machines.
3. **Storage & Vector Infrastructure**: Employs PostgreSQL with asyncpg for relational metadata, document tracking, and conversation turns; and Qdrant Vector Database for high-dimensional approximate nearest neighbor (ANN) vector indexing.

## LLM Fallback Architecture
To guarantee 99.9% availability during provider disruptions, the system implements a resilient multi-tier LLM cascade:
- **Primary LLM Provider**: Groq running `llama-3.3-70b-versatile` with temperature 0.1 for high-precision grounded reasoning.
- **Fallback Chain**: If Groq encounters rate-limiting (HTTP 429), timeouts, or service outages, execution immediately cascades through:
  1. `llama-3.1-8b-instant` (low-latency fallback)
  2. `mixtral-8x7b-32768` (extended context fallback)
  3. `gemma2-9b-it` (tertiary fallback)
- **Secondary Cloud Provider**: Google Gemini (`gemini-2.5-flash`) acts as an external provider fallback when entire primary provider clusters are unreachable.

## Query Pipeline and Streaming Lifecycle
When a user submits a natural-language query:
1. The request enters `POST /query` and is validated against user rate limits.
2. The user query is embedded using Gemini embeddings with `task_type="RETRIEVAL_QUERY"`.
3. An ANN search is executed against Qdrant fetching the top-k chunks.
4. Candidate chunks are filtered through an absolute cosine similarity floor (`RETRIEVAL_MIN_SCORE = 0.63`) and a relative gap filter (`RETRIEVAL_MAX_GAP = 0.05`).
5. Surviving chunks are formatted into a prompt context with source metadata.
6. The selected LLM generates the response, streamed as Server-Sent Events (SSE) with `event: chunk`, followed by `event: sources` and `[DONE]`.

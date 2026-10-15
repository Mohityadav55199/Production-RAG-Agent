# Hybrid Retrieval and Reranking Architecture

This specification outlines the hybrid search pipeline combining dense vector embeddings with sparse lexical indexing, fused via Reciprocal Rank Fusion (RRF) and scored by a second-stage reranker.

## The Semantic vs Lexical Gap

Dense retrieval models (e.g., `text-embedding-004`) excel at conceptual understanding, synonyms, and semantic paraphrasing. However, they frequently suffer from false positives on exact technical symbols, specific error codes, unique function identifiers, and acronyms (e.g., `k8s`, `Qdrant`, `pLDDT`, `HTTP 429`).

To bridge this gap, the system deploys a two-tier retrieval architecture:
1. **Dense Vector Search**: Approximate Nearest Neighbors (ANN) over 768-dimensional normalized embeddings indexed in Qdrant with HNSW cosine similarity.
2. **Sparse Lexical Search**: BM25 / token-frequency inverted index targeting technical tokens, symbols, and exact code identifiers.

## Reciprocal Rank Fusion (RRF) Formulation

The candidate results from dense vector retrieval and sparse lexical retrieval are merged using Reciprocal Rank Fusion:

$$RRF(d) = \frac{w_{\text{dense}}}{k + \text{rank}_{\text{dense}}(d)} + \frac{w_{\text{sparse}}}{k + \text{rank}_{\text{sparse}}(d)}$$

Where:
- $k$ is the smoothing constant, set to **60** to prevent top outliers from dominating the blended score.
- $w_{\text{dense}}$ is the dense weight (default **0.65**).
- $w_{\text{sparse}}$ is the sparse lexical weight (default **0.35**).
- $\text{rank}(d)$ is the 1-based ordinal position of chunk $d$ in the respective retrieval candidate list. If a document is absent from a retriever's candidate set, its rank term defaults to infinity ($1 / \infty = 0$).

## Flash Cross-Encoder Reranker

Following candidate generation, the top $N = 15$ candidates are scored by a cross-encoder flash reranker before selecting the final $K = 5$ chunks:
- **Scoring Dimensions**:
  1. Exact token coverage: Proportion of non-stopword query tokens present in the chunk.
  2. Heading and section weight: Exact or partial matches against markdown headers (`#`, `##`, `###`) receive a **1.25x boost**.
  3. Contiguous phrase bonus: Matching 2-gram and 3-gram contiguous sequences from the query grants a **1.40x boost**.
  4. Length penalty: Chunks under 100 characters receive a soft damping factor to favor substantive context.
- **Latency Budget**: Reranking overhead is capped at under **15 milliseconds** per query to maintain sub-second total RAG response times.

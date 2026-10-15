# Embedding and Semantic Chunking Specification

## Embedding Model Configuration
The RAG system utilizes Google Gemini embedding models:
- **Model Name**: `models/gemini-embedding-001`
- **Output Vector Dimension**: 3072 floating point numbers
- **Distance Metric**: Cosine similarity (`Distance.COSINE` in Qdrant)
- **Embedding Task Types**:
  - `RETRIEVAL_DOCUMENT`: Applied when vectorizing document chunks during ingestion.
  - `RETRIEVAL_QUERY`: Applied when vectorizing user queries at search time. Differentiating task types significantly improves retrieval recall.

## Adaptive Semantic Chunker
Rather than slicing text arbitrarily by character count, the system implements structure-aware chunking:
- **Heading Detection**: Regex parser identifies Markdown headers (`#` through `######`). Each chunk preserves its closest section and heading metadata.
- **Chunk Sizing Parameters**:
  - `MIN_CHUNK_SIZE = 500`: Minimum characters before greedy grouping terminates.
  - `MAX_CHUNK_SIZE = 2000`: Hard threshold. Blocks exceeding this size trigger recursive character splitting.
  - `CHUNK_OVERLAP = 200`: Overlapping characters maintained between sequential chunks to preserve cross-boundary semantics.
- **Fallback Separators**: When splitting oversized paragraphs, the recursive splitter prioritizes `\n\n`, followed by `\n`, `. `, and space.

## Resilient API Call Retries and Batching
To protect against Gemini API rate limits and transient 503 errors:
- **Batch Sizing**: Chunks are embedded in batches of 5 (`EMBEDDING_BATCH_SIZE = 5`).
- **Exponential Backoff**: If an embedding request fails, the client retries up to 5 times (`MAX_EMBED_RETRIES = 5`) starting with an initial backoff of 1.0 second up to a ceiling of 16.0 seconds (`MAX_BACKOFF = 16.0`).
- **Jitter**: Decorrelated full jitter (`ENABLE_JITTER = True`) is added to retry intervals to avoid synchronized request spikes.
- **Concurrency Limiter**: Global asyncio semaphore limits concurrent embedding requests to `MAX_CONCURRENT_EMBEDDINGS = 1` on the free tier.

# Data Ingestion and Multi-Format Document Pipeline

## Supported File Formats and Extraction Strategies
The ingestion subsystem handles multi-modal enterprise files with dedicated parsers:
- **PDF Documents (`.pdf`)**: Parsed via PyMuPDF (fitz) extracting structured markdown text and embedded high-resolution figures. Scanned pages trigger Tesseract OCR fallback.
- **Word Documents (`.docx`)**: Parsed using `python-docx` extracting paragraph hierarchy, bulleted lists, and inline tables converted to markdown.
- **Presentations (`.pptx`)**: Parsed with `python-pptx`, preserving slide titles and speaker notes.
- **Spreadsheets (`.xlsx`, `.csv`)**: Parsed with `openpyxl` and `pandas`, converting sheets into pipe-delimited markdown tables.
- **Markdown and Text (`.md`, `.txt`)**: Ingested directly into the semantic chunker.

## Deterministic Point ID Generation
To ensure idempotency across repeated uploads and network re-transmissions:
- Each vector point in Qdrant is assigned a deterministic UUIDv5 generated from a composite key: `(filename, page_number, section, heading, chunk_index, text, document_id)`.
- Before generating embeddings, the ingestion service checks existing point IDs in Qdrant. Chunks that already exist are skipped, avoiding unnecessary Gemini API costs.

## Checkpointing and Failure Recovery
Document processing follows an atomic state machine:
- The database record transitions through stages: `pending` -> `parsing` -> `chunking` -> `checking_existing_vectors` -> `embedding_and_indexing` -> `completed`.
- If an ingestion worker crashes midway through a 500-page document, the background recovery process resumes at the exact batch offset recorded in `embedded_chunks`.
- Orphan vectors from failed uploads are detected and purged by the periodic orphan cleanup background worker.

# RAG Retrieval Evaluation & Hyperparameter Tuning Suite

A quantitative benchmarking and tuning framework for evaluating retrieval quality (**Hit-Rate@k**, **MRR**, **Precision@k**) before making chunker or threshold adjustments.

---

## 1. Directory Structure

```
backend/eval/
├── corpus/                                 # Ground-truth multi-topic benchmark documents
│   ├── architecture_overview.md            # System architecture, fallback chains, streaming
│   ├── company_employee_handbook.md        # Remote policies, PTO, stipends, code standards
│   ├── data_ingestion_pipeline.md          # Multi-format parsers, OCR, idempotent IDs
│   ├── deployment_and_devops.md            # Cloud infrastructure, CORS policies, health probes
│   ├── embedding_and_chunking_spec.md      # Gemini 3072 embeddings, chunker specs, jitter
│   └── security_and_auth_policy.md         # JWT authentication, proxy headers, rate limits
├── dataset.json                            # 30 curated question/expected-source pairs
├── evaluate.py                             # Evaluation runner & parameter tuning harness
└── README.md                               # This documentation
```

---

## 2. Evaluation Dataset (`dataset.json`)

Contains **30 high-fidelity test pairs** across 4 categories:
- **`factual`** (12 queries): Exact names, models, versions, and configuration settings.
- **`technical_numeric`** (8 queries): Numerical limits, hours, rates, and pixel constraints.
- **`conceptual`** (9 queries): Lifecycle mechanics, idempotency guarantees, and architectural reasoning.
- **`semantic_paraphrase`** (1 query): Queries worded with indirect synonyms and alternate terminology.

Each entry includes:
```json
{
  "id": 1,
  "question": "What model is used as the primary LLM and what is its default temperature?",
  "expected_sources": ["architecture_overview.md"],
  "expected_section": "LLM Fallback Architecture",
  "category": "factual",
  "difficulty": "easy",
  "ground_truth": "The primary LLM model is llama-3.3-70b-versatile with a temperature of 0.1."
}
```

---

## 3. Running Retrieval Evaluation

### A. Quick Baseline Evaluation (Offline / Standalone)
Runs instantly in < 100 ms with zero API costs:
```bash
python backend/eval/evaluate.py
```
Output includes:
- **Hit-Rate@1, Hit-Rate@3, Hit-Rate@5, Hit-Rate@10**
- **MRR (Mean Reciprocal Rank)**
- Breakdown by Query Category and Difficulty
- Diagnostics for any missed queries

### B. Hyperparameter Tuning (`top_k`, `min_score`, `max_gap`)
Executes a grid-search sweep across retrieval thresholds to find optimal settings:
```bash
python backend/eval/evaluate.py --tune
```

### C. Chunker Sizing Tuning (`min_chunk_size`, `max_chunk_size`, `chunk_overlap`)
Sweeps chunker boundaries to evaluate impact on chunk density and retrieval accuracy:
```bash
python backend/eval/evaluate.py --tune-chunker
```

### D. Live Evaluation against Qdrant + Gemini
Evaluates against the live vector database and embeddings:
```bash
python backend/eval/evaluate.py --live --top-k 5 --min-score 0.63 --max-gap 0.05
```

### E. JSON Export for CI/CD Tracking
Save benchmark run outputs for automated regression testing:
```bash
python backend/eval/evaluate.py --json-out benchmark_results.json
```

---

## 4. Automated Tests

Run the test suite with pytest:
```bash
pytest backend/tests/test_retrieval_eval.py
```
Validates schema integrity, 30 question coverage, and metric computation correctness.

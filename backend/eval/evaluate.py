#!/usr/bin/env python3
"""
RAG Retrieval Evaluation & Tuning Harness.

Evaluates retrieval quality (Hit-Rate@k, MRR, Precision, Recall) across an evaluation
benchmark dataset (e.g. 30 question/expected-source pairs). Supports tuning chunker
parameters (min/max size, overlap), top_k, min_score, and max_gap thresholds.

Usage:
    # Run evaluation in offline / standalone mode (fast, deterministic, zero-API cost):
    python backend/eval/evaluate.py

    # Run parameter sweep / grid search to find optimal retrieval settings:
    python backend/eval/evaluate.py --tune

    # Run chunker parameter sweep (evaluates chunk sizes and overlap):
    python backend/eval/evaluate.py --tune-chunker

    # Run against live Qdrant and Gemini API:
    python backend/eval/evaluate.py --live --top-k 5 --min-score 0.63 --max-gap 0.05

    # Save benchmark run to JSON:
    python backend/eval/evaluate.py --json-out benchmark_results.json
"""

import argparse
import asyncio
import json
import math
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Ensure backend root is on sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.chunker import build_chunks, TextChunk


# ── Data Models ───────────────────────────────────────────────────────────────

@dataclass
class EvalItem:
    id: int
    question: str
    expected_sources: list[str]
    expected_section: str | None = None
    category: str = "general"
    difficulty: str = "medium"
    ground_truth: str = ""
    history: list[dict[str, str]] = field(default_factory=list)   # earlier turns (follow-up questions)


@dataclass
class RetrievedCandidate:
    filename: str
    text: str
    score: float
    chunk_index: int = 0
    section: str | None = None
    heading: str | None = None
    char_start: int = 0
    char_end: int = 0


@dataclass
class QueryResult:
    item: EvalItem
    candidates: list[RetrievedCandidate]
    hit_at_1: bool
    hit_at_3: bool
    hit_at_5: bool
    hit_at_10: bool
    reciprocal_rank: float
    top_source: str | None
    top_score: float
    latency_ms: float
    section_rank: int = 0          # 1-based rank of the first chunk inside the expected section; 0 = none


@dataclass
class BenchmarkSummary:
    total_queries: int
    hit_rate_1: float
    hit_rate_3: float
    hit_rate_5: float
    hit_rate_10: float
    mrr: float
    avg_latency_ms: float
    category_breakdown: dict[str, dict[str, float]]
    difficulty_breakdown: dict[str, dict[str, float]]
    missed_queries: list[dict[str, Any]]
    section_hit_1: float = 0.0
    section_hit_5: float = 0.0
    section_mrr: float = 0.0


# ── In-Memory Fast Semantic / Lexical Indexer for Offline Tuning ──────────────

class LocalBenchmarkIndex:
    """
    Lightweight, self-contained vector & BM25-hybrid index for offline evaluation
    and fast hyperparameter tuning without incurring API costs or latency.
    """

    def __init__(
        self,
        corpus_dir: Path,
        min_chunk_size: int = 500,
        max_chunk_size: int = 2000,
        chunk_overlap: int = 200,
    ):
        self.corpus_dir = corpus_dir
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.chunk_overlap = chunk_overlap
        self.chunks: list[dict[str, Any]] = []
        self.vocab: dict[str, int] = {}
        self.idf: dict[str, float] = {}
        self.doc_vectors: list[dict[str, float]] = []
        self._build_index()

    def _tokenize(self, text: str) -> list[str]:
        words = re.findall(r"\b[a-zA-Z0-9_\-\.]{2,}\b", text.lower())
        # Character 3-grams to capture subword/model-name similarities
        subwords = [w for w in words]
        return subwords

    def _build_index(self):
        self.chunks.clear()
        doc_count = 0
        df: Counter = Counter()

        for file_path in sorted(self.corpus_dir.glob("*.md")):
            content = file_path.read_text(encoding="utf-8")
            file_chunks = build_chunks(
                text=content,
                min_chunk_size=self.min_chunk_size,
                max_chunk_size=self.max_chunk_size,
                chunk_overlap=self.chunk_overlap,
            )
            for c in file_chunks:
                tokens = self._tokenize(c.text)
                unique_tokens = set(tokens)
                df.update(unique_tokens)
                self.chunks.append({
                    "filename": file_path.name,
                    "text": c.text,
                    "section": c.section,
                    "heading": c.heading,
                    "chunk_index": c.chunk_index,
                    "char_start": c.char_start,
                    "char_end": c.char_end,
                    "tokens": tokens,
                })
                doc_count += 1

        # Compute IDF
        total_docs = max(1, len(self.chunks))
        self.idf = {term: math.log(1.0 + (total_docs - count + 0.5) / (count + 0.5)) for term, count in df.items()}

        # Compute normalized TF-IDF vectors
        self.doc_vectors = []
        for ch in self.chunks:
            tf = Counter(ch["tokens"])
            length = len(ch["tokens"]) or 1
            vec: dict[str, float] = {}
            for term, count in tf.items():
                tfidf = (count / length) * self.idf.get(term, 1.0)
                vec[term] = tfidf
            # Normalize vector
            norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
            norm_vec = {t: v / norm for t, v in vec.items()}
            self.doc_vectors.append(norm_vec)

    def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
        max_gap: float | None = None,
        history: list[dict[str, str]] | None = None,   # unused: the lexical index has no query rewriting
    ) -> list[RetrievedCandidate]:
        q_tokens = self._tokenize(query)
        if not q_tokens:
            return []

        q_tf = Counter(q_tokens)
        q_len = len(q_tokens) or 1
        q_vec = {}
        for term, count in q_tf.items():
            tfidf = (count / q_len) * self.idf.get(term, 1.0)
            q_vec[term] = tfidf
        q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1.0
        q_norm_vec = {t: v / q_norm for t, v in q_vec.items()}

        scores: list[tuple[int, float]] = []
        for idx, doc_vec in enumerate(self.doc_vectors):
            dot = sum(q_norm_vec[term] * doc_vec[term] for term in q_norm_vec if term in doc_vec)
            # Map score to [0, 1] cosine range
            scores.append((idx, dot))

        scores.sort(key=lambda x: x[1], reverse=True)

        if not scores:
            return []

        top_score = scores[0][1]
        gap_cutoff = (top_score - max_gap) if (max_gap is not None and max_gap >= 0.0) else -1.0

        candidates: list[RetrievedCandidate] = []
        for idx, score in scores:
            if score < min_score:
                continue
            if score < gap_cutoff:
                continue
            ch = self.chunks[idx]
            candidates.append(
                RetrievedCandidate(
                    filename=ch["filename"],
                    text=ch["text"],
                    score=float(score),
                    chunk_index=ch["chunk_index"],
                    section=ch["section"],
                    heading=ch["heading"],
                    char_start=ch["char_start"],
                    char_end=ch["char_end"],
                )
            )
            if len(candidates) >= top_k:
                break

        return candidates


# ── Live Qdrant + Gemini Retrieval Searcher ───────────────────────────────────

class LiveBenchmarkIndex:
    """
    The real retrieval path (Gemini embeddings + Qdrant cosine search) over the benchmark corpus.

    The corpus is embedded once into a throw-away embedded Qdrant store under ``eval/.qdrant`` (never the
    application's own collection), then every question is embedded with RETRIEVAL_QUERY and searched, with the
    same score floor and gap filter as ``retrieve_chunks``. With ``condense=True`` follow-up questions are first
    rewritten by ``condense_question``, exactly as the chat pipeline does.
    """

    COLLECTION = "rag_eval"

    def __init__(self, corpus_dir: Path, condense: bool = False, rebuild: bool = False):
        self.corpus_dir = corpus_dir
        self.condense = condense
        self.rebuild = rebuild
        self.chunks: list[dict[str, Any]] = []
        self._client = None
        self._ready = False

    async def _build(self) -> None:
        from qdrant_client import AsyncQdrantClient
        from qdrant_client.http import models as qm

        from app.services.embedding_service import embed_batch_with_retry

        self._client = AsyncQdrantClient(path=str(SCRIPT_DIR / ".qdrant"))
        existing = {c.name for c in (await self._client.get_collections()).collections}

        for file_path in sorted(self.corpus_dir.glob("*.md")):
            for c in build_chunks(file_path.read_text(encoding="utf-8")):
                self.chunks.append({"filename": file_path.name, "text": c.text, "chunk_index": c.chunk_index,
                                    "section": c.section, "heading": c.heading,
                                    "char_start": c.char_start, "char_end": c.char_end})

        if self.COLLECTION in existing and not self.rebuild:
            info = await self._client.get_collection(self.COLLECTION)
            if info.points_count == len(self.chunks):
                self._ready = True
                return
        if self.COLLECTION in existing:
            await self._client.delete_collection(self.COLLECTION)

        print(f"Embedding {len(self.chunks)} corpus chunks with Gemini ...")
        vectors = await embed_batch_with_retry([c["text"] for c in self.chunks], task_type="RETRIEVAL_DOCUMENT")
        await self._client.create_collection(
            self.COLLECTION,
            vectors_config=qm.VectorParams(size=len(vectors[0]), distance=qm.Distance.COSINE),
        )
        await self._client.upsert(
            self.COLLECTION,
            points=[qm.PointStruct(id=i, vector=v, payload=self.chunks[i]) for i, v in enumerate(vectors)],
        )
        self._ready = True

    async def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
        max_gap: float | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> list[RetrievedCandidate]:
        from app.services.embedding_service import embed_batch_with_retry

        if not self._ready:
            await self._build()
        if self.condense and history:
            from langchain_core.messages import AIMessage, HumanMessage

            from app.services.query_rewriter import condense_question

            msgs = [(HumanMessage if h["role"] == "user" else AIMessage)(content=h["content"]) for h in history]
            query = await condense_question(query, msgs)

        vector = (await embed_batch_with_retry([query], task_type="RETRIEVAL_QUERY"))[0]
        points = (await self._client.query_points(
            self.COLLECTION, query=vector, limit=top_k, with_payload=True)).points
        hits = [p for p in points if p.score >= min_score]
        if hits and max_gap is not None and max_gap >= 0.0:
            hits = [p for p in hits if p.score >= hits[0].score - max_gap]
        return [
            RetrievedCandidate(
                filename=p.payload["filename"], text=p.payload["text"], score=p.score,
                chunk_index=p.payload["chunk_index"], section=p.payload.get("section"),
                heading=p.payload.get("heading"),
                char_start=p.payload.get("char_start", 0), char_end=p.payload.get("char_end", 0),
            )
            for p in hits
        ]

    def search_sync(self, *args, **kwargs) -> list[RetrievedCandidate]:
        return asyncio.run(self.search(*args, **kwargs))


# ── Section ground truth ──────────────────────────────────────────────────────

_MIN_SECTION_OVERLAP = 100   # characters a chunk must share with the expected section to count as covering it


def section_ranges(corpus_dir: Path) -> dict[tuple[str, str], tuple[int, int]]:
    """(file, heading text) -> (start, end) character range of that section in the file."""
    ranges: dict[tuple[str, str], tuple[int, int]] = {}
    for file_path in sorted(corpus_dir.glob("*.md")):
        text = file_path.read_text(encoding="utf-8")
        marks = [(m.start(), m.group(2).strip()) for m in re.finditer(r"^(#{1,6})\s+(.+)$", text, re.M)]
        for i, (start, title) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
            ranges[(file_path.name, title)] = (start, end)
    return ranges


def covers_section(cand: RetrievedCandidate, item: EvalItem, ranges: dict[tuple[str, str], tuple[int, int]]) -> bool:
    """True when the chunk is from an expected file and actually overlaps the expected section's text."""
    if cand.filename not in item.expected_sources:
        return False
    span = ranges.get((cand.filename, item.expected_section or ""))
    if span is None:
        return True   # no section recorded for this item: a file-level hit is all we can check
    overlap = min(cand.char_end, span[1]) - max(cand.char_start, span[0])
    return overlap >= min(_MIN_SECTION_OVERLAP, span[1] - span[0])


# ── Evaluation Engine ─────────────────────────────────────────────────────────

def evaluate_dataset(
    search_fn,
    dataset: list[EvalItem],
    top_k: int = 5,
    min_score: float = 0.0,
    max_gap: float | None = None,
    ranges: dict[tuple[str, str], tuple[int, int]] | None = None,
) -> BenchmarkSummary:
    results: list[QueryResult] = []
    ranges = ranges or {}

    for item in dataset:
        t0 = time.perf_counter()
        candidates = search_fn(item.question, top_k=top_k, min_score=min_score, max_gap=max_gap,
                               history=item.history)
        latency = (time.perf_counter() - t0) * 1000.0

        retrieved_sources = [c.filename for c in candidates]
        expected_set = set(item.expected_sources)

        hit_1 = bool(set(retrieved_sources[:1]) & expected_set)
        hit_3 = bool(set(retrieved_sources[:3]) & expected_set)
        hit_5 = bool(set(retrieved_sources[:5]) & expected_set)
        hit_10 = bool(set(retrieved_sources[:10]) & expected_set)

        reciprocal_rank = 0.0
        for rank, src in enumerate(retrieved_sources, start=1):
            if src in expected_set:
                reciprocal_rank = 1.0 / rank
                break

        section_rank = next(
            (rank for rank, c in enumerate(candidates, start=1) if covers_section(c, item, ranges)), 0)

        top_src = retrieved_sources[0] if retrieved_sources else None
        top_sc = candidates[0].score if candidates else 0.0

        results.append(
            QueryResult(
                item=item,
                candidates=candidates,
                hit_at_1=hit_1,
                hit_at_3=hit_3,
                hit_at_5=hit_5,
                hit_at_10=hit_10,
                reciprocal_rank=reciprocal_rank,
                top_source=top_src,
                top_score=top_sc,
                latency_ms=latency,
                section_rank=section_rank,
            )
        )

    n = len(results) or 1
    hit_rate_1 = sum(1 for r in results if r.hit_at_1) / n
    hit_rate_3 = sum(1 for r in results if r.hit_at_3) / n
    hit_rate_5 = sum(1 for r in results if r.hit_at_5) / n
    hit_rate_10 = sum(1 for r in results if r.hit_at_10) / n
    mrr = sum(r.reciprocal_rank for r in results) / n
    avg_latency = sum(r.latency_ms for r in results) / n
    section_hit_1 = sum(1 for r in results if r.section_rank == 1) / n
    section_hit_5 = sum(1 for r in results if 0 < r.section_rank <= 5) / n
    section_mrr = sum(1.0 / r.section_rank for r in results if r.section_rank) / n

    # Category breakdown
    cat_stats: dict[str, list[QueryResult]] = {}
    diff_stats: dict[str, list[QueryResult]] = {}
    for r in results:
        cat_stats.setdefault(r.item.category, []).append(r)
        diff_stats.setdefault(r.item.difficulty, []).append(r)

    def calc_group(group: list[QueryResult]) -> dict[str, float]:
        gn = len(group) or 1
        return {
            "count": len(group),
            "hit@1": sum(1 for r in group if r.hit_at_1) / gn,
            "hit@3": sum(1 for r in group if r.hit_at_3) / gn,
            "hit@5": sum(1 for r in group if r.hit_at_5) / gn,
            "mrr": sum(r.reciprocal_rank for r in group) / gn,
            "sec@1": sum(1 for r in group if r.section_rank == 1) / gn,
            "sec@5": sum(1 for r in group if 0 < r.section_rank <= 5) / gn,
        }

    cat_breakdown = {k: calc_group(v) for k, v in cat_stats.items()}
    diff_breakdown = {k: calc_group(v) for k, v in diff_stats.items()}

    missed = [
        {
            "id": r.item.id,
            "question": r.item.question,
            "expected": r.item.expected_sources,
            "retrieved": [c.filename for c in r.candidates],
            "top_score": r.top_score,
            "category": r.item.category,
            "expected_section": r.item.expected_section,
            "file_hit": r.hit_at_5,
        }
        for r in results
        if not (0 < r.section_rank <= 5)
    ]

    return BenchmarkSummary(
        total_queries=len(results),
        hit_rate_1=hit_rate_1,
        hit_rate_3=hit_rate_3,
        hit_rate_5=hit_rate_5,
        hit_rate_10=hit_rate_10,
        mrr=mrr,
        avg_latency_ms=avg_latency,
        category_breakdown=cat_breakdown,
        difficulty_breakdown=diff_breakdown,
        missed_queries=missed,
        section_hit_1=section_hit_1,
        section_hit_5=section_hit_5,
        section_mrr=section_mrr,
    )


# ── Reporting and Presentation ────────────────────────────────────────────────

def print_summary_report(summary: BenchmarkSummary, params_info: str):
    print("\n" + "=" * 80)
    print(" RAG RETRIEVAL BENCHMARK REPORT ".center(80, "="))
    print("=" * 80)
    print(f"Configuration: {params_info}")
    print(f"Total Evaluation Pairs: {summary.total_queries}")
    print(f"Average Query Latency : {summary.avg_latency_ms:.2f} ms")
    print("-" * 80)
    print(" CORE RETRIEVAL METRICS ".center(80, "-"))
    print(f"  • Hit-Rate@1  : {summary.hit_rate_1 * 100:6.2f}%  (Expected source ranked 1st)")
    print(f"  • Hit-Rate@3  : {summary.hit_rate_3 * 100:6.2f}%  (Expected source in Top 3)")
    print(f"  • Hit-Rate@5  : {summary.hit_rate_5 * 100:6.2f}%  (Expected source in Top 5)")
    print(f"  • Hit-Rate@10 : {summary.hit_rate_10 * 100:6.2f}%  (Expected source in Top 10)")
    print(f"  • MRR         : {summary.mrr:6.4f}   (Mean Reciprocal Rank)")
    print(f"  • Section@1   : {summary.section_hit_1 * 100:6.2f}%  (Top chunk covers the expected section)")
    print(f"  • Section@5   : {summary.section_hit_5 * 100:6.2f}%  (Expected section covered in Top 5)")
    print(f"  • Section MRR : {summary.section_mrr:6.4f}")
    print("-" * 80)

    print(" BREAKDOWN BY CATEGORY ".center(80, "-"))
    print(f"{'Category':<22} | {'Count':<6} | {'Hit@1':<8} | {'Hit@3':<8} | {'Hit@5':<8} | {'MRR':<8} | {'Sec@1':<8} | {'Sec@5':<8}")
    print("-" * 80)
    for cat, stats in sorted(summary.category_breakdown.items()):
        print(
            f"{cat:<22} | {int(stats['count']):<6} | {stats['hit@1']*100:6.1f}% | "
            f"{stats['hit@3']*100:6.1f}% | {stats['hit@5']*100:6.1f}% | {stats['mrr']:6.3f} | "
            f"{stats['sec@1']*100:6.1f}% | {stats['sec@5']*100:6.1f}%"
        )

    print("-" * 80)
    print(" BREAKDOWN BY DIFFICULTY ".center(80, "-"))
    print(f"{'Difficulty':<22} | {'Count':<6} | {'Hit@1':<8} | {'Hit@3':<8} | {'Hit@5':<8} | {'MRR':<8} | {'Sec@1':<8} | {'Sec@5':<8}")
    print("-" * 80)
    for diff, stats in sorted(summary.difficulty_breakdown.items()):
        print(
            f"{diff:<22} | {int(stats['count']):<6} | {stats['hit@1']*100:6.1f}% | "
            f"{stats['hit@3']*100:6.1f}% | {stats['hit@5']*100:6.1f}% | {stats['mrr']:6.3f} | "
            f"{stats['sec@1']*100:6.1f}% | {stats['sec@5']*100:6.1f}%"
        )

    if summary.missed_queries:
        print("-" * 80)
        print(f" MISSED QUERIES (expected section not in Top 5) [Count: {len(summary.missed_queries)}] ".center(80, "-"))
        for m in summary.missed_queries:
            print(f"  [Q#{m['id']}] {m['question']}")
            print(f"     Expected : {m['expected']} / {m['expected_section']} (right file in Top 5: {m['file_hit']})")
            print(f"     Retrieved: {m['retrieved']}")
            print(f"     Top Score: {m['top_score']:.4f} | Category: {m['category']}")
    else:
        print("-" * 80)
        print(" PERFECT RETRIEVAL: 100% Hit-Rate@5 across all test queries! ".center(80, " "))
    print("=" * 80 + "\n")


# ── Hyperparameter Tuning / Sweep ─────────────────────────────────────────────

def run_parameter_tuning(corpus_dir: Path, dataset: list[EvalItem]):
    print("\n" + "=" * 90)
    print(" PARAMETER TUNING: SWEEPING TOP_K, MIN_SCORE, AND MAX_GAP ".center(90, "="))
    print("=" * 90)

    index = LocalBenchmarkIndex(corpus_dir)

    top_k_options = [1, 3, 5, 8]
    min_score_options = [0.0, 0.05, 0.10, 0.15]
    max_gap_options = [None, 0.05, 0.10, 0.20]

    results = []

    print(f"{'top_k':<6} | {'min_score':<10} | {'max_gap':<9} | {'Hit@1':<8} | {'Hit@3':<8} | {'Hit@5':<8} | {'MRR':<8} | {'Sec@1':<8} | {'Sec@5':<8}")
    print("-" * 90)

    for k in top_k_options:
        for ms in min_score_options:
            for mg in max_gap_options:
                summary = evaluate_dataset(
                    search_fn=index.search,
                    dataset=dataset,
                    top_k=k,
                    min_score=ms,
                    max_gap=mg,
                )
                gap_str = f"{mg:.2f}" if mg is not None else "None"
                results.append((k, ms, gap_str, summary.hit_rate_1, summary.hit_rate_3, summary.hit_rate_5, summary.mrr))
                print(
                    f"{k:<6} | {ms:<10.2f} | {gap_str:<9} | {summary.hit_rate_1*100:6.1f}% | "
                    f"{summary.hit_rate_3*100:6.1f}% | {summary.hit_rate_5*100:6.1f}% | {summary.mrr:6.3f}"
                )

    # Find optimal configuration
    results.sort(key=lambda x: (x[5], x[6], x[3]), reverse=True)
    best = results[0]
    print("=" * 90)
    print(f" OPTIMAL CONFIGURATION: top_k={best[0]}, min_score={best[1]}, max_gap={best[2]}")
    print(f"   => Hit@5: {best[5]*100:.2f}%, Hit@1: {best[3]*100:.2f}%, MRR: {best[6]:.4f}")
    print("=" * 90 + "\n")


def run_chunker_tuning(corpus_dir: Path, dataset: list[EvalItem]):
    print("\n" + "=" * 90)
    print(" CHUNKER TUNING: SWEEPING MIN_CHUNK_SIZE, MAX_CHUNK_SIZE, OVERLAP ".center(90, "="))
    print("=" * 90)

    configs = [
        {"min_size": 250, "max_size": 1000, "overlap": 100},
        {"min_size": 500, "max_size": 1500, "overlap": 150},
        {"min_size": 500, "max_size": 2000, "overlap": 200},
        {"min_size": 800, "max_size": 2500, "overlap": 300},
    ]

    print(f"{'min_size':<10} | {'max_size':<10} | {'overlap':<9} | {'Total Chunks':<14} | {'Hit@1':<8} | {'Hit@3':<8} | {'Hit@5':<8} | {'MRR':<8} | {'Sec@1':<8} | {'Sec@5':<8}")
    print("-" * 90)

    for cfg in configs:
        index = LocalBenchmarkIndex(
            corpus_dir=corpus_dir,
            min_chunk_size=cfg["min_size"],
            max_chunk_size=cfg["max_size"],
            chunk_overlap=cfg["overlap"],
        )
        summary = evaluate_dataset(
            search_fn=index.search,
            dataset=dataset,
            top_k=5,
            min_score=0.0,
            max_gap=None,
        )
        print(
            f"{cfg['min_size']:<10} | {cfg['max_size']:<10} | {cfg['overlap']:<9} | {len(index.chunks):<14} | "
            f"{summary.hit_rate_1*100:6.1f}% | {summary.hit_rate_3*100:6.1f}% | {summary.hit_rate_5*100:6.1f}% | {summary.mrr:6.3f}"
        )
    print("=" * 90 + "\n")


# ── Main Entrypoint ───────────────────────────────────────────────────────────

def load_dataset(dataset_path: Path) -> list[EvalItem]:
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [
        EvalItem(
            id=d["id"],
            question=d["question"],
            expected_sources=d["expected_sources"],
            expected_section=d.get("expected_section"),
            category=d.get("category", "general"),
            difficulty=d.get("difficulty", "medium"),
            ground_truth=d.get("ground_truth", ""),
            history=d.get("history", []),
        )
        for d in data
    ]


def main():
    parser = argparse.ArgumentParser(description="Evaluate RAG Retrieval quality and tune hyperparameters.")
    parser.add_argument("--dataset", type=Path, default=SCRIPT_DIR / "dataset.json", help="Path to evaluation dataset JSON.")
    parser.add_argument("--corpus", type=Path, default=SCRIPT_DIR / "corpus", help="Path to evaluation corpus directory.")
    parser.add_argument("--top-k", type=int, default=5, help="Number of retrieved chunks (default: 5).")
    parser.add_argument("--min-score", type=float, default=0.0, help="Minimum cosine score floor (default: 0.0).")
    parser.add_argument("--max-gap", type=float, default=None, help="Relative score gap from top hit (default: None).")
    parser.add_argument("--tune", action="store_true", help="Run grid search parameter sweep for top_k, min_score, and max_gap.")
    parser.add_argument("--tune-chunker", action="store_true", help="Run chunker parameter sweep across size and overlap.")
    parser.add_argument("--live", action="store_true",
                        help="Embed the corpus with Gemini into a private Qdrant store and search it (needs GOOGLE_API_KEY).")
    parser.add_argument("--condense", action="store_true",
                        help="With --live: rewrite follow-up questions into standalone queries before searching.")
    parser.add_argument("--rebuild", action="store_true", help="With --live: re-embed the corpus even if already indexed.")
    parser.add_argument("--json-out", type=Path, default=None, help="Save evaluation summary to JSON file.")

    args = parser.parse_args()

    if not args.dataset.exists():
        print(f"Error: Dataset not found at {args.dataset}", file=sys.stderr)
        sys.exit(1)

    if not args.corpus.exists():
        print(f"Error: Corpus directory not found at {args.corpus}", file=sys.stderr)
        sys.exit(1)

    dataset = load_dataset(args.dataset)
    print(f"Loaded {len(dataset)} evaluation pairs from {args.dataset.name}")

    if args.tune:
        run_parameter_tuning(args.corpus, dataset)
        return

    if args.tune_chunker:
        run_chunker_tuning(args.corpus, dataset)
        return

    if args.live:
        print("Running live evaluation against Gemini embeddings + a private Qdrant store ...")
        live = LiveBenchmarkIndex(args.corpus, condense=args.condense, rebuild=args.rebuild)
        search_fn = live.search_sync
        mode_label = "Live Gemini + Qdrant" + (" + question condensing" if args.condense else "")
    else:
        index = LocalBenchmarkIndex(args.corpus)
        search_fn = index.search
        mode_label = f"Local Offline Index ({len(index.chunks)} chunks from {len(list(args.corpus.glob('*.md')))} docs)"

    summary = evaluate_dataset(
        search_fn=search_fn,
        dataset=dataset,
        top_k=args.top_k,
        min_score=args.min_score,
        max_gap=args.max_gap,
        ranges=section_ranges(args.corpus),
    )

    params_info = f"Mode: {mode_label} | top_k: {args.top_k} | min_score: {args.min_score} | max_gap: {args.max_gap}"
    print_summary_report(summary, params_info)

    if args.json_out:
        out_dict = {
            "config": {
                "mode": mode_label,
                "top_k": args.top_k,
                "min_score": args.min_score,
                "max_gap": args.max_gap,
            },
            "metrics": {
                "total_queries": summary.total_queries,
                "hit_rate_1": summary.hit_rate_1,
                "hit_rate_3": summary.hit_rate_3,
                "hit_rate_5": summary.hit_rate_5,
                "hit_rate_10": summary.hit_rate_10,
                "mrr": summary.mrr,
                "section_hit_1": summary.section_hit_1,
                "section_hit_5": summary.section_hit_5,
                "section_mrr": summary.section_mrr,
                "avg_latency_ms": summary.avg_latency_ms,
            },
            "category_breakdown": summary.category_breakdown,
            "difficulty_breakdown": summary.difficulty_breakdown,
            "missed_queries": summary.missed_queries,
        }
        args.json_out.write_text(json.dumps(out_dict, indent=2), encoding="utf-8")
        print(f"Saved evaluation results to {args.json_out}")


if __name__ == "__main__":
    main()

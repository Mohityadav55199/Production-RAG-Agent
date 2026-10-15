"""
Per-question latency and token metrics.

stream_rag fills a QueryTimer while the answer streams; record() saves it in the background so a slow write
never delays the answer, and summary() aggregates the last days for the admin dashboard.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select

from app.db.metric_models import QueryMetric
from app.db.postgres import get_db_session
from app.utils.logging import get_logger

logger = get_logger(__name__)

_pending: set[asyncio.Task] = set()


@dataclass
class QueryTimer:
    user_id: str | None
    answer_style: str | None = None
    scope_kind: str | None = None
    images: int = 0
    started: float = field(default_factory=time.perf_counter)
    retrieval_ms: int | None = None
    first_token_ms: int | None = None
    retrieved_chunks: int = 0
    provider: str | None = None
    model: str | None = None
    fallback_used: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)

    def mark_retrieved(self, chunks: int) -> None:
        if self.retrieval_ms is None:
            self.retrieval_ms = self.elapsed_ms()
            self.retrieved_chunks = chunks

    def mark_first_token(self) -> None:
        if self.first_token_ms is None:
            self.first_token_ms = self.elapsed_ms()

    def add_usage(self, usage: dict | None) -> None:
        if not usage:
            return
        self.input_tokens = (self.input_tokens or 0) + int(usage.get("input_tokens") or 0)
        self.output_tokens = (self.output_tokens or 0) + int(usage.get("output_tokens") or 0)

    def record(self, status: str) -> None:
        """Save in the background; metrics must never break or slow a request."""
        row = QueryMetric(
            id=uuid.uuid4(), user_id=self.user_id, status=status, answer_style=self.answer_style,
            scope_kind=self.scope_kind, images=self.images, retrieved_chunks=self.retrieved_chunks,
            retrieval_ms=self.retrieval_ms, first_token_ms=self.first_token_ms, total_ms=self.elapsed_ms(),
            provider=self.provider, model=self.model, fallback_used=self.fallback_used,
            input_tokens=self.input_tokens, output_tokens=self.output_tokens,
        )
        try:
            task = asyncio.get_running_loop().create_task(_save(row))
        except RuntimeError:
            return
        _pending.add(task)
        task.add_done_callback(_pending.discard)


async def _save(row: QueryMetric) -> None:
    try:
        async with get_db_session() as session:
            session.add(row)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not save query metrics: %s", exc)


def _percentile(values: list[int], p: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p * (len(ordered) - 1))))]


async def summary(days: int = 7) -> dict:
    """Latency percentiles, token totals, error and fallback rates, and a per-model breakdown."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with get_db_session() as session:
        rows = (await session.execute(
            select(QueryMetric.status, QueryMetric.total_ms, QueryMetric.first_token_ms, QueryMetric.retrieval_ms,
                   QueryMetric.fallback_used)
            .where(QueryMetric.created_at >= since)
        )).all()
        by_model = (await session.execute(
            select(
                QueryMetric.provider, QueryMetric.model, func.count(),
                func.avg(QueryMetric.total_ms), func.avg(QueryMetric.first_token_ms),
                func.coalesce(func.sum(QueryMetric.input_tokens), 0), func.coalesce(func.sum(QueryMetric.output_tokens), 0),
                func.sum(case((QueryMetric.status == "error", 1), else_=0)),
            )
            .where(QueryMetric.created_at >= since)
            .group_by(QueryMetric.provider, QueryMetric.model)
            .order_by(func.count().desc())
        )).all()

    ok = [r for r in rows if r.status == "ok"]
    total = len(rows)
    return {
        "days": days,
        "questions": total,
        "errors": sum(1 for r in rows if r.status == "error"),
        "cancelled": sum(1 for r in rows if r.status == "cancelled"),
        "fallback_rate": round(sum(1 for r in rows if r.fallback_used) / total, 3) if total else 0.0,
        "latency_ms": {
            "total_p50": _percentile([r.total_ms for r in ok], 0.5),
            "total_p95": _percentile([r.total_ms for r in ok], 0.95),
            "first_token_p50": _percentile([r.first_token_ms for r in ok if r.first_token_ms is not None], 0.5),
            "first_token_p95": _percentile([r.first_token_ms for r in ok if r.first_token_ms is not None], 0.95),
            "retrieval_p50": _percentile([r.retrieval_ms for r in ok if r.retrieval_ms is not None], 0.5),
        },
        "models": [
            {
                "provider": provider, "model": model, "questions": count,
                "avg_total_ms": round(avg_total) if avg_total is not None else None,
                "avg_first_token_ms": round(avg_first) if avg_first is not None else None,
                "input_tokens": int(tokens_in), "output_tokens": int(tokens_out), "errors": int(errors or 0),
            }
            for provider, model, count, avg_total, avg_first, tokens_in, tokens_out, errors in by_model
        ],
    }

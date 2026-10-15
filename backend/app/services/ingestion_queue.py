"""
Durable upload queue.

Uploads are registered at once (see document_service.queue_uploads) and their bytes are stored in the
ingestion_jobs table. One worker task per server process claims jobs in order and runs the ingestion
pipeline on them. Because the bytes are in PostgreSQL rather than in memory, a restart or crash
mid-processing loses nothing: on startup every unfinished job is put back in the queue and the
pipeline resumes (already-embedded chunks are skipped by their deterministic ids).

Claiming uses SELECT ... FOR UPDATE SKIP LOCKED, so it stays correct if more than one process runs.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import delete, select, text, update

from app.config import get_settings
from app.db.models import Document, DocumentStatus, IngestionJob
from app.db.postgres import get_db_session
from app.utils.logging import get_logger

logger = get_logger(__name__)

MAX_ATTEMPTS = 3              # a job that crashed the process this many times is given up on
STALE_AFTER_MINUTES = 30      # a "running" job not touched for this long was abandoned by a dead process
POLL_SECONDS = 30             # safety net; new uploads wake the worker immediately

_wake = asyncio.Event()


def notify() -> None:
    """Wake the worker: a job was just queued."""
    _wake.set()


async def enqueue(document_id: uuid.UUID, filename: str, content: bytes) -> None:
    async with get_db_session() as session:
        existing = await session.scalar(select(IngestionJob.id).where(IngestionJob.document_id == document_id))
        if existing is None:
            session.add(IngestionJob(id=uuid.uuid4(), document_id=document_id, filename=filename, content=content))
        else:  # re-upload of a document that is already queued: take the fresh bytes, start over
            await session.execute(
                update(IngestionJob).where(IngestionJob.id == existing)
                .values(content=content, filename=filename, status="queued", attempts=0, locked_at=None)
            )
    notify()


async def _claim() -> tuple[uuid.UUID, uuid.UUID, str, bytes, int] | None:
    """Take the oldest queued (or abandoned) job; None when there is nothing to do."""
    async with get_db_session() as session:
        row = (await session.execute(text(f"""
            UPDATE ingestion_jobs SET status = 'running', attempts = attempts + 1, locked_at = now()
            WHERE id = (
                SELECT id FROM ingestion_jobs
                WHERE status = 'queued'
                   OR (status = 'running' AND locked_at < now() - interval '{STALE_AFTER_MINUTES} minutes')
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id, document_id, filename, content, attempts
        """))).first()
    return tuple(row) if row else None


async def _finish(job_id: uuid.UUID) -> None:
    async with get_db_session() as session:
        await session.execute(delete(IngestionJob).where(IngestionJob.id == job_id))


async def _give_up(job_id: uuid.UUID, document_id: uuid.UUID, attempts: int) -> None:
    async with get_db_session() as session:
        await session.execute(
            update(Document).where(Document.id == document_id).values(
                status=DocumentStatus.FAILED,
                current_stage="failed",
                error_message=f"Processing stopped the server {attempts} times; giving up on this file.",
            )
        )
        await session.execute(delete(IngestionJob).where(IngestionJob.id == job_id))


async def process_next() -> bool:
    """Run one job to completion. Returns False when the queue is empty."""
    from app.services.document_service import _run_pipeline

    claimed = await _claim()
    if claimed is None:
        return False
    job_id, document_id, filename, content, attempts = claimed

    if attempts > MAX_ATTEMPTS:
        logger.error("Ingestion job %s failed %d times; marking the document failed", job_id, attempts - 1)
        await _give_up(job_id, document_id, attempts - 1)
        return True

    async with get_db_session() as session:
        doc = await session.get(Document, document_id)
    if doc is None:  # the user deleted the document while it waited
        await _finish(job_id)
        return True

    logger.info("Ingesting '%s' (document %s, attempt %d)", filename, document_id, attempts)
    await _run_pipeline(doc, filename, content, get_settings())   # records COMPLETED / FAILED on the document
    await _finish(job_id)
    return True


async def requeue_unfinished() -> int:
    """On startup: jobs a previous process was running are queued again. Returns how many."""
    async with get_db_session() as session:
        result = await session.execute(
            update(IngestionJob).where(IngestionJob.status == "running").values(status="queued", locked_at=None)
        )
        queued = await session.scalar(select(text("count(*)")).select_from(IngestionJob))
    if result.rowcount:
        logger.info("Re-queued %d upload(s) interrupted by a restart", result.rowcount)
    return int(queued or 0)


async def run_worker() -> None:
    """Background task: drain the queue, then wait for new uploads (or the poll interval)."""
    while True:
        try:
            while await process_next():
                pass
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a broken job must not stop the worker
            logger.exception("Ingestion worker error; continuing")
            await asyncio.sleep(5)
            continue
        _wake.clear()
        try:
            await asyncio.wait_for(_wake.wait(), timeout=POLL_SECONDS)
        except asyncio.TimeoutError:
            pass

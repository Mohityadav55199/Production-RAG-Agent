"""
Resolve what a question or comparison is about: everything, one imported
project (all documents named "<project>/..."), or a single document.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.db.models import Document, DocumentStatus
from app.db.postgres import get_db_session

OVERVIEW_FILENAME = "PROJECT_OVERVIEW.md"


@dataclass
class ResolvedScope:
    label: str                       # human-readable, used in prompts
    document_ids: list[str] | None   # None = whole knowledge base
    overview_document_id: str | None = None


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def resolve_scope(project: str | None = None, document_id: str | None = None) -> ResolvedScope:
    if document_id:
        async with get_db_session() as session:
            doc = await session.get(Document, uuid.UUID(document_id))
        if doc is None or doc.status != DocumentStatus.COMPLETED:
            raise ValueError("The selected document was not found or has not finished indexing.")
        return ResolvedScope(label=f"document '{doc.filename}'", document_ids=[str(doc.id)])

    if project:
        async with get_db_session() as session:
            rows = (await session.execute(
                select(Document.id, Document.filename).where(
                    Document.filename.like(f"{_escape_like(project)}/%", escape="\\"),
                    Document.status == DocumentStatus.COMPLETED,
                )
            )).all()
        if not rows:
            raise ValueError(f"Project '{project}' has no indexed files yet.")
        overview = next((str(r.id) for r in rows if r.filename == f"{project}/{OVERVIEW_FILENAME}"), None)
        return ResolvedScope(
            label=f"code project '{project}'",
            document_ids=[str(r.id) for r in rows],
            overview_document_id=overview,
        )

    return ResolvedScope(label="the whole knowledge base", document_ids=None)


async def list_sources() -> dict:
    """Projects (grouped by path prefix) and standalone documents that can be chatted with or compared."""
    async with get_db_session() as session:
        rows = (await session.execute(
            select(Document.id, Document.filename)
            .where(Document.status == DocumentStatus.COMPLETED)
            .order_by(Document.created_at.desc())
        )).all()

    projects: dict[str, int] = {}
    documents: list[dict] = []
    for row in rows:
        if "/" in row.filename:
            name = row.filename.split("/", 1)[0]
            projects[name] = projects.get(name, 0) + 1
        else:
            documents.append({"id": str(row.id), "filename": row.filename})

    return {
        "projects": [{"name": n, "file_count": c} for n, c in sorted(projects.items())],
        "documents": documents,
    }

"""
Imported code projects: summaries, deletion and replace-on-reimport.

A project is every document whose filename starts with "<project>/" (see
project_import). All queries are scoped to the owning user.
"""

from sqlalchemy import case, delete, func, select

from app.db.models import Document, DocumentStatus
from app.db.postgres import get_db_session
from app.services.vector_service import delete_by_document_ids
from app.utils.logging import get_logger

logger = get_logger(__name__)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_projects(user_id: str | None) -> list[dict]:
    """One row per project with file counts by state, computed in SQL (not limited by page size)."""
    name = func.split_part(Document.filename, "/", 1)
    state = case(
        (Document.status == DocumentStatus.COMPLETED, "indexed"),
        (Document.status == DocumentStatus.FAILED, "failed"),
        else_="processing",
    )
    async with get_db_session() as session:
        counts = (await session.execute(
            select(name.label("name"), state.label("state"), func.count().label("n"))
            .where(Document.user_id == user_id, Document.filename.like("%/%"))
            .group_by(name, state)
        )).all()
        errors = (await session.execute(
            select(name.label("name"), Document.error_message)
            .where(
                Document.user_id == user_id,
                Document.filename.like("%/%"),
                Document.status == DocumentStatus.FAILED,
                Document.error_message.is_not(None),
            )
        )).all()

    projects: dict[str, dict] = {}
    for row in counts:
        p = projects.setdefault(
            row.name, {"name": row.name, "total": 0, "indexed": 0, "processing": 0, "failed": 0, "first_error": None}
        )
        p[row.state] += row.n
        p["total"] += row.n
    for row in errors:
        if row.name in projects and projects[row.name]["first_error"] is None:
            projects[row.name]["first_error"] = row.error_message[:300]
    return sorted(projects.values(), key=lambda p: p["name"].lower())


async def delete_project(user_id: str | None, project: str) -> int:
    """Delete every file of a project (vectors first, then rows). Returns the number of files removed."""
    async with get_db_session() as session:
        ids = (await session.execute(
            select(Document.id).where(
                Document.user_id == user_id,
                Document.filename.like(f"{_escape_like(project)}/%", escape="\\"),
            )
        )).scalars().all()
    if not ids:
        return 0

    # Vectors first: if this fails the rows are kept and the delete can be retried
    await delete_by_document_ids([str(i) for i in ids])
    async with get_db_session() as session:
        await session.execute(delete(Document).where(Document.id.in_(ids), Document.user_id == user_id))
    logger.info("Deleted project '%s' (%d files)", project, len(ids))
    return len(ids)

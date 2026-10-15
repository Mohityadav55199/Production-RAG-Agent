"""
Per-user daily quotas.

Sign-up is open and every question and upload spends the shared LLM and embedding quota, so one account must not
be able to use it all up. Usage is counted from the database (questions asked and files uploaded in the last 24
hours), so it survives restarts and works across instances. The administrator is exempt; a limit of 0 turns a
quota off.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select

from app.config import get_settings
from app.db.conversation_models import Conversation, Message
from app.db.models import Document
from app.db.postgres import get_db_session
from app.services.auth import CurrentUser, is_admin_user

_WINDOW = timedelta(hours=24)


async def _count_questions(user_key: str, since: datetime) -> int:
    async with get_db_session() as session:
        return await session.scalar(
            select(func.count()).select_from(Message).join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.user_id == user_key, Message.role == "user", Message.created_at >= since)
        ) or 0


async def _count_uploads(user_key: str, since: datetime) -> int:
    async with get_db_session() as session:
        return await session.scalar(
            select(func.count()).select_from(Document).where(Document.user_id == user_key, Document.created_at >= since)
        ) or 0


def _over(used: int, adding: int, limit: int) -> bool:
    return limit > 0 and used + adding > limit


async def enforce_daily_quota(user: CurrentUser, kind: str, adding: int = 1) -> None:
    """Raise HTTP 429 when *user* would exceed today's limit for "questions" or "uploads"."""
    settings = get_settings()
    limit, count, noun = {
        "questions": (settings.QUERY_DAILY_LIMIT, _count_questions, "questions"),
        "uploads": (settings.UPLOAD_DAILY_LIMIT, _count_uploads, "file uploads"),
    }[kind]
    if limit <= 0 or await is_admin_user(user.id):
        return
    used = await count(user.key, datetime.now(timezone.utc) - _WINDOW)
    if _over(used, adding, limit):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Daily limit reached ({limit} {noun} per 24 hours). Try again tomorrow.",
        )


# ── Storage ──────────────────────────────────────────────────────────────────

def storage_limit_bytes() -> int:
    """Each user's storage allowance in bytes; 0 means unlimited."""
    return max(0, get_settings().STORAGE_LIMIT_MB) * 1024 * 1024


async def storage_used_bytes(user_key: str | None, project_name: str | None = None) -> int:
    """Total size of *user_key*'s documents, or only of one imported project's files."""
    query = select(func.coalesce(func.sum(Document.file_size), 0)).where(Document.user_id == user_key)
    if project_name is not None:
        query = query.where(Document.filename.like(f"{_escape_like(project_name)}/%", escape="\\"))
    async with get_db_session() as session:
        return int(await session.scalar(query) or 0)


def format_bytes(n: int) -> str:
    """1536 -> '1.5 KB' (matches the size format the app shows)."""
    if n < 1024:
        return f"{n} B"
    size = float(n)
    for unit in ("KB", "MB", "GB"):
        size /= 1024
        if size < 1024 or unit == "GB":
            break
    return f"{size:.1f}".removesuffix(".0") + f" {unit}"


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def enforce_storage_quota(user: CurrentUser, adding: int, replacing_project: str | None = None) -> None:
    """Raise HTTP 413 when *adding* bytes would take *user* past their storage allowance.

    Re-importing a project replaces it, so its current files don't count against the new import.
    """
    limit = storage_limit_bytes()
    if limit <= 0:
        return
    used = await storage_used_bytes(user.key)
    if replacing_project:
        used -= await storage_used_bytes(user.key, replacing_project)
    if used + adding > limit:
        left = max(0, limit - used)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Not enough storage: {format_bytes(left)} left of {format_bytes(limit)}, "
                f"and this needs {format_bytes(adding)}. Delete some documents to make room."
            ),
        )

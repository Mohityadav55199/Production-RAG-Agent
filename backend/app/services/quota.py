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

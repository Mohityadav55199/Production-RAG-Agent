"""
POST /feedback         - rate an answer (any signed-in user)
GET  /admin/feedback   - every rating, newest first (administrator), to review bad answers and extend the eval set
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.feedback_models import AnswerFeedback
from app.db.postgres import get_db_session
from app.services.auth import CurrentUser, get_current_user

router = APIRouter(tags=["Feedback"])
admin_router = APIRouter(prefix="/admin", tags=["Admin"])


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    question: str = Field(min_length=1, max_length=4000)
    answer: str = Field(min_length=1, max_length=20000)
    conversation_id: uuid.UUID | None = None
    cited_files: list[str] = Field(default_factory=list, max_length=20)
    comment: str | None = Field(default=None, max_length=1000)


@router.post("/feedback", status_code=status.HTTP_201_CREATED, summary="Rate an answer")
async def submit_feedback(body: FeedbackRequest, user: CurrentUser = Depends(get_current_user)) -> dict:
    row = AnswerFeedback(
        user_id=user.key,
        conversation_id=body.conversation_id,
        rating=body.rating,
        question=body.question,
        answer=body.answer,
        cited_files=[name[:300] for name in body.cited_files],
        comment=body.comment,
    )
    async with get_db_session() as session:
        session.add(row)
    return {"id": str(row.id)}


@admin_router.get("/feedback", summary="All answer ratings (administrator)")
async def list_feedback(rating: Literal["up", "down"] | None = None, limit: int = 200) -> list[dict]:
    query = select(AnswerFeedback).order_by(AnswerFeedback.created_at.desc()).limit(min(max(limit, 1), 1000))
    if rating:
        query = query.where(AnswerFeedback.rating == rating)
    async with get_db_session() as session:
        rows = (await session.scalars(query)).all()
    return [
        {"id": str(r.id), "rating": r.rating, "question": r.question, "answer": r.answer,
         "cited_files": r.cited_files, "comment": r.comment, "created_at": r.created_at.isoformat()}
        for r in rows
    ]

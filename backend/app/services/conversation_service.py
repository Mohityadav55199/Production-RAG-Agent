"""
Conversation history CRUD service (Phase 4).

Manages Conversation rows and Message rows in PostgreSQL.
All operations are async and use the existing get_db_session() context manager.

Responsibilities:
  - get_or_create_conversation  — resolve or mint a new session UUID
  - load_history                — fetch last N turns as LangChain messages
  - save_question / save_answer — persist the two halves of a turn
"""

import uuid
from datetime import datetime, timezone

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy import select

from app.db.conversation_models import Conversation, Message
from app.db.postgres import get_db_session
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Maximum number of *pairs* (user+assistant) to load as context window.
# Kept at 3 pairs: enough for coreference resolution, small enough to prevent
# the model from repeating unrelated content from distant turns.
_DEFAULT_HISTORY_PAIRS = 3


async def get_or_create_conversation(
    conversation_id: uuid.UUID | None,
    user_id: str | None = None,
) -> uuid.UUID:
    """
    Return the UUID of the requested conversation, or create a new one.

    If *conversation_id* is provided but does not exist in the database, a
    **new** conversation is created (defensive: avoids 404 mid-stream).

    Returns:
        UUID of the resolved or newly created Conversation.
    """
    async with get_db_session() as session:
        if conversation_id is not None:
            result = await session.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            existing = result.scalar_one_or_none()
            # A conversation id that belongs to someone else is treated as unknown
            if existing is not None and existing.user_id == user_id:
                logger.debug("Resuming conversation id=%s", conversation_id)
                return existing.id

            logger.warning(
                "conversation_id=%s not found — starting new conversation",
                conversation_id,
            )

        new_conv = Conversation(id=uuid.uuid4(), user_id=user_id)
        session.add(new_conv)
        await session.flush()
        conv_id = new_conv.id

    logger.info("Created new conversation id=%s", conv_id)
    return conv_id


async def load_history(
    conversation_id: uuid.UUID,
    max_pairs: int = _DEFAULT_HISTORY_PAIRS,
) -> list[BaseMessage]:
    """
    Load the most recent *max_pairs* user+assistant exchanges from the DB
    and return them as an ordered list of LangChain BaseMessage objects.

    The list is returned in chronological order (oldest first) so it can
    be directly appended to the LLM prompt.

    Args:
        conversation_id: UUID of the conversation to load.
        max_pairs:       Maximum number of user/assistant turns to include.

    Returns:
        List of HumanMessage / AIMessage objects, oldest first.
    """
    # Fetch the last (max_pairs * 2) rows to cover complete pairs
    async with get_db_session() as session:
        result = await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            # Older turns stored both halves with one timestamp; role breaks the tie (user before assistant)
            .order_by(Message.created_at.desc(), Message.role.asc())
            .limit(max_pairs * 2)
        )
        rows = list(reversed(result.scalars().all()))

    messages: list[BaseMessage] = []
    for i, row in enumerate(rows):
        if row.role == "user":
            # A question whose answer never arrived (client left, generation failed, empty reply) is not
            # history. Empty messages would also make Claude reject the whole request.
            answered = i + 1 < len(rows) and rows[i + 1].role == "assistant" and bool((rows[i + 1].content or "").strip())
            if answered and (row.content or "").strip():
                messages.append(HumanMessage(content=row.content))
        elif row.role == "assistant" and (row.content or "").strip():
            if messages and isinstance(messages[-1], HumanMessage):
                messages.append(AIMessage(content=row.content))

    logger.debug(
        "Loaded %d history messages for conversation_id=%s",
        len(messages),
        conversation_id,
    )
    return messages


async def _add_message(conversation_id: uuid.UUID, role: str, content: str) -> None:
    now = datetime.now(tz=timezone.utc)
    async with get_db_session() as session:
        conv = await session.get(Conversation, conversation_id)
        if conv is not None:
            conv.updated_at = now  # keeps the conversation list sorted by activity
        session.add(Message(id=uuid.uuid4(), conversation_id=conversation_id, role=role, content=content, created_at=now))


async def save_question(conversation_id: uuid.UUID, user_message: str) -> None:
    """Record the question before answering it, so it counts toward the daily quota even when the client
    disconnects or generation fails."""
    await _add_message(conversation_id, "user", user_message)
    logger.debug("Saved question for conversation_id=%s (%d chars)", conversation_id, len(user_message))


async def save_answer(conversation_id: uuid.UUID, assistant_message: str) -> None:
    """Record the answer to the question saved last."""
    await _add_message(conversation_id, "assistant", assistant_message)
    logger.debug("Saved answer for conversation_id=%s (%d chars)", conversation_id, len(assistant_message))

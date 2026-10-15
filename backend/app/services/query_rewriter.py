"""
Follow-up question condensing.

A follow-up such as "what about the frontend?" embeds poorly on its own: the
words that carry its meaning live in the earlier turns. Before retrieval the
question is rewritten into a standalone search query using the recent history.
The user's original wording is still what the answer prompt receives.

Any failure (no key, rate limit, timeout, odd output) returns the original
question, so retrieval never gets worse than it is without this step.
"""

from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.config import get_settings
from app.services.llm_factory import get_rewrite_llm
from app.utils.logging import get_logger

logger = get_logger(__name__)

_HISTORY_TURNS = 4          # most recent messages (two exchanges) are enough to resolve "it"/"that"
_ANSWER_CHARS = 300         # earlier answers are trimmed; only the topic matters here
_MAX_QUERY_CHARS = 400
_TIMEOUT_SECONDS = 8.0

_PROMPT = """\
Rewrite the user's last question as one standalone search query, using the \
conversation only to replace references such as "it", "that", "the other one" \
or to restore a dropped topic. Keep every concrete term from the question. \
If the question already makes sense on its own, return it unchanged. \
Do not answer it. Output only the query, on a single line."""


def _render_history(history: list[BaseMessage]) -> str:
    lines = []
    for msg in history[-_HISTORY_TURNS:]:
        text = msg.content if isinstance(msg.content, str) else str(msg.content)
        if isinstance(msg, AIMessage):
            text = text[:_ANSWER_CHARS]
        role = "Assistant" if isinstance(msg, AIMessage) else "User"
        lines.append(f"{role}: {text}")
    return "\n".join(lines)


def _clean(raw: str, original: str) -> str:
    query = raw.strip().splitlines()[0].strip() if raw.strip() else ""
    if query.lower().startswith(("query:", "standalone question:", "rewritten:")):
        query = query.split(":", 1)[1].strip()
    query = query.strip('"\'`').strip()
    if not query or len(query) > _MAX_QUERY_CHARS:
        return original
    return query


async def condense_question(query: str, history: list[BaseMessage]) -> str:
    """Return a standalone version of *query*, or *query* itself when there is nothing to resolve."""
    if not history or not get_settings().QUERY_REWRITE_ENABLED:
        return query
    try:
        llm = get_rewrite_llm()
        if llm is None:
            return query
        messages = [
            SystemMessage(content=_PROMPT),
            HumanMessage(content=f"Conversation:\n{_render_history(history)}\n\nLast question: {query}"),
        ]
        response = await asyncio.wait_for(llm.ainvoke(messages), timeout=_TIMEOUT_SECONDS)
        content = response.content if isinstance(response.content, str) else str(response.content)
        condensed = _clean(content, query)
        if condensed != query:
            logger.debug("condense_question: %r -> %r", query[:80], condensed[:120])
        return condensed
    except Exception as exc:  # noqa: BLE001 - retrieval must still work without the rewrite
        logger.warning("condense_question failed (%s); using the original question", exc)
        return query

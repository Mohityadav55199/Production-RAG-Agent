"""LLM helpers for the resume agents: JSON extraction with rate-limit retries."""

import asyncio
import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.utils.logging import get_logger

logger = get_logger(__name__)

_RATE_LIMIT_HINTS = ("429", "rate limit", "rate_limit", "tokens per minute", "quota", "resource_exhausted")


def extract_json(text: str) -> dict:
    """Parse the first JSON object in an LLM reply (handles ```json fences and chatter)."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("No JSON object found in model output")
    return json.loads(cleaned[start : end + 1])


def _reply_text(response) -> str:
    content = response.content
    if isinstance(content, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content or "")


async def llm_text(system: str, user: str, retries: int = 3) -> str:
    """Single LLM call with backoff on rate limits."""
    from app.services.llm_factory import get_configured_llm

    llm = get_configured_llm()
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    for attempt in range(retries):
        try:
            return _reply_text(await llm.ainvoke(messages))
        except Exception as exc:
            if attempt < retries - 1 and any(h in str(exc).lower() for h in _RATE_LIMIT_HINTS):
                wait = 8 * (attempt + 1)
                logger.warning("LLM rate limited, retrying in %ds", wait)
                await asyncio.sleep(wait)
                continue
            raise
    raise RuntimeError("unreachable")


async def llm_json(system: str, user: str, retries: int = 3) -> dict:
    """LLM call that must return a JSON object; retries on bad JSON and rate limits."""
    from app.services.llm_factory import get_configured_llm

    llm = get_configured_llm()
    messages = [
        SystemMessage(content=system + "\n\nReply with ONLY a single valid JSON object. No markdown, no commentary."),
        HumanMessage(content=user),
    ]
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return extract_json(_reply_text(await llm.ainvoke(messages)))
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            logger.warning("LLM returned invalid JSON (attempt %d): %s", attempt + 1, exc)
            messages.append(HumanMessage(content="That was not valid JSON. Reply with ONLY the JSON object."))
        except Exception as exc:
            last_error = exc
            if attempt < retries - 1 and any(h in str(exc).lower() for h in _RATE_LIMIT_HINTS):
                wait = 8 * (attempt + 1)
                logger.warning("LLM rate limited, retrying in %ds", wait)
                await asyncio.sleep(wait)
                continue
            raise
    raise ValueError(f"Model did not return valid JSON: {last_error}")

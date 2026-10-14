"""
Health-check service.

Performs real connectivity checks against:
  - Google Gemini   → lightweight models.list call
  - PostgreSQL      → raw asyncpg ping (SELECT 1)
  - Qdrant          → cluster info endpoint
"""

import asyncio

import asyncpg
import google.generativeai as genai

from app.config import get_settings
from app.db.qdrant import get_qdrant_client
from app.schemas.health import HealthResponse, ServiceStatus
from app.utils.logging import get_logger

logger = get_logger(__name__)


async def _check_gemini(settings) -> ServiceStatus:
    """
    Verify connectivity to the Gemini API by listing available models.
    Uses asyncio.to_thread because the google-generativeai SDK is synchronous.
    """
    try:
        genai.configure(api_key=settings.GOOGLE_API_KEY)

        def _list_models():
            models = list(genai.list_models())
            return models

        models = await asyncio.wait_for(
            asyncio.to_thread(_list_models),
            timeout=10,
        )
        logger.debug("Gemini check OK — %d models available", len(models))
        return "connected"
    except Exception as exc:
        logger.warning("Gemini check failed: %s", exc)
        return "not_connected"


async def _check_groq(settings) -> ServiceStatus | None:
    """Verify connectivity to Groq API if key is configured."""
    if not getattr(settings, "GROQ_API_KEY", None):
        return None
    try:
        from groq import AsyncGroq
        client = AsyncGroq(api_key=settings.GROQ_API_KEY, timeout=5.0)
        await asyncio.wait_for(client.models.list(), timeout=5)
        logger.debug("Groq check OK")
        return "connected"
    except Exception as exc:
        logger.warning("Groq check failed: %s", exc)
        return "not_connected"


async def _check_postgres(settings) -> ServiceStatus:
    """Open a raw asyncpg connection and execute SELECT 1."""
    try:
        if settings.DATABASE_URL:
            raw_url = settings.DATABASE_URL
            if "+asyncpg" in raw_url:
                raw_url = raw_url.replace("+asyncpg", "")
            elif raw_url.startswith("postgres://"):
                raw_url = raw_url.replace("postgres://", "postgresql://", 1)
            
            from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
            parsed = urlparse(raw_url)
            if parsed.query:
                allowed_params = {
                    "ssl", "timeout", "command_timeout", "statement_cache_size",
                    "max_cached_statement_lifetime", "max_cacheable_statement_size",
                    "server_settings"
                }
                query_params = parse_qsl(parsed.query)
                new_params = []
                ssl_set = False
                for k, v in query_params:
                    if k == "sslmode":
                        if v != "disable" and not ssl_set:
                            new_params.append(("ssl", "require"))
                            ssl_set = True
                    elif k == "ssl":
                        new_params.append((k, v))
                        ssl_set = True
                    elif k in allowed_params:
                        new_params.append((k, v))
                raw_url = urlunparse(parsed._replace(query=urlencode(new_params)))

            conn: asyncpg.Connection = await asyncio.wait_for(
                asyncpg.connect(raw_url),
                timeout=5,
            )
        else:
            conn: asyncpg.Connection = await asyncio.wait_for(
                asyncpg.connect(
                    host=settings.POSTGRES_HOST,
                    port=settings.POSTGRES_PORT,
                    user=settings.POSTGRES_USER,
                    password=settings.POSTGRES_PASSWORD,
                    database=settings.POSTGRES_DB,
                ),
                timeout=5,
            )
        await conn.fetchval("SELECT 1")
        await conn.close()
        logger.debug("PostgreSQL check OK")
        return "connected"
    except Exception as exc:
        logger.warning("PostgreSQL check failed: %s", exc)
        return "not_connected"


async def _check_qdrant() -> ServiceStatus:
    """Call Qdrant's cluster info endpoint via the async client."""
    try:
        client = get_qdrant_client()
        info = await asyncio.wait_for(client.get_collections(), timeout=5)
        logger.debug(
            "Qdrant check OK — %d collection(s)", len(info.collections)
        )
        return "connected"
    except Exception as exc:
        logger.warning("Qdrant check failed: %s", exc)
        return "not_connected"


async def get_health() -> HealthResponse:
    """
    Run all connectivity checks concurrently and return an aggregated result.
    overall status is 'ok' only when all three services are connected.
    """
    settings = get_settings()

    gemini_status, groq_status, postgres_status, qdrant_status = await asyncio.gather(
        _check_gemini(settings),
        _check_groq(settings),
        _check_postgres(settings),
        _check_qdrant(),
    )

    core_statuses = [gemini_status, postgres_status, qdrant_status]
    if groq_status is not None:
        core_statuses.append(groq_status)

    overall = "ok" if all(s == "connected" for s in core_statuses) else "degraded"

    return HealthResponse(
        status=overall,
        gemini=gemini_status,
        postgres=postgres_status,
        qdrant=qdrant_status,
        groq=groq_status,
    )

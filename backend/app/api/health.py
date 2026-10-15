"""
Health API router.
"""

from fastapi import APIRouter

from app.schemas.health import HealthResponse
from app.services.health_service import get_health

router = APIRouter(tags=["Health"])


@router.get("/", summary="API root", include_in_schema=False)
async def root() -> dict:
    """Opening the API's address in a browser shows that it is up instead of a bare 404."""
    from app.config import get_settings

    settings = get_settings()
    return {"name": settings.APP_NAME, "version": settings.APP_VERSION, "status": "running", "health": "/health"}


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="System health check",
    description=(
        "Returns the connectivity status for Gemini, PostgreSQL, and Qdrant. "
        "Overall `status` is `ok` only when all services are reachable."
    ),
)
async def health_check() -> HealthResponse:
    return await get_health()

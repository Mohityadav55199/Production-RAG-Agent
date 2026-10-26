"""
FastAPI application entry point.

Responsibilities:
  - Bootstrap logging
  - Register lifespan (startup / shutdown hooks)
  - Add middleware (CORS, request-ID)
  - Mount all API routers
"""

import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.feedback import admin_router as admin_feedback_router, router as feedback_router
from app.api.assets import router as assets_router
from app.api.auth import router as auth_router
from app.api.collections import router as collections_router
from app.api.compare import router as compare_router
from app.api.document_management import router as document_management_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.projects import router as projects_router
from app.api.query import router as query_router
from app.api.resume import router as resume_router
from app.config import get_settings
from app.services.auth import require_admin
from app.services.email_verification import require_verified_user
from app.db import models  # noqa: F401 — registers Phase 2 tables with Base.metadata
from app.db import conversation_models  # noqa: F401 — registers Phase 4 tables
from app.db import resume_models  # noqa: F401 — registers resume tables
from app.db import auth_models  # noqa: F401 — registers the users table
from app.db import asset_models  # noqa: F401 — registers the document_assets table
from app.db import feedback_models  # noqa: F401 — registers the answer_feedback table
from app.db import metric_models  # noqa: F401 — registers the query_metrics table
from app.db.postgres import dispose_engine, get_engine
from app.db.postgres import Base
from app.db.qdrant import close_qdrant_client
from app.services.vector_service import ensure_collection
from app.utils.logging import get_logger, setup_logging

# ── Bootstrap logging immediately (before any other import that logs) ─────────
_settings = get_settings()
setup_logging(level=_settings.LOG_LEVEL, environment=_settings.ENVIRONMENT)  # type: ignore[arg-type]
logger = get_logger(__name__)

# ── Error tracking: only when a Sentry DSN is configured ──────────────────────
if _settings.SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=_settings.SENTRY_DSN,
        environment=_settings.ENVIRONMENT,
        release=_settings.APP_VERSION,
        traces_sample_rate=_settings.SENTRY_TRACES_SAMPLE_RATE,
        send_default_pii=False,          # no IPs, cookies or user details
        max_request_body_size="never",   # questions and uploaded files never leave the server
    )
    logger.info("Sentry error tracking enabled")


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info(
        "Starting %s v%s [%s]",
        _settings.APP_NAME,
        _settings.APP_VERSION,
        _settings.ENVIRONMENT,
    )

    # ── Startup: create PostgreSQL tables ────────────────────────────────────
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("PostgreSQL tables verified / created")
    from app.db.migrations import run_migrations
    await run_migrations(engine)

    # ── Startup: ensure Qdrant collection exists ──────────────────────────────
    await ensure_collection()

    # ── Startup: re-queue interrupted uploads; fail stuck documents nothing can resume ──
    from app.services.document_service import recover_stuck_documents
    await recover_stuck_documents()

    # ── Startup: the configured administrator account (ADMIN_EMAIL + ADMIN_PASSWORD) ──
    from app.services.accounts import ensure_admin
    await ensure_admin()

    # ── Startup: resume indexing interrupted by a restart ─────────────────────
    from app.services.resume.library import recover_pending_indexing
    try:
        await recover_pending_indexing()
    except Exception:
        logger.exception("Could not recover pending resume indexing")

    # ── Startup: learn which Groq models exist, so retired ones are skipped (refreshed every 6 h) ──
    import asyncio

    from app.services.llm_factory import keep_groq_models_fresh
    model_refresh = asyncio.create_task(keep_groq_models_fresh())

    # ── Startup: the upload worker (resumes uploads a restart interrupted) ────
    from app.services.ingestion_queue import run_worker
    ingestion_worker = asyncio.create_task(run_worker())

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down — releasing resources …")
    model_refresh.cancel()
    ingestion_worker.cancel()
    await dispose_engine()
    await close_qdrant_client()
    logger.info("Shutdown complete")


# ── Application factory ───────────────────────────────────────────────────────
def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Production-ready RAG Agent API",
        docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
        redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
        openapi_url="/openapi.json" if settings.ENVIRONMENT != "production" else None,
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Auth is a bearer token in the Authorization header, never a cookie, so credentialed CORS is not needed
    if settings.ENVIRONMENT == "production" and "*" in settings.CORS_ORIGINS:
        logger.warning("CORS_ORIGINS allows any origin in production; set it to the frontend's URL")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Request-ID & latency middleware ───────────────────────────────────────
    @app.middleware("http")
    async def request_context_middleware(
        request: Request, call_next
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        start = time.perf_counter()
        response: Response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.2f}"
        logger.info(
            "%s %s -> %d  (%.2f ms) [%s]",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            request_id,
        )
        return response

    # ── Routers ───────────────────────────────────────────────────────────────
    # Public: health checks and the auth endpoints themselves
    app.include_router(health_router)
    app.include_router(auth_router)

    # Everything else requires a logged-in user (with a confirmed email when verification is on);
    # handlers scope data to that user
    protected = [Depends(require_verified_user)]
    app.include_router(documents_router, dependencies=protected)             # POST /upload
    app.include_router(document_management_router, dependencies=protected)   # GET/DELETE /documents
    app.include_router(assets_router, dependencies=protected)                # GET /assets/{id}
    app.include_router(projects_router, dependencies=protected)              # /projects/*
    app.include_router(resume_router, dependencies=protected)                # /resume/*
    app.include_router(compare_router, dependencies=protected)               # POST /compare (SSE)
    app.include_router(query_router, dependencies=protected)                 # POST /query (SSE)
    app.include_router(feedback_router, dependencies=protected)              # POST /feedback
    # Administrator tools: network check, and the Qdrant collection API (it acts on the shared index)
    app.include_router(admin_router, dependencies=[Depends(require_admin)])
    app.include_router(admin_feedback_router, dependencies=[Depends(require_admin)])   # GET /admin/feedback
    # The Qdrant collection admin API acts on the shared index, so it is admin-only
    app.include_router(collections_router, dependencies=[Depends(require_admin)])

    return app


app = create_app()

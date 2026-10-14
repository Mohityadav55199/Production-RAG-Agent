"""
Comparison API router.

POST /compare — compare two sources (pasted code/text, an imported project,
                or a document) and stream a structured analysis as SSE,
                using the same event format as POST /query plus a "diff"
                event when both sides are pasted text.
"""

import json
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.services.compare_service import CompareRequest, stream_comparison
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Compare"])


def _sse(payload: dict | str) -> str:
    if isinstance(payload, str):
        return f"data: {payload}\n\n"
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _generate(request: Request, body: CompareRequest) -> AsyncGenerator[str, None]:
    yield _sse({"type": "thinking"})
    try:
        async for event in stream_comparison(body):
            if await request.is_disconnected():
                logger.info("Client disconnected during comparison")
                return
            yield _sse(event)
    except ValueError as exc:
        yield _sse({"type": "error", "message": str(exc)})
    except Exception as exc:
        logger.exception("Comparison failed")
        yield _sse({"type": "error", "message": f"Comparison failed: {type(exc).__name__}: {exc}"})
    yield _sse("[DONE]")


@router.post(
    "/compare",
    summary="Compare two code snippets, projects or documents (SSE stream)",
    response_class=StreamingResponse,
)
async def compare_endpoint(body: CompareRequest, request: Request) -> StreamingResponse:
    logger.info("POST /compare | A=%s B=%s", body.left.type, body.right.type)
    return StreamingResponse(
        _generate(request, body),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

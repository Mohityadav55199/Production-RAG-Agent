"""
Comparison API router.

POST /compare/extract-code — read the code out of a screenshot (so it can be compared)
POST /compare — compare two sources (pasted code/text, an imported project,
                or a document) and stream a structured analysis as SSE,
                using the same event format as POST /query plus a "diff"
                event when both sides are pasted text.
"""

import asyncio
import io
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from app.services.auth import CurrentUser, get_current_user
from app.services.compare_service import CompareRequest, stream_comparison
from app.services.vision import (
    CHAT_FORMATS,
    ImageError,
    QuotaError,
    check_vision_quota,
    inspect_image,
    normalize_image,
    transcribe_code,
    vision_available,
)
from app.utils.errors import client_error_message
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Compare"])

MAX_SCREENSHOT_BYTES = 8 * 1024 * 1024


def _sse(payload: dict | str) -> str:
    if isinstance(payload, str):
        return f"data: {payload}\n\n"
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _generate(request: Request, body: CompareRequest, user_id: str) -> AsyncGenerator[str, None]:
    yield _sse({"type": "thinking"})
    try:
        async for event in stream_comparison(body, user_id):
            if await request.is_disconnected():
                logger.info("Client disconnected during comparison")
                return
            yield _sse(event)
    except ValueError as exc:
        yield _sse({"type": "error", "message": str(exc)})
    except Exception as exc:
        logger.exception("Comparison failed")
        yield _sse({"type": "error", "message": client_error_message(exc, "comparing")})
    yield _sse("[DONE]")


@router.post("/compare/extract-code", summary="Read the code out of a screenshot")
async def extract_code(file: UploadFile = File(...), user: CurrentUser = Depends(get_current_user)) -> dict:
    """Gemini transcribes the code exactly (indentation included); without a key, OCR is used, which is
    rougher. The caller shows the text for review before comparing."""
    content = await file.read(MAX_SCREENSHOT_BYTES + 1)
    try:
        inspect_image(content, max_bytes=MAX_SCREENSHOT_BYTES, allowed_formats=CHAT_FORMATS)
        jpeg, _, _ = normalize_image(content, max_edge=2000, quality=88)   # larger than usual: small text must stay legible
    except ImageError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    text, language, engine = "", None, ""
    if vision_available():
        try:
            check_vision_quota(user.key)
        except QuotaError as exc:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
        try:
            text, language = await transcribe_code(jpeg)
            engine = "gemini"
        except Exception as exc:
            logger.warning("Gemini could not read the code screenshot (%s); falling back to OCR", exc)

    if not text.strip():
        try:
            from PIL import Image

            from app.services.ocr import get_ocr_service

            def run_ocr() -> str:
                with Image.open(io.BytesIO(jpeg)) as img:
                    return get_ocr_service().extract_text(img)[0]

            text, engine = await asyncio.to_thread(run_ocr), "ocr"
        except Exception as exc:
            logger.warning("OCR failed on the code screenshot: %s", exc)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Could not read text from the image. Set GOOGLE_API_KEY on the server for reliable code reading.",
            ) from exc

    if not text.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No code was found in that image.")
    return {
        "text": text[:100_000],
        "language": language,
        "engine": engine,
        "note": None if engine == "gemini" else "Read with OCR, which can miss indentation or symbols. Check it before comparing.",
    }


@router.post(
    "/compare",
    summary="Compare two code snippets, projects or documents (SSE stream)",
    response_class=StreamingResponse,
)
async def compare_endpoint(
    body: CompareRequest, request: Request, user: CurrentUser = Depends(get_current_user)
) -> StreamingResponse:
    logger.info("POST /compare | A=%s B=%s", body.left.type, body.right.type)
    return StreamingResponse(
        _generate(request, body, user.key),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

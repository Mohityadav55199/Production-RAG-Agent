"""
Images stored with documents.

GET /assets/{id}?size=thumb|full   the image bytes, only for the document's owner

The browser cannot attach the login header to an <img> tag, so the frontend fetches these with the
header and shows them from a blob URL (the CSP already allows blob: images).
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.services.asset_service import get_asset
from app.services.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/assets", tags=["Assets"])


@router.get("/{asset_id}", summary="Download a stored image (thumbnail or full size)")
async def download_asset(
    asset_id: uuid.UUID,
    size: Literal["thumb", "full"] = Query("full"),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    asset = await get_asset(asset_id, user.key)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found.")
    return Response(
        content=asset.thumb if size == "thumb" else asset.display,
        media_type=asset.mime,
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
        },
    )

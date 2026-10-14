"""
Administrator endpoints (the account named by ADMIN_EMAIL / the first account).

GET /admin/network  - what the server sees for this request, and what to change, to verify the proxy settings
"""

from fastapi import APIRouter, Request

from app.utils.client_ip import describe

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/network", summary="Show how this request reached the server (client address detection)")
async def network_check(request: Request) -> dict:
    return describe(request)

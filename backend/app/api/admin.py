"""
Administrator endpoints (the account named by ADMIN_EMAIL / the first account).

GET /admin/network  - what the server sees for this request, to verify the proxy settings
"""

from fastapi import APIRouter, Request

from app.utils.client_ip import describe

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/network", summary="Show how this request reached the server (client address detection)")
async def network_check(request: Request) -> dict:
    info = describe(request)
    info["how_to_check"] = (
        "Open this page from your own computer and compare 'detected_client_ip' with your public IP "
        "(search 'what is my IP'). If it shows a different address, change TRUSTED_PROXY_HOPS or set "
        "CLIENT_IP_HEADER; the 'headers' list shows what your proxy sends."
    )
    return info

"""
Administrator endpoints (the account named by ADMIN_EMAIL / the first account).

GET /admin/network  - what the server sees for this request, and what to change, to verify the proxy settings
GET /admin/metrics  - question latency, token use, error and fallback rates over the last days
"""

from fastapi import APIRouter, Query, Request

from app.services.metrics import metrics as embedding_metrics
from app.services.query_metrics import summary

from app.utils.client_ip import describe

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/network", summary="Show how this request reached the server (client address detection)")
async def network_check(request: Request) -> dict:
    return describe(request)


@router.get("/metrics", summary="Question latency, token use, error and fallback rates")
async def query_metrics(days: int = Query(7, ge=1, le=90)) -> dict:
    return {**await summary(days), "embeddings": embedding_metrics.get_stats()}

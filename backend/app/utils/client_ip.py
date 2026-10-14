"""
Finding the real client address behind reverse proxies.

Anything a client sends can be forged, so only entries written by our own proxies are trusted:

- CLIENT_IP_HEADER, if configured (for example "cf-connecting-ip", which Cloudflare always
  overwrites), is used when present;
- otherwise X-Forwarded-For is read from the END, TRUSTED_PROXY_HOPS entries in (entries further left
  are client-supplied);
- otherwise the socket address.

Nothing security-critical depends on this: it feeds abuse limits (per-address login failures and
sign-ups). Password guessing against one account is capped regardless of address (see api/auth.py).
The admin "network check" shows what the server actually receives, so the setting can be verified.
"""

from fastapi import Request

from app.config import get_settings

_INTERESTING_HEADERS = (
    "x-forwarded-for", "x-real-ip", "cf-connecting-ip", "true-client-ip", "forwarded", "x-forwarded-proto",
)


def _xff_entries(request: Request) -> list[str]:
    return [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]


def client_ip(request: Request) -> str:
    settings = get_settings()
    header = settings.CLIENT_IP_HEADER.strip().lower()
    if header:
        value = request.headers.get(header, "").split(",")[0].strip()
        if value:
            return value
    entries = _xff_entries(request)
    hops = max(1, settings.TRUSTED_PROXY_HOPS)
    if entries:
        return entries[-hops] if len(entries) >= hops else entries[0]
    return request.client.host if request.client else "unknown"


def describe(request: Request) -> dict:
    """What this server sees, for the admin network check."""
    settings = get_settings()
    return {
        "detected_client_ip": client_ip(request),
        "socket_address": request.client.host if request.client else None,
        "trusted_proxy_hops": settings.TRUSTED_PROXY_HOPS,
        "client_ip_header": settings.CLIENT_IP_HEADER or None,
        "headers": {h: request.headers[h] for h in _INTERESTING_HEADERS if h in request.headers},
        "x_forwarded_for_entries": _xff_entries(request),
    }

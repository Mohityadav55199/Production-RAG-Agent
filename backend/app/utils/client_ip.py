"""
Finding the client address behind reverse proxies.

Two addresses matter, and they are different when a frontend such as Vercel proxies API calls:

  peer    the address that actually connected to us, as recorded by our own infrastructure. A client
          cannot forge it. Behind Vercel -> Cloudflare -> Render this is a Vercel server, shared by
          every user, so it is only useful as a coarse "this origin is flooding us" signal.
  client  the end user. A trusted frontend proxy passes it along (Vercel sets X-Forwarded-For and
          Forwarded to the visitor's address and overwrites anything the visitor sent). It is only
          believed when FRONTEND_FORWARDS_CLIENT_IP is on, and only if it is a valid public address.
          Someone who calls the backend directly (skipping the frontend) can forge it, which is why
          the peer gets its own, much looser, limit.

How `peer` is found, in order:
  1. CLIENT_IP_HEADER, if configured (e.g. cf-connecting-ip, which Cloudflare always overwrites);
  2. the Nth entry from the END of X-Forwarded-For (TRUSTED_PROXY_HOPS): entries on the left are
     client-supplied and never trusted for this;
  3. the socket address.

Nothing here protects accounts: password guessing is capped per account whatever the address
(see api/auth.py). These addresses only feed abuse limits. The admin "network check" shows exactly
what the server receives and says what to change, so the settings can be verified on the live site.
"""

import ipaddress
from dataclasses import dataclass

from fastapi import Request

from app.config import get_settings

_INTERESTING_HEADERS = (
    "x-forwarded-for", "forwarded", "x-real-ip", "cf-connecting-ip", "true-client-ip", "x-forwarded-proto",
)


@dataclass(frozen=True)
class ClientAddress:
    client: str   # for fine-grained abuse limits
    peer: str     # unforgeable connecting address, for coarse limits


def _xff_entries(request: Request) -> list[str]:
    return [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]


def _public_ip(value: str | None) -> str | None:
    """The value as a normalised address if it is a public IP, else None (garbage, private, loopback...)."""
    if not value:
        return None
    try:
        ip = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return None
    return str(ip)


def _forwarded_for(request: Request) -> str | None:
    """The first `for=` value of the RFC 7239 Forwarded header, without quotes, brackets or port."""
    header = request.headers.get("forwarded", "")
    for element in header.split(",")[:1]:
        for part in element.split(";"):
            name, _, value = part.strip().partition("=")
            if name.lower() != "for":
                continue
            value = value.strip().strip('"')
            if value.startswith("["):                       # [2001:db8::1]:4711
                return value[1:].split("]")[0]
            if value.count(":") == 1:                       # 203.0.113.9:4711
                return value.split(":")[0]
            return value
    return None


def _peer(request: Request) -> str:
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


def _claimed_client(request: Request) -> str | None:
    """The end-user address a frontend proxy passed along, if it is a usable public address."""
    entries = _xff_entries(request)
    return _public_ip(_forwarded_for(request)) or _public_ip(entries[0] if entries else None)


def client_address(request: Request) -> ClientAddress:
    peer = _peer(request)
    client = peer
    if get_settings().FRONTEND_FORWARDS_CLIENT_IP:
        client = _claimed_client(request) or peer
    return ClientAddress(client=client, peer=peer)


def client_ip(request: Request) -> str:
    return client_address(request).client


def _is_private(value: str) -> bool:
    try:
        return not ipaddress.ip_address(value).is_global
    except ValueError:
        return True


def describe(request: Request) -> dict:
    """What this server sees, and what to change, for the admin network check."""
    settings = get_settings()
    address = client_address(request)
    claimed = _claimed_client(request)
    present = {h for h in _INTERESTING_HEADERS if h in request.headers}

    notes: list[str] = []
    if _is_private(address.client):
        notes.append(
            f"The detected address {address.client} is private (an internal proxy hop), so every visitor "
            "would share it. Set CLIENT_IP_HEADER to a header your proxy always overwrites (for Render behind "
            "Cloudflare: cf-connecting-ip), or raise TRUSTED_PROXY_HOPS."
        )
    if claimed and claimed != address.peer and not settings.FRONTEND_FORWARDS_CLIENT_IP:
        notes.append(
            f"A frontend proxy (such as Vercel) is forwarding what looks like the visitor's address, {claimed}, "
            f"but FRONTEND_FORWARDS_CLIENT_IP is off, so visitors are identified by the proxy's address "
            f"{address.peer} instead and share one bucket. Turn it on if your frontend always overwrites "
            "X-Forwarded-For (Vercel does)."
        )
    if "cf-connecting-ip" in present and not settings.CLIENT_IP_HEADER:
        notes.append(
            "Cloudflare's cf-connecting-ip header is present. Setting CLIENT_IP_HEADER=cf-connecting-ip gives "
            "an address clients cannot forge."
        )
    if not notes:
        notes.append(
            "Looks consistent. Compare the detected client IP with your own public IP "
            "(search 'what is my IP'); they should match."
        )

    return {
        "detected_client_ip": address.client,
        "peer_ip": address.peer,
        "socket_address": request.client.host if request.client else None,
        "trusted_proxy_hops": settings.TRUSTED_PROXY_HOPS,
        "client_ip_header": settings.CLIENT_IP_HEADER or None,
        "frontend_forwards_client_ip": settings.FRONTEND_FORWARDS_CLIENT_IP,
        "forwarded_client_candidate": claimed,
        "headers": {h: request.headers[h] for h in _INTERESTING_HEADERS if h in request.headers},
        "x_forwarded_for_entries": _xff_entries(request),
        "notes": notes,
    }

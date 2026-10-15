"""
Email verification.

Active only when an email provider is configured (RESEND_API_KEY) and REQUIRE_EMAIL_VERIFICATION is on. New
accounts then get a link (a signed token, valid 48 hours) and cannot use the app until they open it.
Accounts created without email configured, and the administrator, are never blocked.
"""

from __future__ import annotations

import html
import time
import uuid

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from sqlalchemy import select

from app.config import get_settings
from app.db.auth_models import User
from app.db.postgres import get_db_session
from app.services.auth import _ALGORITHM, CurrentUser, _secret, get_current_user
from app.utils.logging import get_logger

logger = get_logger(__name__)

LINK_HOURS = 48


def email_configured() -> bool:
    return bool(get_settings().RESEND_API_KEY)


def verification_active() -> bool:
    s = get_settings()
    return email_configured() and s.REQUIRE_EMAIL_VERIFICATION


def app_url() -> str:
    s = get_settings()
    if s.APP_URL:
        return s.APP_URL.rstrip("/")
    origin = next((o for o in s.CORS_ORIGINS if o and o != "*"), "http://localhost:3000")
    return origin.rstrip("/")


def create_verify_token(user_id: uuid.UUID, email: str) -> str:
    now = int(time.time())
    payload = {"sub": str(user_id), "email": email, "typ": "verify", "iat": now, "exp": now + LINK_HOURS * 3600}
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def read_verify_token(token: str) -> tuple[uuid.UUID, str]:
    try:
        payload = jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
        if payload.get("typ") != "verify":
            raise ValueError("not a verification token")
        return uuid.UUID(payload["sub"]), payload.get("email", "")
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link has expired. Log in and ask for a new one.") from exc
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This verification link is not valid.") from exc


async def send_email(to: str, subject: str, text: str, html_body: str) -> None:
    """Send through Resend's HTTP API. Raises on failure."""
    s = get_settings()
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {s.RESEND_API_KEY}"},
            json={"from": s.EMAIL_FROM, "to": [to], "subject": subject, "text": text, "html": html_body},
        )
    if r.status_code >= 300:
        raise RuntimeError(f"Email provider answered {r.status_code}: {r.text[:200]}")


async def send_verification(user_id: uuid.UUID, email: str) -> None:
    link = f"{app_url()}/verify-email?token={create_verify_token(user_id, email)}"
    text = (
        "Confirm your email address to start using RAG Agent:\n\n"
        f"{link}\n\nThe link works for {LINK_HOURS} hours. If you didn't sign up, ignore this email."
    )
    html_body = (
        "<p>Confirm your email address to start using RAG Agent.</p>"
        f'<p><a href="{html.escape(link)}">Confirm my email</a></p>'
        f"<p>The link works for {LINK_HOURS} hours. If you didn't sign up, ignore this email.</p>"
    )
    await send_email(email, "Confirm your email for RAG Agent", text, html_body)


async def mark_verified(user_id: uuid.UUID) -> User | None:
    async with get_db_session() as session:
        user = await session.get(User, user_id)
        if user is not None:
            user.email_verified = True
        return user


async def require_verified_user(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Router dependency: the account may use the app (verified, admin, or verification not active)."""
    if not verification_active():
        return user
    async with get_db_session() as session:
        row = (await session.execute(
            select(User.email_verified, User.is_admin).where(User.id == user.id)
        )).first()
    if row is not None and not row.email_verified and not row.is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Please confirm your email address first. We sent a link to {user.email}.",
        )
    return user

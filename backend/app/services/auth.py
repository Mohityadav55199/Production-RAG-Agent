"""
Authentication helpers: password hashing (bcrypt), signed tokens (JWT) and the
FastAPI dependencies that every protected route uses.
"""

import asyncio
import secrets
import time
import uuid
from dataclasses import dataclass

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

_bearer = HTTPBearer(auto_error=False)
_ALGORITHM = "HS256"
_fallback_secret: str | None = None

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72  # bcrypt ignores everything past 72 bytes

# bcrypt is deliberately slow (~250 ms of CPU). It runs in worker threads, and at most a few at once,
# so a burst of logins can neither freeze the event loop nor exhaust the CPU.
_hash_slots = asyncio.Semaphore(4)


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str

    @property
    def key(self) -> str:
        """String form used in the user_id columns."""
        return str(self.id)


def _secret() -> str:
    global _fallback_secret
    configured = get_settings().JWT_SECRET
    if configured:
        return configured
    if _fallback_secret is None:
        _fallback_secret = secrets.token_urlsafe(48)
        logger.warning(
            "JWT_SECRET is not set: using a random secret. Everyone is logged out on every restart. "
            "Set JWT_SECRET to a long random string in your environment."
        )
    return _fallback_secret


# ── Passwords ────────────────────────────────────────────────────────────────

def validate_password(password: str) -> str | None:
    """Return an error message if the password is unacceptable, else None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return "Password is too long (max 72 bytes)."
    return None


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:MAX_PASSWORD_BYTES], password_hash.encode("ascii"))
    except ValueError:
        return False


async def hash_password_async(password: str) -> str:
    async with _hash_slots:
        return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password: str, password_hash: str) -> bool:
    async with _hash_slots:
        return await asyncio.to_thread(verify_password, password, password_hash)


# A real bcrypt hash checked when the email is unknown, so login time doesn't reveal which emails exist
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


# ── Tokens ───────────────────────────────────────────────────────────────────

def create_token(user_id: uuid.UUID, email: str) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": now,
        "exp": now + get_settings().JWT_EXPIRE_HOURS * 3600,
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def decode_token(token: str) -> CurrentUser:
    try:
        payload = jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
        if payload.get("typ") == "device":      # device tokens are not login sessions
            raise ValueError("device token used as a session")
        return CurrentUser(id=uuid.UUID(payload["sub"]), email=payload.get("email", ""))
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Your session has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ── Trusted-device tokens ────────────────────────────────────────────────────
# Issued after each successful login and kept by the browser. A login that presents a valid one for
# that account is not blocked by the per-account failure cap, so someone guessing passwords can never
# lock the real owner out of their usual device.

DEVICE_TOKEN_DAYS = 180


def create_device_token(user_id: uuid.UUID) -> str:
    now = int(time.time())
    payload = {"sub": str(user_id), "typ": "device", "iat": now, "exp": now + DEVICE_TOKEN_DAYS * 86400}
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def is_trusted_device(token: str | None, user_id: uuid.UUID) -> bool:
    if not token:
        return False
    try:
        payload = jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
        return payload.get("typ") == "device" and payload.get("sub") == str(user_id)
    except jwt.PyJWTError:
        return False


# ── FastAPI dependencies ─────────────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Please log in to continue.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_token(credentials.credentials)


# ── Administrator ────────────────────────────────────────────────────────────
# The flag lives on the user row. It is set only by accounts.ensure_admin (ADMIN_EMAIL + ADMIN_PASSWORD
# in the server environment) or, when no admin is configured, for the very first account. It can never
# be obtained by registering an address.

async def is_admin_user(user_id: uuid.UUID) -> bool:
    from sqlalchemy import select

    from app.db.auth_models import User
    from app.db.postgres import get_db_session

    async with get_db_session() as session:
        return bool(await session.scalar(select(User.is_admin).where(User.id == user_id)))


async def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not await is_admin_user(user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This action is restricted to the administrator.")
    return user

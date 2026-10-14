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
        return CurrentUser(id=uuid.UUID(payload["sub"]), email=payload.get("email", ""))
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Your session has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


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


# ── Admin = the owner: the first account ever created ────────────────────────
# Deriving admin from an email address would let anyone register that address first and
# become admin (emails are not verified). The first account is fixed once it exists.

_owner_id: uuid.UUID | None = None


def reset_owner_cache() -> None:
    global _owner_id
    _owner_id = None


async def get_owner_id() -> uuid.UUID | None:
    global _owner_id
    if _owner_id is None:
        from sqlalchemy import select

        from app.db.auth_models import User
        from app.db.postgres import get_db_session

        async with get_db_session() as session:
            _owner_id = await session.scalar(select(User.id).order_by(User.created_at.asc()).limit(1))
    return _owner_id


async def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.id != await get_owner_id():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This action is restricted to the administrator.")
    return user

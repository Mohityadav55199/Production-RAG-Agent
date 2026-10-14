"""
Auth API.

POST /auth/signup  – create an account, returns a token
POST /auth/login   – returns a token
GET  /auth/me      – the current user (validates a stored token)
"""

import re
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db.auth_models import User
from app.db.postgres import get_db_session
from app.services.auth import (
    DUMMY_HASH,
    CurrentUser,
    create_token,
    get_current_user,
    hash_password,
    validate_password,
    verify_password,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")

# ── Brute-force protection (per process; fine for a single Render instance) ──
_WINDOW_SECONDS = 15 * 60
_MAX_FAILURES = 6
_failures: dict[str, deque[float]] = defaultdict(deque)


def _client_key(request: Request, email: str) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    return f"{ip}|{email}"


def _check_rate_limit(key: str) -> None:
    now = time.time()
    attempts = _failures[key]
    while attempts and now - attempts[0] > _WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= _MAX_FAILURES:
        wait = int(_WINDOW_SECONDS - (now - attempts[0])) // 60 + 1
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many failed attempts. Try again in about {wait} minute{'s' if wait != 1 else ''}.",
        )


class Credentials(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=200)


class AuthResponse(BaseModel):
    token: str
    user: dict


def _normalise_email(email: str) -> str:
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter a valid email address.")
    return email


def _response(user_id, email: str) -> AuthResponse:
    return AuthResponse(token=create_token(user_id, email), user={"id": str(user_id), "email": email})


async def _claim_existing_data(session, user_id: str) -> None:
    """The first account to register adopts everything created before accounts existed."""
    for table in ("documents", "conversations", "resumes", "resume_generations"):
        result = await session.execute(
            text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"), {"uid": user_id}
        )
        if result.rowcount:
            logger.info("Assigned %d existing %s rows to the first user", result.rowcount, table)


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: Credentials) -> AuthResponse:
    if not get_settings().ALLOW_SIGNUP:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is closed.")
    email = _normalise_email(body.email)
    problem = validate_password(body.password)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)

    password_hash = hash_password(body.password)
    try:
        async with get_db_session() as session:
            is_first = (await session.scalar(select(func.count()).select_from(User))) == 0
            user = User(email=email, password_hash=password_hash)
            session.add(user)
            await session.flush()
            if is_first:
                await _claim_existing_data(session, str(user.id))
            user_id = user.id
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists. Try logging in.")
    logger.info("New user registered: %s", email)
    return _response(user_id, email)


@router.post("/login", response_model=AuthResponse)
async def login(body: Credentials, request: Request) -> AuthResponse:
    email = body.email.strip().lower()
    key = _client_key(request, email)
    _check_rate_limit(key)

    async with get_db_session() as session:
        user = await session.scalar(select(User).where(User.email == email))

    # Always run one bcrypt check so response time doesn't reveal whether the email exists
    valid = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid:
        _failures[key].append(time.time())
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")

    _failures.pop(key, None)
    return _response(user.id, user.email)


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"id": str(user.id), "email": user.email}

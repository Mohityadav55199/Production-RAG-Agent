"""
Auth API.

POST /auth/signup  – create an account, returns a token
POST /auth/login   – returns a token
GET  /auth/me      – the current user (validates a stored token)
"""

import re
import time
from collections import deque

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
    hash_password_async,
    validate_password,
    verify_password_async,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


class SlidingWindowLimiter:
    """Counts events per key inside a time window. Memory is bounded: expired keys are pruned,
    and if an attacker floods with unique keys the oldest ones are dropped."""

    def __init__(self, limit: int, window_seconds: int, max_keys: int = 10_000):
        self.limit = limit
        self.window = window_seconds
        self.max_keys = max_keys
        self._events: dict[str, deque[float]] = {}

    def _prune(self, now: float) -> None:
        if len(self._events) <= self.max_keys:
            return
        for key in [k for k, q in self._events.items() if not q or now - q[-1] > self.window]:
            del self._events[key]
        if len(self._events) > self.max_keys:  # still flooded: drop the oldest tenth
            oldest = sorted(self._events, key=lambda k: self._events[k][-1])[: self.max_keys // 10]
            for key in oldest:
                del self._events[key]

    def retry_after_minutes(self, key: str) -> int | None:
        """Minutes until the key may try again, or None if it is under the limit."""
        now = time.time()
        events = self._events.get(key)
        if not events:
            return None
        while events and now - events[0] > self.window:
            events.popleft()
        if len(events) >= self.limit:
            return int(self.window - (now - events[0])) // 60 + 1
        return None

    def hit(self, key: str) -> None:
        now = time.time()
        self._prune(now)
        self._events.setdefault(key, deque()).append(now)

    def reset(self, key: str) -> None:
        self._events.pop(key, None)


# Per process, which is fine for a single instance.
_login_by_ip_email = SlidingWindowLimiter(limit=6, window_seconds=15 * 60)   # one address guessing one account
_login_by_ip = SlidingWindowLimiter(limit=30, window_seconds=15 * 60)        # one address, any account
# Per account whatever the address: bounds password guessing even if address detection is wrong or
# the attacker rotates addresses. (The cost is that guessing can temporarily lock an account out.)
_login_by_email = SlidingWindowLimiter(limit=12, window_seconds=15 * 60)
_signup_by_ip = SlidingWindowLimiter(limit=10, window_seconds=60 * 60)


def _client_ip(request: Request) -> str:
    """Best-effort client address behind a trusted reverse proxy.

    X-Forwarded-For is "client-supplied..., address-the-first-proxy-saw, ...". Only the entries our own
    proxies append are trustworthy, so count from the right (TRUSTED_PROXY_HOPS) and never take the leftmost."""
    forwarded = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    hops = max(1, get_settings().TRUSTED_PROXY_HOPS)
    if forwarded:
        return forwarded[-hops] if len(forwarded) >= hops else forwarded[0]
    return request.client.host if request.client else "unknown"


def _enforce(limiter: SlidingWindowLimiter, key: str, what: str) -> None:
    wait = limiter.retry_after_minutes(key)
    if wait is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many {what}. Try again in about {wait} minute{'s' if wait != 1 else ''}.",
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
async def signup(body: Credentials, request: Request) -> AuthResponse:
    if not get_settings().ALLOW_SIGNUP:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is closed.")
    ip = _client_ip(request)
    _enforce(_signup_by_ip, ip, "sign-up attempts from this network")
    _signup_by_ip.hit(ip)

    email = _normalise_email(body.email)
    problem = validate_password(body.password)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)

    password_hash = await hash_password_async(body.password)
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
    logger.info("New user registered: id=%s", user_id)
    return _response(user_id, email)


@router.post("/login", response_model=AuthResponse)
async def login(body: Credentials, request: Request) -> AuthResponse:
    email = body.email.strip().lower()
    ip = _client_ip(request)
    account_key = f"{ip}|{email}"
    _enforce(_login_by_ip, ip, "failed attempts from this network")
    _enforce(_login_by_ip_email, account_key, "failed attempts for this account")
    _enforce(_login_by_email, email, "failed attempts for this account")

    async with get_db_session() as session:
        user = await session.scalar(select(User).where(User.email == email))

    # Always run one bcrypt check so response time doesn't reveal whether the email exists
    valid = await verify_password_async(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid:
        _login_by_ip.hit(ip)
        _login_by_ip_email.hit(account_key)
        _login_by_email.hit(email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")

    _login_by_ip_email.reset(account_key)
    _login_by_email.reset(email)
    return _response(user.id, user.email)


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"id": str(user.id), "email": user.email}

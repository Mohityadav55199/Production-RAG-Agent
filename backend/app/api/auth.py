"""
Auth API.

POST /auth/signup  – create an account, returns a session token (+ a trusted-device token)
POST /auth/login   – returns the same
GET  /auth/me      – the current user, including whether they are the administrator
POST /auth/verify-email         – confirm an email address with the link's token
POST /auth/resend-verification  – send the confirmation link again (3 per hour)

Password guessing is bounded without relying on the client address (which can be hard to determine
behind proxies and can be forged):

  per account, any address   12 failures / 15 min   – the real brute-force cap
  per address + account       6 failures / 15 min
  per address, any account   30 failures / 15 min   – floods
  sign-ups per address       10 / hour

The per-account cap would let an attacker lock the owner out, so a login that presents a valid
trusted-device token for that account (issued after every successful login and kept by the owner's
browser) is exempt from it. Attackers never have one, so they stay capped; the owner on their usual
device cannot be locked out.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db.auth_models import User
from app.db.postgres import get_db_session
from app.services.accounts import EMAIL_RE, admin_is_configured, claim_existing_data
from app.services.auth import (
    DUMMY_HASH,
    CurrentUser,
    create_device_token,
    create_token,
    get_current_user,
    hash_password_async,
    is_trusted_device,
    validate_password,
    verify_password_async,
)
from app.services.email_verification import mark_verified, read_verify_token, send_verification, verification_active
from app.utils.client_ip import client_address
from app.utils.rate_limit import SlidingWindowLimiter
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])


# Per process, which is fine for a single instance.
_login_by_ip_email = SlidingWindowLimiter(limit=6, window_seconds=15 * 60)
_login_by_ip = SlidingWindowLimiter(limit=30, window_seconds=15 * 60)
_login_by_email = SlidingWindowLimiter(limit=12, window_seconds=15 * 60)
_signup_by_ip = SlidingWindowLimiter(limit=10, window_seconds=60 * 60)
# The connecting ("peer") address cannot be forged, but behind a frontend proxy it is shared by every visitor,
# so these are far looser: they only stop one origin (e.g. someone bypassing the frontend and forging the
# visitor address to dodge the limits above) from flooding the API.
_login_by_peer = SlidingWindowLimiter(limit=600, window_seconds=15 * 60)
_signup_by_peer = SlidingWindowLimiter(limit=200, window_seconds=60 * 60)
_resend_by_user = SlidingWindowLimiter(limit=3, window_seconds=60 * 60)


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
    device: str | None = Field(None, max_length=2000, description="Trusted-device token from a previous login.")


class AuthResponse(BaseModel):
    token: str
    device: str
    user: dict


def _normalise_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter a valid email address.")
    return email


def _response(user: User) -> AuthResponse:
    return AuthResponse(
        token=create_token(user.id, user.email),
        device=create_device_token(user.id),
        user={
            "id": str(user.id), "email": user.email, "is_admin": bool(user.is_admin),
            "email_verified": bool(user.email_verified),
        },
    )


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: Credentials, request: Request) -> AuthResponse:
    if not get_settings().ALLOW_SIGNUP:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is closed.")
    address = client_address(request)
    ip = address.client
    _enforce(_signup_by_ip, ip, "sign-up attempts from this network")
    _enforce(_signup_by_peer, address.peer, "sign-up attempts from this network")
    _signup_by_ip.hit(ip)
    _signup_by_peer.hit(address.peer)

    email = _normalise_email(body.email)
    problem = validate_password(body.password)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)

    password_hash = await hash_password_async(body.password)
    try:
        async with get_db_session() as session:
            is_first = (await session.scalar(select(func.count()).select_from(User))) == 0
            # With ADMIN_EMAIL configured the admin is provisioned at startup; otherwise the first
            # account (the person who set the site up) is the admin.
            user = User(
                email=email, password_hash=password_hash, is_admin=is_first and not admin_is_configured(),
                email_verified=not verification_active(),
            )
            session.add(user)
            await session.flush()
            if is_first:
                await claim_existing_data(session, str(user.id))
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists. Try logging in.")
    logger.info("New user registered: id=%s", user.id)
    if not user.email_verified:
        try:
            await send_verification(user.id, user.email)
        except Exception as exc:  # noqa: BLE001 - the account exists; the user can ask for the link again
            logger.warning("Could not send the verification email for user %s: %s", user.id, exc)
    return _response(user)


@router.post("/login", response_model=AuthResponse)
async def login(body: Credentials, request: Request) -> AuthResponse:
    email = body.email.strip().lower()
    address = client_address(request)
    ip = address.client
    ip_email_key = f"{ip}|{email}"
    _enforce(_login_by_ip, ip, "failed attempts from this network")
    _enforce(_login_by_peer, address.peer, "failed attempts from this network")

    async with get_db_session() as session:
        user = await session.scalar(select(User).where(User.email == email))

    trusted = bool(user and is_trusted_device(body.device, user.id))
    _enforce(_login_by_ip_email, ip_email_key, "failed attempts for this account")
    if not trusted:
        _enforce(_login_by_email, email, "failed attempts for this account")

    # Always run one bcrypt check so response time doesn't reveal whether the email exists
    valid = await verify_password_async(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid:
        _login_by_ip.hit(ip)
        _login_by_peer.hit(address.peer)
        _login_by_ip_email.hit(ip_email_key)
        if not trusted:
            _login_by_email.hit(email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")

    _login_by_ip_email.reset(ip_email_key)
    _login_by_email.reset(email)
    return _response(user)


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    async with get_db_session() as session:
        row = await session.get(User, user.id)
    return {
        "id": str(user.id), "email": user.email, "is_admin": bool(row and row.is_admin),
        "email_verified": bool(row is None or row.email_verified or not verification_active()),
    }


class VerifyRequest(BaseModel):
    token: str = Field(..., max_length=2000)


@router.post("/verify-email", summary="Confirm an email address with the token from the link")
async def verify_email(body: VerifyRequest) -> dict:
    user_id, _ = read_verify_token(body.token)
    user = await mark_verified(user_id)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This verification link is not valid.")
    return {"ok": True, "email": user.email}


@router.post("/resend-verification", summary="Send the confirmation link again")
async def resend_verification(user: CurrentUser = Depends(get_current_user)) -> dict:
    async with get_db_session() as session:
        row = await session.get(User, user.id)
    if row is None or row.email_verified or not verification_active():
        return {"ok": True, "sent": False}
    _enforce(_resend_by_user, str(user.id), "confirmation emails")
    _resend_by_user.hit(str(user.id))
    try:
        await send_verification(row.id, row.email)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not resend the verification email for user %s: %s", user.id, exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Could not send the email. Try again in a few minutes.") from exc
    return {"ok": True, "sent": True}

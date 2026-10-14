"""
Account provisioning that is shared by the sign-up route and startup.

The administrator is configured, not self-declared: ADMIN_EMAIL + ADMIN_PASSWORD create (or take over)
that account at startup. Email addresses are not verified, so the admin flag can never be granted by
registering an address; only whoever controls the server's environment can set it.
"""

import re

from sqlalchemy import func, select, text, update

from app.config import get_settings
from app.db.auth_models import User
from app.db.postgres import get_db_session
from app.services.auth import hash_password_async, validate_password, verify_password_async
from app.utils.logging import get_logger

logger = get_logger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")

# Tables that carry a user_id and may hold rows created before accounts existed
_OWNED_TABLES = ("documents", "conversations", "resumes", "resume_generations")


async def claim_existing_data(session, user_id: str) -> None:
    """The first account adopts everything created before accounts existed."""
    for table in _OWNED_TABLES:
        result = await session.execute(
            text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"), {"uid": user_id}
        )
        if result.rowcount:
            logger.info("Assigned %d existing %s rows to the first user", result.rowcount, table)


def admin_is_configured() -> bool:
    return bool(get_settings().ADMIN_EMAIL.strip())


async def ensure_admin() -> None:
    """
    Make the configured account exist and be the one and only administrator.

    - ADMIN_EMAIL + ADMIN_PASSWORD are the source of truth: the account is created if missing, and its
      password is reset to ADMIN_PASSWORD if it differs (so the owner can always get back in).
    - Everyone else loses the admin flag.
    - If the database has no users yet, the new admin also adopts data that predates accounts.
    - ADMIN_EMAIL without ADMIN_PASSWORD does nothing (and says so): promoting an account that anyone
      could have registered would be exactly the hijack this design avoids.
    Never raises; a bad configuration is logged and ignored so the app still starts.
    """
    settings = get_settings()
    email = settings.ADMIN_EMAIL.strip().lower()
    password = settings.ADMIN_PASSWORD
    if not email:
        return
    if not EMAIL_RE.match(email):
        logger.error("ADMIN_EMAIL %r is not a valid email address; admin setup skipped", email)
        return
    if not password:
        logger.error("ADMIN_EMAIL is set but ADMIN_PASSWORD is not; admin setup skipped "
                     "(set both, or remove ADMIN_EMAIL)")
        return
    problem = validate_password(password)
    if problem:
        logger.error("ADMIN_PASSWORD rejected: %s Admin setup skipped.", problem)
        return

    try:
        async with get_db_session() as session:
            user = await session.scalar(select(User).where(User.email == email))
            if user is None:
                is_first = (await session.scalar(select(func.count()).select_from(User))) == 0
                user = User(email=email, password_hash=await hash_password_async(password), is_admin=True)
                session.add(user)
                await session.flush()
                if is_first:
                    await claim_existing_data(session, str(user.id))
                logger.info("Created administrator account %s", email)
            else:
                if not await verify_password_async(password, user.password_hash):
                    user.password_hash = await hash_password_async(password)
                    logger.info("Reset the administrator's password from ADMIN_PASSWORD")
                user.is_admin = True

            demoted = await session.execute(
                update(User).where(User.id != user.id, User.is_admin.is_(True)).values(is_admin=False)
            )
            if demoted.rowcount:
                logger.warning("Removed the admin flag from %d other account(s)", demoted.rowcount)
    except Exception:
        logger.exception("Could not set up the administrator account")

"""
Idempotent schema upgrades run at startup, after ``Base.metadata.create_all``.

``create_all`` creates missing tables but never alters existing ones, so the
columns and indexes added for user accounts are applied here. Every statement
is safe to run repeatedly and on a fresh database.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.utils.logging import get_logger

logger = get_logger(__name__)

_STATEMENTS = [
    # Documents become per-user
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS user_id VARCHAR(64)",
    "CREATE INDEX IF NOT EXISTS ix_documents_user_id ON documents (user_id)",
    # file_hash was globally unique; it must now be unique per user instead
    "ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_file_hash_key",
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM pg_indexes
            WHERE tablename = 'documents' AND indexname = 'ix_documents_file_hash'
              AND indexdef LIKE 'CREATE UNIQUE%'
        ) THEN
            DROP INDEX ix_documents_file_hash;
        END IF;
    END $$
    """,
    "CREATE INDEX IF NOT EXISTS ix_documents_file_hash ON documents (file_hash)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_user_hash ON documents (user_id, file_hash)",
    # Administrator flag (replaces "the oldest account is admin")
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false",
    # Deployments created before the flag existed: keep the original owner (oldest account) as admin
    """
    UPDATE users SET is_admin = true
    WHERE id = (SELECT id FROM users ORDER BY created_at ASC LIMIT 1)
      AND NOT EXISTS (SELECT 1 FROM users WHERE is_admin)
    """,
    # Conversations become per-user
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS user_id VARCHAR(64)",
    "CREATE INDEX IF NOT EXISTS ix_conversations_user_id ON conversations (user_id)",
]


async def run_migrations(engine: AsyncEngine) -> None:
    for statement in _STATEMENTS:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(statement))
        except Exception as exc:  # never block startup on a migration hiccup
            logger.error("Migration statement failed (%s): %s", " ".join(statement.split())[:80], exc)
    logger.info("Schema migrations applied")

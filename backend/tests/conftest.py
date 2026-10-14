"""
Shared test setup.

Most tests are pure and need nothing. The API tests need a real PostgreSQL database; set
TEST_DATABASE_URL (e.g. postgresql+asyncpg://postgres:pw@localhost:5433/test) to run them.
The database name must contain "test": the schema is wiped at the start of the run.
"""

import asyncio
import os
import uuid

import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# Settings are cached on first import, so the environment must be prepared before `app` is imported.
os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret-123456")
os.environ.setdefault("ENVIRONMENT", "development")
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

requires_db = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="set TEST_DATABASE_URL (database name must contain 'test') to run API tests"
)


def _asyncpg_dsn() -> str:
    return TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)


def run_sql(query: str, *args):
    """Run one raw SQL statement against the test database (for seeding and inspection)."""
    import asyncpg

    async def go():
        conn = await asyncpg.connect(_asyncpg_dsn())
        try:
            return await conn.fetch(query, *args)
        finally:
            await conn.close()

    return asyncio.run(go())


def insert_document(filename: str, file_hash: str, user_id: str | None, status: str = "COMPLETED") -> uuid.UUID:
    doc_id = uuid.uuid4()
    run_sql(
        """INSERT INTO documents (id, filename, file_size, file_hash, user_id, status, chunk_count, page_count,
           total_chunks, embedded_chunks, failed_chunks, file_type, parser_used, ocr_used, extraction_method,
           created_at, updated_at)
           VALUES ($1,$2,10,$3,$4,$5::documentstatus,1,1,1,1,0,'txt','utf8',false,'native',now(),now())""",
        doc_id, filename, file_hash, user_id, status,
    )
    return doc_id


def insert_documents_bulk(rows: list[tuple[str, str, str | None, str, str | None]]) -> None:
    """Insert many documents over ONE connection. Rows: (filename, file_hash, user_id, status, error_message)."""
    import asyncpg

    async def go():
        conn = await asyncpg.connect(_asyncpg_dsn())
        try:
            await conn.executemany(
                """INSERT INTO documents (id, filename, file_size, file_hash, user_id, status, chunk_count, page_count,
                   total_chunks, embedded_chunks, failed_chunks, file_type, parser_used, ocr_used, extraction_method,
                   error_message, created_at, updated_at)
                   VALUES ($1,$2,10,$3,$4,$5::documentstatus,1,1,1,1,0,'txt','utf8',false,'native',$6,now(),now())""",
                [(uuid.uuid4(), name, h, user, status, err) for name, h, user, status, err in rows],
            )
        finally:
            await conn.close()

    asyncio.run(go())


@pytest.fixture(scope="session")
def client():
    """A TestClient running the real app (including startup migrations) on a freshly wiped test database."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    db_name = TEST_DATABASE_URL.rsplit("/", 1)[-1].split("?")[0]
    assert "test" in db_name, f"refusing to wipe database '{db_name}': its name must contain 'test'"

    run_sql("DROP SCHEMA public CASCADE")
    run_sql("CREATE SCHEMA public")

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}

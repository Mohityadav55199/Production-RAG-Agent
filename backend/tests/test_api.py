"""
API tests against the real app and a real PostgreSQL database (see conftest.py).

Covers login, per-user data isolation, the owner-only admin API, the project endpoints, rate limits,
per-user resume limits and startup recovery. Users are created once for the module; the first one
registered is the owner/administrator.
"""

import asyncio
import hashlib
import threading
import time
import uuid

import pytest
from fastapi import Depends

from tests.conftest import auth_header, insert_document, insert_documents_bulk, requires_db, run_sql

pytestmark = requires_db


# ── Test-only routes that expose internal helpers through the real auth dependency ───────────────

@pytest.fixture(scope="module", autouse=True)
def _helper_routes(client):
    from app.main import app
    from app.services.auth import CurrentUser, get_current_user
    from app.services.conversation_service import get_or_create_conversation
    from app.services.resume.library import recover_pending_indexing
    from app.services.scope_service import resolve_scope

    async def scope(kind: str = "all", user: CurrentUser = Depends(get_current_user)):
        return {"ids": (await resolve_scope(user.key, kind=kind)).document_ids}

    async def conv(conversation_id: uuid.UUID, user: CurrentUser = Depends(get_current_user)):
        return {"id": str(await get_or_create_conversation(conversation_id, user.key))}

    async def recover():
        return {"recovered": await recover_pending_indexing()}

    app.add_api_route("/_scope", scope, methods=["GET"])
    app.add_api_route("/_conv/{conversation_id}", conv, methods=["GET"])
    app.add_api_route("/_recover", recover, methods=["POST"])


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Rate-limit state is per process; keep tests independent of each other."""
    from app.api import auth as auth_api

    for limiter in (auth_api._login_by_ip_email, auth_api._login_by_ip, auth_api._login_by_email, auth_api._signup_by_ip):
        limiter._events.clear()
    yield


@pytest.fixture(scope="module")
def users(client):
    """Alice registers first (owner) and adopts data that predates accounts; Bob registers second."""
    insert_document("legacy.txt", "h-legacy", None)
    legacy_conv = uuid.uuid4()
    run_sql("INSERT INTO conversations (id, created_at, updated_at) VALUES ($1, now(), now())", legacy_conv)

    a = client.post("/auth/signup", json={"email": "Alice@Example.com", "password": "correct horse 1"})
    b = client.post("/auth/signup", json={"email": "bob@example.com", "password": "bobs password 3"})
    assert a.status_code == 201 and b.status_code == 201
    return {
        "alice": auth_header(a.json()["token"]),
        "bob": auth_header(b.json()["token"]),
        "alice_id": a.json()["user"]["id"],
        "bob_id": b.json()["user"]["id"],
        "legacy_conv": legacy_conv,
    }


# ── Authentication ───────────────────────────────────────────────────────────────────────────────

class TestAuthentication:
    @pytest.mark.parametrize("path", ["/documents", "/projects", "/projects/sources", "/resume/library",
                                      "/resume/generations"])
    def test_data_endpoints_require_login(self, client, path):
        assert client.get(path).status_code == 401

    def test_writes_require_login(self, client):
        assert client.post("/query", json={"query": "hi"}).status_code == 401
        assert client.post("/upload", files={"files": ("a.txt", b"hello")}).status_code == 401
        assert client.post("/compare", json={}).status_code in (401, 422)
        assert client.post("/resume/tailor", json={}).status_code in (401, 422)

    def test_health_is_public(self, client):
        assert client.get("/health").status_code == 200

    def test_garbage_and_tampered_tokens_are_rejected(self, client, users):
        assert client.get("/documents", headers=auth_header("garbage")).status_code == 401
        tampered = users["alice"]["Authorization"][:-3] + "abc"
        assert client.get("/documents", headers={"Authorization": tampered}).status_code == 401

    def test_signup_validation(self, client):
        assert client.post("/auth/signup", json={"email": "a@x.com", "password": "short"}).status_code == 422
        assert client.post("/auth/signup", json={"email": "nope", "password": "long enough 1"}).status_code == 422
        too_long = "x" * 80
        assert client.post("/auth/signup", json={"email": "c@x.com", "password": too_long}).status_code == 422

    def test_duplicate_email_is_case_insensitive(self, client, users):
        r = client.post("/auth/signup", json={"email": "ALICE@example.com", "password": "another pass 2"})
        assert r.status_code == 409

    def test_login(self, client, users):
        ok = client.post("/auth/login", json={"email": "alice@example.com", "password": "correct horse 1"})
        assert ok.status_code == 200 and ok.json()["user"]["email"] == "alice@example.com"
        bad = client.post("/auth/login", json={"email": "alice@example.com", "password": "wrong wrong wrong"})
        ghost = client.post("/auth/login", json={"email": "ghost@example.com", "password": "whatever 123"})
        assert bad.status_code == ghost.status_code == 401
        assert bad.json()["detail"] == ghost.json()["detail"]            # no hint about which emails exist

    def test_me(self, client, users):
        me = client.get("/auth/me", headers=users["alice"]).json()
        assert me["email"] == "alice@example.com" and me["id"] == users["alice_id"]

    def test_password_hashing_runs_off_the_event_loop(self, monkeypatch):
        from app.services import auth

        seen = {}
        monkeypatch.setattr(auth, "hash_password", lambda pw: seen.setdefault("thread", threading.current_thread()) and "x")
        asyncio.run(auth.hash_password_async("some password"))
        assert seen["thread"] is not threading.main_thread()


# ── Rate limits ──────────────────────────────────────────────────────────────────────────────────

class TestRateLimits:
    def test_forged_forwarded_for_entries_do_not_evade_the_limit(self, client, users):
        """A real proxy appends the true client address at the END; anything to its left is client-supplied."""
        codes = [
            client.post("/auth/login", headers={"X-Forwarded-For": f"10.0.0.{i}, 9.9.9.9"},
                        json={"email": "victim@example.com", "password": f"guess number {i}"}).status_code
            for i in range(8)
        ]
        assert codes.count(401) == 6 and 429 in codes, codes

    def test_rotating_addresses_still_cannot_brute_force_one_account(self, client, users):
        """Even if the address detection is fooled completely, the per-account cap holds."""
        codes = [
            client.post("/auth/login", headers={"X-Forwarded-For": f"10.1.{i // 250}.{i % 250}"},
                        json={"email": "victim2@example.com", "password": f"guess number {i}"}).status_code
            for i in range(16)
        ]
        assert codes.count(401) == 12 and codes.count(429) == 4, codes

    def test_client_address_comes_from_the_trusted_end_of_the_header(self):
        from types import SimpleNamespace

        from app.api.auth import _client_ip

        def req(xff=None, host="172.18.0.2"):
            headers = {"x-forwarded-for": xff} if xff else {}
            return SimpleNamespace(headers=headers, client=SimpleNamespace(host=host))

        assert _client_ip(req("1.1.1.1, 9.9.9.9")) == "9.9.9.9"          # leftmost (forgeable) is ignored
        assert _client_ip(req("9.9.9.9")) == "9.9.9.9"
        assert _client_ip(req(None)) == "172.18.0.2"                       # no proxy header: socket address

    def test_a_correct_login_resets_the_account_counter(self, client, users):
        for i in range(3):
            client.post("/auth/login", json={"email": "bob@example.com", "password": f"nope nope {i}"})
        assert client.post("/auth/login", json={"email": "bob@example.com", "password": "bobs password 3"}).status_code == 200
        for i in range(5):   # would exceed the limit if the earlier failures still counted
            assert client.post("/auth/login", json={"email": "bob@example.com", "password": f"bad bad {i}"}).status_code == 401

    def test_signup_attempts_per_address_are_limited(self, client):
        codes = [client.post("/auth/signup", json={"email": f"spam{i}@example.com", "password": "spam password 1"}).status_code
                 for i in range(12)]
        assert 429 in codes
        run_sql("DELETE FROM users WHERE email LIKE 'spam%@example.com'")

    def test_limiter_memory_is_bounded(self):
        from app.api.auth import SlidingWindowLimiter

        limiter = SlidingWindowLimiter(limit=3, window_seconds=60, max_keys=100)
        for i in range(1000):
            limiter.hit(f"attacker-{i}")
        assert len(limiter._events) <= 110

    def test_limiter_window_expires(self):
        from app.api.auth import SlidingWindowLimiter

        limiter = SlidingWindowLimiter(limit=2, window_seconds=1)
        limiter.hit("k"); limiter.hit("k")
        assert limiter.retry_after_minutes("k") is not None
        time.sleep(1.1)
        assert limiter.retry_after_minutes("k") is None


# ── Data isolation ───────────────────────────────────────────────────────────────────────────────

class TestIsolation:
    def test_first_user_adopts_legacy_data_second_does_not(self, client, users):
        alice = client.get("/documents", headers=users["alice"]).json()
        assert [d["filename"] for d in alice["documents"]] == ["legacy.txt"]
        assert client.get("/documents", headers=users["bob"]).json()["total"] == 0

    def test_cannot_delete_someone_elses_document(self, client, users):
        doc_id = client.get("/documents", headers=users["alice"]).json()["documents"][0]["document_id"]
        assert client.delete(f"/documents/{doc_id}", headers=users["bob"]).status_code == 404
        assert client.get("/documents", headers=users["alice"]).json()["total"] >= 1

    def test_retrieval_scope_only_ever_contains_own_documents(self, client, users):
        bob_doc = insert_document("bob_notes.txt", "h-bob", users["bob_id"])
        insert_document("proj/main.py", "h-proj", users["alice_id"])
        ids_a = set(client.get("/_scope", headers=users["alice"]).json()["ids"])
        ids_b = set(client.get("/_scope", headers=users["bob"]).json()["ids"])
        assert str(bob_doc) in ids_b and str(bob_doc) not in ids_a
        assert not ids_a & ids_b
        assert len(client.get("/_scope?kind=projects", headers=users["alice"]).json()["ids"]) == 1
        assert client.get("/_scope?kind=projects", headers=users["bob"]).json()["ids"] == []

    def test_sources_are_per_user(self, client, users):
        a = client.get("/projects/sources", headers=users["alice"]).json()
        b = client.get("/projects/sources", headers=users["bob"]).json()
        assert [p["name"] for p in a["projects"]] == ["proj"] and b["projects"] == []
        assert [d["filename"] for d in b["documents"]] == ["bob_notes.txt"]

    def test_conversations_belong_to_their_owner(self, client, users):
        conv = str(users["legacy_conv"])
        assert client.get(f"/_conv/{conv}", headers=users["alice"]).json()["id"] == conv
        assert client.get(f"/_conv/{conv}", headers=users["bob"]).json()["id"] != conv

    def test_same_file_uploaded_by_two_users_is_two_independent_documents(self, client, users):
        content = b"The quick brown fox jumps over the lazy dog. " * 20
        a = client.post("/upload", headers=users["alice"], files={"files": ("same.txt", content)}).json()
        b = client.post("/upload", headers=users["bob"], files={"files": ("same.txt", content)}).json()
        da, db = a["documents"][0], b["documents"][0]
        assert da["document_id"] != db["document_id"]
        assert da["status"] != "already_exists" and db["status"] != "already_exists"


class TestResumeIsolationAndGate:
    @pytest.fixture(scope="class")
    def seeded(self, client, users):
        rid, ok_gen, low_gen = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        run_sql("""INSERT INTO resumes (id, user_id, label, file_type, raw_text, profile, index_status, item_count, created_at)
                   VALUES ($1, $2, 'Alice resume', 'text', 'x', '{}'::jsonb, 'ready', 0, now())""", rid, users["alice_id"])
        run_sql("""INSERT INTO resume_generations (id, user_id, output_name, jd_text, ats_score, threshold, attempts,
                   released, pdf_compiled, breakdown, report, tex, created_at)
                   VALUES ($1, $2, 'alice_cv', 'jd', 90, 82, 1, true, false, '{}'::jsonb, '{}'::jsonb, 'TEX', now())""",
                ok_gen, users["alice_id"])
        run_sql("""INSERT INTO resume_generations (id, user_id, output_name, jd_text, ats_score, threshold, attempts,
                   released, pdf_compiled, breakdown, report, created_at)
                   VALUES ($1, $2, 'low', 'jd', 70, 82, 3, false, false, '{}'::jsonb, '{}'::jsonb, now())""",
                low_gen, users["alice_id"])
        return {"resume": rid, "released": ok_gen, "withheld": low_gen}

    def test_library_is_private(self, client, users, seeded):
        assert len(client.get("/resume/library", headers=users["alice"]).json()["resumes"]) == 1
        assert client.get("/resume/library", headers=users["bob"]).json()["resumes"] == []
        assert client.get(f"/resume/library/{seeded['resume']}", headers=users["bob"]).status_code == 404
        assert client.delete(f"/resume/library/{seeded['resume']}", headers=users["bob"]).status_code == 404
        assert len(client.get("/resume/library", headers=users["alice"]).json()["resumes"]) == 1

    def test_generations_are_private(self, client, users, seeded):
        gid = seeded["released"]
        assert client.get(f"/resume/generations/{gid}", headers=users["bob"]).status_code == 404
        assert client.get(f"/resume/generations/{gid}/tex", headers=users["bob"]).status_code == 404
        client.delete(f"/resume/generations/{gid}", headers=users["bob"])           # must not delete Alice's run
        assert client.get(f"/resume/generations/{gid}/tex", headers=users["alice"]).text == "TEX"

    def test_released_files_download_but_withheld_ones_never_do(self, client, users, seeded):
        low = seeded["withheld"]
        assert client.get(f"/resume/generations/{low}/tex", headers=users["alice"]).status_code == 403
        assert client.get(f"/resume/generations/{low}/pdf", headers=users["alice"]).status_code == 403
        assert client.get(f"/resume/generations/{low}", headers=users["alice"]).json()["tex"] is None

    def test_one_tailoring_run_at_a_time_per_user(self, client, users):
        from app.api import resume as resume_api

        resume_api._active_runs.add(users["bob_id"])
        try:
            r = client.post("/resume/tailor", headers=users["bob"], json={"jd_text": "x" * 120, "output_name": "cv"})
        finally:
            resume_api._active_runs.discard(users["bob_id"])
        assert "already have a resume run in progress" in r.text

    def test_daily_tailoring_limit(self, client, users):
        from app.config import get_settings

        limit = get_settings().RESUME_DAILY_LIMIT
        for _ in range(limit):
            run_sql("""INSERT INTO resume_generations (id, user_id, output_name, jd_text, ats_score, threshold, attempts,
                       released, pdf_compiled, breakdown, report, created_at)
                       VALUES ($1, $2, 'bulk', 'jd', 10, 82, 1, false, false, '{}'::jsonb, '{}'::jsonb, now())""",
                    uuid.uuid4(), users["bob_id"])
        r = client.post("/resume/tailor", headers=users["bob"], json={"jd_text": "x" * 120, "output_name": "cv"})
        assert "Daily limit reached" in r.text
        run_sql("DELETE FROM resume_generations WHERE output_name = 'bulk'")

    def test_resume_indexing_interrupted_by_a_restart_is_recovered(self, client, users):
        rid = uuid.uuid4()
        run_sql("""INSERT INTO resumes (id, user_id, label, file_type, raw_text, profile, index_status, item_count, created_at)
                   VALUES ($1, $2, 'stuck', 'text', 'x', '{}'::jsonb, 'pending', 0, now())""", rid, users["alice_id"])
        assert client.post("/_recover").json()["recovered"] >= 1
        for _ in range(40):
            status = run_sql("SELECT index_status FROM resumes WHERE id = $1", rid)[0]["index_status"]
            if status != "pending":
                break
            time.sleep(0.25)
        assert status in ("ready", "failed")                       # no longer stuck on "pending"


# ── Admin ────────────────────────────────────────────────────────────────────────────────────────

class TestAdmin:
    def test_only_the_first_account_is_admin(self, client, users):
        assert client.get("/collections", headers=users["alice"]).status_code == 200
        assert client.get("/collections", headers=users["bob"]).status_code == 403
        assert client.get("/collections").status_code in (401, 403)

    def test_registering_an_admins_email_does_not_confer_admin_rights(self, client, users):
        """Admin used to be decided by email address, which anyone could register first."""
        r = client.post("/auth/signup", json={"email": "admin@example.com", "password": "attacker pass 9"})
        assert r.status_code == 201
        token = auth_header(r.json()["token"])
        assert client.get("/collections", headers=token).status_code == 403


# ── Projects ─────────────────────────────────────────────────────────────────────────────────────

class TestProjects:
    @pytest.fixture(scope="class")
    def big_project(self, client, users):
        """150 files (more than one page of documents): 120 indexed, 20 processing, 10 failed."""
        rows = []
        for i in range(150):
            status = "COMPLETED" if i < 120 else "PARSING" if i < 140 else "FAILED"
            error = "AssertionError: boom" if status == "FAILED" else None
            rows.append((f"big/src/f{i:03}.py", f"hash-big-{i}", users["alice_id"], status, error))
        insert_documents_bulk(rows)
        return "big"

    def test_summary_counts_are_exact_beyond_one_page(self, client, users, big_project):
        projects = {p["name"]: p for p in client.get("/projects", headers=users["alice"]).json()["projects"]}
        big = projects["big"]
        assert (big["total"], big["indexed"], big["processing"], big["failed"]) == (150, 120, 20, 10)
        assert big["first_error"] == "AssertionError: boom"

    def test_summary_is_per_user(self, client, users, big_project):
        assert client.get("/projects", headers=users["bob"]).json()["projects"] == []

    def test_cannot_delete_someone_elses_project(self, client, users, big_project):
        assert client.delete("/projects/big", headers=users["bob"]).status_code == 404
        names = [p["name"] for p in client.get("/projects", headers=users["alice"]).json()["projects"]]
        assert "big" in names

    def test_delete_removes_every_file_in_one_call(self, client, users, big_project):
        r = client.delete("/projects/big", headers=users["alice"])
        assert r.status_code == 200 and r.json()["files"] == 150
        names = [p["name"] for p in client.get("/projects", headers=users["alice"]).json()["projects"]]
        assert "big" not in names
        assert client.delete("/projects/big", headers=users["alice"]).status_code == 404

    def test_project_name_with_wildcard_characters_matches_only_itself(self, client, users):
        insert_document("my_app/a.py", "h-w1", users["alice_id"])
        insert_document("myXapp/a.py", "h-w2", users["alice_id"])
        assert client.delete("/projects/my_app", headers=users["alice"]).json()["files"] == 1
        names = [p["name"] for p in client.get("/projects", headers=users["alice"]).json()["projects"]]
        assert "myXapp" in names


# ── Uploads ──────────────────────────────────────────────────────────────────────────────────────

class TestUploads:
    def test_upload_returns_immediately_and_processes_in_the_background(self, client, users):
        started = time.time()
        r = client.post("/upload", headers=users["alice"],
                        files={"files": ("bg.txt", b"A short document about background processing. " * 15)})
        assert r.status_code == 200
        doc = r.json()["documents"][0]
        assert doc["status"] == "pending" and doc["document_id"]
        assert time.time() - started < 5                          # did not wait for embedding

    def test_duplicates_are_reported_immediately(self, client, users):
        content = b"Duplicate detection should be instant. " * 15
        insert_document("dup.txt", hashlib.sha256(content).hexdigest(), users["alice_id"])
        r = client.post("/upload", headers=users["alice"], files={"files": ("dup.txt", content)})
        assert r.json()["documents"][0]["status"] == "already_exists"

    def test_documents_list_can_be_filtered_by_kind(self, client, users):
        insert_document("kind/x.py", "h-kind", users["alice_id"])
        docs = client.get("/documents?kind=documents&limit=100", headers=users["alice"]).json()["documents"]
        projects = client.get("/documents?kind=projects&limit=100", headers=users["alice"]).json()["documents"]
        assert all("/" not in d["filename"] for d in docs)
        assert projects and all("/" in d["filename"] for d in projects)

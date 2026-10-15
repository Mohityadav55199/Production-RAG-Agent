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

    async def run_ensure_admin():
        from app.services.accounts import ensure_admin

        await ensure_admin()
        return {"ok": True}

    app.add_api_route("/_scope", scope, methods=["GET"])
    app.add_api_route("/_conv/{conversation_id}", conv, methods=["GET"])
    app.add_api_route("/_recover", recover, methods=["POST"])
    app.add_api_route("/_ensure_admin", run_ensure_admin, methods=["POST"])


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Rate-limit state is per process; keep tests independent of each other."""
    from app.api import auth as auth_api

    for limiter in (auth_api._login_by_ip_email, auth_api._login_by_ip, auth_api._login_by_email,
                    auth_api._signup_by_ip, auth_api._login_by_peer, auth_api._signup_by_peer):
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

    @staticmethod
    def _req(headers=None, host="172.18.0.2"):
        from types import SimpleNamespace

        return SimpleNamespace(headers={k.lower(): v for k, v in (headers or {}).items()},
                               client=SimpleNamespace(host=host))

    def test_client_address_comes_from_the_trusted_end_of_the_header(self):
        from app.utils.client_ip import client_ip

        assert client_ip(self._req({"X-Forwarded-For": "1.1.1.1, 9.9.9.9"})) == "9.9.9.9"   # leftmost is forgeable
        assert client_ip(self._req({"X-Forwarded-For": "9.9.9.9"})) == "9.9.9.9"
        assert client_ip(self._req()) == "172.18.0.2"                                        # no header: socket address

    def test_number_of_trusted_proxy_hops_is_configurable(self, monkeypatch):
        from app.config import get_settings
        from app.utils.client_ip import client_ip

        monkeypatch.setattr(get_settings(), "TRUSTED_PROXY_HOPS", 2)
        header = {"X-Forwarded-For": "6.6.6.6, 1.2.3.4, 10.0.0.1"}     # forged, real client, first proxy
        assert client_ip(self._req(header)) == "1.2.3.4"

    def test_a_configured_client_ip_header_wins_when_present(self, monkeypatch):
        from app.config import get_settings
        from app.utils.client_ip import client_ip

        monkeypatch.setattr(get_settings(), "CLIENT_IP_HEADER", "CF-Connecting-IP")
        assert client_ip(self._req({"CF-Connecting-IP": "8.8.4.4", "X-Forwarded-For": "1.1.1.1, 9.9.9.9"})) == "8.8.4.4"
        assert client_ip(self._req({"X-Forwarded-For": "1.1.1.1, 9.9.9.9"})) == "9.9.9.9"   # header absent: falls back

    def test_admin_network_check_reports_what_the_server_sees(self, client, users):
        r = client.get("/admin/network", headers={**users["alice"], "X-Forwarded-For": "1.1.1.1, 9.9.9.9"})
        body = r.json()
        assert r.status_code == 200
        assert body["detected_client_ip"] == "9.9.9.9" and body["x_forwarded_for_entries"] == ["1.1.1.1", "9.9.9.9"]
        assert client.get("/admin/network", headers=users["bob"]).status_code == 403

    def test_a_correct_login_resets_the_account_counter(self, client, users):
        for i in range(3):
            client.post("/auth/login", json={"email": "bob@example.com", "password": f"nope nope {i}"})
        assert client.post("/auth/login", json={"email": "bob@example.com", "password": "bobs password 3"}).status_code == 200
        for i in range(5):   # would exceed the limit if the earlier failures still counted
            assert client.post("/auth/login", json={"email": "bob@example.com", "password": f"bad bad {i}"}).status_code == 401

    def test_the_owner_on_a_trusted_device_cannot_be_locked_out(self, client):
        """An attacker can exhaust the per-account cap, but never holds the owner's device token."""
        email, password = "dana@example.com", "dana password 1"
        signup = client.post("/auth/signup", json={"email": email, "password": password}).json()
        device = signup["device"]
        for i in range(12):                                         # attacker rotating addresses
            client.post("/auth/login", headers={"X-Forwarded-For": f"10.2.0.{i}"},
                        json={"email": email, "password": f"attacker guess {i}"})
        locked = client.post("/auth/login", headers={"X-Forwarded-For": "10.2.1.1"},
                             json={"email": email, "password": password})
        assert locked.status_code == 429                            # a stranger is locked out, even with the right password
        owner = client.post("/auth/login", headers={"X-Forwarded-For": "10.2.1.2"},
                            json={"email": email, "password": password, "device": device})
        assert owner.status_code == 200                             # the owner's usual device still works
        run_sql("DELETE FROM users WHERE email = $1", email)

    def test_a_device_token_only_helps_its_own_account(self, client, users):
        other = client.post("/auth/signup", json={"email": "erin@example.com", "password": "erin password 1"}).json()
        email = "frank@example.com"
        client.post("/auth/signup", json={"email": email, "password": "frank password 1"})
        for i in range(12):
            client.post("/auth/login", headers={"X-Forwarded-For": f"10.3.0.{i}"},
                        json={"email": email, "password": f"guess {i}"})
        r = client.post("/auth/login", headers={"X-Forwarded-For": "10.3.1.1"},
                        json={"email": email, "password": "frank password 1", "device": other["device"]})
        assert r.status_code == 429
        run_sql("DELETE FROM users WHERE email IN ('erin@example.com', $1)", email)

    def test_trusted_devices_are_still_limited_per_address(self, client):
        email = "gina@example.com"
        device = client.post("/auth/signup", json={"email": email, "password": "gina password 1"}).json()["device"]
        codes = [client.post("/auth/login", headers={"X-Forwarded-For": "10.4.0.1"},
                             json={"email": email, "password": f"bad {i}", "device": device}).status_code
                 for i in range(8)]
        assert codes.count(401) == 6 and 429 in codes                # a stolen device token is not a free pass
        run_sql("DELETE FROM users WHERE email = $1", email)

    def test_device_and_session_tokens_are_not_interchangeable(self, client, users):
        device = client.post("/auth/login", json={"email": "alice@example.com", "password": "correct horse 1"}).json()["device"]
        assert client.get("/documents", headers=auth_header(device)).status_code == 401
        session = users["alice"]["Authorization"].split(" ", 1)[1]
        r = client.post("/auth/login", headers={"X-Forwarded-For": "10.5.0.1"},
                        json={"email": "alice@example.com", "password": "wrong password 1", "device": session})
        assert r.status_code == 401                                  # a session token is not a device token

    @pytest.fixture
    def behind_vercel(self, monkeypatch):
        """Production topology: browser -> Vercel -> Cloudflare -> Render."""
        from app.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "CLIENT_IP_HEADER", "cf-connecting-ip")
        monkeypatch.setattr(settings, "FRONTEND_FORWARDS_CLIENT_IP", True)

    @staticmethod
    def _via_vercel(visitor_ip: str) -> dict:
        # cf-connecting-ip is Vercel's server: identical for every visitor
        return {"cf-connecting-ip": "65.2.144.101", "forwarded": f"for={visitor_ip};host=site;proto=https"}

    def test_visitors_behind_the_frontend_proxy_do_not_share_a_rate_limit_bucket(self, client, behind_vercel):
        noisy = [client.post("/auth/login", headers=self._via_vercel("8.8.8.8"),
                             json={"email": "noisy@example.com", "password": f"guess {i}"}).status_code
                 for i in range(8)]
        assert noisy.count(401) == 6 and 429 in noisy                    # the noisy visitor is limited...
        calm = client.post("/auth/login", headers=self._via_vercel("1.1.1.1"),
                           json={"email": "calm@example.com", "password": "wrong"})
        assert calm.status_code == 401                                   # ...and a different visitor is not affected

    def test_per_visitor_ip_flood_limit_is_per_visitor_not_global(self, client, behind_vercel):
        for i in range(30):                                              # one visitor, many accounts
            client.post("/auth/login", headers=self._via_vercel("8.8.8.8"),
                        json={"email": f"user{i}@example.com", "password": "wrong"})
        blocked = client.post("/auth/login", headers=self._via_vercel("8.8.8.8"),
                              json={"email": "another@example.com", "password": "wrong"})
        other = client.post("/auth/login", headers=self._via_vercel("1.1.1.1"),
                            json={"email": "another@example.com", "password": "wrong"})
        assert blocked.status_code == 429 and other.status_code == 401

    def test_forging_the_visitor_address_cannot_get_around_the_origin_limit(self, client, behind_vercel, monkeypatch):
        """Calling the backend directly lets you forge the forwarded address, but not the connecting one."""
        from app.api import auth as auth_api

        monkeypatch.setattr(auth_api._login_by_peer, "limit", 5)
        codes = [client.post("/auth/login", headers=self._via_vercel(f"8.8.{i}.{i + 1}"),
                             json={"email": f"forger{i}@example.com", "password": "wrong"}).status_code
                 for i in range(8)]
        assert codes.count(401) == 5 and codes.count(429) == 3, codes

    def test_signup_flood_with_forged_visitor_addresses_hits_the_origin_limit(self, client, behind_vercel, monkeypatch):
        from app.api import auth as auth_api

        monkeypatch.setattr(auth_api._signup_by_peer, "limit", 3)
        codes = [client.post("/auth/signup", headers=self._via_vercel(f"9.9.{i}.{i + 1}"),
                             json={"email": f"flood{i}@example.com", "password": "flood password 1"}).status_code
                 for i in range(5)]
        assert codes.count(201) == 3 and codes.count(429) == 2, codes
        run_sql("DELETE FROM users WHERE email LIKE 'flood%@example.com'")

    def test_network_check_with_the_production_headers(self, client, users, behind_vercel):
        headers = {**users["alice"],
                   "x-forwarded-for": "220.158.168.162,65.2.144.101, 172.71.198.72, 10.27.213.240",
                   "cf-connecting-ip": "65.2.144.101",
                   "forwarded": "for=220.158.168.162;host=production-rag-agent.onrender.com;proto=https"}
        body = client.get("/admin/network", headers=headers).json()
        assert body["detected_client_ip"] == "220.158.168.162" and body["peer_ip"] == "65.2.144.101"
        assert "consistent" in body["notes"][0]

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


class TestQuestions:
    def test_question_is_saved_before_the_answer_and_errors_stay_generic(self, client, users, monkeypatch):
        import app.api.query as query_api

        async def failing_stream(**kwargs):
            raise RuntimeError("could not reach postgresql://admin:hunter2@db.internal/rag")
            yield  # pragma: no cover - makes this an async generator

        monkeypatch.setattr(query_api, "stream_rag", failing_stream)
        res = client.post("/query", headers=users["bob"], json={"query": "what does the report say?"})
        assert res.status_code == 200
        assert "hunter2" not in res.text and "Something went wrong" in res.text
        assert "access-control-allow-origin" not in {k.lower() for k in res.headers}

        rows = run_sql(
            "SELECT m.role, m.content FROM messages m JOIN conversations c ON c.id = m.conversation_id "
            "WHERE c.user_id = $1",
            users["bob_id"],
        )
        # Counted toward the daily quota even though no answer was produced
        assert [(r["role"], r["content"]) for r in rows] == [("user", "what does the report say?")]

    def test_unanswered_questions_are_left_out_of_history(self, client, users):
        from app.main import app
        from app.services.conversation_service import (
            get_or_create_conversation, load_history, save_answer, save_question,
        )

        async def history_route():
            conv = await get_or_create_conversation(None, users["alice_id"])
            await save_question(conv, "first question")       # its answer never arrived
            await save_question(conv, "second question")
            await save_answer(conv, "second answer")
            return [m.content for m in await load_history(conv)]

        app.add_api_route("/_history_check", history_route, methods=["GET"])
        assert client.get("/_history_check").json() == ["second question", "second answer"]


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

    def test_a_run_with_no_compiled_file_has_nothing_to_download(self, client, users, seeded):
        low = seeded["withheld"]
        assert client.get(f"/resume/generations/{low}/tex", headers=users["alice"]).status_code == 404
        assert client.get(f"/resume/generations/{low}/pdf", headers=users["alice"]).status_code == 404
        detail = client.get(f"/resume/generations/{low}", headers=users["alice"]).json()
        assert detail["tex"] is None and detail["below_threshold"] is True and detail["editable"] is False

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
    def test_without_configuration_only_the_first_account_is_admin(self, client, users):
        assert client.get("/collections", headers=users["alice"]).status_code == 200
        assert client.get("/collections", headers=users["bob"]).status_code == 403
        assert client.get("/collections").status_code in (401, 403)
        assert client.get("/auth/me", headers=users["alice"]).json()["is_admin"] is True
        assert client.get("/auth/me", headers=users["bob"]).json()["is_admin"] is False

    def test_registering_an_admins_email_does_not_confer_admin_rights(self, client, users):
        """Admin used to be decided by email address, which anyone could register first."""
        r = client.post("/auth/signup", json={"email": "admin@example.com", "password": "attacker pass 9"})
        assert r.status_code == 201
        token = auth_header(r.json()["token"])
        assert client.get("/collections", headers=token).status_code == 403


class TestConfiguredAdmin:
    """ADMIN_EMAIL + ADMIN_PASSWORD make that account the one and only administrator."""

    @pytest.fixture(autouse=True)
    def _restore(self, client, users):
        from app.config import get_settings

        settings = get_settings()
        before = (settings.ADMIN_EMAIL, settings.ADMIN_PASSWORD)
        yield settings
        settings.ADMIN_EMAIL, settings.ADMIN_PASSWORD = before
        run_sql("DELETE FROM users WHERE email IN ('boss@example.com', 'owner@example.com')")
        run_sql("UPDATE users SET is_admin = (email = 'alice@example.com')")   # back to the baseline

    @staticmethod
    def _configure(settings, email, password, client):
        settings.ADMIN_EMAIL, settings.ADMIN_PASSWORD = email, password
        assert client.post("/_ensure_admin").status_code == 200

    @staticmethod
    def _login(client, email, password):
        return client.post("/auth/login", headers={"X-Forwarded-For": "10.9.0.1"},
                           json={"email": email, "password": password})

    def test_creates_the_account_and_makes_it_the_only_admin(self, client, users, _restore):
        self._configure(_restore, "Boss@Example.com", "boss password 1", client)
        r = self._login(client, "boss@example.com", "boss password 1")
        assert r.status_code == 200 and r.json()["user"]["is_admin"] is True
        boss = auth_header(r.json()["token"])
        assert client.get("/auth/me", headers=boss).json()["is_admin"] is True
        assert client.get("/collections", headers=boss).status_code == 200
        assert client.get("/admin/network", headers=boss).status_code == 200
        assert client.get("/collections", headers=users["alice"]).status_code == 403     # previous admin demoted
        assert client.get("/auth/me", headers=users["alice"]).json()["is_admin"] is False

    def test_the_admin_is_also_a_normal_user_with_private_data(self, client, users, _restore):
        self._configure(_restore, "boss@example.com", "boss password 1", client)
        boss = auth_header(self._login(client, "boss@example.com", "boss password 1").json()["token"])
        assert client.get("/documents", headers=boss).json()["total"] == 0
        assert client.get("/resume/library", headers=boss).json()["resumes"] == []

    def test_the_address_cannot_be_registered_through_the_form_afterwards(self, client, users, _restore):
        self._configure(_restore, "boss@example.com", "boss password 1", client)
        r = client.post("/auth/signup", json={"email": "boss@example.com", "password": "attacker pass 9"})
        assert r.status_code == 409

    def test_rerunning_is_harmless_and_a_new_password_replaces_the_old_one(self, client, users, _restore):
        self._configure(_restore, "boss@example.com", "boss password 1", client)
        self._configure(_restore, "boss@example.com", "boss password 1", client)
        assert self._login(client, "boss@example.com", "boss password 1").status_code == 200
        self._configure(_restore, "boss@example.com", "new boss password 2", client)
        assert self._login(client, "boss@example.com", "boss password 1").status_code == 401
        assert self._login(client, "boss@example.com", "new boss password 2").status_code == 200
        assert run_sql("SELECT count(*) AS n FROM users WHERE is_admin")[0]["n"] == 1

    def test_an_account_registered_by_someone_else_is_taken_over_not_trusted(self, client, users, _restore):
        """If an attacker registered the admin's address first, the configured password takes the account back."""
        squatter = client.post("/auth/signup", json={"email": "owner@example.com", "password": "squatter pass 1"})
        assert squatter.status_code == 201 and squatter.json()["user"]["is_admin"] is False
        self._configure(_restore, "owner@example.com", "real owner pass 1", client)
        assert self._login(client, "owner@example.com", "squatter pass 1").status_code == 401
        assert self._login(client, "owner@example.com", "real owner pass 1").json()["user"]["is_admin"] is True

    def test_an_email_without_a_password_changes_nothing(self, client, users, _restore):
        """Promoting an account that anyone could have registered is exactly the hijack to avoid."""
        client.post("/auth/signup", json={"email": "owner@example.com", "password": "squatter pass 1"})
        self._configure(_restore, "owner@example.com", "", client)
        me = client.post("/auth/login", headers={"X-Forwarded-For": "10.9.0.2"},
                         json={"email": "owner@example.com", "password": "squatter pass 1"}).json()
        assert me["user"]["is_admin"] is False
        assert client.get("/auth/me", headers=users["alice"]).json()["is_admin"] is True

    def test_a_weak_admin_password_is_rejected_and_ignored(self, client, users, _restore):
        self._configure(_restore, "boss@example.com", "short", client)
        assert run_sql("SELECT count(*) AS n FROM users WHERE email = 'boss@example.com'")[0]["n"] == 0
        assert client.get("/auth/me", headers=users["alice"]).json()["is_admin"] is True


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


class TestResumeEditing:
    """The editable draft: review data, downloads below the gate, re-scoring and bullet suggestions."""

    JD = {"title": "Backend Engineer", "company": "Initech", "seniority": "mid",
          "must_have": ["Python", "FastAPI", "Kubernetes"], "nice_to_have": ["React"], "responsibilities": []}

    @pytest.fixture(scope="class")
    def seeded(self, client, users):
        import json

        from tests.sample_data import LIBRARY_CORPUS, LIBRARY_PROFILE

        resume, gen = uuid.uuid4(), uuid.uuid4()
        run_sql("""INSERT INTO resumes (id, user_id, label, file_type, raw_text, profile, index_status, item_count, created_at)
                   VALUES ($1, $2, 'Asha', 'text', $3, $4::jsonb, 'ready', 0, now())""",
                resume, users["alice_id"], LIBRARY_CORPUS, json.dumps(LIBRARY_PROFILE))
        stored = {"jd": self.JD, "warnings": [], "compile_error": "", "draft": LIBRARY_PROFILE,
                  "ai_draft": LIBRARY_PROFILE, "options": {"template": "classic", "font_pt": 10, "margin_in": 0.6},
                  "resume_ids": [str(resume)]}
        breakdown = {"total": 70, "has_jd": True, "pdf_checked": False, "matched": [], "fixes": [],
                     "missing_must": ["Kubernetes"], "missing_nice": [],
                     "components": [{"key": "keywords", "label": "Keyword match", "score": 60, "weight": 50,
                                     "details": "", "findings": []}]}
        run_sql("""INSERT INTO resume_generations (id, user_id, output_name, jd_text, ats_score, threshold, attempts,
                   released, pdf_compiled, breakdown, report, tex, pdf, created_at)
                   VALUES ($1, $2, 'asha_cv', 'jd text', 70, 82, 3, false, true, $3::jsonb, $4::jsonb, 'LOWTEX', $5, now())""",
                gen, users["alice_id"], json.dumps(breakdown), json.dumps(stored), b"%PDF-below-gate")
        return {"gen": gen, "profile": LIBRARY_PROFILE}

    def test_detail_carries_the_draft_sources_and_gap_report(self, client, users, seeded):
        d = client.get(f"/resume/generations/{seeded['gen']}", headers=users["alice"]).json()
        assert d["editable"] and d["below_threshold"] and d["tex"] == "LOWTEX"
        assert d["draft"]["name"] == "Asha Verma" and d["ai_draft"] == d["draft"]
        assert d["options"]["template"] == "classic"
        assert {b["status"] for b in d["annotated"]["experience"][0]["bullets"]} == {"original"}
        assert d["gap"]["lacking_must"] == ["Kubernetes"]
        assert d["gap"]["score"] <= d["gap"]["with_lacking_score"] <= 100

    def test_a_draft_below_the_gate_downloads_like_any_other(self, client, users, seeded):
        r = client.get(f"/resume/generations/{seeded['gen']}/pdf", headers=users["alice"])
        assert r.status_code == 200 and r.content == b"%PDF-below-gate"
        assert client.get(f"/resume/generations/{seeded['gen']}/tex", headers=users["alice"]).text == "LOWTEX"

    def test_editing_endpoints_are_private(self, client, users, seeded):
        gid = seeded["gen"]
        assert client.get(f"/resume/generations/{gid}", headers=users["bob"]).status_code == 404
        assert client.post(f"/resume/generations/{gid}/rescore", headers=users["bob"],
                           json={"draft": seeded["profile"]}).status_code == 404
        assert client.post(f"/resume/generations/{gid}/regenerate-bullet", headers=users["bob"],
                           json={"kind": "experience", "name": "Acme"}).status_code == 404

    def test_rescore_saves_the_edit_and_the_new_score(self, client, users, seeded, monkeypatch):
        from app.api import resume as resume_api

        captured = {}

        async def fake_score(profile, options, jd, jd_text, with_fit=True):
            captured["bullets"], captured["template"] = profile.experience[0].bullets, options.template
            return {"score": 90, "tex": "NEWTEX", "pdf": b"%PDF-new", "warnings": [], "compile_error": "",
                    "compile_failed": False,
                    "report": {"total": 90, "has_jd": True, "pdf_checked": True, "matched": ["Python"], "fixes": [],
                               "missing_must": [], "missing_nice": [], "components": []}}

        monkeypatch.setattr(resume_api, "score_profile", fake_score)
        draft = {**seeded["profile"]}
        draft["experience"] = [{**draft["experience"][0], "bullets": [
            "Built REST APIs with FastAPI serving 50k requests/day and cutting latency by 35%."]}]
        r = client.post(f"/resume/generations/{seeded['gen']}/rescore", headers=users["alice"],
                        json={"draft": draft, "options": {"template": "compact", "font_pt": 11, "margin_in": 0.5}})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ats_score"] == 90 and d["released"] is True and d["below_threshold"] is False
        assert d["tex"] == "NEWTEX" and d["options"]["template"] == "compact" and captured["template"] == "compact"
        assert len(captured["bullets"]) == 1 and d["draft"]["experience"][0]["bullets"] == captured["bullets"]
        assert len(d["ai_draft"]["experience"][0]["bullets"]) == 4                  # the AI's original is kept
        assert client.get(f"/resume/generations/{seeded['gen']}/pdf", headers=users["alice"]).content == b"%PDF-new"

    def test_rescore_rejects_an_oversized_draft(self, client, users, seeded):
        draft = {**seeded["profile"]}
        draft["experience"] = [{**draft["experience"][0], "bullets": ["x"] * 11}]
        r = client.post(f"/resume/generations/{seeded['gen']}/rescore", headers=users["alice"], json={"draft": draft})
        assert r.status_code == 422

    def test_regenerate_returns_options_and_refuses_unknown_items(self, client, users, seeded, monkeypatch):
        from app.api import resume as resume_api

        seen = {}

        async def fake_regen(sources, jd, corpus, current="", already_used=None, instruction=""):
            seen.update(sources=sources, current=current, instruction=instruction)
            return [{"text": "Built FastAPI APIs.", "source": sources[0]}]

        monkeypatch.setattr(resume_api, "regenerate_bullet", fake_regen)
        ok = client.post(f"/resume/generations/{seeded['gen']}/regenerate-bullet", headers=users["alice"],
                         json={"kind": "experience", "name": "Acme", "current": "old", "instruction": "shorter"})
        assert ok.status_code == 200 and ok.json()["options"][0]["text"] == "Built FastAPI APIs."
        assert seen["sources"] == seeded["profile"]["experience"][0]["bullets"] and seen["instruction"] == "shorter"
        nope = client.post(f"/resume/generations/{seeded['gen']}/regenerate-bullet", headers=users["alice"],
                           json={"kind": "experience", "name": "Globex"})
        assert nope.status_code == 422 and "without inventing facts" in nope.json()["detail"]


def test_root_says_the_api_is_running(client):
    res = client.get("/")
    assert res.status_code == 200
    assert res.json()["status"] == "running" and res.json()["health"] == "/health"

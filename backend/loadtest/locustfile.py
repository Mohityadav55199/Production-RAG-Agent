"""Load test for the RAG API (Locust).

Simulates people who sign in, check health and ask questions over the streaming /query endpoint. It records, for
every question, the time to the first streamed token (what a user feels) as well as the total time.

Run it against a LOCAL backend, not the Render free tier (see the guard below):

    # 1. Start the API with the per-user daily limit switched off, otherwise users hit it after 100 questions
    QUERY_DAILY_LIMIT=0 UPLOAD_DAILY_LIMIT=0 uvicorn app.main:app --port 8000

    # 2. Upload a few documents once (the demo seed script does this: scripts/seed_demo.py)

    # 3. Run the test: headless, 10 simulated users, 2 minutes
    pip install -r loadtest/requirements.txt
    locust -f loadtest/locustfile.py --host http://localhost:8000 --headless -u 10 -r 2 -t 2m --csv loadtest/results/run

    # or with the web UI on http://localhost:8089
    locust -f loadtest/locustfile.py --host http://localhost:8000

Environment variables:
    LOADTEST_USERS         number of test accounts to create and share (default 5; signup is limited to 10/hour per IP)
    LOADTEST_PASSWORD      password for the test accounts
    LOADTEST_ALLOW_REMOTE  set to 1 to allow a non-local host (do not point this at the Render free tier)
"""

import itertools
import json
import os
import random
import time
import uuid

from locust import HttpUser, between, events, task

QUESTIONS = [
    "What is the remote work policy?",
    "How does the backend stream answers to the frontend?",
    "What is the maximum upload size?",
    "How are passwords stored?",
    "What happens when the primary model is rate limited?",
    "How is a document chunked before it is embedded?",
    "Which roles can see usage statistics?",
]

PASSWORD = os.environ.get("LOADTEST_PASSWORD", "LoadTest-Password-1")
POOL_SIZE = int(os.environ.get("LOADTEST_USERS", "5"))
RUN_ID = uuid.uuid4().hex[:8]
_accounts = itertools.cycle([f"loadtest-{RUN_ID}-{i}@example.com" for i in range(POOL_SIZE)])


@events.init.add_listener
def refuse_remote_hosts(environment, **_kwargs):
    """Never hammer a deployed free-tier instance by accident: it burns the monthly hours and the model quota."""
    host = (environment.host or "").lower()
    local = any(part in host for part in ("localhost", "127.0.0.1", "0.0.0.0"))
    if host and not local and os.environ.get("LOADTEST_ALLOW_REMOTE") != "1":
        raise SystemExit(
            f"Refusing to load test {environment.host}. Run the API locally, or set LOADTEST_ALLOW_REMOTE=1 "
            "if you really mean it (never against the Render free tier)."
        )


class RagUser(HttpUser):
    wait_time = between(2, 6)   # a person reads the answer before asking again

    def on_start(self) -> None:
        self.email = next(_accounts)
        body = {"email": self.email, "password": PASSWORD}
        with self.client.post("/auth/signup", json=body, name="/auth/signup", catch_response=True) as res:
            if res.status_code == 409:       # another simulated user already created this account
                res.success()
                res = self.client.post("/auth/login", json=body, name="/auth/login")
            elif res.status_code != 201:
                res.failure(f"signup failed: {res.status_code} {res.text[:120]}")
                return
        self.client.headers["Authorization"] = f"Bearer {res.json()['token']}"
        self.conversation_id: str | None = None

    @task(1)
    def health(self) -> None:
        self.client.get("/health", name="/health")

    @task(1)
    def list_documents(self) -> None:
        self.client.get("/documents", name="/documents")

    @task(6)
    def ask_question(self) -> None:
        payload = {
            "query": random.choice(QUESTIONS),
            "answer_style": "concise",
            "top_k": 5,
            "conversation_id": self.conversation_id,
        }
        started = time.perf_counter()
        first_token_ms = None
        failure = None
        with self.client.post("/query", json=payload, stream=True, name="/query (total)", catch_response=True) as res:
            if res.status_code != 200:
                res.failure(f"HTTP {res.status_code}: {res.text[:120]}")
                return
            for line in res.iter_lines():
                if not line or not line.startswith(b"data:"):
                    continue
                data = line[5:].strip()
                if data == b"[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                kind = event.get("type")
                if kind == "chunk" and first_token_ms is None:
                    first_token_ms = (time.perf_counter() - started) * 1000
                elif kind == "done":
                    self.conversation_id = event.get("conversation_id") or self.conversation_id
                elif kind == "error":
                    failure = event.get("message", "stream error")
            if failure:
                res.failure(failure)
            elif first_token_ms is None:
                res.failure("stream ended without an answer")
            else:
                res.success()

        if first_token_ms is not None:
            # Reported as its own row so the CSV shows time-to-first-token separately from total time
            events.request.fire(
                request_type="SSE", name="/query (first token)", response_time=first_token_ms,
                response_length=0, exception=None, context={},
            )

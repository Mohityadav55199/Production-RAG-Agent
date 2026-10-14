"""
Image features through the real API on a real database, with Gemini and the embedding service replaced by
fakes (no network): the image library, figures from documents, questions about attached images, and
reading code from screenshots.
"""

import json
import time
import uuid

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from pydantic import Field

from app.services import vision
from app.services.parsers import figures
from app.utils.rate_limit import SlidingWindowLimiter
from tests.conftest import auth_header, requires_db, run_sql
from tests.images import SENTENCE, b64, encoded, pdf_with_images, png

pytestmark = requires_db

VECTOR = [1.0] + [0.0] * 3071          # every text embeds to the same vector, so everything matches everything


# ── fakes ────────────────────────────────────────────────────────────────────────────────────────

class RecordingChat(GenericFakeChatModel):
    """A chat model that streams a canned answer and remembers every message list it was given."""

    seen: list = Field(default_factory=list)

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        yield from super()._stream(messages, stop=stop, run_manager=run_manager, **kwargs)


def make_chat(answer="The chart shows steady growth."):
    return RecordingChat(messages=iter([AIMessage(content=answer)]))


def sse_events(response) -> list[dict]:
    events = []
    for line in response.text.splitlines():
        if line.startswith("data:") and line.strip() != "data: [DONE]":
            events.append(json.loads(line[5:]))
    return events


@pytest.fixture(autouse=True)
def _isolation(monkeypatch):
    from app.api import auth as auth_api

    for limiter in (auth_api._login_by_ip_email, auth_api._login_by_ip, auth_api._login_by_email,
                    auth_api._signup_by_ip, auth_api._login_by_peer, auth_api._signup_by_peer):
        limiter._events.clear()
    monkeypatch.setattr(vision, "_quota", SlidingWindowLimiter(limit=100, window_seconds=3600))
    yield


@pytest.fixture
def fakes(monkeypatch):
    """No network: embeddings are constant vectors, and image captions/OCR are canned."""
    async def fake_embed(texts, task_type="RETRIEVAL_DOCUMENT"):
        return [VECTOR for _ in texts]

    monkeypatch.setattr("app.services.document_service.embed_batch_with_retry", fake_embed)
    monkeypatch.setattr("app.services.retrieval_service.embed_batch_with_retry", fake_embed)
    monkeypatch.setattr(figures, "describe_image_sync", lambda jpeg, hint="": "Revenue by region bar chart")
    monkeypatch.setattr("app.services.parsers.image_parser.describe_image_sync",
                        lambda jpeg, hint="": "A bar chart of unit sales")

    from app.services.parsers.factory import _parsers

    monkeypatch.setattr(_parsers["image"], "ocr_service",
                        type("OCR", (), {"extract_text": lambda self, img: ("Total: 42 units", "fake-ocr")})())
    monkeypatch.setattr(_parsers["pdf"], "ocr_service",
                        type("OCR", (), {"extract_text": lambda self, img: ("", "fake-ocr")})())


@pytest.fixture
def vision_on(monkeypatch, fakes):
    """Pretend a Gemini key exists and route image requests to a recording fake. Returns the fake."""
    chat = make_chat()
    for target in ("app.api.query.vision_available", "app.services.rag_graph.vision_available",
                   "app.api.compare.vision_available"):
        monkeypatch.setattr(target, lambda: True)
    monkeypatch.setattr("app.services.rag_graph.vision_chat_model", lambda streaming=False: chat)
    return chat


@pytest.fixture(scope="module")
def people(client):
    tag = uuid.uuid4().hex[:8]
    out = {}
    for name in ("ann", "ben"):
        r = client.post("/auth/signup", json={"email": f"img.{name}.{tag}@example.com", "password": f"{name} password 1"})
        assert r.status_code == 201, r.text
        out[name] = auth_header(r.json()["token"])
        out[f"{name}_id"] = r.json()["user"]["id"]
    return out


def upload_and_wait(client, headers, filename, content, timeout=40):
    r = client.post("/upload", headers=headers, files={"files": (filename, content)})
    assert r.status_code == 200, r.text
    doc_id = r.json()["documents"][0]["document_id"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        docs = client.get("/documents?limit=100", headers=headers).json()["documents"]
        doc = next(d for d in docs if d["document_id"] == doc_id)
        if doc["status"] in ("completed", "failed"):
            assert doc["status"] == "completed", doc.get("error")
            return doc
        time.sleep(0.3)
    raise AssertionError("document did not finish processing")


def insert_asset(document_id, user_id, display: bytes, thumb: bytes, kind="figure", page=1) -> uuid.UUID:
    asset_id = uuid.uuid4()
    run_sql(
        """INSERT INTO document_assets (id, document_id, user_id, kind, page_number, position, width, height, mime,
           display, thumb, created_at) VALUES ($1,$2,$3,$4,$5,0,200,120,'image/jpeg',$6,$7,now())""",
        asset_id, document_id, user_id, kind, page, display, thumb,
    )
    return asset_id


# ── the image endpoint ───────────────────────────────────────────────────────────────────────────

class TestAssetsEndpoint:
    @pytest.fixture
    def asset(self, client, people):
        doc = run_sql("""INSERT INTO documents (id, filename, file_size, file_hash, user_id, status, chunk_count, page_count,
                         total_chunks, embedded_chunks, failed_chunks, file_type, parser_used, ocr_used, extraction_method,
                         created_at, updated_at)
                         VALUES (gen_random_uuid(), 'a.pdf', 1, $1, $2, 'COMPLETED', 1, 1, 1, 1, 0, 'pdf', 'x', false,
                         'native', now(), now()) RETURNING id""", uuid.uuid4().hex, people["ann_id"])[0]["id"]
        display, thumb = encoded("JPEG", 300, 200), encoded("JPEG", 100, 60)
        return insert_asset(doc, people["ann_id"], display, thumb), display, thumb

    def test_the_owner_gets_the_image_with_safe_headers(self, client, people, asset):
        asset_id, display, thumb = asset
        r = client.get(f"/assets/{asset_id}", headers=people["ann"])
        assert r.status_code == 200 and r.content == display
        assert r.headers["content-type"] == "image/jpeg"
        assert r.headers["x-content-type-options"] == "nosniff" and "private" in r.headers["cache-control"]
        assert client.get(f"/assets/{asset_id}?size=thumb", headers=people["ann"]).content == thumb

    def test_other_users_and_anonymous_visitors_cannot_see_it(self, client, people, asset):
        asset_id, _, _ = asset
        assert client.get(f"/assets/{asset_id}", headers=people["ben"]).status_code == 404
        assert client.get(f"/assets/{asset_id}").status_code == 401

    def test_bad_requests(self, client, people, asset):
        asset_id, _, _ = asset
        assert client.get(f"/assets/{asset_id}?size=huge", headers=people["ann"]).status_code == 422
        assert client.get(f"/assets/{uuid.uuid4()}", headers=people["ann"]).status_code == 404
        assert client.get("/assets/not-a-uuid", headers=people["ann"]).status_code == 422


# ── image library ────────────────────────────────────────────────────────────────────────────────

class TestImageLibrary:
    def test_an_uploaded_image_is_indexed_with_a_thumbnail_that_only_its_owner_can_see(self, client, people, fakes):
        doc = upload_and_wait(client, people["ann"], "sales.png", png(400, 300))
        assert doc["preview_asset_id"]
        thumb = client.get(f"/assets/{doc['preview_asset_id']}?size=thumb", headers=people["ann"])
        assert thumb.status_code == 200 and thumb.content[:2] == b"\xff\xd8"
        assert client.get(f"/assets/{doc['preview_asset_id']}", headers=people["ben"]).status_code == 404
        assert [d["preview_asset_id"] for d in client.get("/documents?limit=100", headers=people["ben"]).json()["documents"]
                if d["preview_asset_id"]] == []

    def test_questions_find_the_image_and_the_answer_carries_its_thumbnail(self, client, people, fakes, monkeypatch):
        doc = upload_and_wait(client, people["ann"], "q3_chart.png", png(420, 320))
        monkeypatch.setattr("app.services.rag_graph._build_llm", lambda state=None: make_chat("It shows unit sales."))
        r = client.post("/query", headers=people["ann"], json={"query": "which chart shows unit sales?"})
        sources = next(e for e in sse_events(r) if e["type"] == "sources")["sources"]
        mine = [s for s in sources if s["filename"] == "q3_chart.png"]
        assert mine and mine[0]["images"] == [doc["preview_asset_id"]]
        assert "A bar chart of unit sales" in mine[0]["text_snippet"] and "Total: 42 units" in mine[0]["text_snippet"]

    def test_deleting_the_document_deletes_its_images(self, client, people, fakes):
        doc = upload_and_wait(client, people["ann"], "temp_image.png", png(380, 300))
        asset_id = doc["preview_asset_id"]
        assert client.delete(f"/documents/{doc['document_id']}", headers=people["ann"]).status_code == 200
        assert client.get(f"/assets/{asset_id}", headers=people["ann"]).status_code == 404
        assert run_sql("SELECT count(*) AS n FROM document_assets WHERE id = $1", uuid.UUID(asset_id))[0]["n"] == 0

    def test_a_file_that_is_not_an_image_is_rejected_cleanly(self, client, people, fakes):
        r = client.post("/upload", headers=people["ann"], files={"files": ("fake.png", b"this is not a png at all")})
        assert r.status_code in (400, 415)


# ── figures from documents ───────────────────────────────────────────────────────────────────────

class TestDocumentFigures:
    def test_a_figure_is_shown_with_sources_from_its_page_only(self, client, people, fakes, monkeypatch):
        pdf = pdf_with_images([
            {"text": SENTENCE * 25},
            {"text": SENTENCE * 25, "images": [png(420, 320)]},
        ])
        upload_and_wait(client, people["ann"], "annual_report.pdf", pdf)
        monkeypatch.setattr("app.services.rag_graph._build_llm", lambda state=None: make_chat("Revenue grew."))
        r = client.post("/query", headers=people["ann"], json={"query": "how did revenue develop?", "top_k": 20})
        sources = [s for s in next(e for e in sse_events(r) if e["type"] == "sources")["sources"]
                   if s["filename"] == "annual_report.pdf"]
        page2 = [s for s in sources if s["page_number"] == 2]
        page1 = [s for s in sources if s["page_number"] == 1]
        assert page2 and all(len(s["images"]) == 1 for s in page2)
        assert page1 and all(s["images"] == [] for s in page1)
        figure = client.get(f"/assets/{page2[0]['images'][0]}?size=thumb", headers=people["ann"])
        assert figure.status_code == 200 and figure.content[:2] == b"\xff\xd8"
        assert client.get(f"/assets/{page2[0]['images'][0]}", headers=people["ben"]).status_code == 404

    def test_figures_do_not_appear_as_document_thumbnails(self, client, people, fakes):
        pdf = pdf_with_images([{"text": SENTENCE * 5, "images": [png(400, 300)]}])
        doc = upload_and_wait(client, people["ann"], "with_figure.pdf", pdf)
        assert doc["preview_asset_id"] is None                       # only picture documents get one


# ── asking about an image ────────────────────────────────────────────────────────────────────────

def image_payload(data=None, mime="image/png"):
    return {"mime": mime, "data": b64(data or png(500, 400))}


class TestChatWithImages:
    def test_gemini_receives_the_question_the_image_and_the_documents(self, client, people, vision_on):
        r = client.post("/query", headers=people["ben"],
                        json={"query": "What does this error mean?", "images": [image_payload()]})
        assert r.status_code == 200
        events = sse_events(r)
        assert [e["type"] for e in events if e["type"] in ("sources", "done")] == ["sources", "done"]
        assert "".join(e["content"] for e in events if e["type"] == "chunk").strip() == "The chart shows steady growth."

        messages = vision_on.seen[0]
        human = messages[-1].content
        assert isinstance(human, list) and human[0]["type"] == "text"
        assert "What does this error mean?" in human[0]["text"] and "attached 1 image" in human[0]["text"]
        assert human[1]["type"] == "image_url" and human[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert "DATA, never" in messages[0].content                  # the injection rule is in the system prompt

    def test_the_image_is_never_stored_only_a_note_that_one_was_attached(self, client, people, vision_on):
        client.post("/query", headers=people["ben"], json={"query": "explain this picture", "images": [image_payload()]})
        rows = run_sql("SELECT role, content FROM messages ORDER BY created_at DESC LIMIT 6")
        user_rows = [r["content"] for r in rows if r["role"] == "user"]
        assert any(c.endswith("[Attached 1 image(s)]") for c in user_rows)
        assert not any("base64" in r["content"] or "data:image" in r["content"] for r in rows)

    def test_several_images_are_all_sent(self, client, people, vision_on):
        client.post("/query", headers=people["ben"],
                    json={"query": "compare these", "images": [image_payload(), image_payload(encoded("JPEG", 300, 200), "image/jpeg")]})
        parts = vision_on.seen[0][-1].content
        assert [p["type"] for p in parts] == ["text", "image_url", "image_url"]

    def test_text_questions_never_touch_the_vision_model(self, client, people, vision_on, monkeypatch):
        text_chat = make_chat("Plain answer.")
        monkeypatch.setattr("app.services.rag_graph._build_llm", lambda state=None: text_chat)
        r = client.post("/query", headers=people["ben"], json={"query": "just a text question"})
        assert r.status_code == 200 and vision_on.seen == []
        assert isinstance(text_chat.seen[0][-1].content, str)

    @pytest.mark.parametrize("images,status,fragment", [
        ([{"mime": "image/png", "data": "not base64 !!"}], 400, "base64"),
        ([{"mime": "image/png", "data": b64(b"<svg xmlns='http://www.w3.org/2000/svg'/>")}], 400, "not a supported image"),
        ([{"mime": "image/png", "data": b64(b"plain text pretending to be a png")}], 400, "not a supported image"),
        ([{"mime": "image/png", "data": b64(png(7000, 7000, noise=False))}], 400, "too large"),
        ([{"mime": "image/bmp", "data": "AAAA"}], 422, None),               # type not allowed by the schema
    ])
    def test_bad_attachments_are_clear_errors_not_stream_failures(self, client, people, vision_on, images, status, fragment):
        r = client.post("/query", headers=people["ben"], json={"query": "q", "images": images})
        assert r.status_code == status
        if fragment:
            assert fragment in r.json()["detail"]

    def test_too_many_images_are_rejected(self, client, people, vision_on):
        r = client.post("/query", headers=people["ben"], json={"query": "q", "images": [image_payload()] * 4})
        assert r.status_code == 422

    def test_without_a_gemini_key_the_message_says_so(self, client, people, monkeypatch):
        monkeypatch.setattr("app.api.query.vision_available", lambda: False)
        r = client.post("/query", headers=people["ben"], json={"query": "q", "images": [image_payload()]})
        assert r.status_code == 503 and "GOOGLE_API_KEY" in r.json()["detail"]

    def test_image_questions_are_rate_limited_per_user(self, client, people, vision_on, monkeypatch):
        monkeypatch.setattr(vision, "_quota", SlidingWindowLimiter(limit=1, window_seconds=3600))
        body = {"query": "q", "images": [image_payload()]}
        assert client.post("/query", headers=people["ben"], json=body).status_code == 200
        limited = client.post("/query", headers=people["ben"], json=body)
        assert limited.status_code == 429 and "Too many image requests" in limited.json()["detail"]
        assert client.post("/query", headers=people["ann"], json=body).status_code == 200      # another user is unaffected

    def test_login_is_required(self, client, vision_on):
        assert client.post("/query", json={"query": "q", "images": [image_payload()]}).status_code == 401


# ── code screenshots ─────────────────────────────────────────────────────────────────────────────

CODE = "int main() {\n    for (int i = 0; i < 3; i++) {\n        cout << i;\n    }\n}"


class TestCodeScreenshots:
    @staticmethod
    def post(client, headers, data=None, name="shot.png"):
        return client.post("/compare/extract-code", headers=headers, files={"file": (name, png(600, 400) if data is None else data)})

    def test_code_is_read_with_its_language_and_indentation(self, client, people, vision_on, monkeypatch):
        async def fake(jpeg):
            assert jpeg[:2] == b"\xff\xd8"
            return CODE, "c++"

        monkeypatch.setattr("app.api.compare.transcribe_code", fake)
        r = self.post(client, people["ann"])
        assert r.status_code == 200
        body = r.json()
        assert body["text"] == CODE and body["language"] == "c++" and body["engine"] == "gemini" and body["note"] is None
        assert body["text"].splitlines()[2].startswith("        ")

    def test_without_gemini_ocr_is_used_with_a_warning(self, client, people, monkeypatch):
        monkeypatch.setattr("app.api.compare.vision_available", lambda: False)
        monkeypatch.setattr("app.services.ocr.get_ocr_service",
                            lambda: type("OCR", (), {"extract_text": lambda self, img: ("x = 1\ny = 2", "fake")})())
        body = self.post(client, people["ann"]).json()
        assert body["engine"] == "ocr" and "OCR" in body["note"] and body["text"] == "x = 1\ny = 2"

    def test_a_gemini_failure_falls_back_to_ocr(self, client, people, vision_on, monkeypatch):
        async def boom(jpeg):
            raise RuntimeError("rate limited")

        monkeypatch.setattr("app.api.compare.transcribe_code", boom)
        monkeypatch.setattr("app.services.ocr.get_ocr_service",
                            lambda: type("OCR", (), {"extract_text": lambda self, img: ("fallback text", "fake")})())
        assert self.post(client, people["ann"]).json()["engine"] == "ocr"

    def test_an_image_with_no_code_is_a_clear_error(self, client, people, monkeypatch):
        monkeypatch.setattr("app.api.compare.vision_available", lambda: False)
        monkeypatch.setattr("app.services.ocr.get_ocr_service",
                            lambda: type("OCR", (), {"extract_text": lambda self, img: ("   ", "fake")})())
        r = self.post(client, people["ann"])
        assert r.status_code == 422 and "No code" in r.json()["detail"]

    @pytest.mark.parametrize("data,name", [
        (b"plain text", "notes.png"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "diagram.png"),
        (b"", "empty.png"),
    ])
    def test_files_that_are_not_images_are_rejected(self, client, people, vision_on, data, name):
        assert self.post(client, people["ann"], data, name).status_code == 400

    def test_login_is_required_and_the_quota_applies(self, client, people, vision_on, monkeypatch):
        assert client.post("/compare/extract-code", files={"file": ("a.png", png())}).status_code == 401

        async def fake(jpeg):
            return CODE, None

        monkeypatch.setattr("app.api.compare.transcribe_code", fake)
        monkeypatch.setattr(vision, "_quota", SlidingWindowLimiter(limit=1, window_seconds=3600))
        assert self.post(client, people["ann"]).status_code == 200
        assert self.post(client, people["ann"]).status_code == 429

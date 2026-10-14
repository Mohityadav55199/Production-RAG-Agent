"""Uploads are verified by content, not by file extension."""

import uuid

import pytest

from tests.conftest import auth_header, requires_db
from tests.images import SENTENCE, encoded, pdf_with_images, png

pytestmark = requires_db


@pytest.fixture(scope="module")
def uploader(client):
    r = client.post("/auth/signup", json={"email": f"upload.{uuid.uuid4().hex[:8]}@example.com", "password": "upload password 1"})
    assert r.status_code == 201
    return auth_header(r.json()["token"])


@pytest.fixture(autouse=True)
def _reset_signup_limit():
    from app.api import auth as auth_api

    for limiter in (auth_api._signup_by_ip, auth_api._signup_by_peer):
        limiter._events.clear()


def upload(client, headers, name, data):
    return client.post("/upload", headers=headers, files={"files": (name, data)})


class TestSpoofedExtensions:
    @pytest.mark.parametrize("name", [
        "report.pdf", "report.docx", "slides.pptx", "sheet.xlsx", "photo.png", "photo.jpg", "photo.jpeg",
        "scan.tiff", "scan.bmp", "photo.webp",
    ])
    def test_plain_text_pretending_to_be_a_binary_file_is_rejected(self, client, uploader, name):
        r = upload(client, uploader, name, b"This is just text, whatever the file name claims. " * 5)
        assert r.status_code == 415, name

    def test_svg_is_not_accepted_as_an_image(self, client, uploader):
        svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
        assert upload(client, uploader, "logo.png", svg).status_code == 415

    def test_a_decompression_bomb_is_rejected_at_upload(self, client, uploader):
        assert upload(client, uploader, "huge.png", png(7000, 7000, noise=False)).status_code == 415

    def test_a_pdf_renamed_to_png_is_rejected(self, client, uploader):
        assert upload(client, uploader, "doc.png", pdf_with_images([{"text": SENTENCE * 3}])).status_code == 415

    def test_the_error_names_the_problem(self, client, uploader):
        detail = upload(client, uploader, "photo.png", b"not an image").json()["detail"]
        assert "photo.png" in detail and "not a usable image" in detail


class TestGenuineFilesStillWork:
    def test_real_pdf(self, client, uploader):
        assert upload(client, uploader, "ok.pdf", pdf_with_images([{"text": SENTENCE * 3}])).status_code == 200

    def test_real_images_in_each_format(self, client, uploader):
        for name, data in [("a.png", png(300, 200)), ("b.jpg", encoded("JPEG", 300, 200)),
                           ("c.webp", encoded("WEBP", 300, 200)), ("d.bmp", encoded("BMP", 300, 200))]:
            r = upload(client, uploader, name, data)
            assert r.status_code == 200, (name, r.text)

    def test_a_pdf_with_a_little_junk_before_the_header_is_still_accepted(self, client, uploader):
        pdf = b"\n\n  " + pdf_with_images([{"text": SENTENCE * 3 + " junk-header"}])
        assert upload(client, uploader, "leading_junk.pdf", pdf).status_code == 200

    def test_real_text_files(self, client, uploader):
        assert upload(client, uploader, "notes.txt", b"Some perfectly ordinary notes. " * 10).status_code == 200
        assert upload(client, uploader, "data.csv", b"a,b\n1,2\n3,4\n" * 10).status_code == 200

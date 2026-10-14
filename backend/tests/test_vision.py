import io

import pytest
from PIL import Image

from app.config import get_settings
from app.services import vision
from app.services.vision import ImageError, QuotaError
from tests.images import b64, encoded, png


class TestInspect:
    @pytest.mark.parametrize("fmt,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp"), ("GIF", "image/gif")])
    def test_real_images_are_accepted_with_the_detected_type(self, fmt, mime):
        info = vision.inspect_image(encoded(fmt), max_bytes=5_000_000)
        assert info.mime == mime and (info.width, info.height) == (200, 120)

    @pytest.mark.parametrize("data,why", [
        (b"", "empty"),
        (b"just some text", "not an image"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "svg can carry script"),
        (b"%PDF-1.4 not an image", "pdf"),
        (b"\x89PNG\r\n\x1a\n" + b"garbage" * 10, "truncated png"),
    ])
    def test_non_images_are_rejected(self, data, why):
        with pytest.raises(ImageError):
            vision.inspect_image(data, max_bytes=5_000_000)

    def test_too_many_bytes_is_rejected(self):
        with pytest.raises(ImageError, match="larger than"):
            vision.inspect_image(png(), max_bytes=1000)

    def test_a_decompression_bomb_is_rejected_before_it_is_decoded(self):
        bomb = io.BytesIO()
        Image.new("1", (7000, 7000)).save(bomb, format="PNG")         # 49 megapixels, a few KB on disk
        assert len(bomb.getvalue()) < 100_000
        with pytest.raises(ImageError, match="too large"):
            vision.inspect_image(bomb.getvalue(), max_bytes=5_000_000)

    def test_formats_can_be_restricted(self):
        bmp = encoded("BMP")
        assert vision.inspect_image(bmp, max_bytes=5_000_000).format == "BMP"
        with pytest.raises(ImageError, match="not supported here"):
            vision.inspect_image(bmp, max_bytes=5_000_000, allowed_formats=vision.CHAT_FORMATS)


class TestNormalize:
    def test_output_is_a_fresh_jpeg_no_larger_than_the_limit(self):
        out, w, h = vision.normalize_image(png(3000, 1500))
        assert out[:2] == b"\xff\xd8" and max(w, h) == 1600
        with Image.open(io.BytesIO(out)) as img:
            assert img.format == "JPEG" and img.size == (w, h)

    def test_transparency_becomes_white_not_black(self):
        rgba = encoded("PNG", 50, 50, mode="RGBA")
        clear = io.BytesIO()
        Image.new("RGBA", (50, 50), (0, 0, 0, 0)).save(clear, format="PNG")
        out, _, _ = vision.normalize_image(clear.getvalue())
        with Image.open(io.BytesIO(out)) as img:
            r, g, b = img.getpixel((25, 25))
            assert min(r, g, b) > 240
        assert vision.normalize_image(rgba)[0][:2] == b"\xff\xd8"

    def test_metadata_is_stripped_and_orientation_applied(self):
        src = Image.new("RGB", (200, 100), "blue")
        exif = Image.Exif()
        exif[0x0112] = 6                      # rotate 90 degrees
        exif[0x010F] = "SecretCameraMaker"
        buf = io.BytesIO()
        src.save(buf, format="JPEG", exif=exif)
        assert b"SecretCameraMaker" in buf.getvalue()
        out, w, h = vision.normalize_image(buf.getvalue())
        assert b"SecretCameraMaker" not in out
        assert (w, h) == (100, 200)

    def test_a_large_photo_is_reduced_correctly_without_decoding_it_at_full_size(self):
        big = io.BytesIO()
        Image.new("RGB", (5000, 3500), (20, 120, 220)).save(big, format="JPEG", quality=80)
        out, w, h = vision.normalize_image(big.getvalue())
        assert max(w, h) == 1600 and abs(w / h - 5000 / 3500) < 0.02
        with Image.open(io.BytesIO(out)) as img:
            r, g, b = img.getpixel((w // 2, h // 2))
            assert abs(r - 20) < 12 and abs(g - 120) < 12 and abs(b - 220) < 12     # colours survive the reduced decode

    def test_the_pixel_limit_error_states_the_real_limit(self):
        bomb = io.BytesIO()
        Image.new("1", (7000, 7000)).save(bomb, format="PNG")
        with pytest.raises(ImageError, match=r"more than 25 megapixels"):
            vision.inspect_image(bomb.getvalue(), max_bytes=5_000_000)

    def test_variants_are_bounded(self):
        v = vision.make_variants(png(2400, 1800))
        assert max(v.width, v.height) <= vision.DISPLAY_EDGE
        with Image.open(io.BytesIO(v.thumb)) as thumb:
            assert max(thumb.size) <= vision.THUMB_EDGE
        assert len(v.thumb) < len(v.display)

    def test_unprocessable_input_is_a_clean_error(self):
        with pytest.raises(ImageError):
            vision.normalize_image(b"not an image")


class TestChatAttachments:
    def test_a_valid_attachment_becomes_a_clean_jpeg(self):
        out = vision.decode_chat_image(b64(png(500, 400)))
        assert out[:2] == b"\xff\xd8"

    def test_the_declared_type_is_irrelevant_only_the_bytes_count(self):
        assert vision.decode_chat_image(b64(encoded("WEBP")))[:2] == b"\xff\xd8"

    @pytest.mark.parametrize("payload", ["not base64 !!!", "@@@@", "abc"])
    def test_bad_base64_is_rejected(self, payload):
        with pytest.raises(ImageError):
            vision.decode_chat_image(payload)

    def test_svg_is_rejected_even_when_labelled_as_png(self):
        with pytest.raises(ImageError):
            vision.decode_chat_image(b64(b"<svg xmlns='http://www.w3.org/2000/svg'/>"))

    def test_oversized_attachments_are_rejected(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "CHAT_IMAGE_MAX_BYTES", 2000)
        with pytest.raises(ImageError, match="larger than"):
            vision.decode_chat_image(b64(png(400, 400)))

    def test_bmp_is_not_accepted_in_chat(self):
        with pytest.raises(ImageError):
            vision.decode_chat_image(b64(encoded("BMP")))


class TestMessages:
    def test_image_content_puts_the_text_first_then_each_image(self):
        content = vision.image_content("what is this?", [b"\xff\xd8abc", b"\xff\xd8def"])
        assert content[0] == {"type": "text", "text": "what is this?"}
        assert [c["type"] for c in content] == ["text", "image_url", "image_url"]
        assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    def test_without_images_it_is_just_the_text(self):
        assert vision.image_content("hi", []) == [{"type": "text", "text": "hi"}]


class TestCodeReplyParsing:
    def test_fenced_reply_with_language(self):
        code, lang = vision.parse_code_reply("LANGUAGE: C++\n```cpp\nint main() {\n    return 0;\n}\n```")
        assert code == "int main() {\n    return 0;\n}" and lang == "c++"

    def test_indentation_is_preserved(self):
        code, _ = vision.parse_code_reply("LANGUAGE: python\n```\ndef f(x):\n    if x:\n        return 1\n```")
        assert code.splitlines()[2] == "        return 1"

    def test_unknown_language_is_none(self):
        assert vision.parse_code_reply("LANGUAGE: unknown\n```\nx = 1\n```")[1] is None

    def test_reply_without_fences_still_yields_the_code(self):
        code, lang = vision.parse_code_reply("LANGUAGE: python\nprint('hi')")
        assert code == "print('hi')" and lang == "python"


class TestDescribe:
    def test_no_key_means_no_description_and_no_call(self, monkeypatch):
        monkeypatch.setattr(vision, "vision_available", lambda: False)
        assert vision.describe_image_sync(b"x") is None

    def test_a_failing_model_gives_none_not_an_exception(self, monkeypatch):
        class Boom:
            def invoke(self, _):
                raise RuntimeError("quota exceeded")

        monkeypatch.setattr(vision, "vision_available", lambda: True)
        monkeypatch.setattr(vision, "vision_chat_model", lambda streaming=False: Boom())
        assert vision.describe_image_sync(b"x") is None

    def test_the_reply_is_trimmed_and_limited(self, monkeypatch):
        class Model:
            def invoke(self, messages):
                self.seen = messages
                return type("R", (), {"content": "  A bar chart.  " + "x" * 5000})()

        model = Model()
        monkeypatch.setattr(vision, "vision_available", lambda: True)
        monkeypatch.setattr(vision, "vision_chat_model", lambda streaming=False: model)
        text = vision.describe_image_sync(b"\xff\xd8abc", hint="File name: chart.png")
        assert text.startswith("A bar chart.") and len(text) <= 1500
        assert any(p.get("type") == "image_url" for p in model.seen[0].content)
        assert "chart.png" in model.seen[0].content[0]["text"]


class TestQuota:
    def test_users_are_limited_independently(self, monkeypatch):
        from app.utils.rate_limit import SlidingWindowLimiter

        monkeypatch.setattr(vision, "_quota", SlidingWindowLimiter(limit=2, window_seconds=3600))
        vision.check_vision_quota("alice")
        vision.check_vision_quota("alice")
        with pytest.raises(QuotaError, match="Too many image requests"):
            vision.check_vision_quota("alice")
        vision.check_vision_quota("bob")                 # unaffected

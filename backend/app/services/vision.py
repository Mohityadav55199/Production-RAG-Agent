"""
Image handling and Gemini vision.

Every image that enters the system (chat attachments, uploads, figures pulled out of documents,
code screenshots) goes through the same two steps:

1. ``inspect_image`` rejects anything that is not a real raster image, is too large in bytes or pixels
   (decompression bombs), or is SVG (which can carry script).
2. ``normalize_image`` / ``make_variants`` decode it and write a brand-new JPEG, so metadata (EXIF, GPS,
   embedded payloads) is dropped and downstream code only ever sees a clean, bounded image.

Vision itself uses Gemini (the app already has a key for embeddings). Groq's models used for text chat do
not accept images, so image requests never go through the Groq fallback chain.
"""

import base64
import io
import re
from dataclasses import dataclass

from langchain_core.messages import HumanMessage
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import get_settings
from app.utils.logging import get_logger
from app.utils.rate_limit import SlidingWindowLimiter

logger = get_logger(__name__)

# PIL format name -> MIME type
RASTER_FORMATS = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "MPO": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    "BMP": "image/bmp",
    "TIFF": "image/tiff",
}
CHAT_FORMATS = {"PNG", "JPEG", "MPO", "WEBP", "GIF"}

DISPLAY_EDGE = 1600
THUMB_EDGE = 320


class ImageError(ValueError):
    """The image is unusable; the message is safe to show the user."""


class QuotaError(Exception):
    """The user made too many vision requests."""


@dataclass(frozen=True)
class ImageInfo:
    format: str
    mime: str
    width: int
    height: int


@dataclass(frozen=True)
class Variants:
    display: bytes
    thumb: bytes
    width: int
    height: int


def inspect_image(data: bytes, *, max_bytes: int, allowed_formats: set[str] | None = None) -> ImageInfo:
    """Validate raw bytes as a bounded raster image without fully decoding them."""
    if not data:
        raise ImageError("The image is empty.")
    if len(data) > max_bytes:
        raise ImageError(f"The image is larger than {max_bytes // (1024 * 1024)} MB.")
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = (img.format or "").upper()
            width, height = img.size
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise ImageError("That file is not a supported image (PNG, JPEG, WebP, GIF, BMP or TIFF).") from exc

    if fmt not in RASTER_FORMATS or (allowed_formats is not None and fmt not in allowed_formats):
        raise ImageError(f"{fmt.title() or 'This'} images are not supported here (use PNG, JPEG or WebP).")
    if width < 1 or height < 1:
        raise ImageError("The image has no pixels.")
    if width * height > get_settings().IMAGE_MAX_PIXELS:
        limit_mp = get_settings().IMAGE_MAX_PIXELS // 1_000_000
        raise ImageError(f"The image is too large (more than {limit_mp} megapixels). Resize it and try again.")
    return ImageInfo(format=fmt, mime=RASTER_FORMATS[fmt], width=width, height=height)


def normalize_image(data: bytes, max_edge: int = DISPLAY_EDGE, quality: int = 82) -> tuple[bytes, int, int]:
    """Decode and re-encode as a fresh JPEG no larger than ``max_edge`` pixels. Drops all metadata."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format == "JPEG":
                # Decode big photos at a reduced size (1/2, 1/4 or 1/8): far less memory, same result after resizing
                img.draft("RGB", (max_edge, max_edge))
            img = ImageOps.exif_transpose(img)
            if img.mode in ("RGBA", "LA", "P"):
                rgba = img.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.split()[-1])
                img = background
            else:
                img = img.convert("RGB")
            img.thumbnail((max_edge, max_edge), Image.LANCZOS)
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=quality, optimize=True)
            return out.getvalue(), img.width, img.height
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise ImageError("The image could not be processed.") from exc


def make_variants(data: bytes) -> Variants:
    display, width, height = normalize_image(data, DISPLAY_EDGE, 82)
    thumb, _, _ = normalize_image(display, THUMB_EDGE, 72)
    return Variants(display=display, thumb=thumb, width=width, height=height)


def to_data_url(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")


def decode_chat_image(data_b64: str) -> bytes:
    """Validate one chat attachment and return it as a clean, bounded JPEG."""
    settings = get_settings()
    try:
        raw = base64.b64decode(data_b64, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ImageError("An attached image is not valid base64 data.") from exc
    inspect_image(raw, max_bytes=settings.CHAT_IMAGE_MAX_BYTES, allowed_formats=CHAT_FORMATS)
    jpeg, _, _ = normalize_image(raw, DISPLAY_EDGE, 85)
    return jpeg


# ── Gemini ───────────────────────────────────────────────────────────────────────────────────────

def vision_available() -> bool:
    return bool(get_settings().GOOGLE_API_KEY)


def vision_chat_model(streaming: bool = False):
    """A Gemini chat model for image requests (never wrapped in the text-only Groq fallback chain)."""
    from app.services.llm_factory import build_chat_model

    s = get_settings()
    return build_chat_model("gemini", s.GEMINI_MODEL, s.GOOGLE_API_KEY, temperature=0.1, streaming=streaming)


def image_content(text: str, images: list[bytes]) -> list[dict]:
    """A multimodal message body: the text followed by each image as a data URL."""
    return [
        {"type": "text", "text": text},
        *({"type": "image_url", "image_url": {"url": to_data_url(img)}} for img in images),
    ]


def _reply_text(response) -> str:
    content = response.content
    if isinstance(content, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content or "")


_DESCRIBE_PROMPT = (
    "Describe this image for a search index, in at most 150 words. Start with the kind of image "
    "(photo, chart, diagram, screenshot, slide, scanned document). Give the main subject and transcribe "
    "all clearly visible text verbatim. For charts and tables, name the axes/columns, the series and the "
    "key values. State only what is visible; do not speculate."
)


def describe_image_sync(jpeg: bytes, hint: str = "") -> str | None:
    """Caption an image (blocking; used during ingestion in a worker thread). None if unavailable or failed."""
    if not vision_available():
        return None
    prompt = _DESCRIBE_PROMPT + (f" Context: {hint}" if hint else "")
    try:
        reply = vision_chat_model().invoke([HumanMessage(content=image_content(prompt, [jpeg]))])
        text = _reply_text(reply).strip()
        return text[:1500] or None
    except Exception as exc:
        logger.warning("Image description failed: %s", exc)
        return None


_CODE_PROMPT = (
    "This image contains source code. Transcribe it EXACTLY as written: keep every character, line break "
    "and the original indentation, and do not fix mistakes or add comments. Reply in this format and nothing "
    "else:\nLANGUAGE: <the programming language, or unknown>\n```\n<the code>\n```"
)


def parse_code_reply(reply: str) -> tuple[str, str | None]:
    """Extract (code, language) from the reply to _CODE_PROMPT, tolerating missing fences."""
    language = None
    m = re.search(r"LANGUAGE:\s*([^\n]+)", reply, flags=re.I)
    if m and m.group(1).strip().lower() not in ("", "unknown", "none"):
        language = m.group(1).strip().strip("`").lower()
    fence = re.search(r"```[^\n]*\n(.*?)```", reply, flags=re.S)
    code = fence.group(1) if fence else re.sub(r"^LANGUAGE:[^\n]*\n?", "", reply, flags=re.I)
    return code.strip("\n"), language


async def transcribe_code(jpeg: bytes) -> tuple[str, str | None]:
    reply = await vision_chat_model().ainvoke([HumanMessage(content=image_content(_CODE_PROMPT, [jpeg]))])
    return parse_code_reply(_reply_text(reply))


# ── Per-user quota (image requests cost real money on the shared key) ───────────────────────────

_quota = SlidingWindowLimiter(limit=get_settings().VISION_REQUESTS_PER_HOUR, window_seconds=3600)


def check_vision_quota(user_key: str) -> None:
    """Count one vision request for the user, or raise QuotaError when they are over the hourly limit."""
    wait = _quota.retry_after_minutes(user_key)
    if wait is not None:
        raise QuotaError(f"Too many image requests. Try again in about {wait} minute{'s' if wait != 1 else ''}.")
    _quota.hit(user_key)

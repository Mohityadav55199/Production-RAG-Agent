"""
Pictures found inside documents (PDF figures, slide images, Word images).

Parsers hand over the raw image bytes they find; this module keeps the meaningful ones (not logos,
rules or tiny icons), re-encodes them safely (see services/vision.py), optionally captions the biggest
few with Gemini, and folds those captions into the page text so that questions about a chart or diagram
can actually find it.
"""

import hashlib
from dataclasses import dataclass

from app.config import get_settings
from app.services.parsers.base import ExtractedImage, ExtractedPage
from app.services.vision import ImageError, describe_image_sync, inspect_image, make_variants
from app.utils.logging import get_logger

logger = get_logger(__name__)

MIN_SIDE = 120            # px: skip icons and bullets
MIN_AREA = 25_000         # px^2
MAX_ASPECT = 8.0          # skip thin rules and banners
RAW_LIMIT_BYTES = 50 * 1024 * 1024


@dataclass
class RawImage:
    page_number: int
    data: bytes


def build_figures(raw: list[RawImage], max_count: int | None = None, skip_pages: set[int] | None = None) -> list[ExtractedImage]:
    """Filter, de-duplicate and re-encode raw images. Keeps the largest `max_count`, in page order."""
    max_count = max_count or get_settings().MAX_ASSETS_PER_DOC
    skip_pages = skip_pages or set()
    seen: set[str] = set()
    found: list[tuple[int, ExtractedImage]] = []

    for item in raw:
        if item.page_number in skip_pages:
            continue
        digest = hashlib.sha1(item.data).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        try:
            info = inspect_image(item.data, max_bytes=RAW_LIMIT_BYTES)
            if min(info.width, info.height) < MIN_SIDE or info.width * info.height < MIN_AREA:
                continue
            if max(info.width / info.height, info.height / info.width) > MAX_ASPECT:
                continue
            variants = make_variants(item.data)
        except ImageError:
            continue
        found.append((
            info.width * info.height,
            ExtractedImage(
                page_number=item.page_number, display=variants.display, thumb=variants.thumb,
                width=variants.width, height=variants.height,
            ),
        ))

    largest = sorted(found, key=lambda pair: pair[0], reverse=True)[:max_count]
    kept = sorted((image for _, image in largest), key=lambda image: image.page_number)
    counters: dict[int, int] = {}
    for image in kept:
        image.position = counters.get(image.page_number, 0)
        counters[image.page_number] = image.position + 1
    return kept


def caption_figures(images: list[ExtractedImage], hint: str = "") -> None:
    """Caption the largest few figures with Gemini (blocking; runs in the ingestion worker thread).
    Quota and time are bounded by IMAGE_CAPTION_MAX_PER_DOC; failures just leave a figure uncaptioned."""
    limit = get_settings().IMAGE_CAPTION_MAX_PER_DOC
    biggest = sorted(images, key=lambda image: image.width * image.height, reverse=True)[:limit]
    for image in biggest:
        image.caption = describe_image_sync(image.display, hint=hint)


def merge_captions(pages: list[ExtractedPage], images: list[ExtractedImage]) -> list[ExtractedPage]:
    """Append "[Figure on page N: caption]" to each page's text (creating pages that were only a picture)
    and recompute the character offsets."""
    extra: dict[int, list[str]] = {}
    for image in images:
        if image.caption:
            extra.setdefault(image.page_number, []).append(f"[Figure on page {image.page_number}: {image.caption}]")
    if not extra:
        return pages

    texts = {page.page_number: page.text for page in pages}
    for number, captions in extra.items():
        texts[number] = "\n\n".join(filter(None, [texts.get(number, ""), *captions]))

    merged: list[ExtractedPage] = []
    cursor = 0
    for number in sorted(texts):
        text = texts[number]
        merged.append(ExtractedPage(page_number=number, text=text, char_start=cursor, char_end=cursor + len(text)))
        cursor += len(text) + 2
    return merged

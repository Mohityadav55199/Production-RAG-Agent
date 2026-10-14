from app.services.ocr import get_ocr_service
from app.services.parsers.base import DocumentParser, ExtractedImage, ExtractedPage, ExtractionResult
from app.services.vision import ImageError, describe_image_sync, inspect_image, make_variants
from app.utils.logging import get_logger

from PIL import Image
import io

logger = get_logger(__name__)

MAX_IMAGE_BYTES = 50 * 1024 * 1024   # the upload limit applies first; this is a backstop


class ImageParser(DocumentParser):
    """
    Parses an image file into searchable text and keeps the picture itself, so it can be shown as a
    thumbnail next to answers.

    The text has two parts: an AI description (what the picture shows, including charts and diagrams,
    which OCR cannot read) and the text found by OCR. Either is enough; a photo or diagram with no
    text still works as long as a description could be generated.
    """

    def __init__(self):
        self.ocr_service = get_ocr_service()

    def parse(self, content: bytes, filename: str) -> ExtractionResult:
        try:
            info = inspect_image(content, max_bytes=MAX_IMAGE_BYTES)
            variants = make_variants(content)
        except ImageError as exc:
            raise ValueError(f"Cannot open Image '{filename}': {exc}") from exc

        ocr_text, engine_name = "", None
        try:
            with Image.open(io.BytesIO(variants.display)) as img:
                ocr_text, engine_name = self.ocr_service.extract_text(img)
            ocr_text = ocr_text.strip()
        except Exception as exc:                       # OCR is optional when a description exists
            logger.warning("OCR failed for image '%s': %s", filename, exc)

        description = describe_image_sync(variants.display, hint=f"File name: {filename}")

        if not ocr_text and not description:
            raise ValueError(
                f"Image '{filename}' has no readable text, and an AI description could not be generated. "
                "Set GOOGLE_API_KEY on the server to enable image understanding."
            )

        sections = [f"Image file: {filename}"]
        if description:
            sections.append(f"Description: {description}")
        if ocr_text:
            sections.append(f"Text in the image (OCR):\n{ocr_text}")
        full_text = "\n\n".join(sections)

        method = "+".join(m for m, used in (("ocr", bool(ocr_text)), ("vision", bool(description))) if used)

        return ExtractionResult(
            pages=[ExtractedPage(page_number=1, text=full_text, char_start=0, char_end=len(full_text))],
            full_text=full_text,
            page_count=1,
            char_count=len(full_text),
            file_type=info.format.lower(),
            parser_used="ImageParser",
            ocr_used=bool(ocr_text),
            ocr_engine=engine_name if ocr_text else None,
            extraction_method=method,
            images=[ExtractedImage(
                page_number=1, display=variants.display, thumb=variants.thumb,
                width=variants.width, height=variants.height, kind="image", caption=description,
            )],
        )

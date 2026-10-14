import io

from docx import Document as DocxDocument

from app.services.parsers.base import DocumentParser, ExtractedPage, ExtractionResult
from app.services.parsers.figures import RawImage, build_figures, caption_figures, merge_captions
from app.utils.logging import get_logger

logger = get_logger(__name__)

MAX_IMAGE_CANDIDATES = 150


class DocxParser(DocumentParser):
    def parse(self, content: bytes, filename: str) -> ExtractionResult:
        try:
            doc = DocxDocument(io.BytesIO(content))
        except Exception as exc:
            raise ValueError(f"Cannot open DOCX '{filename}': {exc}") from exc

        full_text = "\n".join(paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip())

        if not full_text:
            raise ValueError(f"DOCX '{filename}' contains no extractable text.")

        # Word has no fixed pages, so the whole document counts as page 1 for chunking and for images
        page = ExtractedPage(
            page_number=1,
            text=full_text,
            char_start=0,
            char_end=len(full_text)
        )

        raw_images: list[RawImage] = []
        try:
            for rel in doc.part.rels.values():
                if rel.is_external or not rel.reltype.endswith("/image"):
                    continue
                raw_images.append(RawImage(1, rel.target_part.blob))
                if len(raw_images) >= MAX_IMAGE_CANDIDATES:
                    break
        except Exception as exc:
            logger.debug("Could not read images from DOCX '%s': %s", filename, exc)

        pages = [page]
        images = build_figures(raw_images)
        if images:
            caption_figures(images, hint=f"An image from the Word document '{filename}'")
            pages = merge_captions(pages, images)
            full_text = "\n\n".join(p.text for p in pages)

        return ExtractionResult(
            pages=pages,
            full_text=full_text,
            page_count=1,
            char_count=len(full_text),
            file_type="docx",
            parser_used="python-docx",
            ocr_used=False,
            ocr_engine=None,
            extraction_method="native",
            images=images,
        )

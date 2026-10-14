import io

import pymupdf as fitz
from PIL import Image

from app.services.ocr import get_ocr_service
from app.services.parsers.base import DocumentParser, ExtractedPage, ExtractionResult
from app.services.parsers.figures import MIN_AREA, MIN_SIDE, RawImage, build_figures, caption_figures, merge_captions
from app.utils.logging import get_logger

logger = get_logger(__name__)

MAX_IMAGE_CANDIDATES = 150           # embedded images examined per PDF (bounds time and memory)
MAX_CANDIDATE_PIXELS = 25_000_000     # matches IMAGE_MAX_PIXELS: bigger would be refused anyway


class PDFParser(DocumentParser):
    """
    Parses PDFs. Automatically falls back to OCR if the native text extraction
    yields very little or no content. Meaningful embedded pictures (charts, diagrams, photos) are
    extracted too, so answers can show them next to the text they illustrate.
    """

    def __init__(self, min_chars_per_page_for_ocr: int = 20):
        self.min_chars = min_chars_per_page_for_ocr
        self.ocr_service = get_ocr_service()

    @staticmethod
    def _collect_images(doc, page, page_number: int, seen_xrefs: set[int], raw: list[RawImage]) -> None:
        for info in page.get_images(full=True):
            xref, width, height = info[0], info[2], info[3]
            if xref in seen_xrefs or len(raw) >= MAX_IMAGE_CANDIDATES:
                continue
            seen_xrefs.add(xref)   # the same logo on every page is only looked at once
            if min(width, height) < MIN_SIDE or width * height < MIN_AREA or width * height > MAX_CANDIDATE_PIXELS:
                continue           # cheap pre-filter, before decoding anything
            try:
                pix = fitz.Pixmap(doc, xref)
                if pix.colorspace is not None and pix.colorspace.n >= 4:    # CMYK -> RGB
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                raw.append(RawImage(page_number, pix.tobytes("png")))
            except Exception as exc:
                logger.debug("Could not extract image xref=%s on page %d: %s", xref, page_number, exc)

    def parse(self, content: bytes, filename: str) -> ExtractionResult:
        try:
            doc: fitz.Document = fitz.open(stream=content, filetype="pdf")
        except Exception as exc:
            raise ValueError(f"Cannot open PDF '{filename}': {exc}") from exc

        pages: list[ExtractedPage] = []
        parts: list[str] = []
        cursor = 0
        total_pages: int = len(doc)

        ocr_was_used = False
        ocr_pages: set[int] = set()
        engines_used = set()
        raw_images: list[RawImage] = []
        seen_xrefs: set[int] = set()

        for page_index in range(total_pages):
            page: fitz.Page = doc[page_index]
            # "markdown" is not a valid PyMuPDF get_text() option (AssertionError, empty message)
            page_text: str = page.get_text("text", sort=True).strip()

            # If native text is too little, we attempt OCR
            if len(page_text) < self.min_chars:
                logger.debug("Page %d of '%s' has little/no text, attempting OCR", page_index + 1, filename)
                try:
                    # Render page to image
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x resolution for better OCR
                    img = Image.open(io.BytesIO(pix.tobytes("png")))

                    ocr_text, engine_name = self.ocr_service.extract_text(img)

                    if ocr_text.strip():
                        page_text = ocr_text.strip()
                        ocr_was_used = True
                        ocr_pages.add(page_index + 1)
                        engines_used.add(engine_name)
                except Exception as e:
                    logger.warning("OCR failed on page %d of '%s': %s", page_index + 1, filename, e)

            # Pictures: a scanned page is one big photo of the page itself, which is not a figure
            if (page_index + 1) not in ocr_pages:
                self._collect_images(doc, page, page_index + 1, seen_xrefs, raw_images)

            if not page_text:
                continue

            start = cursor
            end = start + len(page_text)

            pages.append(ExtractedPage(
                page_number=page_index + 1,
                text=page_text,
                char_start=start,
                char_end=end,
            ))
            parts.append(page_text)
            cursor = end + 2

        doc.close()

        images = build_figures(raw_images, skip_pages=ocr_pages)
        if images:
            caption_figures(images, hint=f"A figure from the PDF '{filename}'")
            pages = merge_captions(pages, images)

        if not pages:
            raise ValueError(f"PDF '{filename}' contains no extractable text even after OCR.")

        full_text = "\n\n".join(p.text for p in pages)

        engine_str = ",".join(engines_used) if engines_used else None
        extraction_method = "ocr" if ocr_was_used else "native"

        return ExtractionResult(
            pages=pages,
            full_text=full_text,
            page_count=total_pages,
            char_count=len(full_text),
            file_type="pdf",
            parser_used="PyMuPDF",
            ocr_used=ocr_was_used,
            ocr_engine=engine_str,
            extraction_method=extraction_method,
            images=images,
        )

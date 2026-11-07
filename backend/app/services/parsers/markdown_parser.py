from app.services.parsers.base import DocumentParser, ExtractionResult, ExtractedPage
from app.utils.logging import get_logger

logger = get_logger(__name__)

class MarkdownParser(DocumentParser):
    def parse(self, content: bytes, filename: str) -> ExtractionResult:
        try:
            raw_text = content.decode("utf-8", errors="replace")
            # Markdown is already plain text, and the raw markup (headings, lists, code fences) helps the
            # chunker split on structure, so it is kept as is rather than converted to HTML.
            full_text = raw_text.strip()
        except Exception as exc:
            raise ValueError(f"Cannot decode Markdown '{filename}': {exc}") from exc

        if not full_text:
            raise ValueError(f"Markdown '{filename}' contains no extractable text.")
            
        page = ExtractedPage(
            page_number=1,
            text=full_text,
            char_start=0,
            char_end=len(full_text)
        )
        
        return ExtractionResult(
            pages=[page],
            full_text=full_text,
            page_count=1,
            char_count=len(full_text),
            file_type="markdown",
            parser_used="markdown",
            ocr_used=False,
            ocr_engine=None,
            extraction_method="native"
        )

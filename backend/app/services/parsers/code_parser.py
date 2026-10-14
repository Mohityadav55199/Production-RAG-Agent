from app.services.parsers.base import DocumentParser, ExtractionResult, ExtractedPage
from app.utils.logging import get_logger

logger = get_logger(__name__)


class CodeParser(DocumentParser):
    """
    Parses source code files. The file path is prepended as a header so the
    first chunk (and the LLM context) always says which file the code is from.
    """

    def parse(self, content: bytes, filename: str) -> ExtractionResult:
        body = content.decode("utf-8", errors="replace").strip()
        if not body:
            raise ValueError(f"Code file '{filename}' is empty.")

        full_text = f"File: {filename}\n\n{body}"
        page = ExtractedPage(page_number=1, text=full_text, char_start=0, char_end=len(full_text))

        return ExtractionResult(
            pages=[page],
            full_text=full_text,
            page_count=1,
            char_count=len(full_text),
            file_type="code",
            parser_used="utf8",
            ocr_used=False,
            ocr_engine=None,
            extraction_method="native",
        )

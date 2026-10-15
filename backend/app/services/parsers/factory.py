import importlib
import mimetypes
from app.services.parsers.base import DocumentParser
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Parser classes by kind. Each module (and its heavy library: pandas, openpyxl, python-pptx, OpenCV ...)
# is imported on first use, which keeps the idle server well inside a 512 MB instance.
_PARSER_CLASSES = {
    "pdf": ("app.services.parsers.pdf_parser", "PDFParser"),
    "docx": ("app.services.parsers.docx_parser", "DocxParser"),
    "pptx": ("app.services.parsers.pptx_parser", "PptxParser"),
    "xlsx": ("app.services.parsers.xlsx_parser", "XlsxParser"),
    "csv": ("app.services.parsers.csv_parser", "CsvParser"),
    "txt": ("app.services.parsers.txt_parser", "TxtParser"),
    "markdown": ("app.services.parsers.markdown_parser", "MarkdownParser"),
    "image": ("app.services.parsers.image_parser", "ImageParser"),
    "code": ("app.services.parsers.code_parser", "CodeParser"),
}


class _LazyParsers(dict):
    """Parser singletons, created the first time each kind is asked for."""

    def __missing__(self, kind: str) -> DocumentParser:
        module, cls = _PARSER_CLASSES[kind]
        parser = getattr(importlib.import_module(module), cls)()
        self[kind] = parser
        return parser


_parsers = _LazyParsers()

def get_parser_for_file(filename: str, mime_type: str = "") -> DocumentParser:
    """
    Returns the appropriate DocumentParser based on filename and mime_type.
    """
    from app.services.project_import import CODE_EXTENSIONS, SPECIAL_FILENAMES

    basename = filename.replace("\\", "/").rsplit("/", 1)[-1].lower()
    ext = basename.split('.')[-1] if '.' in basename else ""
    
    if not mime_type:
        mime_type = mimetypes.guess_type(filename)[0] or ""

    # 1. Check by extension first
    if ext in CODE_EXTENSIONS or basename in SPECIAL_FILENAMES:
        return _parsers["code"]
    elif ext == "pdf":
        return _parsers["pdf"]
    elif ext == "docx":
        return _parsers["docx"]
    elif ext == "pptx":
        return _parsers["pptx"]
    elif ext == "xlsx":
        return _parsers["xlsx"]
    elif ext == "csv":
        return _parsers["csv"]
    elif ext in ("md", "markdown"):
        return _parsers["markdown"]
    elif ext in ("txt", "log", "json"):  # fallback for text files
        return _parsers["txt"]
    elif ext in ("png", "jpg", "jpeg", "tiff", "bmp", "webp"):
        return _parsers["image"]

    # 2. Check by MIME type
    if "pdf" in mime_type:
        return _parsers["pdf"]
    elif "wordprocessingml.document" in mime_type:
        return _parsers["docx"]
    elif "presentationml.presentation" in mime_type:
        return _parsers["pptx"]
    elif "spreadsheetml.sheet" in mime_type:
        return _parsers["xlsx"]
    elif "csv" in mime_type:
        return _parsers["csv"]
    elif "markdown" in mime_type:
        return _parsers["markdown"]
    elif mime_type.startswith("text/"):
        return _parsers["txt"]
    elif mime_type.startswith("image/"):
        return _parsers["image"]

    # Default fallback
    logger.warning("Unrecognized file type for '%s' (mime: %s). Falling back to TXT parser.", filename, mime_type)
    return _parsers["txt"]

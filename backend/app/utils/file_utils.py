"""
File validation utilities for upload endpoints.
"""

from fastapi import HTTPException, UploadFile, status

from app.config import get_settings
from app.services.vision import ImageError, inspect_image

_ALLOWED_EXTENSIONS = {
    "pdf", "docx", "pptx", "xlsx", "csv", "txt", "md", "markdown",
    "png", "jpg", "jpeg", "tiff", "bmp", "webp", "json", "log"
}

_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "tiff", "bmp", "webp"}


async def validate_document_upload(file: UploadFile, settings=None) -> bytes:
    """
    Read the uploaded file into memory and validate:
      1. File size does not exceed MAX_UPLOAD_SIZE_MB
      2. File format is supported
    
    Returns the raw bytes so the caller doesn't re-read from disk.
    Raises HTTPException on any violation.
    """
    if settings is None:
        settings = get_settings()

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    # Read entire file into memory (bounded by max_bytes + 1 so we can detect oversize)
    content = await file.read(max_bytes + 1)

    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File '{file.filename}' exceeds the maximum allowed size "
                f"of {settings.MAX_UPLOAD_SIZE_MB} MB."
            ),
        )

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File '{file.filename}' is empty.",
        )

    filename = file.filename or ""
    ext = filename.lower().split('.')[-1] if '.' in filename else ""
    
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"File '{filename}' has an unsupported extension '{ext}'."
        )

    # 3. Content verification (prevent extension spoofing). Every file type is checked: an unknown or
    #    unverifiable type is rejected rather than waved through.
    header = content[:8]
    is_valid_magic = False

    if ext == "pdf":
        # The spec allows a little junk before the header, but it must appear within the first KB
        is_valid_magic = b"%PDF-" in content[:1024]
    elif ext in {"docx", "pptx", "xlsx"}:
        is_valid_magic = header.startswith(b"PK\x03\x04")          # Office files are zip archives
    elif ext in _IMAGE_EXTENSIONS:
        # A real raster image of a sane size (not SVG, not a decompression bomb)
        try:
            inspect_image(content, max_bytes=max_bytes)
            is_valid_magic = True
        except ImageError as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"File '{filename}' is not a usable image: {exc}",
            ) from exc
    elif ext in {"txt", "md", "markdown", "csv", "json", "log"}:
        # Text files don't have standard magic bytes; verify they contain valid text
        # Attempt decoding with UTF-8, Windows-1252, and Latin-1 fallbacks, ensuring no null bytes
        for encoding in ["utf-8", "windows-1252", "latin-1"]:
            try:
                decoded = content[:1024].decode(encoding)
                if "\x00" not in decoded:
                    is_valid_magic = True
                    break
            except UnicodeDecodeError:
                continue

    if not is_valid_magic:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"File '{filename}' content does not match extension '{ext}'."
        )

    return content

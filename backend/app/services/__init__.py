def __getattr__(name: str):
    if name == "process_uploads":
        from app.services.document_service import process_uploads
        return process_uploads
    elif name == "embed_batch_with_retry":
        from app.services.embedding_service import embed_batch_with_retry
        return embed_batch_with_retry
    elif name == "get_health":
        from app.services.health_service import get_health
        return get_health
    elif name == "extract_pdf":
        from app.services.pdf_service import extract_pdf
        return extract_pdf
    elif name in ("ensure_collection", "upsert_vectors"):
        from app.services import vector_service
        return getattr(vector_service, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "get_health",
    "extract_pdf",
    "embed_batch_with_retry",
    "ensure_collection",
    "upsert_vectors",
    "process_uploads",
]

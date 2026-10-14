"""Storing and looking up the images that belong to documents. Every read is scoped to the owning user."""

import uuid

from sqlalchemy import delete, select

from app.db.asset_models import DocumentAsset
from app.db.postgres import get_db_session
from app.services.parsers.base import ExtractedImage
from app.utils.logging import get_logger

logger = get_logger(__name__)

MAX_IMAGES_PER_SOURCE = 3


async def replace_assets(document_id: uuid.UUID, user_id: str | None, images: list[ExtractedImage]) -> int:
    """Store a document's images, replacing any from an earlier attempt at the same document."""
    async with get_db_session() as session:
        await session.execute(delete(DocumentAsset).where(DocumentAsset.document_id == document_id))
        for image in images:
            session.add(DocumentAsset(
                document_id=document_id,
                user_id=user_id,
                kind=image.kind,
                page_number=image.page_number,
                position=image.position,
                width=image.width,
                height=image.height,
                caption=image.caption,
                display=image.display,
                thumb=image.thumb,
            ))
    if images:
        logger.info("Stored %d image(s) for document %s", len(images), document_id)
    return len(images)


async def images_for_sources(document_ids: list[str], user_id: str | None) -> dict[tuple[str, int], list[str]]:
    """(document_id, page_number) -> up to three asset ids, for attaching thumbnails to answer sources."""
    if not document_ids:
        return {}
    async with get_db_session() as session:
        rows = (await session.execute(
            select(DocumentAsset.id, DocumentAsset.document_id, DocumentAsset.page_number)
            .where(
                DocumentAsset.document_id.in_([uuid.UUID(d) for d in document_ids]),
                DocumentAsset.user_id == user_id,
            )
            .order_by(DocumentAsset.page_number, DocumentAsset.position)
        )).all()
    found: dict[tuple[str, int], list[str]] = {}
    for asset_id, document_id, page in rows:
        bucket = found.setdefault((str(document_id), page), [])
        if len(bucket) < MAX_IMAGES_PER_SOURCE:
            bucket.append(str(asset_id))
    return found


async def preview_assets(document_ids: list[uuid.UUID], user_id: str | None) -> dict[uuid.UUID, uuid.UUID]:
    """document id -> asset id of its picture, for documents that ARE an image (shown in the documents list)."""
    if not document_ids:
        return {}
    async with get_db_session() as session:
        rows = (await session.execute(
            select(DocumentAsset.document_id, DocumentAsset.id)
            .where(
                DocumentAsset.document_id.in_(document_ids),
                DocumentAsset.user_id == user_id,
                DocumentAsset.kind == "image",
            )
        )).all()
    return {document_id: asset_id for document_id, asset_id in rows}


async def get_asset(asset_id: uuid.UUID, user_id: str | None) -> DocumentAsset | None:
    async with get_db_session() as session:
        asset = await session.get(DocumentAsset, asset_id)
    return asset if asset is not None and asset.user_id == user_id else None

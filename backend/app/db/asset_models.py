"""Images attached to documents: uploaded pictures and figures extracted from PDFs, slides and Word files."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.postgres import Base


class DocumentAsset(Base):
    __tablename__ = "document_assets"
    __table_args__ = (Index("ix_document_assets_doc_page", "document_id", "page_number", "position"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Deleting a document removes its images (the database cascades the delete)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # "image": the document IS a picture. "figure": a picture found inside a PDF/slide/Word file.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="figure")
    page_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime: Mapped[str] = mapped_column(String(32), nullable=False, default="image/jpeg")
    display: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)   # up to 1600 px
    thumb: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)     # up to 320 px
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

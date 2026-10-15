"""
Resume feature ORM models.

``Resume``            – one resume in the user's library (raw text + structured profile)
``ResumeGeneration``  – one tailoring run: JD, ATS score and (only when the score
                        gate was passed) the generated LaTeX and PDF.

``user_id`` is nullable and unused until accounts are added; it is here so that
login can later scope every row to its owner without a schema change.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.postgres import Base


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    source_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False, default="text")
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    profile: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Vector indexing of this resume's items: pending | ready | failed
    index_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ResumeGeneration(Base):
    __tablename__ = "resume_generations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    output_name: Mapped[str] = mapped_column(String(200), nullable=False)
    job_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    jd_text: Mapped[str] = mapped_column(Text, nullable=False)
    ats_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=82)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # True only when ats_score >= threshold. LaTeX/PDF are stored only in that case.
    released: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pdf_compiled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    report: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    tex: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class JobApplication(Base):
    __tablename__ = "job_applications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    company: Mapped[str] = mapped_column(String(200), nullable=False)
    job_title: Mapped[str] = mapped_column(String(200), nullable=False)
    job_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    salary: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="saved")
    resume_generation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resume_version_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ats_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    jd_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


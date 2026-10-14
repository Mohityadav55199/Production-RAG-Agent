"""
Resume API.

Library      POST/GET/DELETE /resume/library        – the user's resumes (the RAG source)
ATS check    POST /resume/ats-check                 – score any PDF/DOCX, optionally against a JD
Tailoring    POST /resume/tailor                    – multi-agent run, streamed as SSE
History      GET  /resume/generations[/{id}]        – past runs
Downloads    GET  /resume/generations/{id}/pdf|tex  – only when the ATS gate was passed
"""

import json
import re
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.config import get_settings
from app.services.auth import CurrentUser, get_current_user
from app.db.postgres import get_db_session
from app.db.resume_models import Resume, ResumeGeneration
from app.services.resume import ats, library
from app.services.resume.agents import analyze_jd, run_tailoring, score_text
from app.services.resume.schemas import Profile
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/resume", tags=["Resume"])

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_JD_CHARS = 12_000


# ── Helpers ──────────────────────────────────────────────────────────────────

def _sse(payload: dict | str) -> str:
    return f"data: {payload}\n\n" if isinstance(payload, str) else f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _safe_name(name: str, fallback: str = "resume") -> str:
    name = re.sub(r"\.(pdf|tex)$", "", name.strip(), flags=re.IGNORECASE)
    name = re.sub(r"[^A-Za-z0-9._ -]", "", name).strip(" .")[:100]
    return name or fallback


async def _read_upload(file: UploadFile) -> tuple[bytes, str]:
    filename = (file.filename or "upload").replace("\\", "/").rsplit("/", 1)[-1]
    content = await file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is larger than 5 MB.")
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is empty.")
    return content, filename


def _summary(r: Resume) -> dict:
    p = r.profile or {}
    return {
        "id": str(r.id),
        "label": r.label,
        "filename": r.source_filename,
        "file_type": r.file_type,
        "index_status": r.index_status,
        "item_count": r.item_count,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "name": p.get("name", ""),
        "counts": {
            "experience": len(p.get("experience", [])),
            "projects": len(p.get("projects", [])),
            "skills": sum(len(v) for v in p.get("skills", {}).values()),
            "education": len(p.get("education", [])),
        },
    }


def _generation_summary(g: ResumeGeneration) -> dict:
    return {
        "id": str(g.id),
        "output_name": g.output_name,
        "job_title": g.job_title,
        "company": g.company,
        "ats_score": g.ats_score,
        "threshold": g.threshold,
        "released": g.released,
        "pdf_available": bool(g.pdf),
        "attempts": g.attempts,
        "created_at": g.created_at.isoformat() if g.created_at else None,
    }


# ── Library ──────────────────────────────────────────────────────────────────

@router.post("/library", summary="Add a resume to the library (file upload or pasted text)")
async def add_resume(
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
    label: str | None = Form(None),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    if file is None and not (text and text.strip()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Upload a resume file or paste its text.")

    try:
        if file is not None:
            content, filename = await _read_upload(file)
            raw_text, file_type = library.extract_text(content, filename)
        else:
            raw_text, file_type, filename = text.strip(), "text", None
        profile = await library.build_profile(raw_text)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except Exception as exc:
        logger.exception("Resume analysis failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Could not analyse the resume: {type(exc).__name__}: {exc}") from exc

    row = Resume(
        id=uuid.uuid4(),
        user_id=user.key,
        label=(label or "").strip()[:200] or (filename or profile.name or "Pasted resume"),
        source_filename=filename,
        file_type=file_type,
        raw_text=raw_text,
        profile=profile.model_dump(),
        index_status="pending",
    )
    async with get_db_session() as session:
        session.add(row)
        await session.flush()
        await session.refresh(row)
        summary = _summary(row)

    library.schedule_indexing(str(row.id), profile)
    return summary


@router.get("/library", summary="List resumes in the library")
async def list_library(user: CurrentUser = Depends(get_current_user)) -> dict:
    async with get_db_session() as session:
        rows = (await session.execute(
            select(Resume).where(Resume.user_id == user.key).order_by(Resume.created_at.desc())
        )).scalars().all()
    return {"resumes": [_summary(r) for r in rows]}


@router.get("/library/{resume_id}", summary="Get a resume's structured profile")
async def get_resume(resume_id: uuid.UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with get_db_session() as session:
        row = await session.get(Resume, resume_id)
    if row is None or row.user_id != user.key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found.")
    return {**_summary(row), "profile": row.profile}


@router.delete("/library/{resume_id}", summary="Delete a resume and its search index")
async def delete_resume(resume_id: uuid.UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with get_db_session() as session:
        owned = await session.scalar(select(Resume.id).where(Resume.id == resume_id, Resume.user_id == user.key))
    if owned is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found.")
    await library.delete_resume_vectors(str(resume_id))
    async with get_db_session() as session:
        await session.execute(delete(Resume).where(Resume.id == resume_id, Resume.user_id == user.key))
    return {"deleted": str(resume_id)}


@router.post("/extract-text", summary="Extract text from a file (used for uploading a job description)")
async def extract_text_endpoint(file: UploadFile = File(...)) -> dict:
    content, filename = await _read_upload(file)
    try:
        text, _ = library.extract_text(content, filename)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"text": text[:MAX_JD_CHARS], "filename": filename}


# ── ATS check ────────────────────────────────────────────────────────────────

@router.post("/ats-check", summary="Estimate the ATS score of any resume file")
async def ats_check(file: UploadFile = File(...), jd_text: str | None = Form(None)) -> dict:
    content, filename = await _read_upload(file)
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext not in ("pdf", "docx"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "ATS check supports PDF and DOCX files.")

    try:
        if ext == "pdf":
            text, meta = ats.pdf_text_and_meta(content)
        else:
            text, _ = library.extract_text(content, filename)
            meta = None
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if len(text.strip()) < 50:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "No readable text found. If this is a scanned or image-based PDF, an ATS cannot read it either.",
        )

    jd_text = (jd_text or "").strip()[:MAX_JD_CHARS]
    jd = None
    if jd_text:
        try:
            jd = await analyze_jd(jd_text)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if jd:
        report = await score_text(text, jd, jd_text, meta)
    else:
        report = ats.build_report(text, None, meta)

    return {
        "filename": filename,
        "report": report.to_dict(),
        "jd": jd.model_dump() if jd else None,
        "pages": meta["pages"] if meta else None,
        "extracted_preview": text[:2500],
        "disclaimer": "Estimated score. No single ATS exists; real systems (Workday, Greenhouse, Lever, Taleo) parse differently.",
    }


# ── Tailoring ────────────────────────────────────────────────────────────────

class TailorRequest(BaseModel):
    jd_text: str = Field(..., min_length=80, max_length=MAX_JD_CHARS, description="The job description.")
    output_name: str = Field("resume", max_length=100, description="Name for the generated PDF/LaTeX files.")
    resume_ids: list[uuid.UUID] | None = Field(None, description="Library resumes to use; default is all.")


_active_runs: set[str] = set()   # users with a tailoring run in progress (one at a time each)


async def _runs_today(user_id: str) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    async with get_db_session() as session:
        return await session.scalar(
            select(func.count()).select_from(ResumeGeneration).where(
                ResumeGeneration.user_id == user_id, ResumeGeneration.created_at >= since
            )
        ) or 0


async def _tailor_stream(request: Request, body: TailorRequest, user_id: str) -> AsyncGenerator[str, None]:
    settings = get_settings()
    threshold = settings.RESUME_ATS_THRESHOLD
    output_name = _safe_name(body.output_name)

    yield _sse({"type": "thinking"})

    # Each run makes several LLM calls on a shared quota: one at a time per user, and a daily cap
    if user_id in _active_runs:
        yield _sse({"type": "error", "message": "You already have a resume run in progress. Wait for it to finish."})
        yield _sse("[DONE]")
        return
    if await _runs_today(user_id) >= settings.RESUME_DAILY_LIMIT:
        yield _sse({"type": "error", "message": (
            f"Daily limit reached ({settings.RESUME_DAILY_LIMIT} tailoring runs per 24 hours). Try again tomorrow."
        )})
        yield _sse("[DONE]")
        return
    _active_runs.add(user_id)
    try:
        async for chunk in _tailor_run(request, body, user_id, threshold, output_name):
            yield chunk
    finally:
        _active_runs.discard(user_id)


async def _tailor_run(
    request: Request, body: TailorRequest, user_id: str, threshold: int, output_name: str
) -> AsyncGenerator[str, None]:
    async with get_db_session() as session:
        query = select(Resume).where(Resume.user_id == user_id).order_by(Resume.created_at.desc())
        if body.resume_ids:
            query = query.where(Resume.id.in_(body.resume_ids))
        rows = list((await session.execute(query)).scalars().all())
    if not rows:
        yield _sse({"type": "error", "message": "Your resume library is empty. Add at least one resume first."})
        yield _sse("[DONE]")
        return

    try:
        async for event in run_tailoring(body.jd_text, rows, threshold):
            if await request.is_disconnected():
                return
            if event["type"] != "final":
                yield _sse(event)
                continue

            state = event["state"]
            best = state["best"]
            jd = state["jd"]
            score = int(best["score"])
            # Released only when the score passes AND (if a compiler exists) the LaTeX really compiled
            released = score >= threshold and not best.get("compile_failed", False)
            pdf = best["pdf"] if released else None
            tex = best["tex"] if released else None

            generation = ResumeGeneration(
                id=uuid.uuid4(),
                user_id=user_id,
                output_name=output_name,
                job_title=(jd.get("title") or None),
                company=(jd.get("company") or None),
                jd_text=body.jd_text,
                ats_score=score,
                threshold=threshold,
                attempts=int(state.get("attempt", 1)),
                released=released,
                pdf_compiled=bool(pdf),
                breakdown=best["report"],
                report={"jd": jd, "warnings": best["warnings"], "compile_error": best.get("compile_error", "")},
                tex=tex,
                pdf=pdf,
            )
            async with get_db_session() as session:
                session.add(generation)

            yield _sse({
                "type": "result",
                "generation_id": str(generation.id),
                "output_name": output_name,
                "score": score,
                "threshold": threshold,
                "released": released,
                "attempts": generation.attempts,
                "pdf_available": bool(pdf),
                "pdf_compiled": best["report"].get("pdf_compiled", False),
                "tex": tex,
                "report": best["report"],
                "warnings": best["warnings"],
                "jd": jd,
            })
    except Exception as exc:
        logger.exception("Tailoring failed")
        yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
    yield _sse("[DONE]")


@router.post("/tailor", summary="Tailor a resume to a job description (SSE stream)", response_class=StreamingResponse)
async def tailor(
    body: TailorRequest, request: Request, user: CurrentUser = Depends(get_current_user)
) -> StreamingResponse:
    return StreamingResponse(
        _tailor_stream(request, body, user.key),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ── History & downloads ──────────────────────────────────────────────────────

@router.get("/generations", summary="List past tailoring runs")
async def list_generations(user: CurrentUser = Depends(get_current_user)) -> dict:
    async with get_db_session() as session:
        rows = (await session.execute(
            select(ResumeGeneration)
            .where(ResumeGeneration.user_id == user.key)
            .order_by(ResumeGeneration.created_at.desc())
            .limit(100)
        )).scalars().all()
    return {"generations": [_generation_summary(g) for g in rows], "threshold": get_settings().RESUME_ATS_THRESHOLD}


async def _get_generation(generation_id: uuid.UUID, user: CurrentUser) -> ResumeGeneration:
    async with get_db_session() as session:
        row = await session.get(ResumeGeneration, generation_id)
    if row is None or row.user_id != user.key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    return row


@router.get("/generations/{generation_id}", summary="Details of a run (LaTeX only if the gate was passed)")
async def get_generation(generation_id: uuid.UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    g = await _get_generation(generation_id, user)
    return {
        **_generation_summary(g),
        "report": g.breakdown,
        "details": g.report,
        "tex": g.tex if g.released else None,
    }


@router.get("/generations/{generation_id}/pdf", summary="Download the PDF (only if the ATS gate was passed)")
async def download_pdf(generation_id: uuid.UUID, user: CurrentUser = Depends(get_current_user)) -> Response:
    g = await _get_generation(generation_id, user)
    if not g.released:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"ATS score {g.ats_score} is below {g.threshold}; the PDF is not released.")
    if not g.pdf:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No PDF was compiled for this run.")
    return Response(g.pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{g.output_name}.pdf"'})


@router.get("/generations/{generation_id}/tex", summary="Download the LaTeX source (only if the ATS gate was passed)")
async def download_tex(generation_id: uuid.UUID, user: CurrentUser = Depends(get_current_user)) -> Response:
    g = await _get_generation(generation_id, user)
    if not g.released or not g.tex:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"ATS score {g.ats_score} is below {g.threshold}; the LaTeX is not released.")
    return Response(g.tex, media_type="application/x-tex",
                    headers={"Content-Disposition": f'attachment; filename="{g.output_name}.tex"'})


@router.delete("/generations/{generation_id}", summary="Delete a run")
async def delete_generation(generation_id: uuid.UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with get_db_session() as session:
        await session.execute(
            delete(ResumeGeneration).where(ResumeGeneration.id == generation_id, ResumeGeneration.user_id == user.key)
        )
    return {"deleted": str(generation_id)}

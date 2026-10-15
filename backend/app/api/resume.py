"""
Resume API.

Library      POST/GET/DELETE /resume/library        – the user's resumes (the RAG source)
ATS check    POST /resume/ats-check                 – score any PDF/DOCX, optionally against a JD
Tailoring    POST /resume/tailor                    – multi-agent run, streamed as SSE
History      GET  /resume/generations[/{id}]        – past runs, with the editable draft and review data
Editing      POST /resume/generations/{id}/rescore           – re-render and re-score an edited draft
             POST /resume/generations/{id}/regenerate-bullet – grounded alternatives for one bullet
Downloads    GET  /resume/generations/{id}/pdf|tex  – any compiled draft; the app shows when it is below the gate
"""

import hashlib
import json
import re
import uuid
from typing import AsyncGenerator, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.config import get_settings
from app.services.auth import CurrentUser, get_current_user
from app.db.postgres import get_db_session
from app.db.resume_models import JobApplication, Resume, ResumeGeneration
from app.services.resume import ats, library
from app.services.resume.agents import analyze_jd, regenerate_bullet, run_tailoring, score_profile, score_text
from app.services.resume.outreach import generate_cover_letter, generate_recruiter_message
from app.services.resume.review import annotate, claims_check, find_item, gap_report
from app.services.resume.schemas import JDAnalysis, Profile, RenderOptions
from app.utils.rate_limit import SlidingWindowLimiter
from app.utils.errors import client_error_message
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
        "tex_available": bool(g.tex),
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
    options: RenderOptions | None = Field(None, description="Template, font size and margins of the PDF.")


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
        options = body.options or RenderOptions()
        async for event in run_tailoring(body.jd_text, rows, threshold, options=options):
            if await request.is_disconnected():
                return
            if event["type"] != "final":
                yield _sse(event)
                continue

            state = event["state"]
            best = state["best"]
            jd = state["jd"]
            score = int(best["score"])
            # "Released" means the score passed the gate. A draft that compiled can always be downloaded, because
            # the app shows when it is below the gate; LaTeX that failed to compile is never handed out.
            compile_failed = best.get("compile_failed", False)
            released = score >= threshold and not compile_failed
            pdf = best["pdf"]
            tex = None if compile_failed else best["tex"]

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
                report={
                    "jd": jd, "warnings": best["warnings"], "compile_error": best.get("compile_error", ""),
                    "draft": best["draft"], "ai_draft": best["draft"], "options": options.model_dump(),
                    "resume_ids": [str(r.id) for r in rows],
                },
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
                "tex_available": bool(tex),
                "report": best["report"],
                "warnings": best["warnings"],
                "jd": jd,
            })
    except Exception as exc:
        logger.exception("Tailoring failed")
        yield _sse({"type": "error", "message": client_error_message(exc, "tailoring the resume")})
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


async def _library_for(g: ResumeGeneration) -> tuple[Profile | None, str]:
    """The merged library the run used (or all of the user's resumes), and its raw text. None if it was deleted."""
    ids = [uuid.UUID(i) for i in (g.report or {}).get("resume_ids", [])]
    async with get_db_session() as session:
        query = select(Resume).where(Resume.user_id == g.user_id).order_by(Resume.created_at.desc())
        if ids:
            query = query.where(Resume.id.in_(ids))
        rows = list((await session.execute(query)).scalars().all())
    if not rows:
        return None, ""
    merged = library.merge_profiles([Profile.model_validate(r.profile) for r in rows])
    return merged, "\n".join(r.raw_text for r in rows)


async def _generation_detail(g: ResumeGeneration) -> dict:
    stored = g.report or {}
    detail = {
        **_generation_summary(g),
        "report": g.breakdown,
        "details": {
            "jd": stored.get("jd"), "warnings": stored.get("warnings", []),
            "compile_error": stored.get("compile_error", ""),
        },
        "tex": g.tex,
        "below_threshold": g.ats_score < g.threshold,
        "editable": bool(stored.get("draft")),
        "draft": stored.get("draft"),
        "ai_draft": stored.get("ai_draft"),
        "options": stored.get("options") or RenderOptions().model_dump(),
        "annotated": None,
        "gap": None,
        "outreach": _saved_outreach(stored),
    }
    if detail["editable"]:
        library_profile, corpus = await _library_for(g)
        if library_profile is not None:
            draft = Profile.model_validate(stored["draft"])
            jd = JDAnalysis.model_validate(stored["jd"]) if stored.get("jd") else None
            detail["annotated"] = annotate(draft, library_profile, jd)
            if stored.get("jd") and g.breakdown.get("has_jd"):
                detail["gap"] = gap_report(
                    draft, library_profile, JDAnalysis.model_validate(stored["jd"]), g.breakdown, corpus
                )
    return detail


@router.get("/generations/{generation_id}", summary="Details of a run: editable draft, per-bullet sources, gap report")
async def get_generation(generation_id: uuid.UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    return await _generation_detail(await _get_generation(generation_id, user))


@router.get("/generations/{generation_id}/pdf", summary="Download the PDF (any draft that compiled)")
async def download_pdf(generation_id: uuid.UUID, user: CurrentUser = Depends(get_current_user)) -> Response:
    g = await _get_generation(generation_id, user)
    if not g.pdf:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No PDF was compiled for this run.")
    return Response(g.pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{g.output_name}.pdf"'})


@router.get("/generations/{generation_id}/tex", summary="Download the LaTeX source (any draft that compiled)")
async def download_tex(generation_id: uuid.UUID, user: CurrentUser = Depends(get_current_user)) -> Response:
    g = await _get_generation(generation_id, user)
    if not g.tex:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No LaTeX is available for this run.")
    return Response(g.tex, media_type="application/x-tex",
                    headers={"Content-Disposition": f'attachment; filename="{g.output_name}.tex"'})


# ── Editing ──────────────────────────────────────────────────────────────────

MAX_ROLES, MAX_PROJECTS, MAX_BULLETS, MAX_BULLET_CHARS = 15, 12, 10, 600

_edit_limiter = SlidingWindowLimiter(limit=get_settings().RESUME_EDITS_PER_HOUR, window_seconds=3600)


def _check_edit_budget(user_key: str) -> None:
    """Re-scoring compiles a PDF and bullet suggestions call the LLM: cap how often one user can do either."""
    wait = _edit_limiter.retry_after_minutes(user_key)
    if wait is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many edits. Try again in about {wait} minute{'s' if wait != 1 else ''}.",
        )
    _edit_limiter.hit(user_key)


def _check_draft_size(p: Profile) -> None:
    too_big = (
        len(p.experience) > MAX_ROLES or len(p.projects) > MAX_PROJECTS or len(p.summary) > 1200
        or any(len(r.bullets) > MAX_BULLETS for r in p.experience)
        or any(len(r.bullets) > MAX_BULLETS for r in p.projects)
        or any(len(b) > MAX_BULLET_CHARS for r in (*p.experience, *p.projects) for b in r.bullets)
        or sum(len(v) for v in p.skills.values()) > 120
    )
    if too_big:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That draft is too large for a resume.")


class RescoreRequest(BaseModel):
    draft: Profile
    options: RenderOptions | None = None


@router.post("/generations/{generation_id}/rescore", summary="Re-render and re-score an edited draft")
async def rescore(generation_id: uuid.UUID, body: RescoreRequest, user: CurrentUser = Depends(get_current_user)) -> dict:
    g = await _get_generation(generation_id, user)
    stored = g.report or {}
    if not stored.get("jd") or not g.breakdown.get("has_jd"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This run has no job description analysis to score against.")
    _check_draft_size(body.draft)
    _check_edit_budget(user.key)

    options = body.options or RenderOptions.model_validate(stored.get("options") or {})
    jd = JDAnalysis.model_validate(stored["jd"])
    scored = await score_profile(body.draft, options, jd, g.jd_text)

    library_profile, corpus = await _library_for(g)
    warnings = scored["warnings"]
    if library_profile is not None:
        warnings = claims_check(body.draft, library_profile, corpus, jd) + warnings

    score = int(scored["score"])
    compile_failed = scored["compile_failed"]
    async with get_db_session() as session:
        row = await session.get(ResumeGeneration, g.id)
        row.ats_score = score
        row.released = score >= row.threshold and not compile_failed
        row.pdf_compiled = scored["pdf"] is not None
        row.breakdown = scored["report"]
        row.tex = None if compile_failed else scored["tex"]
        row.pdf = scored["pdf"]
        row.report = {
            **(row.report or {}), "draft": body.draft.model_dump(), "options": options.model_dump(),
            "warnings": warnings, "compile_error": scored["compile_error"],
        }
    return await _generation_detail(await _get_generation(generation_id, user))


class BulletRequest(BaseModel):
    kind: Literal["experience", "project"]
    name: str = Field(..., max_length=200, description="Company (experience) or project name.")
    current: str = Field("", max_length=MAX_BULLET_CHARS, description="The bullet to rewrite; empty asks for a new one.")
    already_used: list[str] = Field(default_factory=list, max_length=30)
    instruction: str = Field("", max_length=200)


@router.post("/generations/{generation_id}/regenerate-bullet", summary="Grounded alternatives for one bullet")
async def regenerate_one_bullet(
    generation_id: uuid.UUID, body: BulletRequest, user: CurrentUser = Depends(get_current_user)
) -> dict:
    g = await _get_generation(generation_id, user)
    stored = g.report or {}
    library_profile, corpus = await _library_for(g)
    if not stored.get("jd") or library_profile is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The resumes this run used are no longer in your library.")

    item = (find_item(library_profile.experience, body.name, "company") if body.kind == "experience"
            else find_item(library_profile.projects, body.name, "name"))
    if item is None or not item.bullets:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f'"{body.name}" has no source bullets in your library, so nothing can be written for it without inventing facts.',
        )
    _check_edit_budget(user.key)

    try:
        options = await regenerate_bullet(
            item.bullets, JDAnalysis.model_validate(stored["jd"]), corpus, body.current, body.already_used,
            body.instruction,
        )
    except Exception as exc:
        logger.warning("Bullet regeneration failed: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The AI service is busy. Try again in a moment.") from exc
    if not options:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "No rewrite stayed within the facts in your library. Try again, add a note, or edit the bullet by hand.",
        )
    return {"options": options}


@router.delete("/generations/{generation_id}", summary="Delete a run")
async def delete_generation(generation_id: uuid.UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with get_db_session() as session:
        await session.execute(
            delete(ResumeGeneration).where(ResumeGeneration.id == generation_id, ResumeGeneration.user_id == user.key)
        )
    return {"deleted": str(generation_id)}


# ── Grounded Cover Letter & Recruiter Outreach ───────────────────────────────

class OutreachOptions(BaseModel):
    platform: Literal["linkedin", "email"] = "linkedin"
    regenerate: bool = Field(False, description="Write a new one even if one is saved for this run.")


class CoverLetterOptions(BaseModel):
    regenerate: bool = Field(False, description="Write a new one even if one is saved for this run.")


def _draft_key(stored: dict) -> str:
    """Fingerprint of the draft an outreach text was written from, to tell when the draft has changed since."""
    return hashlib.sha256(json.dumps(stored.get("draft") or {}, sort_keys=True).encode()).hexdigest()[:16]


def _saved_outreach(stored: dict) -> dict:
    """Saved cover letter / recruiter messages, each marked stale when the draft was edited afterwards."""
    saved = stored.get("outreach") or {}
    key = _draft_key(stored)
    mark = lambda item: {**item, "stale": item.get("draft_key") != key} if item else None  # noqa: E731
    return {
        "cover_letter": mark(saved.get("cover_letter")),
        "recruiter": {p: mark(m) for p, m in (saved.get("recruiter") or {}).items()},
    }


async def _outreach_inputs(g: ResumeGeneration) -> tuple[Profile, str, JDAnalysis]:
    """The profile to write from (the edited draft when there is one), the library text that grounds it, the JD."""
    stored = g.report or {}
    if not stored.get("jd") or not g.jd_text:
        raise HTTPException(status.HTTP_409_CONFLICT, "This run has no job description to tailor against.")
    library_profile, corpus = await _library_for(g)
    if library_profile is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The resumes for this run are no longer in your library.")
    # Write from what the user will actually send: the tailored, possibly edited, draft
    profile = Profile.model_validate(stored["draft"]) if stored.get("draft") else library_profile
    return profile, corpus, JDAnalysis.model_validate(stored["jd"])


async def _save_outreach(generation_id: uuid.UUID, kind: str, item: dict, platform: str | None = None) -> None:
    async with get_db_session() as session:
        row = await session.get(ResumeGeneration, generation_id)
        report = dict(row.report or {})
        outreach = dict(report.get("outreach") or {})
        if kind == "cover_letter":
            outreach["cover_letter"] = item
        else:
            outreach["recruiter"] = {**(outreach.get("recruiter") or {}), platform: item}
        report["outreach"] = outreach
        row.report = report   # a new dict, so SQLAlchemy writes the JSON column


@router.post("/generations/{generation_id}/cover-letter", summary="Cover letter for a run (saved; regenerate on request)")
async def generation_cover_letter(
    generation_id: uuid.UUID,
    body: CoverLetterOptions = CoverLetterOptions(),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    g = await _get_generation(generation_id, user)
    saved = _saved_outreach(g.report or {})["cover_letter"]
    if saved and not body.regenerate:
        return saved

    profile, corpus, jd = await _outreach_inputs(g)
    _check_edit_budget(user.key)
    try:
        letter = await generate_cover_letter(profile, jd, g.jd_text, corpus)
    except Exception as exc:
        logger.warning("Cover letter generation failed: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Could not generate cover letter. Try again in a moment.") from exc
    letter = {**letter, "draft_key": _draft_key(g.report or {})}
    await _save_outreach(g.id, "cover_letter", letter)
    return {**letter, "stale": False}


@router.post("/generations/{generation_id}/recruiter-message", summary="Recruiter message for a run (saved per platform)")
async def generation_recruiter_message(
    generation_id: uuid.UUID,
    body: OutreachOptions = OutreachOptions(),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    g = await _get_generation(generation_id, user)
    saved = _saved_outreach(g.report or {})["recruiter"].get(body.platform)
    if saved and not body.regenerate:
        return saved

    profile, corpus, jd = await _outreach_inputs(g)
    _check_edit_budget(user.key)
    try:
        msg = await generate_recruiter_message(profile, jd, g.jd_text, platform=body.platform, corpus=corpus)
    except Exception as exc:
        logger.warning("Recruiter message generation failed: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Could not generate recruiter message. Try again in a moment.") from exc
    msg = {**msg, "draft_key": _draft_key(g.report or {})}
    await _save_outreach(g.id, "recruiter", msg, body.platform)
    return {**msg, "stale": False}


# ── Job Library & Application Tracker ────────────────────────────────────────

class JobCreateRequest(BaseModel):
    company: str = Field(..., max_length=200)
    job_title: str = Field(..., max_length=200)
    job_url: str | None = Field(None, max_length=500)
    location: str | None = Field(None, max_length=200)
    salary: str | None = Field(None, max_length=100)
    status: Literal["saved", "applied", "interviewing", "offered", "rejected", "archived"] = "saved"
    resume_generation_id: uuid.UUID | None = None
    resume_version_name: str | None = Field(None, max_length=200)
    ats_score: int | None = None
    jd_text: str | None = None
    notes: str | None = None
    applied_date: datetime | None = None


class JobUpdateRequest(BaseModel):
    company: str | None = Field(None, max_length=200)
    job_title: str | None = Field(None, max_length=200)
    job_url: str | None = Field(None, max_length=500)
    location: str | None = Field(None, max_length=200)
    salary: str | None = Field(None, max_length=100)
    status: Literal["saved", "applied", "interviewing", "offered", "rejected", "archived"] | None = None
    resume_generation_id: uuid.UUID | None = None
    resume_version_name: str | None = Field(None, max_length=200)
    ats_score: int | None = None
    jd_text: str | None = None
    notes: str | None = None
    applied_date: datetime | None = None


def _job_summary(j: JobApplication) -> dict:
    return {
        "id": str(j.id),
        "company": j.company,
        "job_title": j.job_title,
        "job_url": j.job_url,
        "location": j.location,
        "salary": j.salary,
        "status": j.status,
        "resume_generation_id": str(j.resume_generation_id) if j.resume_generation_id else None,
        "resume_version_name": j.resume_version_name,
        "ats_score": j.ats_score,
        "jd_text": j.jd_text,
        "notes": j.notes,
        "applied_date": j.applied_date.isoformat() if j.applied_date else None,
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "updated_at": j.updated_at.isoformat() if j.updated_at else None,
    }


@router.get("/jobs", summary="List saved jobs and applications")
async def list_jobs(
    status: str | None = None,
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    query = select(JobApplication).where(JobApplication.user_id == user.key)
    if status:
        query = query.where(JobApplication.status == status)
    query = query.order_by(JobApplication.updated_at.desc())

    async with get_db_session() as session:
        result = await session.execute(query)
        rows = result.scalars().all()
    return [_job_summary(r) for r in rows]


@router.post("/jobs", status_code=status.HTTP_201_CREATED, summary="Save a job application")
async def create_job(
    body: JobCreateRequest,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    row = JobApplication(
        id=uuid.uuid4(),
        user_id=user.key,
        company=body.company.strip(),
        job_title=body.job_title.strip(),
        job_url=(body.job_url.strip() if body.job_url else None),
        location=(body.location.strip() if body.location else None),
        salary=(body.salary.strip() if body.salary else None),
        status=body.status,
        resume_generation_id=body.resume_generation_id,
        resume_version_name=body.resume_version_name,
        ats_score=body.ats_score,
        jd_text=body.jd_text,
        notes=body.notes,
        applied_date=body.applied_date,
    )
    async with get_db_session() as session:
        session.add(row)
    return _job_summary(row)


@router.get("/jobs/{job_id}", summary="Get job application detail")
async def get_job_detail(
    job_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    async with get_db_session() as session:
        row = await session.get(JobApplication, job_id)
        if row is None or row.user_id != user.key:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Job application not found.")
        return _job_summary(row)


@router.patch("/jobs/{job_id}", summary="Update a job application")
async def update_job(
    job_id: uuid.UUID,
    body: JobUpdateRequest,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    async with get_db_session() as session:
        row = await session.get(JobApplication, job_id)
        if row is None or row.user_id != user.key:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Job application not found.")

        if body.company is not None:
            row.company = body.company.strip()
        if body.job_title is not None:
            row.job_title = body.job_title.strip()
        if body.job_url is not None:
            row.job_url = body.job_url.strip() or None
        if body.location is not None:
            row.location = body.location.strip() or None
        if body.salary is not None:
            row.salary = body.salary.strip() or None
        if body.status is not None:
            row.status = body.status
            if body.status == "applied" and not row.applied_date:
                row.applied_date = datetime.now(timezone.utc)
        if body.resume_generation_id is not None:
            row.resume_generation_id = body.resume_generation_id
        if body.resume_version_name is not None:
            row.resume_version_name = body.resume_version_name
        if body.ats_score is not None:
            row.ats_score = body.ats_score
        if body.jd_text is not None:
            row.jd_text = body.jd_text
        if body.notes is not None:
            row.notes = body.notes
        if body.applied_date is not None:
            row.applied_date = body.applied_date

        row.updated_at = datetime.now(timezone.utc)
        return _job_summary(row)


@router.delete("/jobs/{job_id}", summary="Delete a job application")
async def delete_job(
    job_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    async with get_db_session() as session:
        row = await session.get(JobApplication, job_id)
        if row is None or row.user_id != user.key:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Job application not found.")
        await session.delete(row)
    return {"deleted": str(job_id)}


"""
Project import API router.

POST /projects/github — index a public GitHub repository by URL
POST /projects/zip    — index a project uploaded as a .zip archive

Both return immediately; files are ingested in the background through the
normal document pipeline, so progress shows up in GET /documents.
"""

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.auth import CurrentUser, get_current_user
from app.services.document_service import process_uploads
from app.services.project_import import (
    MAX_ARCHIVE_BYTES,
    ProjectFiles,
    extract_project_from_zip,
    fetch_github_project,
)
from app.services.scope_service import list_sources
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/projects", tags=["Projects"])

# Keep references so background tasks aren't garbage-collected mid-run
_background_tasks: set[asyncio.Task] = set()


class GithubImportRequest(BaseModel):
    url: str = Field(..., description="https://github.com/owner/repo (optionally /tree/<branch>)")


class ProjectImportResponse(BaseModel):
    project_name: str
    files_queued: int
    files_skipped: int
    truncated: bool
    message: str


async def _ingest_in_background(project: ProjectFiles, user_id: str) -> None:
    try:
        result = await process_uploads(project.files, user_id)
        logger.info(
            "Project '%s' ingested — succeeded=%d failed=%d",
            project.project_name, result.succeeded, result.failed,
        )
    except Exception:
        logger.exception("Background ingestion of project '%s' crashed", project.project_name)


def _queue(project: ProjectFiles, user_id: str) -> ProjectImportResponse:
    task = asyncio.create_task(_ingest_in_background(project, user_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    note = " Only the 200 most important files were included." if project.truncated else ""
    return ProjectImportResponse(
        project_name=project.project_name,
        files_queued=len(project.files),
        files_skipped=project.skipped,
        truncated=project.truncated,
        message=(
            f"Indexing {len(project.files)} files from '{project.project_name}'. "
            f"They will appear in your documents as they finish.{note}"
        ),
    )


@router.get("/sources", summary="List imported projects and standalone documents")
async def get_sources(user: CurrentUser = Depends(get_current_user)) -> dict:
    """Used by the Chat scope picker and the Compare view."""
    return await list_sources(user.key)


@router.post("/github", response_model=ProjectImportResponse, summary="Import a GitHub repository")
async def import_github(
    body: GithubImportRequest, user: CurrentUser = Depends(get_current_user)
) -> ProjectImportResponse:
    try:
        project = await fetch_github_project(body.url, token=get_settings().GITHUB_TOKEN)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("GitHub import failed for %s", body.url)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not download repository: {type(exc).__name__}: {exc}",
        ) from exc
    return _queue(project, user.key)


@router.post("/zip", response_model=ProjectImportResponse, summary="Import a project .zip archive")
async def import_zip(
    file: UploadFile = File(..., description="Project folder compressed as .zip"),
    user: CurrentUser = Depends(get_current_user),
) -> ProjectImportResponse:
    filename = (file.filename or "project.zip").replace("\\", "/").rsplit("/", 1)[-1]
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Please upload a .zip file.")

    content = await file.read(MAX_ARCHIVE_BYTES + 1)
    project_name = filename[:-4] or "project"
    try:
        project = await asyncio.to_thread(extract_project_from_zip, content, project_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _queue(project, user.key)

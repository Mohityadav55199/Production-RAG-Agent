"""
Resume library: text extraction, structured profile building, and the RAG index.

Each resume is broken into small "items" (a job's bullets, a project, a skills
group, an achievement). Items are embedded into their own Qdrant collection
(``resume_items``) so they never mix with the document knowledge base. At
tailoring time the agent retrieves the items most relevant to the job
description and the writer may use only those.
"""

import asyncio
import io
import re
import uuid

from qdrant_client.http import models as qmodels

from app.config import get_settings
from app.db.qdrant import get_qdrant_client
from app.services.embedding_service import embed_batch_with_retry
from app.services.resume.llm_utils import llm_json
from app.services.resume.schemas import Profile
from app.utils.logging import get_logger

logger = get_logger(__name__)

RESUME_COLLECTION = "resume_items"
MAX_RESUME_CHARS = 14_000
_NAMESPACE = uuid.UUID("6f1c1d0e-5a52-4f55-9a3e-0d6a3a9c7e11")

_EXTRACT_PROMPT = """\
You convert a resume into structured JSON. Copy facts exactly as written; never
invent or embellish anything. Use empty strings/arrays for anything missing.

Schema:
{
  "name": "", "email": "", "phone": "", "location": "", "links": ["linkedin/github/portfolio URLs"],
  "summary": "",
  "skills": {"Languages": ["..."], "Frameworks": ["..."], "Tools": ["..."]},
  "experience": [{"company": "", "title": "", "location": "", "dates": "", "bullets": ["..."]}],
  "projects": [{"name": "", "tech": "comma separated", "link": "", "bullets": ["..."]}],
  "education": [{"school": "", "degree": "", "dates": "", "location": "", "details": "GPA, coursework"}],
  "certifications": ["..."], "achievements": ["..."]
}
Group skills into sensible categories using the resume's own wording."""


# ── Text extraction ──────────────────────────────────────────────────────────

def extract_text(content: bytes, filename: str) -> tuple[str, str]:
    """Return (text, file_type) for a PDF, DOCX, TeX or plain-text resume."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if ext == "pdf":
        import pymupdf

        try:
            doc = pymupdf.open(stream=content, filetype="pdf")
        except Exception as exc:
            raise ValueError(f"Cannot open PDF: {exc}") from exc
        with doc:
            text = "\n".join(page.get_text("text", sort=True) for page in doc)
        return text.strip(), "pdf"

    if ext == "docx":
        from docx import Document as DocxDocument

        try:
            doc = DocxDocument(io.BytesIO(content))
        except Exception as exc:
            raise ValueError(f"Cannot open DOCX: {exc}") from exc
        lines = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                lines.append(" | ".join(c.text.strip() for c in row.cells if c.text.strip()))
        return "\n".join(lines).strip(), "docx"

    if ext in ("txt", "md", "markdown", "tex", ""):
        return content.decode("utf-8", errors="replace").strip(), ("tex" if ext == "tex" else "text")

    raise ValueError(f"Unsupported resume format '.{ext}'. Use PDF, DOCX, TXT, MD or TEX.")


# ── Profile building ─────────────────────────────────────────────────────────

async def build_profile(raw_text: str) -> Profile:
    if len(raw_text.strip()) < 80:
        raise ValueError("The resume has too little text to analyse.")
    data = await llm_json(_EXTRACT_PROMPT, f"Resume text:\n\n{raw_text[:MAX_RESUME_CHARS]}")
    profile = Profile.model_validate(data)
    if not (profile.experience or profile.projects or profile.skills or profile.education):
        raise ValueError("Could not find any experience, projects, skills or education in this resume.")
    return profile


def profile_to_items(profile: Profile) -> list[dict]:
    """Flatten a profile into independently retrievable items."""
    items: list[dict] = []
    for exp in profile.experience:
        head = f"{exp.title} at {exp.company}".strip()
        for bullet in exp.bullets:
            items.append({"kind": "experience", "source": head, "text": f"{head}: {bullet}"})
    for proj in profile.projects:
        body = " ".join(proj.bullets)
        items.append({
            "kind": "project",
            "source": proj.name,
            "text": f"Project {proj.name} ({proj.tech}): {body}".strip(),
        })
    for group, skills in profile.skills.items():
        items.append({"kind": "skills", "source": group, "text": f"{group}: {', '.join(skills)}"})
    for ach in profile.achievements:
        items.append({"kind": "achievement", "source": "achievement", "text": ach})
    for cert in profile.certifications:
        items.append({"kind": "certification", "source": "certification", "text": cert})
    return [i for i in items if len(i["text"]) > 8]


# ── Vector index (RAG over the library) ──────────────────────────────────────

async def _ensure_collection() -> None:
    client = get_qdrant_client()
    if await client.collection_exists(RESUME_COLLECTION):
        return
    await client.create_collection(
        collection_name=RESUME_COLLECTION,
        vectors_config=qmodels.VectorParams(
            size=get_settings().EMBEDDING_DIMENSION, distance=qmodels.Distance.COSINE
        ),
    )
    await client.create_payload_index(
        collection_name=RESUME_COLLECTION,
        field_name="resume_id",
        field_schema=qmodels.PayloadSchemaType.KEYWORD,
    )


async def index_resume(resume_id: str, profile: Profile) -> int:
    """Embed a resume's items into Qdrant. Returns the number indexed."""
    items = profile_to_items(profile)
    if not items:
        return 0
    await _ensure_collection()
    client = get_qdrant_client()
    batch = max(1, get_settings().EMBEDDING_BATCH_SIZE)

    for start in range(0, len(items), batch):
        group = items[start : start + batch]
        vectors = await embed_batch_with_retry([i["text"] for i in group], task_type="RETRIEVAL_DOCUMENT")
        await client.upsert(
            collection_name=RESUME_COLLECTION,
            points=[
                qmodels.PointStruct(
                    id=str(uuid.uuid5(_NAMESPACE, f"{resume_id}:{start + n}:{item['text']}")),
                    vector=vector,
                    payload={"resume_id": resume_id, **item},
                )
                for n, (item, vector) in enumerate(zip(group, vectors))
            ],
            wait=True,
        )
    logger.info("Indexed %d items for resume %s", len(items), resume_id)
    return len(items)


async def delete_resume_vectors(resume_id: str) -> None:
    client = get_qdrant_client()
    if not await client.collection_exists(RESUME_COLLECTION):
        return
    await client.delete(
        collection_name=RESUME_COLLECTION,
        points_selector=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[qmodels.FieldCondition(key="resume_id", match=qmodels.MatchValue(value=resume_id))]
            )
        ),
        wait=True,
    )


async def retrieve_items(queries: list[str], resume_ids: list[str], per_query: int = 4, cap: int = 45) -> list[dict]:
    """Semantic search: the library items that best support each JD requirement."""
    if not queries or not resume_ids:
        return []
    client = get_qdrant_client()
    if not await client.collection_exists(RESUME_COLLECTION):
        return []

    vectors = await embed_batch_with_retry(queries, task_type="RETRIEVAL_QUERY")
    flt = qmodels.Filter(
        must=[qmodels.FieldCondition(key="resume_id", match=qmodels.MatchAny(any=resume_ids))]
    )
    found: dict[str, dict] = {}
    for vector in vectors:
        response = await client.query_points(
            collection_name=RESUME_COLLECTION,
            query=vector,
            limit=per_query,
            with_payload=True,
            query_filter=flt,
        )
        for hit in response.points:
            payload = hit.payload or {}
            key = re.sub(r"\W+", " ", payload.get("text", "").lower()).strip()
            if key and (key not in found or hit.score > found[key]["score"]):
                found[key] = {**payload, "score": float(hit.score)}
    ranked = sorted(found.values(), key=lambda i: i["score"], reverse=True)
    return ranked[:cap]


def lexical_items(queries: list[str], profiles: list[Profile], cap: int = 45) -> list[dict]:
    """Fallback when the vector index isn't ready: rank items by keyword overlap."""
    terms = {w for q in queries for w in re.findall(r"[a-z0-9+#.]{2,}", q.lower())}
    scored = []
    for profile in profiles:
        for item in profile_to_items(profile):
            words = set(re.findall(r"[a-z0-9+#.]{2,}", item["text"].lower()))
            overlap = len(words & terms)
            scored.append({**item, "score": overlap / (len(words) ** 0.5 + 1)})
    scored.sort(key=lambda i: i["score"], reverse=True)
    return scored[:cap]


# ── Merging several resumes into one pool ────────────────────────────────────

def merge_profiles(profiles: list[Profile]) -> Profile:
    """Union of all resumes: identity from the newest, every role/project/skill kept once."""
    if not profiles:
        raise ValueError("The resume library is empty. Add at least one resume first.")
    primary = profiles[0]
    merged = Profile(
        name=primary.name, email=primary.email, phone=primary.phone,
        location=primary.location, links=list(primary.links), summary=primary.summary,
    )

    def fill(attr: str):
        if not getattr(merged, attr):
            for p in profiles[1:]:
                if getattr(p, attr):
                    setattr(merged, attr, getattr(p, attr))
                    break

    for attr in ("name", "email", "phone", "location"):
        fill(attr)

    seen_roles: dict[str, int] = {}
    for p in profiles:
        for exp in p.experience:
            key = re.sub(r"\W+", "", f"{exp.company}{exp.title}".lower())
            if key in seen_roles:
                existing = merged.experience[seen_roles[key]]
                known = {re.sub(r"\W+", "", b.lower()) for b in existing.bullets}
                existing.bullets += [b for b in exp.bullets if re.sub(r"\W+", "", b.lower()) not in known]
            else:
                seen_roles[key] = len(merged.experience)
                merged.experience.append(exp.model_copy(deep=True))

    seen_projects: set[str] = set()
    for p in profiles:
        for proj in p.projects:
            key = re.sub(r"\W+", "", proj.name.lower())
            if key and key not in seen_projects:
                seen_projects.add(key)
                merged.projects.append(proj.model_copy(deep=True))

    for p in profiles:
        for group, skills in p.skills.items():
            bucket = merged.skills.setdefault(group, [])
            known = {s.lower() for s in bucket}
            bucket += [s for s in skills if s.lower() not in known]
        for edu in p.education:
            if not any(edu.school.lower() == e.school.lower() and edu.degree.lower() == e.degree.lower()
                       for e in merged.education):
                merged.education.append(edu.model_copy(deep=True))
        for attr in ("certifications", "achievements", "links"):
            bucket = getattr(merged, attr)
            known = {x.lower() for x in bucket}
            bucket += [x for x in getattr(p, attr) if x.lower() not in known]
    return merged


async def index_in_background(resume_id: str, profile: Profile) -> None:
    """Index a resume and record the outcome on its row (never raises)."""
    from sqlalchemy import update

    from app.db.postgres import get_db_session
    from app.db.resume_models import Resume

    try:
        count = await index_resume(resume_id, profile)
        status = "ready"
    except Exception:
        logger.exception("Indexing resume %s failed", resume_id)
        count, status = 0, "failed"
    async with get_db_session() as session:
        await session.execute(
            update(Resume).where(Resume.id == uuid.UUID(resume_id)).values(index_status=status, item_count=count)
        )


async def recover_pending_indexing() -> int:
    """At startup, resumes whose indexing was interrupted by a restart are indexed again."""
    from sqlalchemy import select

    from app.db.postgres import get_db_session
    from app.db.resume_models import Resume

    async with get_db_session() as session:
        rows = (await session.execute(select(Resume).where(Resume.index_status == "pending"))).scalars().all()
        pending = [(str(r.id), Profile.model_validate(r.profile)) for r in rows]
    for resume_id, profile in pending:
        schedule_indexing(resume_id, profile)
    if pending:
        logger.info("Re-indexing %d resume(s) interrupted by a restart", len(pending))
    return len(pending)


_background: set[asyncio.Task] = set()


def schedule_indexing(resume_id: str, profile: Profile) -> None:
    task = asyncio.create_task(index_in_background(resume_id, profile))
    _background.add(task)
    task.add_done_callback(_background.discard)

"""
Multi-agent resume tailoring (LangGraph).

    analyze_jd -> retrieve -> write -> score -+-> done            (score >= threshold)
                                ^             |
                                +-- feedback -+  (score < threshold, attempts left)

Agents:
    JD analyst     structured requirements from the job description
    Retriever      RAG over the user's resume library (semantic, lexical fallback)
    Writer         tailors content using ONLY library evidence
    Grounding      code check that strips anything not found in the library
    ATS scorer     compiled-PDF based score (see ats.py)
    Reviser        turns score findings into feedback for the next attempt

The score threshold is a target, not a lock: the caller records whether the final
score reached it, and the app flags drafts that fall short (they stay downloadable).
"""

import asyncio
import difflib
import hashlib
import re
from collections import OrderedDict
from typing import Any, AsyncGenerator, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.services.resume import ats, library
from app.services.resume.latex import (
    compile_pdf,
    compiler_available,
    profile_plain_text,
    render_latex,
    unsupported_characters,
)
from app.services.resume import grounding
from app.services.resume.llm_utils import llm_json
from app.services.resume.schemas import Education, Experience, JDAnalysis, Profile, Project, RenderOptions
from app.utils.errors import client_error_message
from app.utils.logging import get_logger

logger = get_logger(__name__)

MAX_ROLE_BULLETS = 5
MAX_PROJECTS = 4
MAX_PROJECT_BULLETS = 3

# LLM analyses of recently pasted job descriptions (bounded: the server has little memory)
_JD_CACHE: "OrderedDict[str, JDAnalysis]" = OrderedDict()
_JD_CACHE_SIZE = 200


def clear_jd_cache() -> None:
    """Clear in-memory cached job description analyses (useful for testing and manual resets)."""
    _JD_CACHE.clear()

_JD_PROMPT = """\
You analyse job descriptions for resume tailoring. Extract:
{"title": "job title", "company": "", "seniority": "intern|junior|mid|senior|lead",
 "must_have": ["explicitly REQUIRED technical skills, tools, languages, frameworks, domains (max 15)"],
 "nice_to_have": ["PREFERRED / bonus technical skills (max 10)"],
 "responsibilities": ["short phrases of the main duties (max 8)"]}
Use short canonical names ("Node.js", "PostgreSQL", "REST APIs"). Skip soft skills and filler words."""

_WRITER_PROMPT = """\
You are an expert resume writer tailoring a candidate's resume to a job description.

ABSOLUTE RULES (breaking any is a failure):
1. Use ONLY facts from the candidate's library below. Never invent employers, titles, dates, degrees,
   projects, metrics, numbers or skills. If the library lacks something the job wants, leave it out.
2. You may rephrase bullets and reorder them, and use the job description's wording for a skill ONLY
   when the library shows the candidate really has it.
3. Keep every role listed under ROLES (same company and title). Pick the {max_role_bullets} most relevant
   bullets per role (relevant ones are tagged [RELEVANT]); start each with a strong past-tense verb;
   keep numbers exactly as in the library.
4. Choose the {max_projects} most relevant projects, {max_project_bullets} bullets each at most.
5. Skills: only from the SKILLS POOL, grouped by category, job-relevant skills first.
6. Summary: 2 sentences, no first person, mentioning the target role and the candidate's strongest REAL fit.

Return JSON:
{"summary": "", "skills": {"Category": ["skill"]},
 "experience": [{"company": "", "title": "", "bullets": [""]}],
 "projects": [{"name": "", "bullets": [""]}]}"""

_FIT_PROMPT = """\
You judge how well a resume fits a job description. Score 0-100 using this rubric:
role/title alignment 25, required skills evidenced in the resume 35, relevant experience and projects 25,
seniority fit 15. Be strict and consistent. Return {"score": <integer>, "reason": "<max 25 words>"}"""


class TailorState(TypedDict, total=False):
    jd_text: str
    resume_ids: list[str]
    profiles: list[dict]
    corpus: str
    threshold: int
    max_attempts: int
    jd: dict
    merged: dict
    evidence: list[dict]
    used_semantic: bool
    attempt: int
    feedback: str
    draft: dict
    warnings: list[str]
    tex: str
    pdf: bytes | None
    pdf_compiled: bool
    compile_error: str
    report: dict
    best: dict
    done: bool
    options: dict


def _emit(config: RunnableConfig, event: dict) -> None:
    emit = (config.get("configurable") or {}).get("emit")
    if emit:
        emit(event)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d[\d,.]*\s*(?:%|k|x|\+)?", text.lower()))


def _num_key(n: str) -> str:
    return re.sub(r"\s+", "", n)


def _fuzzy_get(items: dict, name: str):
    """Find the library item a (possibly slightly renamed) draft item refers to."""
    key = _norm(name)
    if not key:
        return None
    if key in items:
        return items[key]
    for k, v in items.items():
        if len(k) >= 4 and len(key) >= 4 and (k in key or key in k):
            return v
    best, best_ratio = None, 0.0
    for k, v in items.items():
        ratio = difflib.SequenceMatcher(None, k, key).ratio()
        if ratio > best_ratio:
            best, best_ratio = v, ratio
    return best if best_ratio >= 0.82 else None


def _closest(bullet: str, originals: list[str]) -> str | None:
    words = set(re.findall(r"[a-z0-9+#]{3,}", bullet.lower()))
    best, best_score = None, 0.0
    for o in originals:
        ow = set(re.findall(r"[a-z0-9+#]{3,}", o.lower()))
        score = len(words & ow) / (len(words | ow) or 1)
        if score > best_score:
            best, best_score = o, score
    return best


def ground_profile(
    draft: Profile, merged: Profile, corpus: str, jd: JDAnalysis | None = None,
) -> tuple[Profile, list[str]]:
    """Force the draft to be a subset of the library: identity, roles, schools and skills come from
    the library; summary and bullets that claim numbers, skills or employers the library doesn't
    support are reverted to the candidate's own wording."""
    warnings: list[str] = []
    pool = {s.lower() for skills in merged.skills.values() for s in skills}

    def claims(text: str) -> list[str]:
        return grounding.unsupported_claims(text, corpus, jd)

    out = Profile(
        name=merged.name, email=merged.email, phone=merged.phone, location=merged.location,
        links=merged.links[:3], education=[e.model_copy(deep=True) for e in merged.education],
        certifications=merged.certifications[:6], achievements=merged.achievements[:4],
    )

    # Summary
    summary = draft.summary.strip()
    if summary and (bad := claims(summary)):
        warnings.append(
            f"Summary mentioned things not in your library ({', '.join(bad[:4])}); used your original summary."
        )
        summary = merged.summary
    out.summary = summary or merged.summary

    # Skills
    removed = []
    for group, skills in draft.skills.items():
        kept = []
        for s in skills:
            if s.lower() in pool or ats.term_in_text(s, corpus):
                kept.append(s)
            else:
                removed.append(s)
        if kept:
            out.skills[group] = list(dict.fromkeys(kept))
    if removed:
        warnings.append("Removed skills not found in your library: " + ", ".join(removed[:12]))
    if not out.skills:
        out.skills = {g: list(s) for g, s in merged.skills.items()}

    # Experience: every library role is kept, in library order; text comes from the draft only if grounded
    draft_by_key = {_norm(e.company): e for e in draft.experience if e.company}
    for role in merged.experience:
        match = _fuzzy_get(draft_by_key, role.company)
        originals = role.bullets
        bullets: list[str] = []
        for b in (match.bullets if match else []):
            if bad := claims(b):
                fix = _closest(b, originals)
                warnings.append(
                    f"A bullet at {role.company} mentioned things not in your library ({', '.join(bad[:3])}); "
                    "reverted to your original wording."
                )
                b = fix or ""
            if b and b not in bullets:
                bullets.append(b)
        if not bullets:
            bullets = originals[:3]
        out.experience.append(Experience(
            company=role.company, title=role.title, location=role.location, dates=role.dates,
            bullets=bullets[:MAX_ROLE_BULLETS],
        ))

    # Projects: only those that exist in the library
    lib_projects = {_norm(p.name): p for p in merged.projects}
    for proj in draft.projects:
        lib = _fuzzy_get(lib_projects, proj.name)
        if not lib:
            warnings.append(f"Dropped project '{proj.name}' (not in your library).")
            continue
        originals = lib.bullets
        bullets = []
        for b in proj.bullets:
            if bad := claims(b):
                warnings.append(
                    f"A bullet in project '{lib.name}' mentioned things not in your library ({', '.join(bad[:3])}); "
                    "reverted to your original wording."
                )
                b = _closest(b, originals) or ""
            if b and b not in bullets:
                bullets.append(b)
        out.projects.append(Project(
            name=lib.name, tech=lib.tech, link=lib.link, bullets=(bullets or originals)[:MAX_PROJECT_BULLETS],
        ))
        if len(out.projects) >= MAX_PROJECTS:
            break
    return out, warnings


# ── Nodes ────────────────────────────────────────────────────────────────────

async def analyze_jd(jd_text: str) -> JDAnalysis:
    jd_key = hashlib.sha256(jd_text.strip().encode("utf-8")).hexdigest()
    if jd_key in _JD_CACHE:
        logger.info("Reusing cached JD analysis for repeated paste")
        _JD_CACHE.move_to_end(jd_key)
        return _JD_CACHE[jd_key].model_copy(deep=True)   # callers may modify their copy

    from_llm = True
    try:
        data = await llm_json(_JD_PROMPT, f"Job description:\n\n{jd_text[:8000]}")
        jd = JDAnalysis.model_validate(data)
    except Exception as exc:
        logger.warning("LLM JD analysis failed (%s); using keyword fallback", exc)
        jd = ats.fallback_jd_analysis(jd_text)
        from_llm = False
    # Make sure well-known tech terms present in the JD are never ignored
    known = {t.lower() for t in jd.must_have + jd.nice_to_have}
    for term in ats.TECH_TERMS:
        if term not in known and ats.term_in_text(term, jd_text) and len(jd.nice_to_have) < 16:
            jd.nice_to_have.append(term)
    if not (jd.must_have or jd.nice_to_have):
        raise ValueError("Could not find any skills or requirements in the job description. Paste the full JD.")
    # Only the LLM's analysis is kept: after a failure, the next paste of this JD tries the LLM again
    if from_llm:
        _JD_CACHE[jd_key] = jd.model_copy(deep=True)
        if len(_JD_CACHE) > _JD_CACHE_SIZE:
            _JD_CACHE.popitem(last=False)
    return jd


async def node_analyze(state: TailorState, config: RunnableConfig) -> dict:
    _emit(config, {"type": "step", "step": "analyze", "status": "running", "message": "Analyzing the job description"})
    jd = await analyze_jd(state["jd_text"])
    _emit(config, {
        "type": "step", "step": "analyze", "status": "done",
        "message": f"Found {len(jd.must_have)} required and {len(jd.nice_to_have)} preferred skills"
                   + (f" for {jd.title}" if jd.title else ""),
    })
    return {"jd": jd.model_dump()}


async def node_retrieve(state: TailorState, config: RunnableConfig) -> dict:
    _emit(config, {"type": "step", "step": "retrieve", "status": "running", "message": "Searching your resume library"})
    jd = JDAnalysis.model_validate(state["jd"])
    profiles = [Profile.model_validate(p) for p in state["profiles"]]
    queries = [f"experience with {t}" for t in jd.must_have[:8]] + jd.responsibilities[:5]
    if jd.title:
        queries.append(jd.title)

    evidence: list[dict] = []
    semantic = False
    try:
        evidence = await library.retrieve_items(queries, state["resume_ids"])
        semantic = bool(evidence)
    except Exception as exc:
        logger.warning("Vector retrieval failed (%s); using keyword ranking", exc)
    if not evidence:
        evidence = library.lexical_items(queries, profiles)

    _emit(config, {
        "type": "step", "step": "retrieve", "status": "done",
        "message": f"Selected {len(evidence)} relevant items from {len(profiles)} resume(s)"
                   + ("" if semantic else " (keyword ranking)"),
    })
    return {"evidence": evidence, "used_semantic": semantic, "attempt": 0, "feedback": "", "warnings": []}


def _writer_context(state: TailorState) -> str:
    merged = Profile.model_validate(state["merged"])
    relevant = {_norm(i["text"]) for i in state["evidence"]}
    lines = ["ROLES (keep all):"]
    for exp in merged.experience:
        lines.append(f"- {exp.title} at {exp.company} ({exp.dates})")
        for b in exp.bullets:
            tag = "[RELEVANT] " if any(_norm(b) in r or r.endswith(_norm(b)) for r in relevant) else ""
            lines.append(f"    * {tag}{b}")

    ranked_projects = []
    evidence_text = " ".join(i["text"].lower() for i in state["evidence"])
    for proj in merged.projects:
        ranked_projects.append((proj.name.lower() in evidence_text, proj))
    ranked_projects.sort(key=lambda x: not x[0])
    lines.append("\nPROJECTS:")
    for is_rel, proj in ranked_projects[:8]:
        lines.append(f"- {proj.name} ({proj.tech}){' [RELEVANT]' if is_rel else ''}")
        lines += [f"    * {b}" for b in proj.bullets]

    lines.append("\nSKILLS POOL:")
    lines += [f"- {g}: {', '.join(s)}" for g, s in merged.skills.items()]
    if merged.summary:
        lines.append(f"\nORIGINAL SUMMARY: {merged.summary}")
    return "\n".join(lines)


async def node_write(state: TailorState, config: RunnableConfig) -> dict:
    attempt = state.get("attempt", 0) + 1
    _emit(config, {
        "type": "step", "step": "write", "status": "running", "attempt": attempt,
        "message": f"Writing the tailored resume (attempt {attempt} of {state['max_attempts']})",
    })
    jd = JDAnalysis.model_validate(state["jd"])
    system = _WRITER_PROMPT.replace("{max_role_bullets}", str(MAX_ROLE_BULLETS)) \
        .replace("{max_projects}", str(MAX_PROJECTS)).replace("{max_project_bullets}", str(MAX_PROJECT_BULLETS))
    user = (
        f"TARGET ROLE: {jd.title or 'n/a'} {('at ' + jd.company) if jd.company else ''}\n"
        f"REQUIRED: {', '.join(jd.must_have)}\nPREFERRED: {', '.join(jd.nice_to_have)}\n"
        f"RESPONSIBILITIES: {'; '.join(jd.responsibilities)}\n\n"
        f"CANDIDATE LIBRARY\n{_writer_context(state)}\n"
    )
    if state.get("feedback"):
        user += f"\nFEEDBACK FROM THE PREVIOUS ATTEMPT (fix these, truthfully):\n{state['feedback']}\n"

    data = await llm_json(system, user)
    merged = Profile.model_validate(state["merged"])
    draft, warnings = ground_profile(Profile.model_validate(data), merged, state["corpus"], jd)
    _emit(config, {"type": "step", "step": "write", "status": "done", "attempt": attempt,
                   "message": f"Draft {attempt} written and checked against your library"})
    return {"draft": draft.model_dump(), "warnings": warnings, "attempt": attempt}


async def judge_fit(text: str, jd: JDAnalysis, jd_text: str) -> tuple[int, str] | None:
    try:
        data = await llm_json(_FIT_PROMPT, f"JOB DESCRIPTION:\n{jd_text[:5000]}\n\nRESUME:\n{text[:7000]}")
        return max(0, min(100, int(data.get("score", 0)))), str(data.get("reason", ""))[:200]
    except Exception as exc:
        logger.warning("Fit judge unavailable: %s", exc)
        return None


async def score_text(
    text: str, jd: JDAnalysis, jd_text: str, meta: dict | None, plain_bullets: list[str] | None = None,
    with_fit: bool = True,
) -> ats.AtsReport:
    fit = await judge_fit(text, jd, jd_text) if with_fit else None
    return ats.build_report(text, jd, meta, fit, plain_bullets)


async def score_profile(
    profile: Profile, options: RenderOptions | None, jd: JDAnalysis, jd_text: str, with_fit: bool = True
) -> dict:
    """Render, compile and ATS-score a profile. Used for every writer draft and again after the user edits one."""
    tex = render_latex(profile, options)

    pdf, compile_error = (None, "")
    template_fallback = False
    if compiler_available():
        pdf, compile_error = await compile_pdf(tex)
        if pdf is None and options is not None and options.preamble:
            # The user's own template didn't compile with this content: use the built-in layout instead
            fallback = options.model_copy(update={"preamble": None})
            tex = render_latex(profile, fallback)
            pdf, compile_error = await compile_pdf(tex)
            template_fallback = pdf is not None

    if pdf:
        text, meta = await asyncio.to_thread(ats.pdf_text_and_meta, pdf)
        report = await score_text(text, jd, jd_text, meta, with_fit=with_fit)
    else:
        text = profile_plain_text(profile)
        report = await score_text(text, jd, jd_text, None, with_fit=with_fit)

    result = report.to_dict()
    result["pdf_compiled"] = pdf is not None
    # The compiler exists but the LaTeX failed: never hand out code that doesn't compile
    compile_failed = compiler_available() and pdf is None
    warnings: list[str] = []
    if compile_failed:
        first_line = next((ln for ln in compile_error.splitlines() if ln.startswith("!")), compile_error[:120])
        warnings.append(f"The LaTeX could not be compiled, so there is nothing to download ({first_line.strip()}).")
    if template_fallback:
        warnings.append("Your base template could not be compiled with this content, so the built-in layout was used.")
    dropped = unsupported_characters(profile)
    if dropped:
        warnings.append(
            "These characters cannot be shown by the LaTeX template and were left out: " + " ".join(dropped[:12])
        )
    return {
        "score": report.total, "tex": tex, "pdf": pdf, "report": result, "warnings": warnings,
        "compile_error": compile_error, "compile_failed": compile_failed,
    }


async def node_score(state: TailorState, config: RunnableConfig) -> dict:
    attempt = state["attempt"]
    _emit(config, {"type": "step", "step": "score", "status": "running", "attempt": attempt,
                   "message": "Compiling the PDF and computing the ATS score"})
    jd = JDAnalysis.model_validate(state["jd"])
    profile = Profile.model_validate(state["draft"])
    options = RenderOptions.model_validate(state.get("options") or {})
    # Skip LLM fit judge on early attempts to save latency and token quota; evaluate fit on final attempt or if threshold reached
    is_final_attempt = attempt >= state.get("max_attempts", 3)
    scored = await score_profile(profile, options, jd, state["jd_text"], with_fit=is_final_attempt)
    if not is_final_attempt and scored["score"] >= state.get("threshold", 82):
        scored = await score_profile(profile, options, jd, state["jd_text"], with_fit=True)

    report, pdf, tex = scored["report"], scored["pdf"], scored["tex"]
    warnings = list(state.get("warnings", [])) + scored["warnings"]
    best = state.get("best") or {}
    candidate = {
        "score": scored["score"], "draft": state["draft"], "tex": tex, "pdf": pdf, "report": report,
        "warnings": warnings, "attempt": attempt, "compile_error": scored["compile_error"],
        "compile_failed": scored["compile_failed"],
    }
    if scored["score"] >= best.get("score", -1):
        best = candidate

    _emit(config, {
        "type": "step", "step": "score", "status": "done", "attempt": attempt, "score": scored["score"],
        "message": f"ATS score {scored['score']} (needs {state['threshold']})",
        "components": [{"label": c["label"], "score": c["score"]} for c in report["components"]],
    })
    return {"tex": tex, "pdf": pdf, "pdf_compiled": pdf is not None, "compile_error": scored["compile_error"],
            "report": report, "best": best}


_BULLET_PROMPT = """You rewrite resume bullets for one job. You are given the SOURCE BULLETS of a single role or project from the
candidate's own library.

RULES (breaking any is a failure):
1. Use ONLY facts in the SOURCE BULLETS. Never add tools, skills, numbers, results or scope that are not there.
2. Keep every number exactly as written. Do not round, scale or invent metrics.
3. One line each, starting with a strong past-tense verb, 12-30 words.
4. Use the job's wording for a skill ONLY if a source bullet shows the candidate really used it.
5. Give three genuinely different options (different emphasis or phrasing).
6. If a USER NOTE is given, follow it as long as it does not break rules 1-2.

Return JSON: {"options": ["", "", ""]}"""


def option_is_grounded(text: str, corpus: str, jd: JDAnalysis) -> bool:
    """A rewritten bullet may not add numbers, skills or employers the library never mentions."""
    return grounding.is_supported(text, corpus, jd)


async def regenerate_bullet(
    sources: list[str], jd: JDAnalysis, corpus: str, current: str = "", already_used: list[str] | None = None,
    instruction: str = "",
) -> list[dict]:
    """Up to three grounded alternatives for one bullet (or a new bullet when *current* is empty)."""
    lines = [
        f"TARGET ROLE: {jd.title or 'n/a'}",
        f"REQUIRED: {', '.join(jd.must_have)}",
        f"PREFERRED: {', '.join(jd.nice_to_have)}",
        "",
        "SOURCE BULLETS:",
        *(f"- {b}" for b in sources),
        "",
    ]
    if current:
        lines += ["BULLET TO REWRITE:", current, ""]
    else:
        lines += ["Write NEW bullets that highlight different facts from the sources than the ones already used.", ""]
    if already_used:
        lines += ["ALREADY IN THE RESUME (do not repeat):", *(f"- {b}" for b in already_used), ""]
    if instruction.strip():
        lines.append(f"USER NOTE: {instruction.strip()[:200]}")
    user = "\n".join(lines)

    data = await llm_json(_BULLET_PROMPT, user)
    seen, out = set(), []
    for raw in data.get("options", []) if isinstance(data.get("options"), list) else []:
        text = re.sub(r"\s+", " ", str(raw or "")).strip().lstrip("-* ").strip()
        if not text or len(text) > 400 or _norm(text) in seen or _norm(text) == _norm(current):
            continue
        if not option_is_grounded(text, corpus, jd):
            continue
        seen.add(_norm(text))
        out.append({"text": text, "source": _closest(text, sources)})
    return out[:3]


def route_after_score(state: TailorState) -> str:
    if state["report"]["total"] >= state["threshold"]:
        return "done"
    if state["attempt"] >= state["max_attempts"]:
        return "done"
    return "feedback"


async def node_feedback(state: TailorState, config: RunnableConfig) -> dict:
    report = state["report"]
    corpus = state["corpus"]
    addable = [t for t in report["missing_must"] + report["missing_nice"] if ats.term_in_text(t, corpus)]
    unavailable = [t for t in report["missing_must"] if not ats.term_in_text(t, corpus)]

    parts = []
    if addable:
        parts.append(
            "These job terms ARE supported by the candidate's library but are missing from the resume. "
            "Work each in naturally where the library backs it: " + ", ".join(addable[:12])
        )
    if unavailable:
        parts.append("The library has NO evidence for: " + ", ".join(unavailable[:10]) + ". Do NOT add these.")
    for comp in report["components"]:
        parts += comp["findings"][:3] if comp["key"] != "keywords" else []
    feedback = "\n".join(f"- {p}" for p in parts)
    _emit(config, {"type": "step", "step": "revise", "status": "done", "attempt": state["attempt"],
                   "message": f"Score {report['total']} is below {state['threshold']}; revising"})
    return {"feedback": feedback}


def _compile_graph():
    graph = StateGraph(TailorState)
    graph.add_node("analyze", node_analyze)
    graph.add_node("retrieve", node_retrieve)
    graph.add_node("write", node_write)
    graph.add_node("score", node_score)
    graph.add_node("feedback", node_feedback)
    graph.add_edge(START, "analyze")
    graph.add_edge("analyze", "retrieve")
    graph.add_edge("retrieve", "write")
    graph.add_edge("write", "score")
    graph.add_conditional_edges("score", route_after_score, {"done": END, "feedback": "feedback"})
    graph.add_edge("feedback", "write")
    return graph.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = _compile_graph()
    return _graph


async def run_tailoring(
    jd_text: str,
    resume_rows: list[Any],
    threshold: int,
    max_attempts: int = 3,
    options: RenderOptions | None = None,
) -> AsyncGenerator[dict, None]:
    """Run the graph, yielding progress events; the last event is {"type": "final", "state": {...}}.
    A heartbeat is sent every 10s so proxies don't close the idle stream."""
    profiles = [Profile.model_validate(r.profile) for r in resume_rows]
    corpus = "\n".join(r.raw_text for r in resume_rows)
    merged = library.merge_profiles(profiles)

    queue: asyncio.Queue = asyncio.Queue()
    initial: TailorState = {
        "jd_text": jd_text,
        "resume_ids": [str(r.id) for r in resume_rows],
        "profiles": [p.model_dump() for p in profiles],
        "corpus": corpus,
        "merged": merged.model_dump(),
        "threshold": threshold,
        "max_attempts": max_attempts,
        "options": (options or RenderOptions()).model_dump(),
    }

    async def worker():
        try:
            final = await get_graph().ainvoke(
                initial, config={"configurable": {"emit": queue.put_nowait}, "recursion_limit": 40}
            )
            queue.put_nowait({"type": "final", "state": final})
        except Exception as exc:
            logger.exception("Tailoring graph failed")
            queue.put_nowait({"type": "error", "message": client_error_message(exc, "tailoring the resume")})
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(worker())
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=10)
            except asyncio.TimeoutError:
                yield {"type": "heartbeat"}
                continue
            if event is None:
                break
            yield event
    finally:
        if not task.done():
            task.cancel()

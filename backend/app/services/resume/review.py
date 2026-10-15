"""
Review helpers for an editable resume draft.

    annotate()      where every bullet came from: the user's library wording, a rewording of it, or new text
    claims_check()  things the user typed that the library does not support (a warning, never a block)
    gap_report()    required skills the resume lacks, split into "your library has it" and "you would need it"

These are pure functions over Profile objects so they can be tested without a database or an LLM.
"""

from __future__ import annotations

import difflib
import re

from app.services.resume import ats
from app.services.resume.latex import profile_plain_text
from app.services.resume.schemas import JDAnalysis, Profile

_REWORD_MIN_SIMILARITY = 0.25    # word overlap needed to call a bullet a rewording of a library bullet
_NAME_MATCH = 0.82


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#]{3,}", s.lower()))


def _similarity(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / (len(wa | wb) or 1)


def find_item(items: list, name: str, attr: str):
    """The library role/project a draft item refers to (exact, contained, or close name)."""
    key = _norm(name)
    if not key:
        return None
    best, best_ratio = None, 0.0
    for item in items:
        other = _norm(getattr(item, attr))
        if other == key:
            return item
        if len(other) >= 4 and len(key) >= 4 and (other in key or key in other):
            return item
        ratio = difflib.SequenceMatcher(None, other, key).ratio()
        if ratio > best_ratio:
            best, best_ratio = item, ratio
    return best if best_ratio >= _NAME_MATCH else None


def _bullet_sources(bullets: list[str], originals: list[str]) -> list[dict]:
    rows = []
    for text in bullets:
        exact = next((o for o in originals if _norm(o) == _norm(text)), None)
        if exact is not None:
            rows.append({"text": text, "status": "original", "source": exact})
            continue
        closest = max(originals, key=lambda o: _similarity(text, o), default=None)
        if closest is not None and _similarity(text, closest) >= _REWORD_MIN_SIMILARITY:
            rows.append({"text": text, "status": "reworded", "source": closest})
        else:
            rows.append({"text": text, "status": "new", "source": None})
    return rows


def annotate(draft: Profile, library: Profile) -> dict:
    """Per role and project: each bullet with its status and library source, plus library bullets left out."""
    experience = []
    for role in draft.experience:
        lib = find_item(library.experience, role.company, "company")
        originals = lib.bullets if lib else []
        rows = _bullet_sources(role.bullets, originals)
        used = {_norm(r["source"]) for r in rows if r["source"]}
        experience.append({
            "company": role.company, "title": role.title, "in_library": lib is not None,
            "bullets": rows, "unused": [o for o in originals if _norm(o) not in used],
        })

    projects = []
    for proj in draft.projects:
        lib = find_item(library.projects, proj.name, "name")
        originals = lib.bullets if lib else []
        rows = _bullet_sources(proj.bullets, originals)
        used = {_norm(r["source"]) for r in rows if r["source"]}
        projects.append({
            "name": proj.name, "in_library": lib is not None,
            "bullets": rows, "unused": [o for o in originals if _norm(o) not in used],
        })

    in_draft = {_norm(p.name) for p in draft.projects}
    left_out = [
        {"name": p.name, "tech": p.tech, "bullets": p.bullets}
        for p in library.projects if _norm(p.name) not in in_draft
    ]
    pool = {s.lower() for skills in library.skills.values() for s in skills}
    new_skills = [s for skills in draft.skills.values() for s in skills if s.lower() not in pool]
    return {"experience": experience, "projects": projects, "left_out_projects": left_out, "new_skills": new_skills}


# ── Claims the library does not support ──────────────────────────────────────

def _numbers(text: str) -> set[str]:
    return {re.sub(r"\s+", "", n) for n in re.findall(r"\d[\d,.]*\s*(?:%|k|x|\+)?", text.lower())}


def claims_check(draft: Profile, library: Profile, corpus: str) -> list[str]:
    """Warnings about edited content the library doesn't back. The user decides; nothing is removed."""
    warnings: list[str] = []
    known_numbers = _numbers(corpus)
    pool = {s.lower() for skills in library.skills.values() for s in skills}

    removed = [
        s for skills in draft.skills.values() for s in skills
        if s.lower() not in pool and not ats.term_in_text(s, corpus)
    ]
    if removed:
        warnings.append("Skills not found in your library: " + ", ".join(dict.fromkeys(removed[:12])) +
                        ". Keep only what you can speak to in an interview.")

    def check_text(where: str, text: str) -> None:
        extra = sorted(_numbers(text) - known_numbers)
        if extra:
            warnings.append(f"{where}: the number {', '.join(extra[:3])} is not in your library.")

    if draft.summary:
        check_text("Summary", draft.summary)
    for role in draft.experience:
        if find_item(library.experience, role.company, "company") is None:
            warnings.append(f"The role at {role.company or 'an unnamed company'} is not in your library.")
        for b in role.bullets:
            check_text(role.company or "Experience", b)
    for proj in draft.projects:
        if find_item(library.projects, proj.name, "name") is None:
            warnings.append(f"The project {proj.name or '(unnamed)'} is not in your library.")
        for b in proj.bullets:
            check_text(proj.name or "Project", b)
    return list(dict.fromkeys(warnings))


# ── Gap report ───────────────────────────────────────────────────────────────

def _library_bullet_for(term: str, library: Profile) -> dict | None:
    for role in library.experience:
        for b in role.bullets:
            if ats.term_in_text(term, b):
                return {"kind": "experience", "item": role.company, "bullet": b}
    for proj in library.projects:
        for b in proj.bullets:
            if ats.term_in_text(term, b):
                return {"kind": "project", "item": proj.name, "bullet": b}
    return None


def _keyword_gain(text: str, extra_terms: list[str], jd: JDAnalysis, report: dict) -> int:
    """Estimated rise in the total score if *extra_terms* were evidenced in the resume."""
    if not extra_terms:
        return 0
    comps = report.get("components", [])
    weight = next((c["weight"] for c in comps if c["key"] == "keywords"), 0)
    total_weight = sum(c["weight"] for c in comps) or 1
    before = ats._keyword_component(text, jd, weight)[0].score
    after = ats._keyword_component(text + "\n" + " ".join(extra_terms), jd, weight)[0].score
    return round((after - before) * weight / total_weight)


def gap_report(draft: Profile, library: Profile, jd: JDAnalysis, report: dict, corpus: str) -> dict:
    """What stands between this draft and a higher score, and how much each part could be worth.

    ``usable`` terms are in the user's library but missing from the draft: adding them is honest.
    ``lacking`` terms are not in the library at all: only gaining the skill closes them, so they are estimates.
    """
    must = report.get("missing_must", [])
    nice = report.get("missing_nice", [])
    usable = [t for t in must + nice if ats.term_in_text(t, corpus)]
    lacking_must = [t for t in must if t not in usable]
    lacking_nice = [t for t in nice if t not in usable]

    text = profile_plain_text(draft)
    total = int(report.get("total", 0))
    gain_usable = _keyword_gain(text, usable, jd, report)
    gain_lacking = _keyword_gain(text + "\n" + " ".join(usable), lacking_must + lacking_nice, jd, report)
    return {
        "score": total,
        "usable": [
            {"term": t, "from": _library_bullet_for(t, library)} for t in usable[:12]
        ],
        "usable_score": min(100, total + gain_usable),
        "lacking_must": lacking_must,
        "lacking_nice": lacking_nice,
        "with_lacking_score": min(100, total + gain_usable + gain_lacking),
    }

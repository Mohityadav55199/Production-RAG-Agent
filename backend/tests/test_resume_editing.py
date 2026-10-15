"""Editable drafts: templates, per-bullet sources, claim warnings, gap report, grounded regeneration, re-scoring."""

import asyncio

import pytest
from pydantic import ValidationError

from app.services.resume import agents, latex
from app.services.resume.review import annotate, claims_check, find_item, gap_report
from app.services.resume.schemas import JDAnalysis, Profile, RenderOptions
from tests.sample_data import LIBRARY_CORPUS, library_profile

ORIGINALS = library_profile().experience[0].bullets
JD = JDAnalysis(must_have=["Python", "FastAPI", "Kubernetes"], nice_to_have=["React", "Terraform"])


def draft_with(bullets: list[str]) -> Profile:
    p = library_profile()
    p.experience[0].bullets = bullets
    return p


# ── Templates ────────────────────────────────────────────────────────────────

def headings(tex: str) -> list[str]:
    return [line[len("\\sectionhead{"):-1] for line in tex.splitlines() if line.startswith("\\sectionhead{")]


def test_default_render_matches_the_classic_template():
    assert latex.render_latex(library_profile()) == latex.render_latex(library_profile(), RenderOptions())


def test_templates_differ_in_look_and_order():
    p = library_profile()
    classic = latex.render_latex(p, RenderOptions(template="classic"))
    compact = latex.render_latex(p, RenderOptions(template="compact"))
    skills_first = latex.render_latex(p, RenderOptions(template="skills_first"))
    assert headings(classic)[:2] == ["Summary", "Skills"]
    assert headings(skills_first)[:2] == ["Skills", "Summary"]
    assert headings(compact) == headings(classic) and compact != classic
    assert "\\normalsize\\bfseries" in compact and "\\large\\bfseries" in classic


def test_font_size_and_margin_reach_the_document():
    tex = latex.render_latex(library_profile(), RenderOptions(font_pt=11, margin_in=0.75))
    assert "\\documentclass[11pt,letterpaper]{article}" in tex
    assert "\\usepackage[margin=0.75in]{geometry}" in tex


@pytest.mark.parametrize("bad", [
    {"template": "fancy"}, {"font_pt": 9}, {"margin_in": 0.2}, {"margin_in": "0.6in}\\input{x"},
])
def test_layout_options_are_a_closed_whitelist(bad):
    with pytest.raises(ValidationError):
        RenderOptions(**bad)


@pytest.mark.skipif(not latex.compiler_available(), reason="pdflatex is not installed")
@pytest.mark.parametrize("template", ["classic", "compact", "skills_first"])
def test_every_template_compiles(template):
    tex = latex.render_latex(library_profile(), RenderOptions(template=template, font_pt=11, margin_in=0.5))
    pdf, error = asyncio.run(latex.compile_pdf(tex))
    assert error == "" and pdf and pdf.startswith(b"%PDF")


# ── Per-bullet sources ───────────────────────────────────────────────────────

def test_bullets_are_marked_original_reworded_or_new():
    reworded = "Built FastAPI REST APIs handling 50k requests/day and cutting latency by 35%."
    fresh = "Organised weekly knowledge-sharing sessions for the whole engineering team."
    out = annotate(draft_with([ORIGINALS[0], reworded, fresh]), library_profile())["experience"][0]
    statuses = [b["status"] for b in out["bullets"]]
    assert statuses == ["original", "reworded", "new"]
    assert out["bullets"][1]["source"] == ORIGINALS[0]
    assert out["bullets"][2]["source"] is None
    assert set(out["unused"]) == set(ORIGINALS[1:])          # library bullets the draft left out


def test_projects_left_out_and_new_skills_are_reported():
    lib = library_profile()
    lib.projects.append(lib.projects[0].model_copy(update={"name": "Other App", "bullets": ["Built another app."]}))
    draft = library_profile()
    draft.skills["Tools"].append("Kubernetes")
    out = annotate(draft, lib)
    assert [p["name"] for p in out["left_out_projects"]] == ["Other App"]
    assert out["new_skills"] == ["Kubernetes"]


def test_find_item_tolerates_renames_but_not_strangers():
    lib = library_profile()
    assert find_item(lib.experience, "ACME", "company") is lib.experience[0]
    assert find_item(lib.experience, "Globex", "company") is None


# ── Claims the library does not back ─────────────────────────────────────────

def test_edits_the_library_does_not_support_are_warned_about_not_removed():
    draft = draft_with(["Cut costs by 90% with Kubernetes.", ORIGINALS[0]])
    draft.skills["Tools"].append("Kubernetes")
    draft.experience.append(draft.experience[0].model_copy(update={"company": "Globex"}))
    warnings = " | ".join(claims_check(draft, library_profile(), LIBRARY_CORPUS))
    assert "Kubernetes" in warnings and "90%" in warnings and "Globex" in warnings
    assert "Cut costs by 90% with Kubernetes." in draft.experience[0].bullets      # the draft is untouched


def test_an_unchanged_library_draft_has_no_warnings():
    assert claims_check(library_profile(), library_profile(), LIBRARY_CORPUS) == []


# ── Gap report ───────────────────────────────────────────────────────────────

REPORT = {
    "total": 70,
    "components": [{"key": "keywords", "weight": 50}, {"key": "parsing", "weight": 30}, {"key": "format", "weight": 20}],
    "missing_must": ["Kubernetes", "Docker"],
    "missing_nice": ["Terraform"],
}


def test_gap_splits_terms_the_library_has_from_terms_it_lacks():
    gap = gap_report(draft_with([ORIGINALS[0]]), library_profile(), JD, REPORT, LIBRARY_CORPUS)
    assert [u["term"] for u in gap["usable"]] == ["Docker"]
    assert gap["usable"][0]["from"]["bullet"] == ORIGINALS[2]               # the library bullet that proves it
    assert gap["lacking_must"] == ["Kubernetes"] and gap["lacking_nice"] == ["Terraform"]
    assert gap["score"] == 70
    assert gap["score"] <= gap["usable_score"] <= gap["with_lacking_score"] <= 100


def test_gap_with_nothing_missing_changes_nothing():
    full = {**REPORT, "missing_must": [], "missing_nice": []}
    gap = gap_report(library_profile(), library_profile(), JD, full, LIBRARY_CORPUS)
    assert gap["usable"] == [] and gap["usable_score"] == gap["with_lacking_score"] == 70


# ── Bullet regeneration ──────────────────────────────────────────────────────

def fake_llm(options):
    async def call(system, user, retries=3):
        call.prompts.append(user)
        return {"options": options}

    call.prompts = []
    return call


def regen(monkeypatch, options, **kw):
    llm = fake_llm(options)
    monkeypatch.setattr(agents, "llm_json", llm)
    out = asyncio.run(agents.regenerate_bullet(ORIGINALS, JD, LIBRARY_CORPUS, **kw))
    return out, llm


def test_regeneration_keeps_only_options_grounded_in_the_library(monkeypatch):
    good = "Engineered FastAPI REST APIs serving 50k requests/day and cutting latency by 35%."
    out, llm = regen(monkeypatch, [
        good,
        "Cut latency by 80% with FastAPI.",                       # number the library never mentions
        "Ran Kubernetes clusters for FastAPI services.",          # a job skill the library does not show
        good,                                                     # duplicate
        "",
    ], current=ORIGINALS[0], instruction="Lead with FastAPI")
    assert [o["text"] for o in out] == [good]
    assert out[0]["source"] == ORIGINALS[0]
    assert "USER NOTE: Lead with FastAPI" in llm.prompts[0] and ORIGINALS[0] in llm.prompts[0]


def test_regeneration_returns_nothing_when_every_option_is_ungrounded(monkeypatch):
    out, _ = regen(monkeypatch, ["Improved revenue by 300% using Kubernetes."], current=ORIGINALS[0])
    assert out == []


def test_new_bullet_prompt_lists_what_is_already_used(monkeypatch):
    _, llm = regen(monkeypatch, [], already_used=[ORIGINALS[0]])
    assert "ALREADY IN THE RESUME" in llm.prompts[0] and "BULLET TO REWRITE" not in llm.prompts[0]


# ── Re-scoring an edited draft ───────────────────────────────────────────────

def test_rescore_reflects_the_edit(monkeypatch):
    async def no_judge(*_a, **_k):
        return None

    monkeypatch.setattr(agents, "compiler_available", lambda: False)
    monkeypatch.setattr(agents, "judge_fit", no_judge)
    jd = JDAnalysis(must_have=["Python", "FastAPI", "Docker"], nice_to_have=[])

    base = asyncio.run(agents.score_profile(draft_with([ORIGINALS[0]]), None, jd, "jd", with_fit=False))
    better = asyncio.run(agents.score_profile(draft_with(ORIGINALS), RenderOptions(template="compact"), jd, "jd", with_fit=False))
    assert better["score"] >= base["score"]
    assert "Docker" in base["report"]["missing_must"] or base["score"] < 100
    assert better["pdf"] is None and better["compile_failed"] is False
    assert "\\normalsize\\bfseries" in better["tex"]

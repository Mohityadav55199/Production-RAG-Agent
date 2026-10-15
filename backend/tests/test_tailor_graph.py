"""
The multi-agent pipeline end to end, with a scripted fake LLM (no network).

The fake writer misbehaves on purpose: it invents skills, an employer, a project and numbers.
The pipeline must strip all of it and still apply the score gate honestly.
"""

import asyncio
import types

import pytest

from app.services.resume import agents, library
from app.services.resume.schemas import Profile
from tests.sample_data import LIBRARY_CORPUS, LIBRARY_PROFILE

THRESHOLD = 82
ORIGINAL_BULLETS = LIBRARY_PROFILE["experience"][0]["bullets"]

ROW = types.SimpleNamespace(
    id="11111111-1111-1111-1111-111111111111", profile=LIBRARY_PROFILE, raw_text=LIBRARY_CORPUS
)


class FakeLLM:
    """Plays the JD analyst, the writer and the fit judge; records every prompt it receives."""

    def __init__(self, must_have: list[str]):
        self.must_have = must_have
        self.writer_prompts: list[str] = []

    async def __call__(self, system: str, user: str, retries: int = 3) -> dict:
        if "analyse job descriptions" in system:
            return {"title": "Backend Engineer", "company": "Initech", "seniority": "mid",
                    "must_have": self.must_have, "nice_to_have": ["React"], "responsibilities": ["build APIs"]}
        if "resume writer" in system:
            self.writer_prompts.append(user)
            return {
                "summary": "Backend engineer with 10 years of experience and a 300% growth record.",
                "skills": {"Languages": ["Python", "Kubernetes", "Go"],
                           "Tools": ["Docker", "PostgreSQL", "Git"]},
                "experience": [
                    {"company": "Acme", "title": "Staff Engineer",
                     "bullets": ["Cut infrastructure cost by 90% using Kubernetes.", *ORIGINAL_BULLETS]},
                    {"company": "Google", "title": "SWE", "bullets": ["Led search."]},
                ],
                "projects": [
                    {"name": "RAG Agent", "bullets": [LIBRARY_PROFILE["projects"][0]["bullets"][0]]},
                    {"name": "Fake Project", "bullets": ["x"]},
                ],
            }
        if "judge how well" in system:
            return {"score": 85, "reason": "solid fit"}
        raise AssertionError(f"unexpected prompt: {system[:60]}")


@pytest.fixture
def pipeline(monkeypatch):
    async def no_vectors(*_a, **_k):
        return []

    monkeypatch.setattr(library, "retrieve_items", no_vectors)           # falls back to keyword ranking
    monkeypatch.setattr(agents, "compiler_available", lambda: False)     # score from text; no pdflatex needed

    def run(must_have: list[str], threshold: int = THRESHOLD):
        agents.clear_jd_cache()
        fake = FakeLLM(must_have)
        monkeypatch.setattr(agents, "llm_json", fake)

        async def go():
            events, final = [], None
            async for event in agents.run_tailoring("x" * 200, [ROW], threshold=threshold, max_attempts=3):
                events.append(event)
                if event["type"] == "final":
                    final = event["state"]
                assert event["type"] != "error", event
            return events, final

        events, final = asyncio.run(go())
        return fake, events, final

    return run


def test_passes_the_gate_when_the_library_satisfies_the_job(pipeline):
    fake, events, final = pipeline(["Python", "FastAPI", "PostgreSQL", "Docker"])
    best = final["best"]
    assert best["score"] >= THRESHOLD
    assert final["attempt"] == 1 and len(fake.writer_prompts) == 1
    steps = [e["step"] for e in events if e["type"] == "step" and e["status"] == "done"]
    assert steps == ["analyze", "retrieve", "write", "score"]


def test_everything_the_writer_invented_is_stripped(pipeline):
    _, _, final = pipeline(["Python", "FastAPI"])
    best = final["best"]
    draft = Profile.model_validate(best["draft"])
    assert draft.skills["Languages"] == ["Python"]                       # Kubernetes and Go removed
    assert [e.company for e in draft.experience] == ["Acme"]             # Google removed
    assert draft.experience[0].title == "Software Engineer"              # model's "Staff Engineer" ignored
    assert "90%" not in " ".join(draft.experience[0].bullets)
    assert [p.name for p in draft.projects] == ["RAG Agent"]             # Fake Project removed
    assert draft.summary == "Full stack developer."                      # fabricated summary numbers rejected
    assert len(best["warnings"]) >= 4


def test_unsatisfiable_job_stays_below_target_after_three_attempts(pipeline):
    fake, _, final = pipeline(["Python", "Kubernetes", "Terraform", "Java", "Spring Boot"])
    best = final["best"]
    assert best["score"] < THRESHOLD
    assert final["attempt"] == 3 and len(fake.writer_prompts) == 3
    assert set(best["report"]["missing_must"]) >= {"Kubernetes", "Terraform", "Java", "Spring Boot"}


def test_feedback_tells_the_writer_not_to_invent_missing_skills(pipeline):
    fake, _, _ = pipeline(["Python", "Kubernetes", "Terraform"])
    assert "FEEDBACK" not in fake.writer_prompts[0]
    second = fake.writer_prompts[1]
    assert "FEEDBACK FROM THE PREVIOUS ATTEMPT" in second
    assert "NO evidence for" in second and "Kubernetes" in second


def test_failed_latex_compile_is_flagged_so_it_cannot_be_released(pipeline, monkeypatch):
    async def broken_compile(_tex):
        return None, "! LaTeX Error: something broke"

    monkeypatch.setattr(agents, "compiler_available", lambda: True)
    monkeypatch.setattr(agents, "compile_pdf", broken_compile)
    _, _, final = pipeline(["Python", "FastAPI", "PostgreSQL", "Docker"])
    best = final["best"]
    assert best["compile_failed"] is True
    assert any("could not be compiled" in w for w in best["warnings"])


def test_invalid_job_description_is_a_clear_error(monkeypatch):
    async def useless(*_a, **_k):
        return {"title": "", "must_have": [], "nice_to_have": [], "responsibilities": []}

    monkeypatch.setattr(agents, "llm_json", useless)
    with pytest.raises(ValueError, match="skills or requirements"):
        asyncio.run(agents.analyze_jd("Lorem ipsum dolor sit amet, nothing technical here at all."))

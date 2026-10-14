"""The writer may only use facts from the library: everything else must be stripped."""

from app.services.resume.agents import ground_profile
from app.services.resume.schemas import Profile
from tests.sample_data import LIBRARY_CORPUS, LIBRARY_PROFILE, library_profile

ORIGINAL = LIBRARY_PROFILE["experience"][0]["bullets"]


def _ground(draft: dict):
    return ground_profile(Profile.model_validate(draft), library_profile(), LIBRARY_CORPUS)


def test_invented_skills_are_removed():
    out, warnings = _ground({"skills": {"Languages": ["Python", "Kubernetes", "Rust"], "Tools": ["Docker"]}})
    assert out.skills["Languages"] == ["Python"]
    assert any("Kubernetes" in w for w in warnings)


def test_common_words_do_not_count_as_evidence_for_a_skill():
    # "go"/"r" appear nowhere as skills in this library; claiming them must not slip through
    out, _ = _ground({"skills": {"Languages": ["Python", "Go", "R"]}})
    assert out.skills["Languages"] == ["Python"]


def test_invented_employers_are_dropped_and_real_ones_keep_library_facts():
    out, _ = _ground({"experience": [
        {"company": "Acme", "title": "CTO", "bullets": [ORIGINAL[0]]},
        {"company": "Google", "title": "SWE", "bullets": ["Led search."]},
    ]})
    assert [e.company for e in out.experience] == ["Acme"]
    assert out.experience[0].title == "Software Engineer"          # title comes from the library, not the model
    assert out.experience[0].dates == "Jun 2023 - Present"


def test_slightly_renamed_company_still_matches():
    out, _ = _ground({"experience": [{"company": "Acme Inc.", "title": "x", "bullets": [ORIGINAL[1]]}]})
    assert ORIGINAL[1] in out.experience[0].bullets


def test_fabricated_numbers_revert_to_the_original_bullet():
    out, warnings = _ground({"experience": [{
        "company": "Acme", "title": "x",
        "bullets": ["Built REST APIs with FastAPI serving 9 million requests/day and cutting latency by 90%."],
    }]})
    assert "9 million" not in " ".join(out.experience[0].bullets)
    assert ORIGINAL[0] in out.experience[0].bullets
    assert any("unsupported numbers" in w for w in warnings)


def test_numbers_that_exist_in_the_library_are_kept():
    rewritten = "Cut API latency by 35% while serving 50k requests/day with FastAPI."
    out, _ = _ground({"experience": [{"company": "Acme", "title": "x", "bullets": [rewritten]}]})
    assert rewritten in out.experience[0].bullets


def test_invented_projects_are_dropped_and_renamed_ones_match():
    out, warnings = _ground({"projects": [
        {"name": "RAG Agent Project", "bullets": ["Built a RAG app indexing 200 files with Gemini embeddings and Groq LLMs."]},
        {"name": "Totally Fake", "bullets": ["x"]},
    ]})
    assert [p.name for p in out.projects] == ["RAG Agent"]
    assert any("Totally Fake" in w for w in warnings)


def test_identity_and_education_always_come_from_the_library():
    out, _ = _ground({"name": "Someone Else", "email": "evil@example.com",
                      "education": [{"school": "MIT", "degree": "PhD"}]})
    assert out.name == "Asha Verma" and out.email == "asha@example.com"
    assert [e.school for e in out.education] == ["Pune University"]


def test_every_library_role_is_kept_even_if_the_model_omits_it():
    out, _ = _ground({"summary": "x"})
    assert [e.company for e in out.experience] == ["Acme"]
    assert out.experience[0].bullets            # falls back to the original bullets


def test_summary_with_unsupported_numbers_falls_back_to_the_original():
    out, _ = _ground({"summary": "Engineer with 15 years of experience and a 300% growth record."})
    assert out.summary == "Full stack developer."

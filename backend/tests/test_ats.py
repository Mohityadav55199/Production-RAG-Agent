from app.services.resume import ats
from app.services.resume.latex import profile_plain_text
from app.services.resume.schemas import JDAnalysis
from tests.sample_data import library_profile

BULLET = "•"


def _experience(split: bool) -> str:
    bullets = [
        "Built REST APIs serving 50k requests per day with FastAPI",
        "Reduced latency by 35% through caching and query tuning",
        "Developed a React dashboard used by 200 analysts weekly",
        "Deployed services using Docker and automated CI pipelines",
        "Implemented unit tests raising coverage to 85 percent",
        "Designed PostgreSQL schemas for four internal tools",
    ]
    sep = "\n" if split else " "
    return "EXPERIENCE\nAcme Corp  Jun 2023 - Present\n" + "\n".join(f"{BULLET}{sep}{b}" for b in bullets)


class TestBulletDetection:
    def test_inline_bullets(self):
        assert len(ats._bullets(_experience(split=False))) == 6

    def test_bullet_glyph_on_its_own_line(self):
        # Many PDFs extract the glyph and the text as separate lines; this used to find 0 bullets
        assert len(ats._bullets(_experience(split=True))) == 6

    def test_short_fragments_are_not_bullets(self):
        assert ats._bullets(f"{BULLET} Yes\n{BULLET} No") == []


class TestKeywordMatching:
    def test_variants_and_synonyms(self):
        assert ats.term_in_text("JavaScript", "Strong js and node skills")
        assert ats.term_in_text("Kubernetes", "deployed on k8s")
        assert ats.term_in_text("PostgreSQL", "we use Postgres")
        assert ats.term_in_text("REST APIs", "designed RESTful API endpoints")

    def test_java_is_not_javascript(self):
        assert not ats.term_in_text("Java", "Frontend work in JavaScript only")
        assert ats.term_in_text("Java", "Backend in Java and Spring")

    def test_c_plus_plus(self):
        assert ats.term_in_text("C++", "Languages: Python, C++, Rust")

    def test_everyday_words_are_not_skills(self):
        text = "I like to go to the gym. The R&D team met. Plan C failed. Go to market strategy."
        for term in ("Go", "Golang", "R", "C"):
            assert not ats.term_in_text(term, text), term

    def test_real_uses_of_ambiguous_names(self):
        assert ats.term_in_text("Go", "Languages: Python, Go, SQL")
        assert ats.term_in_text("Go", "Built microservices in Go and deployed with Docker")
        assert ats.term_in_text("R", "Statistical modelling with R and Python")
        assert ats.term_in_text("Golang", "Services written in Go")
        assert ats.term_in_text("Go", "Experience with Golang preferred")


class TestScoring:
    jd = JDAnalysis(must_have=["Python", "FastAPI", "PostgreSQL", "Kubernetes"], nice_to_have=["React", "Terraform"])

    def test_missing_skills_are_reported_not_hidden(self):
        report = ats.build_report(profile_plain_text(library_profile()), self.jd, None, (80, "ok"))
        assert "Kubernetes" in report.missing_must
        assert "Terraform" in report.missing_nice
        assert {"Python", "FastAPI", "PostgreSQL", "React"} <= set(report.matched)

    def test_must_haves_weigh_more_than_nice_to_haves(self):
        only_nice = ats.build_report("Terraform", JDAnalysis(must_have=["Python"], nice_to_have=["Terraform"]))
        only_must = ats.build_report("Python", JDAnalysis(must_have=["Python"], nice_to_have=["Terraform"]))
        kw = lambda r: next(c.score for c in r.components if c.key == "keywords")
        assert kw(only_must) > kw(only_nice)

    def test_weights_sum_to_100_with_and_without_ai_judge(self):
        text = profile_plain_text(library_profile())
        for fit in ((80, "ok"), None):
            report = ats.build_report(text, self.jd, None, fit)
            assert abs(sum(c.weight for c in report.components) - 100) <= 1

    def test_no_job_description_scores_format_and_parsing_only(self):
        report = ats.build_report(profile_plain_text(library_profile()))
        assert {c.key for c in report.components} == {"parsing", "format"}
        assert not report.has_jd

    def test_empty_text_scores_badly(self):
        report = ats.build_report("hello", None)
        assert report.total < 40
        assert any("email" in f.lower() for f in report.fixes)

    def test_fallback_jd_analysis_finds_terms(self):
        jd = ats.fallback_jd_analysis("We need Python, FastAPI and Docker experience. Knowledge of Go is a plus.")
        assert {"Python".lower(), "fastapi", "docker"} <= {t.lower() for t in jd.must_have + jd.nice_to_have}


def test_a_tool_shows_the_practice_but_not_the_reverse():
    from app.services.resume.ats import term_in_text

    assert term_in_text("ci/cd", "Automated releases with GitHub Actions.")
    assert term_in_text("ci/cd", "Set up continuous integration for the app.")
    assert not term_in_text("github actions", "Built CI/CD pipelines with Fastlane.")

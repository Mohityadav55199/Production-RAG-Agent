"""The resume benchmark: planted fabrications are removed, honest drafts untouched, the right candidate wins."""

from app.services.resume.schemas import Profile
from eval.resume_eval import evaluate_resume as bench
from eval.resume_eval.evaluate_resume import guard_check, job_analysis, load_dataset, rank_of_target


def test_resume_eval_dataset_integrity():
    resumes, jobs = load_dataset()
    assert len(resumes) == 10
    assert len(jobs) == 10

    res_ids = {r["id"] for r in resumes}
    for job in jobs:
        assert job["target_resume_id"] in res_ids
        assert len(job["text"]) > 50


def test_guard_removes_every_planted_fabrication_and_keeps_honest_bullets():
    resumes, jobs = load_dataset()
    by_id = {r["id"]: r for r in resumes}
    for job in jobs:
        leaked, false_reverts = guard_check(Profile.model_validate(by_id[job["target_resume_id"]]), job_analysis(job))
        assert leaked == [], f"{job['title']}: {leaked}"
        assert false_reverts == 0, job["title"]


def test_the_benchmark_would_notice_a_guard_that_does_nothing(monkeypatch):
    monkeypatch.setattr(bench, "ground_profile", lambda draft, merged, corpus, jd=None: (draft, []))
    resumes, jobs = load_dataset()
    profile = Profile.model_validate({r["id"]: r for r in resumes}[jobs[0]["target_resume_id"]])
    leaked, _ = guard_check(profile, job_analysis(jobs[0]))
    assert bench.PLANT_EMPLOYER in leaked and bench.PLANT_NUMBER in leaked and bench.PLANT_PROJECT in leaked


def test_the_target_candidate_ranks_first_for_every_job():
    resumes, jobs = load_dataset()
    by_id = {r["id"]: r for r in resumes}
    for job in jobs:
        score, best_other, rank = rank_of_target(job, by_id)
        assert rank == 1, f"{job['title']}: target {score} vs best other {best_other}"

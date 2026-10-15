import pytest
from app.services.resume import ats
from app.services.resume.latex import profile_plain_text
from app.services.resume.schemas import Profile
from eval.resume_eval.evaluate_resume import evaluate_grounding, load_dataset


def test_resume_eval_dataset_integrity():
    resumes, jobs = load_dataset()
    assert len(resumes) == 10
    assert len(jobs) == 10

    res_ids = {r["id"] for r in resumes}
    for job in jobs:
        assert job["target_resume_id"] in res_ids
        assert len(job["text"]) > 50


def test_resume_eval_grounding_and_directionality():
    resumes, jobs = load_dataset()
    resumes_by_id = {r["id"]: r for r in resumes}

    total_violations = 0
    directional_passes = 0

    for job in jobs:
        target_res = resumes_by_id[job["target_resume_id"]]
        target_profile = Profile.model_validate(target_res)
        target_text = profile_plain_text(target_profile)

        jd = ats.fallback_jd_analysis(job["text"])
        report = ats.build_report(target_text, jd, meta=None, fit=None)

        violations, _ = evaluate_grounding(target_profile, target_text)
        total_violations += violations

        # Cross average
        other_scores = []
        for other_id, other_res in resumes_by_id.items():
            if other_id == job["target_resume_id"]:
                continue
            other_prof = Profile.model_validate(other_res)
            other_text = profile_plain_text(other_prof)
            other_scores.append(ats.build_report(other_text, jd, meta=None, fit=None).total)

        cross_avg = sum(other_scores) / len(other_scores)
        if report.total >= cross_avg:
            directional_passes += 1

    assert total_violations == 0, f"Expected 0 grounding violations, found {total_violations}"
    assert directional_passes == 10, f"Expected 10/10 directional passes, got {directional_passes}"

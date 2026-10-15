"""
Resume Grounding & Directional ATS Scoring Evaluation Suite.

Evaluates 10 candidates against 10 job descriptions:
1. The grounding guard removes fabrications: every draft gets invented skills, an invented employer, an
   invented number and an invented project planted in it, and none may survive ground_profile.
2. The guard leaves honest drafts alone: a draft that only uses library facts must come back unchanged.
3. Scores point the right way: the candidate a job was written for ranks first among all ten.
4. (--live) Cover letters and recruiter messages are generated and checked for unsupported claims.

Usage:
    python backend/eval/resume_eval/evaluate_resume.py
    python backend/eval/resume_eval/evaluate_resume.py --live
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add backend root to sys.path so app imports resolve
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.resume import ats, grounding
from app.services.resume.agents import ground_profile
from app.services.resume.latex import profile_plain_text
from app.services.resume.outreach import generate_cover_letter, generate_recruiter_message
from app.services.resume.schemas import JDAnalysis, Profile, Project

# Skills planted into drafts; each candidate gets the first two its library never mentions
PLANT_SKILLS = ["kubernetes", "terraform", "snowflake", "swiftui", "owasp", "pytorch", "kafka", "flutter"]
PLANT_EMPLOYER = "Initech Global"
PLANT_NUMBER = "7,777"
PLANT_PROJECT = "QuantumLedger"


def load_dataset() -> tuple[list[dict], list[dict]]:
    path = Path(__file__).resolve().parent / "dataset.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["resumes"], data["jobs"]


def job_analysis(job: dict) -> JDAnalysis:
    jd = ats.fallback_jd_analysis(job["text"])
    jd.title, jd.company = job["title"], job["company"]
    return jd


def plant_fabrications(profile: Profile, corpus: str) -> tuple[Profile, list[str]]:
    """A draft that rewrites the library but also claims things the library never mentions."""
    skills = [s for s in PLANT_SKILLS if not ats.term_in_text(s, corpus)][:2]
    draft = profile.model_copy(deep=True)
    draft.summary = f"{profile.summary} Deep expertise in {skills[0].title()} and {skills[1].title()}."
    if draft.experience:
        draft.experience[0].bullets = draft.experience[0].bullets + [
            f"Scaled the {skills[0].title()} platform at {PLANT_EMPLOYER} to {PLANT_NUMBER} daily users.",
        ]
    draft.skills = {**draft.skills, "Planted": [s.title() for s in skills]}
    draft.projects = draft.projects + [Project(name=PLANT_PROJECT, tech=skills[1], bullets=["Built it."])]
    return draft, [*skills, PLANT_EMPLOYER, PLANT_NUMBER, PLANT_PROJECT]


def guard_check(profile: Profile, jd: JDAnalysis) -> tuple[list[str], int]:
    """(planted claims that survived the guard, honest bullets the guard wrongly changed)."""
    corpus = profile_plain_text(profile)
    draft, planted = plant_fabrications(profile, corpus)
    out, _ = ground_profile(draft, profile, corpus, jd)
    text = profile_plain_text(out)
    leaked = [p for p in planted if ats.term_in_text(p, text) or p in text]

    honest, _ = ground_profile(profile.model_copy(deep=True), profile, corpus, jd)
    original = [b for e in profile.experience for b in e.bullets] + [b for p in profile.projects for b in p.bullets]
    kept = {b for e in honest.experience for b in e.bullets} | {b for p in honest.projects for b in p.bullets}
    false_reverts = sum(1 for b in original if b not in kept)
    return leaked, false_reverts


def rank_of_target(job: dict, resumes_by_id: dict[str, dict]) -> tuple[int, int, int]:
    """(target's score, best other score, target's rank among all candidates, 1 = best)."""
    jd = job_analysis(job)
    scores = {
        rid: ats.build_report(profile_plain_text(Profile.model_validate(r)), jd, meta=None, fit=None).total
        for rid, r in resumes_by_id.items()
    }
    target = scores[job["target_resume_id"]]
    best_other = max(s for rid, s in scores.items() if rid != job["target_resume_id"])
    rank = 1 + sum(1 for rid, s in scores.items() if rid != job["target_resume_id"] and s > target)
    return target, best_other, rank


async def run_benchmark(live_mode: bool = False) -> int:
    resumes_data, jobs_data = load_dataset()
    resumes_by_id = {r["id"]: r for r in resumes_data}
    print("=" * 96)
    print("       RESUME GROUNDING & DIRECTIONAL ATS EVALUATION BENCHMARK")
    print(f"       Corpus: {len(resumes_data)} Resumes x {len(jobs_data)} Job Descriptions | Live Mode: {live_mode}")
    print("=" * 96)
    print(f"\n{'Candidate':<18} | {'Target Role':<24} | {'Score':>5} | {'Best other':>10} | {'Rank':>4} | "
          f"{'Leaked':>6} | {'Wrong reverts':>13} | Status")
    print("-" * 96)

    total_leaked = total_reverts = rank_one = 0
    for job in jobs_data:
        target_res = resumes_by_id[job["target_resume_id"]]
        profile = Profile.model_validate(target_res)
        score, best_other, rank = rank_of_target(job, resumes_by_id)
        leaked, reverts = guard_check(profile, job_analysis(job))
        total_leaked += len(leaked)
        total_reverts += reverts
        rank_one += rank == 1
        ok = not leaked and not reverts and rank == 1
        print(f"{target_res['name']:<18} | {job['title'][:24]:<24} | {score:>4}% | {best_other:>9}% | {rank:>4} | "
              f"{len(leaked):>6} | {reverts:>13} | {'PASS' if ok else 'FAIL'}")
        for item in leaked:
            print(f"    leaked: {item}")

    print("\n" + "-" * 96)
    if live_mode:
        print("Generating outreach with the live LLM...")
        sample = Profile.model_validate(resumes_by_id[jobs_data[0]["target_resume_id"]])
        corpus = profile_plain_text(sample)
        jd = job_analysis(jobs_data[0])
        try:
            letter = await generate_cover_letter(sample, jd, jobs_data[0]["text"], corpus)
            print(f"  [x] Cover letter: {len(letter['full_text'])} chars, warnings: {letter['warnings'] or 'none'}")
            msg = await generate_recruiter_message(sample, jd, jobs_data[0]["text"], "linkedin", corpus)
            print(f"  [x] Recruiter message: {len(msg['message'].split())} words, warnings: {msg['warnings'] or 'none'}")
        except Exception as exc:
            print(f"  [!] Live outreach failed: {exc}")
    else:
        claims = grounding.unsupported_claims(
            f"I scaled Kubernetes at {PLANT_EMPLOYER} to {PLANT_NUMBER} users.", "Python developer.",
        )
        print(f"  [x] Outreach claim check (offline): flagged {', '.join(claims)}")

    n = len(jobs_data)
    print("\n" + "=" * 96)
    print("                              EVALUATION SUMMARY")
    print("=" * 96)
    print(f"  * Candidate x job pairs tested          : {n}")
    print(f"  * Planted fabrications that survived    : {total_leaked} (requirement: 0)")
    print(f"  * Honest bullets wrongly reverted       : {total_reverts} (requirement: 0)")
    print(f"  * Right candidate ranked first          : {rank_one}/{n}")
    print("=" * 96)

    if total_leaked == 0 and total_reverts == 0 and rank_one == n:
        print("\nAll benchmark criteria passed successfully!\n")
        return 0
    print("\nNotice: Some benchmark criteria need attention.\n")
    return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate resume grounding and scoring suite.")
    parser.add_argument("--live", action="store_true", help="Also generate outreach with the live LLM.")
    args = parser.parse_args()

    sys.exit(asyncio.run(run_benchmark(live_mode=args.live)))
